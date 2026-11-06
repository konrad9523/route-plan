import csv
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def quantile(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: summarize_search_optimizations.py SUMMARY.csv RAW.csv [RAW.csv ...]")

    rows = []
    for raw_path in sys.argv[2:]:
        with Path(raw_path).open("r", newline="", encoding="utf-8-sig") as source:
            rows.extend(csv.DictReader(source))

    groups = defaultdict(list)
    by_network_query_round = {}
    for row in rows:
        row["elapsed_ns"] = int(row["elapsed_ns"])
        row["elapsed_ms"] = row["elapsed_ns"] / 1_000_000.0
        for name in ("expanded", "queue_pushes", "queue_decreases", "peak_open_entries",
                     "scanned_edges", "successful_relaxations", "stale_pops",
                     "heuristic_evaluations", "auxiliary_queue_pushes"):
            row[name] = int(row[name])
        key = (row["network"], row["config"])
        groups[key].append(row)
        by_network_query_round[(row["network"], row["query"], row["round"], row["config"])] = row

    output = []
    for (network, config), samples in sorted(groups.items()):
        times = [row["elapsed_ms"] for row in samples]
        if config.endswith("_INDEXED"):
            peer = config.removesuffix("_INDEXED") + "_LAZY"
        elif config.startswith("L5_"):
            peer = config.replace("L5_", "L4_", 1)
        elif config.startswith("L4_"):
            peer = "L4_H0_LAZY"
        else:
            peer = "L1_H0_LAZY"
        paired = []
        for row in samples:
            reference = by_network_query_round[(network, row["query"], row["round"], peer)]
            paired.append(reference["elapsed_ms"] / row["elapsed_ms"])
        per_query = defaultdict(lambda: [[], []])
        for row in samples:
            reference = by_network_query_round[(network, row["query"], row["round"], peer)]
            per_query[row["query"]][0].append(reference["elapsed_ms"])
            per_query[row["query"]][1].append(row["elapsed_ms"])
        query_ratios = [statistics.median(pair[0]) / statistics.median(pair[1])
                        for pair in per_query.values()]
        peer_expanded = [
            by_network_query_round[(network, row["query"], row["round"], peer)]["expanded"]
            for row in samples
        ]
        mean_expanded = statistics.fmean(row["expanded"] for row in samples)
        mean_peer_expanded = statistics.fmean(peer_expanded)
        output.append({
            "network": network,
            "config": config,
            "paired_peer": peer,
            "samples": len(samples),
            "median_ms": statistics.median(times),
            "q1_ms": quantile(times, 0.25),
            "q3_ms": quantile(times, 0.75),
            "mean_expanded": mean_expanded,
            "mean_expanded_change_pct_vs_peer": (
                (mean_expanded / mean_peer_expanded - 1.0) * 100.0
                if mean_peer_expanded else 0.0
            ),
            "mean_scanned_edges": statistics.fmean(row["scanned_edges"] for row in samples),
            "mean_queue_pushes": statistics.fmean(row["queue_pushes"] for row in samples),
            "mean_queue_decreases": statistics.fmean(row["queue_decreases"] for row in samples),
            "mean_peak_open_entries": statistics.fmean(row["peak_open_entries"] for row in samples),
            "mean_stale_pops": statistics.fmean(row["stale_pops"] for row in samples),
            "paired_speedup_vs_peer_median": statistics.median(paired),
            "paired_speedup_vs_peer_q1": quantile(paired, 0.25),
            "paired_speedup_vs_peer_q3": quantile(paired, 0.75),
            "paired_variant_faster_samples": sum(value > 1.0 for value in paired),
            "paired_peer_faster_samples": sum(value < 1.0 for value in paired),
            "query_median_speedup_vs_peer_median": statistics.median(query_ratios),
            "query_median_speedup_vs_peer_q1": quantile(query_ratios, 0.25),
            "query_median_speedup_vs_peer_q3": quantile(query_ratios, 0.75),
            "query_median_variant_faster": sum(value > 1.0 for value in query_ratios),
            "query_median_peer_faster": sum(value < 1.0 for value in query_ratios),
        })

    columns = list(output[0])
    with Path(sys.argv[1]).open("w", newline="", encoding="utf-8-sig") as target:
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()
        writer.writerows(output)

    matched = []
    for network in sorted({row["network"] for row in rows}):
        for suffix in ("H0", "ALT4", "ALT8", "ALT16", "MAX4", "MAX8", "MAX16"):
            l1_name = f"L1_{suffix}_LAZY"
            l4_name = f"L4_{suffix}_LAZY"
            l1_samples = groups.get((network, l1_name))
            l4_samples = groups.get((network, l4_name))
            if l1_samples is None or l4_samples is None:
                continue
            l1_by_query = defaultdict(list)
            l4_by_query = defaultdict(list)
            for row in l1_samples:
                l1_by_query[row["query"]].append(row["elapsed_ms"])
            for row in l4_samples:
                l4_by_query[row["query"]].append(row["elapsed_ms"])
            ratios = [statistics.median(l1_by_query[query]) /
                      statistics.median(l4_by_query[query])
                      for query in sorted(l1_by_query)]
            l1_expanded = statistics.fmean(row["expanded"] for row in l1_samples)
            l4_expanded = statistics.fmean(row["expanded"] for row in l4_samples)
            matched.append({
                "network": network,
                "config": suffix,
                "l1_median_ms": statistics.median(row["elapsed_ms"] for row in l1_samples),
                "l4_median_ms": statistics.median(row["elapsed_ms"] for row in l4_samples),
                "l1_mean_expanded": l1_expanded,
                "l4_mean_expanded": l4_expanded,
                "l4_expansion_reduction_pct": (
                    (l1_expanded - l4_expanded) / l1_expanded * 100.0
                    if l1_expanded else 0.0
                ),
                "l1_over_l4_paired_median": statistics.median(ratios),
                "l1_over_l4_paired_q1": quantile(ratios, 0.25),
                "l1_over_l4_paired_q3": quantile(ratios, 0.75),
                "l4_faster_queries": sum(value > 1.0 for value in ratios),
                "l1_faster_queries": sum(value < 1.0 for value in ratios),
                "equal_queries": sum(value == 1.0 for value in ratios),
            })
    if matched:
        matched_columns = list(matched[0])
        matched_path = Path(sys.argv[1]).with_name("L1_vs_L4_matched.csv")
        with matched_path.open("w", newline="", encoding="utf-8-sig") as target:
            writer = csv.DictWriter(target, fieldnames=matched_columns)
            writer.writeheader()
            writer.writerows(matched)


if __name__ == "__main__":
    main()
