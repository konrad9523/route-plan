from heapq import heappop, heappush
from itertools import count
from math import inf


# ============================================================
# 路径恢复
# ============================================================

def _reconstruct_path(prev, prev_edge, start, goal):
    """
    根据前驱节点表和前驱边表恢复完整路径。

    返回
    ----------
    node_path: [start, ..., goal]
    edge_path: [edge_id1, edge_id2, ...]
    """
    # 从终点开始回溯
    node_path = [goal]
    edge_path = []
    node = goal  # 当前回溯到的节点

    # 不断向前驱回溯，直到回到起点
    while node != start:
        edge_path.append(prev_edge[node])  # 记录进入当前节点的边
        node = prev[node]                  # 回到父节点
        node_path.append(node)             # 父节点加入路径

    # 当前顺序是 goal -> start，需要反转
    node_path.reverse()
    edge_path.reverse()
    return node_path, edge_path


# ============================================================
# Dijkstra
# ============================================================

def dijkstra(graph, start, goal):
    """
    Dijkstra 最短路径算法。

    图结构
    ----------
    graph = {node: [(neighbor, weight, edge_id), ...]}

    参数
    ----------
    node:     节点编号
    neighbor: 相邻节点编号
    weight:   边权，例如道路长度（米）
    edge_id:  道路边编号

    返回
    ----------
    node_path:     最短路径经过的节点序列
    edge_path:     最短路径经过的边编号序列
    distance:      最短距离
    visited_count: 已确定节点数量
    """

    # ---------------- 1. 输入检查 ----------------
    if start not in graph:
        raise ValueError(f"起点 {start!r} 不存在")
    if goal not in graph:
        raise ValueError(f"终点 {goal!r} 不存在")
    # 起点就是终点：直接返回
    if start == goal:
        return [start], [], 0.0, 1

    # ---------------- 2. 初始化 ----------------
    seen = {start: 0.0}   # 已发现节点当前最好的候选距离
    dist = {}             # 已正式确定的最短距离
    prev = {start: None}  # 前驱节点
    prev_edge = {}        # 前驱边：prev_edge[v] = 从 prev[v] 到 v 使用的边
    tie_breaker = count() # 距离相同时用于打破平局

    # 优先队列: (当前距离, 编号, 节点)
    queue = [(0.0, next(tie_breaker), start)]

    # ---------------- 3. 主循环 ----------------
    while queue:
        # 取出当前距离最小的节点
        current_dist, _, u = heappop(queue)

        # 惰性删除：已确定过则说明是堆中旧记录，跳过
        if u in dist:
            continue

        # 正式确定 u 的最短距离
        dist[u] = current_dist

        # 到达终点：恢复路径并返回
        if u == goal:
            node_path, edge_path = _reconstruct_path(prev, prev_edge, start, goal)
            return (node_path, edge_path, dist[goal], len(dist))

        # 遍历邻接边
        for v, weight, edge_id in graph[u]:
            # 邻接节点必须存在
            if v not in graph:
                raise ValueError(f"节点 {v!r} 不存在")
            # Dijkstra 不允许负权边
            if weight < 0:
                raise ValueError("Dijkstra不允许负权边")

            # 经 u 到达 v 的新距离
            new_dist = current_dist + weight

            # 松弛：v 未发现，或找到更短路径
            if v not in seen or new_dist < seen[v]:
                seen[v] = new_dist        # 更新最优候选距离
                prev[v] = u               # 记录父节点
                prev_edge[v] = edge_id    # 记录实际使用的道路边
                heappush(queue, (new_dist, next(tie_breaker), v))  # 入队

    # ---------------- 4. 不可达 ----------------
    # 队列空了仍未到达 goal，说明不连通
    return [], [], inf, len(dist)