"""
Balanced Bidirectional A*

基于：
    带权有向图
    双向搜索
    平衡势函数

输入：
    graph[node] = [(neighbor, weight, edge_id)]

返回：
    node_path
    edge_path
    distance
    visited
"""

from heapq import heappush, heappop
from itertools import count
from math import inf

from astar_received_baseline import haversine_distance


# ============================================================
# 构造反向图
# ============================================================

def build_reverse_graph(graph):
    """把有向图反转，用于反向搜索。"""
    reverse = {node: [] for node in graph}

    for u in graph:
        for v, weight, edge_id in graph[u]:
            # 原边 u -> v，反向后是 v -> u
            reverse[v].append((u, weight, edge_id))

    return reverse


# ============================================================
# 路径恢复
# ============================================================

def reconstruct_forward(prev, prev_edge, meet):
    """从 meet 沿正向 prev 回溯到 start，返回节点和边。"""
    nodes = []
    edges = []
    node = meet

    while node is not None:
        nodes.append(node)

        # 记录进入当前节点的边
        if node in prev_edge:
            edges.append(prev_edge[node])

        node = prev.get(node)

    # 回溯顺序是 meet -> start，反转成正序
    nodes.reverse()
    edges.reverse()

    return nodes, edges


def reconstruct_backward(prev, prev_edge, meet, goal):
    """从 meet 沿反向 prev 前进到 goal，返回节点和边。"""
    nodes = []
    edges = []
    node = meet

    while node != goal:
        nxt = prev[node]           # 反向搜索里 prev 指向 goal 方向

        nodes.append(nxt)
        edges.append(prev_edge[node])

        node = nxt

    return nodes, edges


# ============================================================
# 双向 A*
# ============================================================

def bidirectional_astar(graph, positions, start, goal):
    # -------------------------
    # 输入检查
    # -------------------------

    if start not in graph:
        raise ValueError(f"{start}不存在")

    if goal not in graph:
        raise ValueError(f"{goal}不存在")

    if start == goal:
        return [start], [], 0.0, 1

    # 反向图
    reverse = build_reverse_graph(graph)

    # -------------------------
    # 势函数
    # -------------------------

    # 平衡势函数，用于让正向和反向搜索进度均衡
    cache = {}

    def potential(node):
        if node not in cache:
            cache[node] = (
                haversine_distance(positions, node, goal)
                - haversine_distance(positions, start, node)
            ) / 2

        return cache[node]

    ps = potential(start)
    pt = potential(goal)

    # -------------------------
    # 初始化
    # -------------------------

    tie = count()

    # ---------- 正向 ----------

    forward_dist = {start: 0.0}     # 起点到节点的实际代价
    forward_prev = {start: None}    # 前驱节点
    forward_edge = {}               # 进入节点的边
    forward_closed = set()          # 已展开节点

    forward_queue = []
    heappush(forward_queue, (0.0, next(tie), 0.0, start))

    # ---------- 反向 ----------

    backward_dist = {goal: 0.0}     # 节点到终点的实际代价
    backward_prev = {goal: None}    # 反向搜索的前驱（指向 goal 方向）
    backward_edge = {}              # 反向进入节点的边
    backward_closed = set()         # 已展开节点

    backward_queue = []
    heappush(backward_queue, (0.0, next(tie), 0.0, goal))

    # -------------------------
    # 全局变量
    # -------------------------

    best_distance = inf   # 当前最优相遇路径总代价
    meet = None           # 相遇节点
    visited = set()       # 正向 + 反向已展开节点

    # -------------------------
    # 主循环
    # -------------------------

    while forward_queue and backward_queue:

        # 两边当前最小 key
        f_min = forward_queue[0][0]
        b_min = backward_queue[0][0]

        # 停止条件：两边最小 key 之和已无法改进最优解
        if (
            meet is not None
            and f_min + b_min >= best_distance + pt - ps
        ):
            break

        # 选择 key 更小的一边扩展
        direction = "forward" if f_min <= b_min else "backward"

        # ====================================================
        # 正向搜索
        # ====================================================

        if direction == "forward":

            _, _, g, u = heappop(forward_queue)

            # 惰性删除：已展开则跳过
            if u in forward_closed:
                continue

            forward_closed.add(u)
            visited.add(u)

            # 正向节点已在反向距离表中，尝试更新相遇
            if u in backward_dist:
                total = g + backward_dist[u]
                if total < best_distance:
                    best_distance = total
                    meet = u

            # 遍历正向邻接边
            for v, w, eid in graph[u]:

                new_g = g + w

                # 松弛：第一次发现或找到更优路径
                if v not in forward_dist or new_g < forward_dist[v]:

                    forward_dist[v] = new_g
                    forward_prev[v] = u
                    forward_edge[v] = eid

                    # 带势函数的 key
                    key = new_g + potential(v) - ps

                    heappush(forward_queue, (key, next(tie), new_g, v))

        # ====================================================
        # 反向搜索
        # ====================================================

        else:

            _, _, g, u = heappop(backward_queue)

            # 惰性删除：已展开则跳过
            if u in backward_closed:
                continue

            backward_closed.add(u)
            visited.add(u)

            # 反向节点已在正向距离表中，尝试更新相遇
            if u in forward_dist:
                total = g + forward_dist[u]
                if total < best_distance:
                    best_distance = total
                    meet = u

            # 遍历反向邻接边
            for v, w, eid in reverse[u]:

                new_g = g + w

                # 松弛：第一次发现或找到更优路径
                if v not in backward_dist or new_g < backward_dist[v]:

                    backward_dist[v] = new_g
                    backward_prev[v] = u
                    backward_edge[v] = eid

                    # 带势函数的 key（反向符号相反）
                    key = new_g - potential(v) + pt

                    heappush(backward_queue, (key, next(tie), new_g, v))

    # -------------------------
    # 无路径
    # -------------------------

    if meet is None:
        return [], [], inf, len(visited)

    # -------------------------
    # 路径拼接
    # -------------------------

    left_nodes, left_edges = reconstruct_forward(
        forward_prev, forward_edge, meet
    )

    right_nodes, right_edges = reconstruct_backward(
        backward_prev, backward_edge, meet, goal
    )

    # 正向路径 + 反向路径（去重 meet）
    path = left_nodes + right_nodes
    edge_path = left_edges + right_edges

    return path, edge_path, best_distance, len(visited)
