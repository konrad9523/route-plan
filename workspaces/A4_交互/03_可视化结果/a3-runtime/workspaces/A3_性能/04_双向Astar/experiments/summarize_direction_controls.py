#!/usr/bin/env python3
"""Summarize paired direction/meeting/termination control runs."""

from __future__ import annotations

import csv
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


CONTRASTS = (
    ("L0_RECEIVED", "L1_MIN_RELAX", "received L0 vs reweighted L1"),
    ("L0_RECEIVED", "L4_ALT_NATIVE", "native received L0 vs native L4"),
    ("L1_MIN_RELAX", "L1_MIN_RELAX_POP", "pop-time meeting update"),
    ("L1_MIN_RELAX_POP", "L1_ALT_RELAX_POP", "min-key vs alternating direction"),
    ("L1_ALT_RELAX_POP", "L4_ALT_NATIVE", "same alternating schedule; L1 vs native L4"),
    ("L1_ALT_RELAX_POP", "L4_ALT_STRICT", "same schedule; L1 vs BAE key/bound"),
    ("L4_ALT_NATIVE", "L4_ALT_STRICT", "L4 tolerance vs strict bound"),
    ("L1_MIN_RELAX_POP", "L4_MIN_STRICT", "same min-key schedule; L1 vs BAE key/bound"),
)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot calculate a percentile from an empty sample")
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))
    if not rows:
        raise ValueError(f"raw data is empty: {path}")
    return rows


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main(result_root: Path) -> None:
    network_rows: dict[str, list[dict[str, str]]] = {}
    for raw_path in sorted(result_root.glob("*_raw.csv")):
        network_rows[raw_path.name.removesuffix("_raw.csv")] = read_rows(raw_path)
    if len(network_rows) != 3:
        raise ValueError(f"expected 3 network raw files, found {len(network_rows)}")

    summary: list[dict[str, object]] = []
    contrasts: list[dict[str, object]] = []
    query_contrasts: list[dict[str, object]] = []
    for network, rows in network_rows.items():
        by_config: dict[str, list[dict[str, str]]] = defaultdict(list)
        per_query: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
        for row in rows:
            name = row["config"]
            query = int(row["query"])
            by_config[name].append(row)
            per_query[name][query].append(int(row["expanded"]))

        configs = set(by_config)
        query_path = result_root / f"{network}_queries.csv"
        with query_path.open("r", newline="", encoding="utf-8-sig") as source:
            endpoints = {
                int(row["query"]): (int(row["source_index"]), int(row["target_index"]))
                for row in csv.DictReader(source)
            }
        for base, variant, _ in CONTRASTS:
            if base not in configs or variant not in configs:
                raise ValueError(f"missing contrast configuration {base} or {variant} in {network}")

        for config, config_rows in by_config.items():
            expanded_by_query = per_query[config]
            stable = all(len(set(counts)) == 1 for counts in expanded_by_query.values())
            if not stable:
                raise ValueError(f"expanded-node count varied by round for {network}/{config}")
            elapsed_ms = [int(row["elapsed_ns"]) / 1_000_000.0 for row in config_rows]
            expanded = [int(row["expanded"]) for row in config_rows]
            summary.append({
                "network": network,
                "config": config,
                "calls": len(config_rows),
                "queries": len(expanded_by_query),
                "median_ms": f"{statistics.median(elapsed_ms):.6f}",
                "q1_ms": f"{percentile(elapsed_ms, 0.25):.6f}",
                "q3_ms": f"{percentile(elapsed_ms, 0.75):.6f}",
                "mean_expanded": f"{statistics.mean(expanded):.2f}",
                "median_expanded": f"{statistics.median(expanded):.2f}",
                "mean_forward_expanded": f"{statistics.mean(int(row['forward_expanded']) for row in config_rows):.2f}",
                "mean_backward_expanded": f"{statistics.mean(int(row['backward_expanded']) for row in config_rows):.2f}",
                "mean_best_updates": f"{statistics.mean(int(row['best_updates']) for row in config_rows):.2f}",
                "mean_scanned_edges": f"{statistics.mean(int(row['scanned_edges']) for row in config_rows):.2f}",
            })

        for base, variant, explanation in CONTRASTS:
            reductions = []
            wins = 0
            total_base = 0
            total_variant = 0
            for query, base_round_counts in per_query[base].items():
                variant_round_counts = per_query[variant].get(query)
                if variant_round_counts is None:
                    raise ValueError(f"query mismatch in {network}: {base} vs {variant}")
                base_count = base_round_counts[0]
                variant_count = variant_round_counts[0]
                if base_count == 0:
                    raise ValueError(f"zero expanded count for {network}/{base}/query {query}")
                reduction = (base_count - variant_count) / base_count * 100.0
                reductions.append(reduction)
                total_base += base_count
                total_variant += variant_count
                wins += variant_count < base_count
                source, target = endpoints[query]
                query_contrasts.append({
                    "network": network,
                    "query": query,
                    "source_index": source,
                    "target_index": target,
                    "base": base,
                    "variant": variant,
                    "base_expanded": base_count,
                    "variant_expanded": variant_count,
                    "difference": variant_count - base_count,
                    "variant_reduction_pct": f"{reduction:.3f}",
                })
            contrasts.append({
                "network": network,
                "base": base,
                "variant": variant,
                "contrast": explanation,
                "queries": len(reductions),
                "mean_query_reduction_pct": f"{statistics.mean(reductions):.3f}",
                "aggregate_expansion_reduction_pct": f"{(total_base - total_variant) / total_base * 100.0:.3f}",
                "median_reduction_pct": f"{statistics.median(reductions):.3f}",
                "q1_reduction_pct": f"{percentile(reductions, 0.25):.3f}",
                "q3_reduction_pct": f"{percentile(reductions, 0.75):.3f}",
                "variant_fewer_queries": wins,
                "variant_more_queries": sum(value < 0 for value in reductions),
                "equal_queries": sum(value == 0 for value in reductions),
            })

    write_csv(
        result_root / "summary.csv",
        ["network", "config", "calls", "queries", "median_ms", "q1_ms", "q3_ms",
         "mean_expanded", "median_expanded", "mean_forward_expanded",
         "mean_backward_expanded", "mean_best_updates", "mean_scanned_edges"],
        summary,
    )
    write_csv(
        result_root / "contrasts.csv",
        ["network", "base", "variant", "contrast", "queries", "mean_query_reduction_pct",
         "aggregate_expansion_reduction_pct", "median_reduction_pct",
         "q1_reduction_pct", "q3_reduction_pct",
         "variant_fewer_queries", "variant_more_queries", "equal_queries"],
        contrasts,
    )
    write_csv(
        result_root / "query_contrasts.csv",
        ["network", "query", "source_index", "target_index", "base", "variant",
         "base_expanded", "variant_expanded", "difference", "variant_reduction_pct"],
        query_contrasts,
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: summarize_direction_controls.py RESULT_DIRECTORY")
    main(Path(sys.argv[1]))
