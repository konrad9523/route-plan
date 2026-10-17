"""武汉路网 Dijkstra 逐层消融：从收件箱原版累积到 GPT 工作版。

仅使用处理后的武汉 graph.pkl。固定同一组武汉点对，对每层测正确性、展开量和交错耗时。
运行：由项目 Python 环境执行本文件；结果写入本机 cache/a3_wuhan/runs/。
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
from itertools import count
from pathlib import Path

import _paths

DATA_FILE = _paths.processed_dir() / "graph.pkl"
RESULT_FILE = _paths.RESULT_DIR / "wuhan_dijkstra_layered_results.json"

import dijkstra as inbox  # noqa: E402
import improved_algorithms as work  # noqa: E402

SEED = 2026
QUERY_COUNT = 50
ROUNDS = 5
ORDER_MODE = "fixed"
ORDER_SEED = 20260927
TIMING_MODE = "batch"
TOL_M = 1e-5


def largest_scc(graph: dict[int, list[tuple]], n: int) -> list[int]:
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


def unwind(parent, start, goal):
    nodes = [goal]
    edges = []
    node = goal
    while node != start:
        previous, eid = parent[node]
        edges.append(eid)
        node = previous
        nodes.append(node)
    nodes.reverse()
    edges.reverse()
    return nodes, edges


def triple_input_control(graph, start, goal):
    """控制组：收件箱搜索逻辑不变，只把输入换成三元组并忽略 edge_id。"""
    if start not in graph:
        raise ValueError(f"起点 {start!r} 不在图中")
    if goal not in graph:
        raise ValueError(f"终点 {goal!r} 不在图中")
    if start == goal:
        return [start], 0.0, 1
    seen, settled = {start: 0.0}, {}
    parent = {start: None}
    tie = count()
    heap = [(0.0, next(tie), start)]
    while heap:
        distance, _, u = heappop(heap)
        if u in settled:
            continue
        settled[u] = distance
        if u == goal:
            nodes = [goal]
            node = goal
            while node != start:
                node = parent[node]
                nodes.append(node)
            nodes.reverse()
            return nodes, settled[goal], len(settled)
        for v, weight, _eid in graph[u]:
            if v not in graph:
                raise ValueError(f"邻接点 {v!r} 未在 graph 中定义")
            if weight < 0:
                raise ValueError(f"Dijkstra 不允许负权边：{u!r}->{v!r}")
            candidate = distance + weight
            if v in settled:
                if candidate < settled[v]:
                    raise ValueError("发现矛盾路径，请检查负权边")
                continue
            if candidate < seen.get(v, math.inf):
                seen[v] = candidate
                parent[v] = u
                heappush(heap, (candidate, next(tie), v))
    return [], math.inf, len(settled)


def layer1_edge_ids(graph, start, goal):
    """收件箱搜索流程不变；新增 parent=(previous_node, edge_id) 和边路径。"""
    if start not in graph or goal not in graph:
        raise ValueError("起点/终点不在图中")
    if start == goal:
        return [start], [], 0.0, 1
    seen, settled = {start: 0.0}, {}
    parent = {start: None}
    tie = count()
    heap = [(0.0, next(tie), start)]
    while heap:
        distance, _, u = heappop(heap)
        if u in settled:
            continue
        settled[u] = distance
        if u == goal:
            nodes, edges = unwind(parent, start, goal)
            return nodes, edges, settled[goal], len(settled)
        for v, weight, eid in graph[u]:
            if v not in graph:
                raise ValueError(f"邻接点 {v!r} 未在 graph 中定义")
            if weight < 0:
                raise ValueError(f"Dijkstra 不允许负权边：{u!r}->{v!r}")
            candidate = distance + weight
            if v in settled:
                if candidate < settled[v]:
                    raise ValueError("发现矛盾路径，请检查负权边")
                continue
            if candidate < seen.get(v, math.inf):
                seen[v] = candidate
                parent[v] = (u, eid)
                heappush(heap, (candidate, next(tie), v))
    return [], [], math.inf, len(settled)


def layer2_settled_set(graph, start, goal):
    """再改为工作版 dist + settled-set 松弛状态，暂保留输入检查和元组结果。"""
    if start not in graph or goal not in graph:
        raise ValueError("起点/终点不在图中")
    if start == goal:
        return [start], [], 0.0, 1
    best = {start: 0.0}
    settled = set()
    parent = {start: None}
    tie = count()
    heap = [(0.0, next(tie), start)]
    while heap:
        distance, _, u = heappop(heap)
        if u in settled:
            continue
        settled.add(u)
        if u == goal:
            nodes, edges = unwind(parent, start, goal)
            return nodes, edges, distance, len(settled)
        for v, weight, eid in graph[u]:
            if v in settled:
                continue
            if v not in graph:
                raise ValueError(f"邻接点 {v!r} 未在 graph 中定义")
            if weight < 0:
                raise ValueError(f"Dijkstra 不允许负权边：{u!r}->{v!r}")
            candidate = distance + weight
            if candidate < best.get(v, math.inf):
                best[v] = candidate
                parent[v] = (u, eid)
                heappush(heap, (candidate, next(tie), v))
    return [], [], math.inf, len(settled)


def layer3_route_outcome(graph, start, goal):
    """再加 RouteOutcome 与 pushed 计数；保留边检查。"""
    if start not in graph or goal not in graph:
        raise ValueError("起点/终点不在图中")
    if start == goal:
        return work.RouteOutcome("dijkstra", True, [start], [], 0.0, 1, 1)
    best = {start: 0.0}
    settled = set()
    parent = {start: None}
    tie = count()
    heap = [(0.0, next(tie), start)]
    pushed = 1
    while heap:
        distance, _, u = heappop(heap)
        if u in settled:
            continue
        settled.add(u)
        if u == goal:
            nodes, edges = unwind(parent, start, goal)
            return work.RouteOutcome("dijkstra", True, nodes, edges, distance,
                                     len(settled), pushed)
        for v, weight, eid in graph[u]:
            if v in settled:
                continue
            if v not in graph:
                raise ValueError(f"邻接点 {v!r} 未在 graph 中定义")
            if weight < 0:
                raise ValueError(f"Dijkstra 不允许负权边：{u!r}->{v!r}")
            candidate = distance + weight
            if candidate < best.get(v, math.inf):
                best[v] = candidate
                parent[v] = (u, eid)
                heappush(heap, (candidate, next(tie), v))
                pushed += 1
    return work.RouteOutcome("dijkstra", False, expanded=len(settled), pushed=pushed)


def layer4_validated_input(graph, start, goal):
    """上游预检已确认图有效；搜索时省去重复的邻接/负权检查。"""
    if start not in graph or goal not in graph:
        raise ValueError("起点/终点不在图中")
    if start == goal:
        return work.RouteOutcome("dijkstra", True, [start], [], 0.0, 1, 1)
    best = {start: 0.0}
    settled = set()
    parent = {start: None}
    tie = count()
    heap = [(0.0, next(tie), start)]
    pushed = 1
    while heap:
        distance, _, u = heappop(heap)
        if u in settled:
            continue
        settled.add(u)
        if u == goal:
            nodes, edges = unwind(parent, start, goal)
            return work.RouteOutcome("dijkstra", True, nodes, edges, distance,
                                     len(settled), pushed)
        for v, weight, eid in graph[u]:
            if v in settled:
                continue
            candidate = distance + weight
            if candidate < best.get(v, math.inf):
                best[v] = candidate
                parent[v] = (u, eid)
                heappush(heap, (candidate, next(tie), v))
                pushed += 1
    return work.RouteOutcome("dijkstra", False, expanded=len(settled), pushed=pushed)


def unpack(result):
    if isinstance(result, work.RouteOutcome):
        return result.distance, result.expanded, result.pushed, result
    if len(result) == 3:  # 收件箱 API: nodes, distance, visited
        return result[1], result[2], None, result
    return result[2], result[3], None, result


def valid_edge_path(outcome, edge_records):
    if not isinstance(outcome, work.RouteOutcome):
        if len(outcome) != 4:
            return True
        nodes, edge_ids, distance = outcome[0], outcome[1], outcome[2]
    else:
        nodes, edge_ids, distance = outcome.node_path, outcome.edge_path, outcome.distance
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
    return math.isclose(math.fsum(lengths), distance, rel_tol=1e-10, abs_tol=TOL_M)


def main():
    with DATA_FILE.open("rb") as fh:
        data = pickle.load(fh)
    n = data["n_nodes"]
    graph_pairs, graph_edges = {}, {}
    for u in range(n):
        lo, hi = data["indptr"][u], data["indptr"][u + 1]
        graph_pairs[u] = [(int(data["indices"][i]), float(data["weights"][i]))
                          for i in range(lo, hi)]
        graph_edges[u] = [(int(data["indices"][i]), float(data["weights"][i]),
                           int(data["edge_ids"][i])) for i in range(lo, hi)]
    positions = {u: (float(data["lon"][u]), float(data["lat"][u])) for u in range(n)}
    edge_records = data["edges"]

    # Treat the dataset as a trusted input only after this one-time full validation.
    bad_weights = sum(not math.isfinite(float(w)) or float(w) < 0 for w in data["weights"])
    bad_endpoints = sum(v not in graph_edges for outgoing in graph_edges.values()
                        for v, _w, _eid in outgoing)
    if bad_weights or bad_endpoints:
        raise ValueError(f"拒绝测试：负/非有限权边={bad_weights}，未定义邻接点={bad_endpoints}")
    print(f"已预检武汉图：{n:,} nodes, {len(data['edges']):,} edges; "
          f"bad_weights={bad_weights}, undefined_endpoints={bad_endpoints}", flush=True)

    scc = largest_scc(graph_edges, n)
    rng = random.Random(SEED)
    pairs, seen_pairs = [], set()
    while len(pairs) < QUERY_COUNT:
        a, b = rng.choice(scc), rng.choice(scc)
        if a != b and (a, b) not in seen_pairs:
            seen_pairs.add((a, b))
            pairs.append((a, b))

    specs = [
        ("收件箱基线", lambda a, b: inbox.dijkstra(graph_pairs, a, b)),
        ("控制组：收件箱逻辑+三元组输入", lambda a, b: triple_input_control(graph_edges, a, b)),
        ("第1层：父链记录 edge_id", lambda a, b: layer1_edge_ids(graph_edges, a, b)),
        ("第2层：dist + settled-set", lambda a, b: layer2_settled_set(graph_edges, a, b)),
        ("第3层：RouteOutcome + pushed", lambda a, b: layer3_route_outcome(graph_edges, a, b)),
        ("第4层：输入边界校验后省去热循环检查", lambda a, b: layer4_validated_input(graph_edges, a, b)),
        ("第5层：工作版 _Prepared 缓存", lambda a, b: work.dijkstra(graph_edges, positions, a, b)),
    ]

    # Correctness against the untouched inbox implementation and edge-ID path checks.
    correct = {name: {"distance_mismatches": 0, "max_abs_error_m": 0.0,
                      "invalid_edge_paths": 0} for name, _ in specs[1:]}
    for query_index, (a, b) in enumerate(pairs, 1):
        reference = inbox.dijkstra(graph_pairs, a, b)
        for name, run in specs[1:]:
            result = run(a, b)
            distance, _expanded, _pushed, _ = unpack(result)
            err = abs(distance - reference[1])
            correct[name]["max_abs_error_m"] = max(correct[name]["max_abs_error_m"], err)
            correct[name]["distance_mismatches"] += err > TOL_M
            correct[name]["invalid_edge_paths"] += not valid_edge_path(result, edge_records)
        if query_index % 10 == 0:
            print(f"正确性对拍 {query_index}/{len(pairs)}", flush=True)

    # Measure work preparation once, separately; then benchmark warmed queries.
    work._Prepared._cache_key = None
    work._Prepared._cache_val = None
    t0 = time.perf_counter()
    work._Prepared(graph_edges, positions)
    prepare_ms = (time.perf_counter() - t0) * 1000
    for _name, run in specs:
        run(*pairs[0])

    round_times = {name: [] for name, _ in specs}
    query_times = {name: [] for name, _ in specs}
    paired_query_changes = {name: {"inbox": [], "previous": []} for name, _ in specs}
    expanded_sums = {name: 0 for name, _ in specs}
    pushed_sums = {name: 0 for name, _ in specs}
    order_rng = random.Random(ORDER_SEED)
    names = [name for name, _run in specs]
    for round_index in range(ROUNDS):
        if TIMING_MODE == "paired_query":
            round_samples = {name: [] for name in names}
            pair_order = pairs.copy()
            order_rng.shuffle(pair_order)
            for a, b in pair_order:
                order = specs.copy()
                order_rng.shuffle(order)
                query_ms = {}
                for name, run in order:
                    t0 = time.perf_counter()
                    result = run(a, b)
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                    query_ms[name] = elapsed_ms
                    round_samples[name].append(elapsed_ms)
                    query_times[name].append(elapsed_ms)
                    _distance, expanded, pushed, _raw = unpack(result)
                    expanded_sums[name] += expanded
                    if pushed is not None:
                        pushed_sums[name] += pushed
                baseline_ms = query_ms[names[0]]
                for i, name in enumerate(names):
                    previous_ms = query_ms[names[i - 1]] if i else baseline_ms
                    paired_query_changes[name]["inbox"].append(
                        (baseline_ms - query_ms[name]) / baseline_ms * 100
                    )
                    paired_query_changes[name]["previous"].append(
                        (previous_ms - query_ms[name]) / previous_ms * 100
                    )
            for name in names:
                round_times[name].append(statistics.fmean(round_samples[name]))
        else:
            if ORDER_MODE == "random":
                order = specs.copy()
                order_rng.shuffle(order)
            else:
                shift = round_index % len(specs)
                order = specs[shift:] + specs[:shift]
            for name, run in order:
                t0 = time.perf_counter()
                outcomes = [run(a, b) for a, b in pairs]
                round_times[name].append((time.perf_counter() - t0) * 1000 / len(pairs))
                for result in outcomes:
                    _distance, expanded, pushed, _raw = unpack(result)
                    expanded_sums[name] += expanded
                    if pushed is not None:
                        pushed_sums[name] += pushed
        print(f"计时轮次 {round_index + 1}/{ROUNDS} 完成（"
              f"{'逐点配对随机交错' if TIMING_MODE == 'paired_query' else ('批次随机' if ORDER_MODE == 'random' else '批次轮转')}）",
              flush=True)

    timing = {}
    for name, _run in specs:
        values = query_times[name] if TIMING_MODE == "paired_query" else round_times[name]
        quartiles = statistics.quantiles(values, n=4, method="inclusive")
        timing[name] = {
            "median_ms_per_query": statistics.median(values),
            "q1_ms_per_query": quartiles[0],
            "q3_ms_per_query": quartiles[2],
            "min_ms_per_query": min(values),
            "max_ms_per_query": max(values),
            "mean_expanded": expanded_sums[name] / (ROUNDS * len(pairs)),
            "mean_pushed": (pushed_sums[name] / (ROUNDS * len(pairs))
                            if pushed_sums[name] else None),
            "round_ms_per_query": values,
        }

    # Paired-query deltas compare implementations on the exact same route and round.
    baseline_rounds = round_times[names[0]]
    paired_changes = {}
    for i, name in enumerate(names):
        if TIMING_MODE == "paired_query":
            versus_baseline = paired_query_changes[name]["inbox"]
            versus_previous = paired_query_changes[name]["previous"]
        else:
            previous_rounds = round_times[names[i - 1]] if i else baseline_rounds
            versus_baseline = [
                (base - current) / base * 100
                for base, current in zip(baseline_rounds, round_times[name])
            ]
            versus_previous = [
                (previous - current) / previous * 100
                for previous, current in zip(previous_rounds, round_times[name])
            ]
        inbox_q = statistics.quantiles(versus_baseline, n=4, method="inclusive")
        previous_q = statistics.quantiles(versus_previous, n=4, method="inclusive")
        paired_changes[name] = {
            "median_speedup_vs_inbox_pct": statistics.median(versus_baseline),
            "q1_speedup_vs_inbox_pct": inbox_q[0],
            "q3_speedup_vs_inbox_pct": inbox_q[2],
            "median_speedup_vs_previous_layer_pct": statistics.median(versus_previous),
            "q1_speedup_vs_previous_layer_pct": previous_q[0],
            "q3_speedup_vs_previous_layer_pct": previous_q[2],
            "paired_observations": len(versus_baseline),
        }

    # A* / reweighted-Dijkstra is tested only if the sampled reduced costs are nonnegative.
    goals = sorted({b for _a, b in pairs})
    violations, checks, minimum = 0, 0, math.inf
    for goal in goals:
        glon, glat = positions[goal]
        h = [work.plane_projection(*positions[u], glon, glat) for u in range(n)]
        for u, outgoing in graph_edges.items():
            hu = h[u]
            for v, weight, _eid in outgoing:
                reduced = weight + h[v] - hu
                violations += reduced < -TOL_M
                minimum = min(minimum, reduced)
                checks += 1

    result = {
        "dataset": {"path": str(DATA_FILE), "nodes": n,
                    "directed_edges": len(edge_records), "largest_scc_nodes": len(scc),
                    "bad_weights": bad_weights, "undefined_endpoints": bad_endpoints,
                    "weight_unit": "meter"},
        "queries": {"seed": SEED, "count": len(pairs), "ordered_pairs": pairs,
                    "source": "unique ordered pairs sampled from largest SCC"},
        "method": {"rounds": ROUNDS, "timing_mode": TIMING_MODE,
                   "round_order_mode": ORDER_MODE,
                   "round_order_seed": ORDER_SEED,
                   "timing": ("same query: randomize algorithm order; per-query paired timing; "
                              "graph loading, adjacency conversion and SCC excluded"
                              if TIMING_MODE == "paired_query" else
                              "interleaved batches; warm query; graph loading, adjacency conversion and SCC excluded"),
                   "distance_tolerance_m": TOL_M,
                   "work_preparation_ms_once": prepare_ms},
        "correctness_vs_inbox": correct,
        "benchmark": timing,
        "paired_speedups": paired_changes,
        "reweighted_plane_feasibility": {
            "tested": False if violations else True,
            "reason": "negative reduced edge(s); unsafe to run label-setting Dijkstra"
                     if violations else None,
            "goals": len(goals), "edge_checks": checks,
            "negative_reduced_edges_below_tolerance": violations,
            "minimum_reduced_cost_m": minimum},
    }
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"武汉 {n:,} nodes / {len(edge_records):,} directed edges; "
          f"SCC={len(scc):,}, queries={len(pairs)}, rounds={ROUNDS}")
    print(f"_Prepared one-time setup: {prepare_ms:.3f} ms")
    for name, _run in specs:
        row = timing[name]
        paired = paired_changes[name]
        print(f"{name}: median={row['median_ms_per_query']:.3f} ms/query "
              f"IQR={row['q1_ms_per_query']:.3f}..{row['q3_ms_per_query']:.3f}; "
              f"range={row['min_ms_per_query']:.3f}..{row['max_ms_per_query']:.3f}; "
              f"paired-vs-inbox={paired['median_speedup_vs_inbox_pct']:+.2f}%; "
              f"expanded={row['mean_expanded']:.1f}; pushed={row['mean_pushed']}")
    print("Correctness:", json.dumps(correct, ensure_ascii=False))
    print("Plane reweight feasibility:", violations, "negative reduced edges in", checks,
          "checks; minimum", minimum)
    print("Saved", RESULT_FILE)


if __name__ == "__main__":
    main()
