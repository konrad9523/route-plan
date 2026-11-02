"""ALT 地标启发式 A* 实验分支。

只依赖标准库。LandmarkALT 先为每个地标计算：
1. 地标到所有节点的距离；
2. 所有节点到地标的距离（在反向图上运行 Dijkstra）。

有向图上的 ALT 下界为：
    max(d(L,t)-d(L,v), d(v,L)-d(t,L))
多个地标取最大值仍然是可采纳下界；叠加平面投影的前提是该近似本身也可采纳。
"""

from __future__ import annotations

import math
from heapq import heappop, heappush
from itertools import count

import improved_algorithms as work


class LandmarkALT:
    """面向固定图、重复查询的 ALT 预处理器。"""

    def __init__(self, graph, positions, nodes, landmark_count=8):
        self.graph = graph
        self.positions = positions
        self.n = len(graph)
        self.reverse = {u: [] for u in graph}
        for u, edges in graph.items():
            for v, weight, edge_id in edges:
                self.reverse.setdefault(v, []).append((u, weight, edge_id))

        self.landmarks = self._select_landmarks(nodes, landmark_count)
        self.from_landmark = []
        self.to_landmark = []
        for landmark in self.landmarks:
            self.from_landmark.append(self._dijkstra(graph, landmark))
            self.to_landmark.append(self._dijkstra(self.reverse, landmark))

    def _select_landmarks(self, nodes, count_requested):
        candidates = list(nodes)
        if not candidates:
            raise ValueError("ALT 至少需要一个候选节点")
        count_requested = max(1, min(int(count_requested), len(candidates)))

        def spread(a, b):
            alon, alat = self.positions[a]
            blon, blat = self.positions[b]
            return (alon - blon) ** 2 + (alat - blat) ** 2

        first = min(candidates, key=lambda node: (self.positions[node][0], node))
        selected = [first]
        nearest = {node: spread(node, first) for node in candidates}
        for _ in range(1, count_requested):
            next_node = max(candidates, key=lambda node: (nearest[node], -node))
            selected.append(next_node)
            for node in candidates:
                nearest[node] = min(nearest[node], spread(node, next_node))
        return selected

    @staticmethod
    def _dijkstra(adjacency, source):
        distances = [math.inf] * len(adjacency)
        distances[source] = 0.0
        heap = [(0.0, source)]
        while heap:
            distance, node = heappop(heap)
            if distance != distances[node]:
                continue
            for nxt, weight, _edge_id in adjacency[node]:
                candidate = distance + weight
                if candidate < distances[nxt]:
                    distances[nxt] = candidate
                    heappush(heap, (candidate, nxt))
        return distances

    def heuristic(self, node, goal, *, include_plane=True):
        value = 0.0
        for from_dist, to_dist in zip(self.from_landmark, self.to_landmark):
            a = from_dist[goal] - from_dist[node]
            b = to_dist[node] - to_dist[goal]
            if a > value:
                value = a
            if b > value:
                value = b
        if include_plane:
            glon, glat = self.positions[goal]
            value = max(value, work.plane_projection(*self.positions[node], glon, glat))
        return value

    def astar(self, start, goal, *, include_plane=True):
        if start not in self.graph or goal not in self.graph:
            raise ValueError("起点/终点不在图中")
        if start == goal:
            return work.RouteOutcome(
                algorithm="astar(plane+ALT)", found=True,
                node_path=[start], distance=0.0, expanded=1, pushed=1,
            )

        tie = count()
        g_score = {start: 0.0}
        parent = {start: None}
        h_cache = {start: self.heuristic(start, goal, include_plane=include_plane)}
        heap = [(h_cache[start], next(tie), start, 0.0)]
        settled = {}
        pushed = 1

        while heap:
            _f, _order, node, distance = heappop(heap)
            if node in settled and settled[node] <= distance:
                continue
            settled[node] = distance
            if node == goal:
                nodes = [goal]
                edges = []
                current = goal
                while current != start:
                    edge_id, previous = parent[current]
                    edges.append(edge_id)
                    current = previous
                    nodes.append(current)
                nodes.reverse()
                edges.reverse()
                return work.RouteOutcome(
                    algorithm="astar(plane+ALT)", found=True,
                    node_path=nodes, edge_path=edges, distance=distance,
                    expanded=len(settled), pushed=pushed,
                )

            for nxt, weight, edge_id in self.graph[node]:
                candidate = distance + weight
                if candidate >= g_score.get(nxt, math.inf):
                    continue
                g_score[nxt] = candidate
                parent[nxt] = (edge_id, node)
                if nxt not in h_cache:
                    h_cache[nxt] = self.heuristic(nxt, goal, include_plane=include_plane)
                heappush(heap, (candidate + h_cache[nxt], next(tie), nxt, candidate))
                pushed += 1

        return work.RouteOutcome(
            algorithm="astar(plane+ALT)", found=False,
            expanded=len(settled), pushed=pushed,
        )
