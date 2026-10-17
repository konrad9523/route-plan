"""Controlled Dijkstra variants for the Wuhan-road-network experiment.

L1-L3 consume the prevalidated triple adjacency list produced by the notebook.
L2-L4 assume node IDs are dense integers in [0, n_nodes), as in that graph.
"""

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


def _peek_valid(queue, distances, settled):
    while queue:
        distance, _, node = queue[0]
        if node in settled or distance != distances.get(node, inf):
            heappop(queue)
        else:
            return distance
    return inf


def _reconstruct_bidirectional(prev_forward, edge_forward, next_backward,
                               edge_backward, start, goal, meeting):
    left_nodes, left_edges = _reconstruct_dict(
        prev_forward, edge_forward, start, meeting
    )
    right_nodes = [meeting]
    right_edges = []
    node = meeting
    while node != goal:
        right_edges.append(edge_backward[node])
        node = next_backward[node]
        right_nodes.append(node)
    return left_nodes + right_nodes[1:], left_edges + right_edges


def dijkstra_b1(graph, reverse_graph, start, goal):
    """B1: bidirectional Dijkstra; returned settled count sums both search directions."""
    _check_adjacency_endpoints(graph, start, goal)
    if start not in reverse_graph or goal not in reverse_graph:
        raise ValueError("反向图缺少起点或终点")
    if start == goal:
        return [start], [], 0.0, 1

    order_forward = count()
    order_backward = count()
    distance_forward = {start: 0.0}
    distance_backward = {goal: 0.0}
    prev_forward = {start: None}
    edge_forward = {}
    next_backward = {goal: None}
    edge_backward = {}
    settled_forward = {}
    settled_backward = {}
    queue_forward = [(0.0, next(order_forward), start)]
    queue_backward = [(0.0, next(order_backward), goal)]
    best_distance = inf
    meeting = None

    while True:
        min_forward = _peek_valid(
            queue_forward, distance_forward, settled_forward
        )
        min_backward = _peek_valid(
            queue_backward, distance_backward, settled_backward
        )

        if best_distance < inf and min_forward + min_backward >= best_distance:
            break
        if min_forward == inf or min_backward == inf:
            break

        if min_forward <= min_backward:
            distance, _, u = heappop(queue_forward)
            settled_forward[u] = distance

            if u in distance_backward:
                candidate = distance + distance_backward[u]
                if candidate < best_distance:
                    best_distance, meeting = candidate, u

            for v, weight, edge_id in graph[u]:
                candidate = distance + weight
                if candidate < distance_forward.get(v, inf):
                    distance_forward[v] = candidate
                    prev_forward[v] = u
                    edge_forward[v] = edge_id
                    heappush(
                        queue_forward,
                        (candidate, next(order_forward), v),
                    )
                    if v in distance_backward:
                        route_distance = candidate + distance_backward[v]
                        if route_distance < best_distance:
                            best_distance, meeting = route_distance, v
        else:
            distance, _, u = heappop(queue_backward)
            settled_backward[u] = distance

            if u in distance_forward:
                candidate = distance_forward[u] + distance
                if candidate < best_distance:
                    best_distance, meeting = candidate, u

            for v, weight, edge_id in reverse_graph[u]:
                candidate = distance + weight
                if candidate < distance_backward.get(v, inf):
                    distance_backward[v] = candidate
                    next_backward[v] = u
                    edge_backward[v] = edge_id
                    heappush(
                        queue_backward,
                        (candidate, next(order_backward), v),
                    )
                    if v in distance_forward:
                        route_distance = distance_forward[v] + candidate
                        if route_distance < best_distance:
                            best_distance, meeting = route_distance, v

    settled_count = len(settled_forward) + len(settled_backward)
    if meeting is None:
        return [], [], inf, settled_count

    nodes, edges = _reconstruct_bidirectional(
        prev_forward,
        edge_forward,
        next_backward,
        edge_backward,
        start,
        goal,
        meeting,
    )
    return nodes, edges, best_distance, settled_count
