"""在工作区已有的武汉 OSM 路网，对拍收件箱版与 GPT 工作版 Dijkstra。

运行：python wuhan_dijkstra_benchmark.py
测试数据只读；结果写到本机 cache/a3_wuhan/runs/，不覆盖归档结果。
"""

from __future__ import annotations

import json
import math
import pickle
import random
import statistics
import sys
import time
from pathlib import Path


import _paths

DATA_FILE = _paths.processed_dir() / "graph.pkl"
RESULT_FILE = _paths.RESULT_DIR / "wuhan_dijkstra_results.json"

import dijkstra as inbox_dijkstra  # noqa: E402
import improved_algorithms as work  # noqa: E402


QUERY_SEED = 2026
QUERY_COUNT = 50
ROUNDS = 5
ABS_TOL = 1e-5


def largest_scc(graph: dict[int, list[tuple]], n: int) -> list[int]:
    """Iterative Kosaraju; returns a largest strongly connected component."""
    reverse = [[] for _ in range(n)]
    for u, outgoing in graph.items():
        for v, *_ in outgoing:
            reverse[v].append(u)

    seen = bytearray(n)
    order = []
    for root in range(n):
        if seen[root]:
            continue
        seen[root] = 1
        stack = [(root, 0)]
        while stack:
            u, i = stack[-1]
            if i < len(graph[u]):
                v = graph[u][i][0]
                stack[-1] = (u, i + 1)
                if not seen[v]:
                    seen[v] = 1
                    stack.append((v, 0))
            else:
                order.append(u)
                stack.pop()

    seen = bytearray(n)
    best = []
    for root in reversed(order):
        if seen[root]:
            continue
        seen[root] = 1
        component = []
        stack = [root]
        while stack:
            u = stack.pop()
            component.append(u)
            for v in reverse[u]:
                if not seen[v]:
                    seen[v] = 1
                    stack.append(v)
        if len(component) > len(best):
            best = component
    return best


def heuristic_consistency(graph, positions, goals):
    """Check w(u,v)+h(v,t)-h(u,t) >= 0 over all edges for sampled goals."""
    minimum = math.inf
    violations = 0
    checked = 0
    for goal in goals:
        glon, glat = positions[goal]
        h = [work.plane_projection(*positions[u], glon, glat) for u in range(len(graph))]
        for u, outgoing in graph.items():
            hu = h[u]
            for v, weight, _eid in outgoing:
                reduced = weight + h[v] - hu
                minimum = min(minimum, reduced)
                violations += reduced < -ABS_TOL
                checked += 1
    return {"goals_checked": len(goals), "edges_checked": checked,
            "violations_below_minus_tolerance": violations,
            "minimum_reduced_edge_m": minimum}


def valid_edge_path(outcome, edge_records):
    nodes, edge_ids = outcome.node_path, outcome.edge_path
    if len(nodes) != len(edge_ids) + 1:
        return False
    lengths = []
    for u, v, eid in zip(nodes, nodes[1:], edge_ids):
        if not 0 <= eid < len(edge_records):
            return False
        edge = edge_records[eid]
        if edge[0] != u or edge[1] != v:
            return False
        lengths.append(float(edge[2]))
    return math.isclose(math.fsum(lengths), outcome.distance,
                        rel_tol=1e-10, abs_tol=ABS_TOL)


