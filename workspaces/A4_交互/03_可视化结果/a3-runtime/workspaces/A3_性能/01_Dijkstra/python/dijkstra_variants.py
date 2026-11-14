"""One-way Dijkstra baseline optimizations L1-L4 for adjacency and CSR graphs."""

from heapq import heappop, heappush
from itertools import count
from math import inf


def _check_adjacency_endpoints(graph, start, goal):
    if start not in graph:
        raise ValueError(f"起点 {start!r} 不存在")
    if goal not in graph:
        raise ValueError(f"终点 {goal!r} 不存在")


def _reconstruct_dict(prev, prev_edge, start, goal):
    nodes = [goal]
    edges = []
    node = goal
    while node != start:
        edges.append(prev_edge[node])
        node = prev[node]
        nodes.append(node)
    nodes.reverse()
    edges.reverse()
    return nodes, edges


def _reconstruct_arrays(prev, prev_edge, start, goal):
    nodes = [goal]
    edges = []
    node = goal
    while node != start:
        edges.append(int(prev_edge[node]))
        node = int(prev[node])
        nodes.append(node)
    nodes.reverse()
    edges.reverse()
    return nodes, edges


def dijkstra_l1(graph, start, goal):
    """L1: keep A2's dictionary/heap search, relying on the notebook's full-graph precheck."""
    _check_adjacency_endpoints(graph, start, goal)
    if start == goal:
        return [start], [], 0.0, 1

    seen = {start: 0.0}
    settled = {}
    prev = {start: None}
    prev_edge = {}
    order = count()
    queue = [(0.0, next(order), start)]

    while queue:
        distance, _, u = heappop(queue)
        if u in settled:
            continue
        settled[u] = distance

        if u == goal:
            nodes, edges = _reconstruct_dict(prev, prev_edge, start, goal)
            return nodes, edges, distance, len(settled)

        for v, weight, edge_id in graph[u]:
            candidate = distance + weight
            if candidate < seen.get(v, inf):
                seen[v] = candidate
                prev[v] = u
                prev_edge[v] = edge_id
                heappush(queue, (candidate, next(order), v))

    return [], [], inf, len(settled)


def dijkstra_l2(graph, start, goal):
    """L2: use dense arrays for tentative distances and settled state; keep dict predecessors."""
    _check_adjacency_endpoints(graph, start, goal)
    if start == goal:
        return [start], [], 0.0, 1

    n_nodes = len(graph)
    distances = [inf] * n_nodes
    settled = bytearray(n_nodes)
    prev = {start: None}
    prev_edge = {}
    order = count()
    distances[start] = 0.0
    queue = [(0.0, next(order), start)]
    settled_count = 0

    while queue:
        distance, _, u = heappop(queue)
        if settled[u] or distance != distances[u]:
            continue
        settled[u] = 1
        settled_count += 1

        if u == goal:
            nodes, edges = _reconstruct_dict(prev, prev_edge, start, goal)
            return nodes, edges, distance, settled_count

        for v, weight, edge_id in graph[u]:
            candidate = distance + weight
            if candidate < distances[v]:
                distances[v] = candidate
                prev[v] = u
                prev_edge[v] = edge_id
                heappush(queue, (candidate, next(order), v))

    return [], [], inf, settled_count


def dijkstra_l3(graph, start, goal):
    """L3: L2 with predecessor node and edge state stored in dense arrays."""
    _check_adjacency_endpoints(graph, start, goal)
    if start == goal:
        return [start], [], 0.0, 1

    n_nodes = len(graph)
    distances = [inf] * n_nodes
    settled = bytearray(n_nodes)
    prev = [-1] * n_nodes
    prev_edge = [-1] * n_nodes
    order = count()
    distances[start] = 0.0
    queue = [(0.0, next(order), start)]
    settled_count = 0

    while queue:
        distance, _, u = heappop(queue)
        if settled[u] or distance != distances[u]:
            continue
        settled[u] = 1
        settled_count += 1

        if u == goal:
            nodes, edges = _reconstruct_arrays(prev, prev_edge, start, goal)
            return nodes, edges, distance, settled_count

        for v, weight, edge_id in graph[u]:
            candidate = distance + weight
            if candidate < distances[v]:
                distances[v] = candidate
                prev[v] = u
                prev_edge[v] = edge_id
                heappush(queue, (candidate, next(order), v))

    return [], [], inf, settled_count


def dijkstra_l4(graph, start, goal):
    """L4: L3 state with direct edge iteration over the supplied CSR arrays."""
    n_nodes = int(graph["n_nodes"])
    if not (0 <= start < n_nodes):
        raise ValueError(f"起点 {start!r} 不存在")
    if not (0 <= goal < n_nodes):
        raise ValueError(f"终点 {goal!r} 不存在")
    if start == goal:
        return [start], [], 0.0, 1

    indptr = graph["indptr"]
    indices = graph["indices"]
    weights = graph["weights"]
    edge_ids = graph["edge_ids"]

    distances = [inf] * n_nodes
    settled = bytearray(n_nodes)
    prev = [-1] * n_nodes
    prev_edge = [-1] * n_nodes
    order = count()
    distances[start] = 0.0
    queue = [(0.0, next(order), start)]
    settled_count = 0

    while queue:
        distance, _, u = heappop(queue)
        if settled[u] or distance != distances[u]:
            continue
        settled[u] = 1
        settled_count += 1

        if u == goal:
            nodes, edges = _reconstruct_arrays(prev, prev_edge, start, goal)
            return nodes, edges, distance, settled_count

        for i in range(int(indptr[u]), int(indptr[u + 1])):
            v = int(indices[i])
            candidate = distance + float(weights[i])
            if candidate < distances[v]:
                distances[v] = candidate
                prev[v] = u
                prev_edge[v] = int(edge_ids[i])
                heappush(queue, (candidate, next(order), v))

    return [], [], inf, settled_count
