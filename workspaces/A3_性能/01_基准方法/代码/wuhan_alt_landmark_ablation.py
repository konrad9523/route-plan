"""武汉路网 ALT 地标数量消融实验：4、8、16 个地标。

固定同一批查询和计时流程，只改变地标数量。结果写入本机 cache/a3_wuhan/runs/。
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
RESULT_FILE = _paths.RESULT_DIR / "wuhan_alt_landmark_results.json"

import astar_alt  # noqa: E402
import dijkstra as inbox_dijkstra  # noqa: E402
import improved_algorithms as work  # noqa: E402

SEED = 2026
QUERY_COUNT = 50
ROUNDS = 5
LANDMARK_COUNTS = (4, 8, 16)
TOL_M = 1e-5


def largest_scc(graph, n):
    reverse = [[] for _ in range(n)]
    for u, edges in graph.items():
        for v, *_ in edges:
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


def unpack(outcome):
    return outcome.distance, outcome.expanded, outcome.pushed, outcome


def valid_edge_path(outcome, edge_records):
    nodes, edge_ids = outcome.node_path, outcome.edge_path
    if len(nodes) != len(edge_ids) + 1:
        return False
    lengths = []
    for u, v, edge_id in zip(nodes, nodes[1:], edge_ids):
        if not 0 <= edge_id < len(edge_records):
            return False
        edge = edge_records[edge_id]
        if edge[0] != u or edge[1] != v:
            return False
        lengths.append(float(edge[2]))
    return math.isclose(math.fsum(lengths), outcome.distance,
                        rel_tol=1e-10, abs_tol=TOL_M)


def main():
    with DATA_FILE.open("rb") as fh:
        data = pickle.load(fh)
    n = int(data["n_nodes"])
    graph_edges = {}
    graph_pairs = {}
    for u in range(n):
        lo, hi = data["indptr"][u], data["indptr"][u + 1]
        graph_edges[u] = [
            (int(data["indices"][i]), float(data["weights"][i]), int(data["edge_ids"][i]))
            for i in range(lo, hi)
        ]
        graph_pairs[u] = [(v, weight) for v, weight, _eid in graph_edges[u]]
    positions = {u: (float(data["lon"][u]), float(data["lat"][u])) for u in range(n)}
    edge_records = data["edges"]

    bad_weights = sum(not math.isfinite(float(w)) or float(w) < 0 for w in data["weights"])
    bad_endpoints = sum(v not in graph_edges for edges in graph_edges.values()
                        for v, _w, _eid in edges)
    if bad_weights or bad_endpoints:
        raise ValueError(f"拒绝测试：负/非有限权边={bad_weights}，未定义邻接点={bad_endpoints}")

    scc = largest_scc(graph_edges, n)
    rng = random.Random(SEED)
    pairs, seen_pairs = [], set()
    while len(pairs) < QUERY_COUNT:
        start, goal = rng.choice(scc), rng.choice(scc)
        if start != goal and (start, goal) not in seen_pairs:
            seen_pairs.add((start, goal))
            pairs.append((start, goal))

    prepared = {}
    prepare_ms = {}
    for count in LANDMARK_COUNTS:
        t0 = time.perf_counter()
        prepared[count] = astar_alt.LandmarkALT(
            graph_edges, positions, scc, landmark_count=count)
        prepare_ms[count] = (time.perf_counter() - t0) * 1000

    specs = [
        (f"ALT-{count}", lambda a, b, count=count: prepared[count].astar(
            a, b, include_plane=False))
        for count in LANDMARK_COUNTS
    ]

    references = [inbox_dijkstra.dijkstra(graph_pairs, a, b) for a, b in pairs]
    correctness = {}
    for name, run in specs:
        mismatches = 0
        max_error = 0.0
        invalid_paths = 0
        for pair, reference in zip(pairs, references):
            result = run(*pair)
            distance, _expanded, _pushed, outcome = unpack(result)
            error = abs(distance - reference[1])
            max_error = max(max_error, error)
            mismatches += error > TOL_M
            invalid_paths += not valid_edge_path(outcome, edge_records)
        correctness[name] = {
            "distance_mismatches": mismatches,
            "max_abs_error_m": max_error,
            "invalid_edge_paths": invalid_paths,
        }

    round_times = {name: [] for name, _run in specs}
    expanded_sums = {name: 0 for name, _run in specs}
    pushed_sums = {name: 0 for name, _run in specs}
    last_outcomes = {}
    for round_index in range(ROUNDS):
        shift = round_index % len(specs)
        for name, run in specs[shift:] + specs[:shift]:
            t0 = time.perf_counter()
            outcomes = [run(a, b) for a, b in pairs]
            round_times[name].append((time.perf_counter() - t0) * 1000 / len(pairs))
            last_outcomes[name] = outcomes
            for outcome in outcomes:
                _distance, expanded, pushed, _raw = unpack(outcome)
                expanded_sums[name] += expanded
                pushed_sums[name] += pushed

    benchmark = {}
    for name, _run in specs:
        count = int(name.split("-")[1])
        values = round_times[name]
        last = last_outcomes[name]
        expanded = [unpack(outcome)[1] for outcome in last]
        pushed = [unpack(outcome)[2] for outcome in last]
        median_ms = statistics.median(values)
        benchmark[name] = {
            "landmark_count": count,
            "median_ms_per_query": median_ms,
            "min_ms_per_query": min(values),
            "max_ms_per_query": max(values),
            "mean_expanded": expanded_sums[name] / (ROUNDS * len(pairs)),
            "mean_pushed": pushed_sums[name] / (ROUNDS * len(pairs)),
            "last_round_expanded_min": min(expanded),
            "last_round_expanded_median": statistics.median(expanded),
            "last_round_expanded_max": max(expanded),
            "last_round_pushed_min": min(pushed),
            "last_round_pushed_median": statistics.median(pushed),
            "last_round_pushed_max": max(pushed),
            "prepare_ms_once": prepare_ms[count],
            "amortized_ms_per_query_for_this_batch": median_ms + prepare_ms[count] / len(pairs),
            "round_ms_per_query": values,
        }

    result = {
        "dataset": {
            "path": str(DATA_FILE), "nodes": n,
            "directed_edges": len(data["edges"]), "largest_scc_nodes": len(scc),
            "weight_unit": "meter", "bad_weights": bad_weights,
            "undefined_endpoints": bad_endpoints,
        },
        "queries": {"seed": SEED, "count": len(pairs), "ordered_pairs": pairs,
                    "source": "unique ordered pairs sampled from largest SCC"},
        "method": {
            "rounds": ROUNDS,
            "timing": "interleaved warm ALT-only queries; preprocessing excluded from query timing",
            "distance_tolerance_m": TOL_M,
            "landmark_counts": list(LANDMARK_COUNTS),
        },
        "landmarks": {str(count): prepared[count].landmarks for count in LANDMARK_COUNTS},
        "correctness_vs_inbox_dijkstra": correctness,
        "benchmark": benchmark,
    }
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"武汉 {n:,} nodes / {len(data['edges']):,} directed edges; "
          f"SCC={len(scc):,}, queries={len(pairs)}, rounds={ROUNDS}")
    for name, _run in specs:
        row = benchmark[name]
        print(f"{name}: prepare={row['prepare_ms_once']:.3f} ms; "
              f"median={row['median_ms_per_query']:.3f} ms/query "
              f"range={row['min_ms_per_query']:.3f}..{row['max_ms_per_query']:.3f}; "
              f"amortized50={row['amortized_ms_per_query_for_this_batch']:.3f}; "
              f"expanded={row['mean_expanded']:.1f}; pushed={row['mean_pushed']:.1f}")
    print("Correctness:", json.dumps(correctness, ensure_ascii=False))
    print("Saved", RESULT_FILE)


if __name__ == "__main__":
    main()
