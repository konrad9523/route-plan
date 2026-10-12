"""武汉路网 A* 逐层消融实验：收件箱版 -> 工作版 -> ALT。

运行结果写入本机 cache/a3_wuhan/runs/，归档 JSON 不会被覆盖。
"""

from __future__ import annotations

import json
import math
import pickle
import random
import statistics
import sys
import time
from heapq import heappop, heappush
from pathlib import Path

import _paths

DATA_FILE = _paths.processed_dir() / "graph.pkl"
RESULT_FILE = _paths.RESULT_DIR / "wuhan_astar_layered_results.json"

import astar as inbox_astar  # noqa: E402
import dijkstra as inbox_dijkstra  # noqa: E402
import astar_alt  # noqa: E402
import improved_algorithms as work  # noqa: E402

SEED = 2026
QUERY_COUNT = 50
ROUNDS = 5
ALT_LANDMARKS = 8
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
    if isinstance(outcome, work.RouteOutcome):
        return outcome.distance, outcome.expanded, outcome.pushed, outcome
    # inbox A*: nodes, edges, distance, visited_count
    return outcome[2], outcome[3], None, outcome


def reset_work_cache():
    work._Prepared._cache_key = None
    work._Prepared._cache_val = None


def valid_edge_path(outcome, edge_records):
    distance, _expanded, _pushed, raw = unpack(outcome)
    if isinstance(raw, work.RouteOutcome):
        nodes, edge_ids = raw.node_path, raw.edge_path
    else:
        nodes, edge_ids = raw[0], raw[1]
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
    return math.isclose(math.fsum(lengths), distance, rel_tol=1e-10, abs_tol=TOL_M)


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
        graph_pairs[u] = [(v, weight) for v, weight, _edge_id in graph_edges[u]]
    positions = {u: (float(data["lon"][u]), float(data["lat"][u])) for u in range(n)}
    edge_records = data["edges"]

    bad_weights = sum(not math.isfinite(float(w)) or float(w) < 0 for w in data["weights"])
    bad_endpoints = sum(v not in graph_edges for edges in graph_edges.values() for v, _w, _eid in edges)
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

    # ALT 预处理是独立成本，不能混入单次热查询耗时。
    t0 = time.perf_counter()
    alt = astar_alt.LandmarkALT(graph_edges, positions, scc, ALT_LANDMARKS)
    alt_prepare_ms = (time.perf_counter() - t0) * 1000

    def run_work_hav_cold(a, b):
        # 控制组：每次查询前清空工作版准备缓存，用来显示一次性准备成本。
        reset_work_cache()
        return work.astar(graph_edges, positions, a, b, heuristic=work.haversine)

    specs = [
        ("L0 收件箱 Haversine A*", lambda a, b: inbox_astar.astar(graph_edges, positions, a, b)),
        ("控制组 工作版 Haversine（冷启动）", run_work_hav_cold),
        ("L1 工作版 Haversine A*", lambda a, b: work.astar(graph_edges, positions, a, b,
                                                              heuristic=work.haversine)),
        ("L2 工作版平面投影 A*", lambda a, b: work.astar(graph_edges, positions, a, b,
                                                            heuristic=work.plane_projection)),
        ("控制组 ALT（不含平面）", lambda a, b: alt.astar(a, b, include_plane=False)),
        ("L3 平面投影 + ALT A*", lambda a, b: alt.astar(a, b, include_plane=True)),
        ("L4 工作版双向 A*", lambda a, b: work.bidirectional_astar(graph_edges, positions, a, b)),
    ]

    # 先用收件箱 Dijkstra 生成独立最优距离参考，不把这部分计入任何算法计时。
    references = [inbox_dijkstra.dijkstra(graph_pairs, a, b) for a, b in pairs]
    correctness = {}
    for name, run in specs:
        mismatches = 0
        max_error = 0.0
        invalid_paths = 0
        for pair, reference in zip(pairs, references):
            result = run(*pair)
            distance, _expanded, _pushed, _raw = unpack(result)
            error = abs(distance - reference[1])
            max_error = max(max_error, error)
            mismatches += error > TOL_M
            invalid_paths += not valid_edge_path(result, edge_records)
        correctness[name] = {
            "distance_mismatches": mismatches,
            "max_abs_error_m": max_error,
            "invalid_edge_paths": invalid_paths,
        }

    # 工作版的图准备时间单独记录；热查询阶段不重复计入。
    reset_work_cache()
    t0 = time.perf_counter()
    work._Prepared(graph_edges, positions)
    work_prepare_ms = (time.perf_counter() - t0) * 1000
    for _name, run in specs:
        run(*pairs[0])

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
                if pushed is not None:
                    pushed_sums[name] += pushed

    benchmark = {}
    for name, _run in specs:
        values = round_times[name]
        benchmark[name] = {
            "median_ms_per_query": statistics.median(values),
            "min_ms_per_query": min(values),
            "max_ms_per_query": max(values),
            "mean_expanded": expanded_sums[name] / (ROUNDS * len(pairs)),
            "mean_pushed": pushed_sums[name] / (ROUNDS * len(pairs)) if pushed_sums[name] else None,
            "last_round_expanded_median": statistics.median(
                [unpack(outcome)[1] for outcome in last_outcomes[name]]),
            "last_round_expanded_min": min(unpack(outcome)[1] for outcome in last_outcomes[name]),
            "last_round_expanded_max": max(unpack(outcome)[1] for outcome in last_outcomes[name]),
            "last_round_pushed_median": (
                statistics.median([unpack(outcome)[2] for outcome in last_outcomes[name]])
                if unpack(last_outcomes[name][0])[2] is not None else None),
            "last_round_pushed_min": (
                min(unpack(outcome)[2] for outcome in last_outcomes[name])
                if unpack(last_outcomes[name][0])[2] is not None else None),
            "last_round_pushed_max": (
                max(unpack(outcome)[2] for outcome in last_outcomes[name])
                if unpack(last_outcomes[name][0])[2] is not None else None),
            "round_ms_per_query": values,
        }

    # 把一次性准备成本显式摊入本次 50 组查询，避免只看热查询而高估预处理算法。
    for name in ("L1 工作版 Haversine A*", "L2 工作版平面投影 A*", "L3 平面投影 + ALT A*"):
        prep = work_prepare_ms if name.startswith("L1") or name.startswith("L2") else alt_prepare_ms
        benchmark[name]["amortized_ms_per_query_for_this_batch"] = (
            benchmark[name]["median_ms_per_query"] + prep / len(pairs)
        )

    result = {
        "dataset": {
            "path": str(DATA_FILE), "nodes": n,
            "directed_edges": len(edge_records), "largest_scc_nodes": len(scc),
            "weight_unit": "meter", "bad_weights": bad_weights,
            "undefined_endpoints": bad_endpoints,
        },
        "queries": {"seed": SEED, "count": len(pairs), "ordered_pairs": pairs,
                    "source": "unique ordered pairs sampled from largest SCC"},
        "method": {"rounds": ROUNDS, "timing": "interleaved; warm rows exclude preprocessing; cold control intentionally rebuilds",
                   "distance_tolerance_m": TOL_M, "work_prepare_ms_once": work_prepare_ms,
                   "alt_landmark_count": ALT_LANDMARKS, "alt_prepare_ms_once": alt_prepare_ms},
        "landmarks": alt.landmarks,
        "correctness_vs_inbox_dijkstra": correctness,
        "benchmark": benchmark,
    }
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"武汉 {n:,} nodes / {len(edge_records):,} directed edges; "
          f"SCC={len(scc):,}, queries={len(pairs)}, rounds={ROUNDS}")
    print(f"工作版 _Prepared 一次准备: {work_prepare_ms:.3f} ms")
    print(f"ALT 地标: {alt.landmarks}")
    print(f"ALT 一次预处理: {alt_prepare_ms:.3f} ms")
    for name, _run in specs:
        row = benchmark[name]
        print(f"{name}: median={row['median_ms_per_query']:.3f} ms/query "
              f"range={row['min_ms_per_query']:.3f}..{row['max_ms_per_query']:.3f}; "
              f"expanded={row['mean_expanded']:.1f}; pushed={row['mean_pushed']}")
    print("Correctness:", json.dumps(correctness, ensure_ascii=False))
    print("Saved", RESULT_FILE)


if __name__ == "__main__":
    main()