def main():
    print(f"Loading {DATA_FILE}", flush=True)
    with DATA_FILE.open("rb") as fh:
        data = pickle.load(fh)

    n = data["n_nodes"]
    indptr, indices = data["indptr"], data["indices"]
    weights, edge_ids = data["weights"], data["edge_ids"]
    edge_records = data["edges"]
    graph_pairs = {}
    graph_edges = {}
    for u in range(n):
        start, end = indptr[u], indptr[u + 1]
        pairs, triples = [], []
        for i in range(start, end):
            v, weight, eid = int(indices[i]), float(weights[i]), int(edge_ids[i])
            pairs.append((v, weight))
            triples.append((v, weight, eid))
        graph_pairs[u] = pairs
        graph_edges[u] = triples
    positions = {u: (float(data["lon"][u]), float(data["lat"][u]))
                 for u in range(n)}

    negative_or_nonfinite = sum(
        not math.isfinite(float(weight)) or float(weight) < 0 for weight in weights
    )
    if negative_or_nonfinite:
        raise ValueError(f"数据含 {negative_or_nonfinite} 条负权或非有限边，停止 Dijkstra 测试")

    print("Finding largest SCC ...", flush=True)
    scc = largest_scc(graph_edges, n)
    rng = random.Random(QUERY_SEED)
    pairs = []
    seen_pairs = set()
    while len(pairs) < QUERY_COUNT:
        source, target = rng.choice(scc), rng.choice(scc)
        if source != target and (source, target) not in seen_pairs:
            seen_pairs.add((source, target))
            pairs.append((source, target))

    goals = sorted({target for _, target in pairs})
    consistency = heuristic_consistency(graph_edges, positions, goals)
    reduced_enabled = consistency["violations_below_minus_tolerance"] == 0
    tested_work_variants = ["work_plain"]
    if reduced_enabled:
        tested_work_variants.append("work_reweighted")
    print(f"Graph: {n:,} nodes / {len(edge_records):,} directed edges; "
          f"largest SCC {len(scc):,}; pairs {len(pairs)}", flush=True)
    print(f"Plane-potential consistency: {consistency['violations_below_minus_tolerance']} "
          f"violations across {consistency['edges_checked']:,} edge checks", flush=True)

    # Measure one-time work-version preparation separately from warm query time.
    work._Prepared._cache_key = None
    work._Prepared._cache_val = None
    t0 = time.perf_counter()
    work._Prepared(graph_edges, positions)
    prepared_ms = (time.perf_counter() - t0) * 1000

    mismatches = {name: 0 for name in tested_work_variants}
    max_abs_error = {name: 0.0 for name in tested_work_variants}
    bad_paths = {name: 0 for name in tested_work_variants}
    for i, (source, target) in enumerate(pairs, 1):
        _path, reference, _visited = inbox_dijkstra.dijkstra(
            graph_pairs, source, target
        )
        plain = work.dijkstra(graph_edges, positions, source, target)
        variants = [("work_plain", plain)]
        if reduced_enabled:
            reduced = work.dijkstra(
                graph_edges, positions, source, target, use_reduced=True,
                heuristic=work.plane_projection,
            )
            variants.append(("work_reweighted", reduced))
        for name, result in variants:
            error = abs(result.distance - reference) if result.found else math.inf
            max_abs_error[name] = max(max_abs_error[name], error)
            mismatches[name] += error > ABS_TOL
            bad_paths[name] += not valid_edge_path(result, edge_records)
        if i % 10 == 0:
            print(f"  correctness {i}/{len(pairs)}", flush=True)

    specs = [
        ("inbox", lambda a, b: inbox_dijkstra.dijkstra(graph_pairs, a, b)),
        ("work_plain", lambda a, b: work.dijkstra(graph_edges, positions, a, b)),
    ]
    if reduced_enabled:
        specs.append((
            "work_reweighted",
            lambda a, b: work.dijkstra(
                graph_edges, positions, a, b, use_reduced=True,
                heuristic=work.plane_projection,
            ),
        ))

    # Warm each path once; all algorithms then run the same fixed pair set.
    for _name, run in specs:
        run(*pairs[0])
    per_round = {name: [] for name, _ in specs}
    expanded_totals = {name: 0 for name, _ in specs}
    for r in range(ROUNDS):
        shift = r % len(specs)
        order = specs[shift:] + specs[:shift]
        for name, run in order:
            t0 = time.perf_counter()
            outcomes = [run(a, b) for a, b in pairs]
            elapsed_ms = (time.perf_counter() - t0) * 1000
            per_round[name].append(elapsed_ms / len(pairs))
            if name == "inbox":
                expanded_totals[name] += sum(out[2] for out in outcomes)
            else:
                expanded_totals[name] += sum(out.expanded for out in outcomes)
        print(f"  timing round {r + 1}/{ROUNDS}", flush=True)

    timing = {}
    for name, _run in specs:
        timing[name] = {
            "round_ms_per_query": per_round[name],
            "median_ms_per_query": statistics.median(per_round[name]),
            "mean_expanded": expanded_totals[name] / (ROUNDS * len(pairs)),
        }

    result = {
        "dataset": {
            "file": str(DATA_FILE),
            "source": "OpenStreetMap / Overpass API; wuhan_drive.osm processed snapshot",
            "nodes": n,
            "directed_edges": len(edge_records),
            "largest_scc_nodes": len(scc),
            "negative_or_nonfinite_edges": negative_or_nonfinite,
            "weight": "length in meters",
        },
        "queries": {
            "seed": QUERY_SEED,
            "count": len(pairs),
            "sampling": "unique ordered pairs drawn from largest SCC; source != target",
            "targets_checked_for_plane_consistency": len(goals),
        },
        "plane_consistency": consistency,
        "reweighted_plane_branch": {
            "tested": reduced_enabled,
            "skip_reason": None if reduced_enabled else (
                "Plane potential produced negative reduced edges on the tested goals; "
                "label-setting Dijkstra is not benchmarked with this infeasible potential."
            ),
        },
        "correctness": {
            "reference": "inbox dijkstra.py",
            "distance_tolerance_m": ABS_TOL,
            "distance_mismatches": mismatches,
            "max_absolute_distance_error_m": max_abs_error,
            "invalid_work_edge_paths": bad_paths,
        },
        "benchmark": {
            "rounds": ROUNDS,
            "timing_scope": "warm query only; loading, CSR conversion, SCC and one-time _Prepared excluded",
            "work_preparation_ms": prepared_ms,
            "algorithms": timing,
        },
    }
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPreparation: {prepared_ms:.3f} ms")
    for name, values in timing.items():
        print(f"{name:18s} median={values['median_ms_per_query']:.3f} ms/query; "
              f"expanded={values['mean_expanded']:.1f}")
    print(f"Correctness mismatches: {mismatches}")
    print(f"Invalid work edge paths: {bad_paths}")
    print(f"Saved {RESULT_FILE}")


if __name__ == "__main__":
    main()
