from heapq import heappop, heappush
from itertools import count
from math import inf


def _reconstruct_path(prev, start, goal):
    """根据前驱表恢复 start -> goal 的完整路径。"""
    path = [goal]
    node = goal
    while node != start:
        node = prev[node]
        path.append(node)
    path.reverse()
    return path


def dijkstra(graph, start, goal):
    """
    Dijkstra 最短路径算法。

    graph 格式：
        {
            node: [(neighbor, weight), ...]
        }

    返回：
        path, distance, visited_count

    说明：
    - 边权必须非负。
    - seen 保存“已发现但未最终确定”的最好距离。
    - dist 保存“已经正式确定”的最短距离。
    - 使用 heapq + count() 实现最小优先队列。
    - 堆中旧记录采用惰性删除：弹出后发现节点已进入 dist 就跳过。
    """

    if start not in graph:
        raise ValueError(f"起点 {start!r} 不在图中")
    if goal not in graph:
        raise ValueError(f"终点 {goal!r} 不在图中")
    if start == goal:
        return [start], 0.0, 1

    # 候选最短距离
    seen = {start: 0.0}

    # 已最终确定的最短距离
    dist = {}

    # 前驱节点，用于路径恢复
    prev = {start: None}

    # 优先队列元素：(距离, 唯一编号, 节点)
    tie_breaker = count()
    fringe = [(0.0, next(tie_breaker), start)]

    while fringe:
        current_dist, _, u = heappop(fringe)

        # 已经正式确定过，说明这是堆中的旧记录
        if u in dist:
            continue

        # 正式确定 u 的最短距离
        dist[u] = current_dist

        # 终点被正式确定后即可停止
        if u == goal:
            path = _reconstruct_path(prev, start, goal)
            return path, dist[goal], len(dist)

        for v, weight in graph[u]:
            if v not in graph:
                raise ValueError(f"邻接点 {v!r} 未在 graph 中定义")
            if weight < 0:
                raise ValueError(
                    f"Dijkstra 不允许负权边：{u!r} -> {v!r}, weight={weight}"
                )

            new_dist = current_dist + weight

            # 如果 v 已经最终确定，不应再出现更短路径
            if v in dist:
                if new_dist < dist[v]:
                    raise ValueError("发现矛盾路径，请检查是否存在负权边")
                continue

            # 松弛：更新候选距离
            if v not in seen or new_dist < seen[v]:
                seen[v] = new_dist
                prev[v] = u
                heappush(
                    fringe,
                    (new_dist, next(tie_breaker), v)
                )

    # 不可达
    return [], inf, len(dist)
