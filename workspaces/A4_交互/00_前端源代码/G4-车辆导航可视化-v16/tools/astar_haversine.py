"""A* shortest-path search using the Haversine great-circle heuristic.

Graph format: graph[node] = [(neighbor, weight, edge_id), ...]
Coordinates: positions[node] = (longitude, latitude), in degrees.
"""
from heapq import heappop, heappush
from itertools import count
from math import atan2, cos, inf, isfinite, radians, sin, sqrt

# 地球平均半径（米）
EARTH_RADIUS = 6371000.0


def haversine_distance(positions, node_a, node_b):
    """计算两个经纬度节点之间的球面直线距离（米）。"""
    if node_a not in positions:
        raise ValueError(f"节点 {node_a!r} 缺少坐标")
    if node_b not in positions:
        raise ValueError(f"节点 {node_b!r} 缺少坐标")

    lon1, lat1 = positions[node_a]
    lon2, lat2 = positions[node_b]
    lon1, lat1, lon2, lat2 = map(radians, (lon1, lat1, lon2, lat2))
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    a = min(1.0, max(0.0, a))
    return EARTH_RADIUS * 2 * atan2(sqrt(a), sqrt(1 - a))


def estimate_heuristic_scale(graph, positions):
    """估算安全比例，把 Haversine 距离换算成图中边权单位。

    对每条边计算 weight / 球面直线距离并取最小值，保证启发值不会高估
    图上的最短代价。若图中没有非零几何长度边，返回 0（等同 Dijkstra）。
    """
    scale = inf
    for u, outgoing in graph.items():
        if u not in positions:
            raise ValueError(f"节点 {u!r} 缺少坐标")
        for v, weight, _ in outgoing:
            if v not in graph:
                raise ValueError(f"邻接节点 {v!r} 未定义")
            if v not in positions:
                raise ValueError(f"节点 {v!r} 缺少坐标")
            if not isfinite(weight) or weight < 0:
                raise ValueError("A*边权必须是有限非负数")
            distance = haversine_distance(positions, u, v)
            if distance > 0:
                scale = min(scale, weight / distance)
    if scale == inf:
        return 0.0
    return max(0.0, scale * (1.0 - 1e-12))


def _reconstruct_path(prev, prev_edge, start, goal):
    """根据前驱节点和前驱边恢复完整路径。"""
    node_path = [goal]
    edge_path = []
    node = goal
    while node != start:
        if node not in prev or node not in prev_edge:
            raise RuntimeError("前驱记录不完整，无法恢复路径")
        edge_path.append(prev_edge[node])
        node = prev[node]
        node_path.append(node)
    node_path.reverse()
    edge_path.reverse()
    return node_path, edge_path


def astar(graph, positions, start, goal, *, heuristic_scale=None):
    """A* 最短路径算法，返回节点路径、边路径、代价和展开节点数。"""
    if start not in graph:
        raise ValueError(f"起点 {start!r} 不存在")
    if goal not in graph:
        raise ValueError(f"终点 {goal!r} 不存在")
    if heuristic_scale is None:
        heuristic_scale = estimate_heuristic_scale(graph, positions)
    elif not isfinite(heuristic_scale) or heuristic_scale < 0:
        raise ValueError("heuristic_scale必须是有限非负数")
    if start == goal:
        return [start], [], 0.0, 1

    tie_breaker = count()
    h0 = haversine_distance(positions, start, goal) * heuristic_scale
    queue = [(h0, next(tie_breaker), start, 0.0)]
    best_g = {start: 0.0}
    explored_g = {}
    prev = {start: None}
    prev_edge = {}

    while queue:
        _, _, node, g = heappop(queue)
        if g != best_g.get(node):
            continue
        if node in explored_g and g >= explored_g[node]:
            continue
        explored_g[node] = g

        if node == goal:
            node_path, edge_path = _reconstruct_path(prev, prev_edge, start, goal)
            return node_path, edge_path, g, len(explored_g)

        for nxt, weight, edge_id in graph[node]:
            if nxt not in graph:
                raise ValueError(f"邻接节点 {nxt!r} 未定义")
            if nxt not in positions:
                raise ValueError(f"节点 {nxt!r} 缺少坐标")
            if not isfinite(weight) or weight < 0:
                raise ValueError("A*边权必须是有限非负数")

            new_g = g + weight
            if new_g < best_g.get(nxt, inf):
                best_g[nxt] = new_g
                prev[nxt] = node
                prev_edge[nxt] = edge_id
                h = haversine_distance(positions, nxt, goal) * heuristic_scale
                heappush(queue, (new_g + h, next(tie_breaker), nxt, new_g))

    return [], [], inf, len(explored_g)
