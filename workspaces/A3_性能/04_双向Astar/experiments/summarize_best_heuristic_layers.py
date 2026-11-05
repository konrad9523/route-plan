"""Summarize the layer sweep that fixes MAX-8 where supported."""

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
        raise SystemExit(
            "usage: summarize_best_heuristic_layers.py SUMMARY.csv RAW.csv [RAW.csv ...]"
        )

    rows = []
    for raw_path in sys.argv[2:]:
        with Path(raw_path).open("r", newline="", encoding="utf-8-sig") as source:
            rows.extend(csv.DictReader(source))

    groups = defaultdict(list)
    by_query_round = {}
    query_times = defaultdict(list)
    for row in rows:
        row["elapsed_ms"] = int(row["elapsed_ns"]) / 1_000_000.0
        row["expanded"] = int(row["expanded"])
        groups[(row["network"], row["config"])].append(row)
        by_query_round[(row["network"], row["query"], row["round"], row["config"])] = row
        query_times[(row["network"], row["query"], row["config"])].append(row["elapsed_ms"])

    order = [
        "L0_H0_RECEIVED",
        "L1_MAX8",
        "L2_MAX8",
        "L3_MAX8",
        "L4_MAX8",
        "L5_MAX8",
    ]
    previous = {order[i]: order[i - 1] for i in range(1, len(order))}
    query_medians = {
        key: statistics.median(values) for key, values in query_times.items()
    }

    output = []
    for network, config in sorted(groups, key=lambda key: (key[0], order.index(key[1]))):
        samples = groups[(network, config)]
        times = [row["elapsed_ms"] for row in samples]
        expanded = [row["expanded"] for row in samples]
        row = {
            "network": network,
            "config": config,
            "samples": len(samples),
            "median_ms": statistics.median(times),
            "q1_ms": quantile(times, 0.25),
            "q3_ms": quantile(times, 0.75),
            "mean_expanded": statistics.fmean(expanded),
            "previous_config": "",
            "median_time_change_pct_vs_previous": "",
            "mean_expanded_change_pct_vs_previous": "",
            "paired_speedup_vs_previous_median": "",
            "paired_speedup_vs_previous_q1": "",
            "paired_speedup_vs_previous_q3": "",
            "previous_faster_queries": "",
            "current_faster_queries": "",
        }
        if config in previous:
            peer = previous[config]
            peer_samples = groups[(network, peer)]
            peer_times = [item["elapsed_ms"] for item in peer_samples]
            peer_expanded = statistics.fmean(item["expanded"] for item in peer_samples)
            ratios = []
            current_wins = 0
            peer_wins = 0
            for query in sorted({item["query"] for item in samples}):
                current = query_medians[(network, query, config)]
                earlier = query_medians[(network, query, peer)]
                ratios.append(earlier / current)
                current_wins += current < earlier
                peer_wins += current > earlier

            row.update({
                "previous_config": peer,
                "median_time_change_pct_vs_previous": (
                    statistics.median(times) / statistics.median(peer_times) - 1.0
                ) * 100.0,
                "mean_expanded_change_pct_vs_previous": (
                    statistics.fmean(expanded) / peer_expanded - 1.0
                ) * 100.0 if peer_expanded else 0.0,
                "paired_speedup_vs_previous_median": statistics.median(ratios),
                "paired_speedup_vs_previous_q1": quantile(ratios, 0.25),
                "paired_speedup_vs_previous_q3": quantile(ratios, 0.75),
                "previous_faster_queries": peer_wins,
                "current_faster_queries": current_wins,
            })
        output.append(row)

    with Path(sys.argv[1]).open("w", newline="", encoding="utf-8-sig") as target:
        writer = csv.DictWriter(target, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)


if __name__ == "__main__":
    main()
