"""Bidirectional Dijkstra (B1), separated from the one-way variants."""

from heapq import heappop, heappush
from itertools import count
from math import inf

from dijkstra_variants import _check_adjacency_endpoints, _reconstruct_dict


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
