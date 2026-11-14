"""Summarize paired C++ bidirectional A* benchmark CSV files."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path


def quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(raw_files: list[Path], output: Path) -> None:
    rows: list[dict[str, str]] = []
    for file in raw_files:
        with file.open("r", encoding="utf-8-sig", newline="") as stream:
            rows.extend(csv.DictReader(stream))

    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    paired: dict[tuple[str, int, int], dict[str, float]] = defaultdict(dict)
    query_runs: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    for row in rows:
        network = row["network"]
        layer = row["layer"]
        elapsed_ms = int(row["elapsed_ns"]) / 1_000_000
        grouped[(network, layer)].append(row)
        paired[(network, int(row["query"]), int(row["round"]))][layer] = elapsed_ms
        query_runs[(network, int(row["query"]), layer)].append(elapsed_ms)
    query_medians = {
        key: quantile(values, 0.5) for key, values in query_runs.items()
    }

    network_layers = sorted(grouped)
    layer_order = {
        "L0_RECEIVED": 0,
        "L1_EARLY_EXIT": 1,
        "L2_MM": 2,
        "L3_MM_EPSILON": 3,
        "L4_BAE_STAR": 4,
    }
    layer_rows = []
    for network, layer in network_layers:
        layer_records = grouped[(network, layer)]
        times_ms = [int(row["elapsed_ns"]) / 1_000_000 for row in layer_records]
        expanded = [float(row["expanded"]) for row in layer_records]
        scanned = [float(row["scanned_edges"]) for row in layer_records
                   if row["scanned_edges"]]
        speedups = []
        wins = 0
        pairs = 0
        previous_name = next((name for name, order in layer_order.items()
                              if order == layer_order[layer] - 1), None)
        previous_speedups = []
        previous_wins = 0
        previous_pairs = 0
        query_speedups = []
        query_wins = 0
        query_pairs = 0
        previous_query_speedups = []
        previous_query_wins = 0
        for (pair_network, _query, _round), values in paired.items():
            if pair_network != network or layer not in values or "L0_RECEIVED" not in values:
                continue
            speedups.append(values["L0_RECEIVED"] / values[layer])
            wins += values[layer] < values["L0_RECEIVED"]
            pairs += 1
            if previous_name and previous_name in values:
                previous_speedups.append(values[previous_name] / values[layer])
                previous_wins += values[layer] < values[previous_name]
                previous_pairs += 1
        query_ids = sorted({
            query for (query_network, query, query_layer) in query_medians
            if query_network == network and query_layer == layer
        })
        for query in query_ids:
            baseline_query_ms = query_medians[(network, query, "L0_RECEIVED")]
            query_speedups.append(baseline_query_ms / query_medians[(network, query, layer)])
            query_wins += query_medians[(network, query, layer)] < baseline_query_ms
            query_pairs += 1
            if previous_name and (network, query, previous_name) in query_medians:
                previous_ms = query_medians[(network, query, previous_name)]
                current_ms = query_medians[(network, query, layer)]
                previous_query_speedups.append(previous_ms / current_ms)
                previous_query_wins += current_ms < previous_ms
        baseline_rows = grouped.get((network, "L0_RECEIVED"), [])
        baseline_median_ms = quantile(
            [int(row["elapsed_ns"]) / 1_000_000 for row in baseline_rows], 0.5
        )
        baseline_mean_expanded = sum(float(row["expanded"]) for row in baseline_rows) / len(baseline_rows)
        previous_rows = grouped.get((network, previous_name), []) if previous_name else []
        previous_median_ms = quantile(
            [int(row["elapsed_ns"]) / 1_000_000 for row in previous_rows], 0.5
        ) if previous_rows else math.nan
        previous_mean_expanded = (
            sum(float(row["expanded"]) for row in previous_rows) / len(previous_rows)
            if previous_rows else math.nan
        )
        current_median_ms = quantile(times_ms, 0.5)
        current_mean_expanded = sum(expanded) / len(expanded)
        layer_rows.append({
            "network": network,
            "layer": layer,
            "samples": len(layer_records),
            "median_ms": f"{current_median_ms:.6f}",
            "q1_ms": f"{quantile(times_ms, 0.25):.6f}",
            "q3_ms": f"{quantile(times_ms, 0.75):.6f}",
            "mean_expanded": f"{sum(expanded) / len(expanded):.2f}",
            "median_expanded": f"{quantile(expanded, 0.5):.2f}",
            "median_scanned_edges": f"{quantile(scanned, 0.5):.2f}" if scanned else "NA",
            "median_time_change_pct_vs_L0": f"{(current_median_ms / baseline_median_ms - 1) * 100:.2f}",
            "mean_expanded_change_pct_vs_L0": f"{(current_mean_expanded / baseline_mean_expanded - 1) * 100:.2f}",
            "paired_speedup_vs_L0_median": f"{quantile(speedups, 0.5):.4f}",
            "paired_speedup_q1": f"{quantile(speedups, 0.25):.4f}",
            "paired_speedup_q3": f"{quantile(speedups, 0.75):.4f}",
            "paired_wins_vs_L0": f"{wins}/{pairs}",
            "query_median_paired_speedup_vs_L0": f"{quantile(query_speedups, 0.5):.4f}",
            "query_median_speedup_vs_L0_q1": f"{quantile(query_speedups, 0.25):.4f}",
            "query_median_speedup_vs_L0_q3": f"{quantile(query_speedups, 0.75):.4f}",
            "query_median_wins_vs_L0": f"{query_wins}/{query_pairs}",
            "previous_layer": previous_name or "NA",
            "paired_speedup_vs_previous_median": f"{quantile(previous_speedups, 0.5):.4f}" if previous_speedups else "NA",
            "paired_speedup_vs_previous_q1": f"{quantile(previous_speedups, 0.25):.4f}" if previous_speedups else "NA",
            "paired_speedup_vs_previous_q3": f"{quantile(previous_speedups, 0.75):.4f}" if previous_speedups else "NA",
            "paired_wins_vs_previous": f"{previous_wins}/{previous_pairs}" if previous_pairs else "NA",
            "query_median_paired_speedup_vs_previous": f"{quantile(previous_query_speedups, 0.5):.4f}" if previous_query_speedups else "NA",
            "query_median_speedup_vs_previous_q1": f"{quantile(previous_query_speedups, 0.25):.4f}" if previous_query_speedups else "NA",
            "query_median_speedup_vs_previous_q3": f"{quantile(previous_query_speedups, 0.75):.4f}" if previous_query_speedups else "NA",
            "query_median_wins_vs_previous": f"{previous_query_wins}/{query_pairs}" if previous_query_speedups else "NA",
            "median_time_change_pct_vs_previous": f"{(current_median_ms / previous_median_ms - 1) * 100:.2f}" if previous_rows else "NA",
            "mean_expanded_change_pct_vs_previous": f"{(current_mean_expanded / previous_mean_expanded - 1) * 100:.2f}" if previous_rows else "NA",
        })

    output.parent.mkdir(parents=True, exist_ok=True)
    columns = list(layer_rows[0]) if layer_rows else []
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(layer_rows)
    for row in layer_rows:
        print(
            f"{row['network']:10} {row['layer']:16} "
            f"median={row['median_ms']:>10} ms "
            f"expanded_mean={row['mean_expanded']:>10} "
            f"paired_speedup={row['paired_speedup_vs_L0_median']:>8} "
            f"wins={row['paired_wins_vs_L0']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("raw_csv", type=Path, nargs="+")
    args = parser.parse_args()
    summarize(args.raw_csv, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
