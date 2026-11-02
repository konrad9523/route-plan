from heapq import heappop, heappush
from itertools import count
from math import atan2, cos, inf, radians, sin, sqrt

# 地球平均半径（米）
EARTH_RADIUS = 6371000.0


# ============================================================
# Haversine 距离
# ============================================================

def haversine_distance(positions, node_a, node_b):
    """
    计算两个节点之间的球面直线距离（米）。

    positions: {node: (lon, lat)}
    """
    if node_a not in positions:
        raise ValueError(f"节点 {node_a!r} 缺少坐标")
    if node_b not in positions:
        raise ValueError(f"节点 {node_b!r} 缺少坐标")

    lon1, lat1 = positions[node_a]
    lon2, lat2 = positions[node_b]

    # 转换为弧度
    lon1 = radians(lon1)
    lat1 = radians(lat1)
    lon2 = radians(lon2)
    lat2 = radians(lat2)

    dlon = lon2 - lon1
    dlat = lat2 - lat1

    # Haversine 公式
    a = (
        sin(dlat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    )

    # 数值保护：防止浮点误差导致 a 越界
    a = min(1.0, max(0.0, a))

    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return EARTH_RADIUS * c


# ============================================================
# 路径恢复
# ============================================================

def _reconstruct_path(prev, prev_edge, start, goal):
    """
    根据前驱节点和前驱边恢复完整路径。

    返回
    ----------
    node_path: [start, ..., goal]
    edge_path: [edge_id1, edge_id2, ...]
    """
    node_path = [goal]
    edge_path = []
    node = goal  # 当前回溯到的节点

    # 不断向前驱回溯，直到回到起点
    while node != start:
        edge_path.append(prev_edge[node])  # 当前节点由哪条边进入
        node = prev[node]                  # 回到父节点
        node_path.append(node)             # 父节点加入路径

    node_path.reverse()
    edge_path.reverse()
    return node_path, edge_path


# ============================================================
# A*
# ============================================================

def astar(graph, positions, start, goal):
    """
    A* 最短路径算法。

    图结构
    ----------
    graph = {node: [(neighbor, weight, edge_id), ...]}
    positions = {node: (lon, lat)}

    返回
    ----------
    node_path:     最短路径经过的节点序列
    edge_path:     最短路径经过的道路边编号
    distance:      最短距离（米）
    visited_count: 实际展开的不同节点数

    核心: f(n) = g(n) + h(n)
        g(n) = 起点到当前节点的实际距离
        h(n) = 当前节点到终点的 Haversine 距离
    """

    # ---------------- 1. 输入检查 ----------------
    if start not in graph:
        raise ValueError(f"起点 {start!r} 不存在")
    if goal not in graph:
        raise ValueError(f"终点 {goal!r} 不存在")
    if start == goal:
        return [start], [], 0.0, 1

    # ---------------- 2. 初始化 ----------------
    tie_breaker = count()  # 距离相同时用于打破平局

    # 起点启发值
    h0 = haversine_distance(positions, start, goal)

    # 优先队列: (f, 编号, node, g)
    queue = [(h0, next(tie_breaker), start, 0.0)]

    # 已发现节点: node -> (当前最好g, h)
    enqueued = {start: (0.0, h0)}

    # 已展开节点: node -> 展开时的 g
    explored_g = {}

    # 前驱节点
    prev = {start: None}

    # 前驱道路边: prev_edge[v] = 从 prev[v] 到 v 使用的边
    prev_edge = {}

    # ---------------- 3. 主循环 ----------------
    while queue:
        # 弹出 f 最小的节点
        _, _, node, g = heappop(queue)

        # 惰性删除：已展开过且本次 g 不更优，则跳过
        if node in explored_g:
            if g >= explored_g[node]:
                continue

        # 正式展开
        explored_g[node] = g

        # 到达终点：恢复路径并返回
        if node == goal:
            node_path, edge_path = _reconstruct_path(prev, prev_edge, start, goal)
            return (node_path, edge_path, g, len(explored_g))

        # 遍历邻接边
        for nxt, weight, edge_id in graph[node]:
            # 邻接节点检查
            if nxt not in graph:
                raise ValueError(f"邻接节点 {nxt!r} 未定义")
            # 坐标检查
            if nxt not in positions:
                raise ValueError(f"节点 {nxt!r} 缺少坐标")
            # 非负权
            if weight < 0:
                raise ValueError("A*不允许负权边")

            # 新的实际代价
            new_g = g + weight

            # 判断是否已有更好的路径
            if nxt in enqueued:
                old_g, h = enqueued[nxt]
                if old_g <= new_g:
                    continue
            else:
                # 第一次发现该节点，计算并缓存 Haversine
                h = haversine_distance(positions, nxt, goal)

            # 更新状态
            enqueued[nxt] = (new_g, h)  # 更新候选 g 与 h
            prev[nxt] = node            # 记录父节点
            prev_edge[nxt] = edge_id    # 记录进入 nxt 使用的边

            # 入优先队列: (f = g + h, 编号, node, g)
            heappush(queue, (new_g + h, next(tie_breaker), nxt, new_g))

    # ---------------- 4. 不可达 ----------------
    return [], [], inf, len(explored_g)
