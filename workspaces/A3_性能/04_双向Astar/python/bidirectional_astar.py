"""Bidirectional A* B1 using the shared geometric/ALT heuristic helpers."""

from heapq import heappop, heappush
from itertools import count
from math import fsum, inf, isfinite

from astar_variants import (
    LANDMARK_SAFETY,
    _check_endpoints,
    _heuristic,
    _restore_dict,
)


def bidirectional_astar(graph, reverse_graph, positions, start, goal, *,
                        heuristic="H0", heuristic_scale=None, projected=None,
                        plane_scale=None, alt=None, landmark_count=0, stats=None):
    """Exact bidirectional A* via one consistent target potential and reweighted edges.

    Both Dijkstra queues operate on the same nonnegative reduced costs. The stopping
    bound is min_forward + min_backward >= best_complete_route, not first meeting.
    """
    _check_endpoints(graph, start, goal)
    if heuristic not in {"H0", "PLANE", "ALT", "MAX", "MAX_PLANE"}:
        raise ValueError(f"未知启发式：{heuristic!r}")
    if start not in reverse_graph or goal not in reverse_graph:
        raise ValueError("反向图缺少起点或终点")
    if heuristic in {"H0", "MAX"} and heuristic_scale is None:
        raise ValueError("请预先传入 Haversine 安全比例")
    if heuristic in {"PLANE", "MAX_PLANE"} and (projected is None or plane_scale is None):
        raise ValueError("平面启发式需要投影坐标与安全比例")
    if heuristic in {"ALT", "MAX", "MAX_PLANE"} and (alt is None or landmark_count < 1):
        raise ValueError("ALT 启发式需要有效的地标表与地标数")
    if heuristic in {"ALT", "MAX", "MAX_PLANE"} and landmark_count > len(alt.landmarks):
        raise ValueError("请求的地标数超过已预处理表的数量")
    if heuristic_scale is not None and (not isfinite(heuristic_scale) or heuristic_scale < 0):
        raise ValueError("heuristic_scale 必须为有限非负数")
    if plane_scale is not None and (not isfinite(plane_scale) or plane_scale < 0):
        raise ValueError("plane_scale 必须为有限非负数")
    if start == goal:
        if stats is not None:
            stats.update(pushed_count=1, scanned_edges=0, heuristic_evaluations=0, expanded_nodes=1)
        return [start], [], 0.0, 1

    h_cache = {}
    h_calls = 0

    def potential(node):
        nonlocal h_calls
        if node not in h_cache:
            h_cache[node] = LANDMARK_SAFETY * _heuristic(
                node, goal, heuristic, positions, heuristic_scale,
                projected, plane_scale, alt, landmark_count,
            )
            h_calls += 1
        return h_cache[node]

    def reduced(weight, u, v):
        value = weight + potential(u) - potential(v)
        if value < -1e-9:
            raise ValueError("双向 A* 启发函数不一致，重标权边出现负值")
        return max(0.0, value)

    order_f, order_b = count(), count()
    dist_f, dist_b = {start: 0.0}, {goal: 0.0}
    settled_f, settled_b = {}, {}
    parent_f, edge_f = {start: None}, {}
    next_b, edge_b = {goal: None}, {}
    qf = [(0.0, next(order_f), start)]
    qb = [(0.0, next(order_b), goal)]
    best = inf
    join = None
    scanned = pushed = 0

    def consider(left, right, bridge, value):
        nonlocal best, join
        if value < best:
            best, join = value, (left, right, bridge)

    def top_valid(queue, distances, settled):
        while queue:
            distance, _order, node = queue[0]
            if node in settled or distance != distances.get(node, inf):
                heappop(queue)
            else:
                return distance
        return inf

    while True:
        min_f = top_valid(qf, dist_f, settled_f)
        min_b = top_valid(qb, dist_b, settled_b)
        if best < inf and min_f + min_b >= best:
            break
        if min_f == inf or min_b == inf:
            break
        if min_f <= min_b:
            distance, _order, u = heappop(qf)
            settled_f[u] = distance
            if u in dist_b:
                consider(u, u, None, distance + dist_b[u])
            for v, weight, edge_id in graph[u]:
                scanned += 1
                reduced_weight = reduced(weight, u, v)
                candidate = distance + reduced_weight
                if candidate < dist_f.get(v, inf):
                    dist_f[v] = candidate
                    parent_f[v], edge_f[v] = u, edge_id
                    heappush(qf, (candidate, next(order_f), v))
                    pushed += 1
                if v in dist_b:
                    consider(u, v, (edge_id, weight), distance + reduced_weight + dist_b[v])
        else:
            distance, _order, v = heappop(qb)
            settled_b[v] = distance
            if v in dist_f:
                consider(v, v, None, dist_f[v] + distance)
            for u, weight, edge_id in reverse_graph[v]:
                scanned += 1
                reduced_weight = reduced(weight, u, v)
                candidate = distance + reduced_weight
                if candidate < dist_b.get(u, inf):
                    dist_b[u] = candidate
                    next_b[u], edge_b[u] = v, edge_id
                    heappush(qb, (candidate, next(order_b), u))
                    pushed += 1
                if u in dist_f:
                    consider(u, v, (edge_id, weight), dist_f[u] + reduced_weight + distance)

    expanded = len(settled_f) + len(settled_b)
    if join is None:
        if stats is not None:
            stats.update(pushed_count=pushed + 2, scanned_edges=scanned,
                         heuristic_evaluations=h_calls, expanded_nodes=expanded)
        return [], [], inf, expanded

    left, right, bridge = join
    nodes, path_edges = _restore_dict(parent_f, edge_f, start, left)
    if bridge is not None:
        bridge_id, _bridge_weight = bridge
        nodes.append(right)
        path_edges.append(bridge_id)
    node = right
    while node != goal:
        if node not in next_b or node not in edge_b:
            raise RuntimeError("反向前驱记录不完整，无法恢复双向路径")
        path_edges.append(edge_b[node])
        node = next_b[node]
        nodes.append(node)
        if len(nodes) > len(graph):
            raise RuntimeError("双向前驱链存在环")
    route_weights = []
    for u, v, edge_id in zip(nodes, nodes[1:], path_edges):
        for nxt, weight, candidate_edge_id in graph[u]:
            if nxt == v and candidate_edge_id == edge_id:
                route_weights.append(weight)
                break
        else:
            raise RuntimeError("双向路径包含不属于原图的 edge_id")
    route_distance = fsum(route_weights)
    if stats is not None:
        stats.update(pushed_count=pushed + 2, scanned_edges=scanned,
                     heuristic_evaluations=h_calls, expanded_nodes=expanded)
    return nodes, path_edges, route_distance, expanded
