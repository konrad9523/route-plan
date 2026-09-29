"""基于边状态的 Dijkstra/A* 路径规划。"""

from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from math import inf
from time import perf_counter

from .costs import CostModel
from .geo import append_geometry
from .models import Edge, Graph, RouteResult


class NoRouteError(RuntimeError):
    """当起点和终点之间不存在满足约束的路线时抛出。"""


@dataclass(frozen=True, slots=True)
class _State:
    previous_edge_id: int | None
    node_id: int


def _reconstruct(
    graph: Graph,
    states: dict[_State, tuple[_State, int] | None],
    final_state: _State,
) -> tuple[list[int], list[int], tuple[float, float], float, float]:
    edge_ids: list[int] = []
    state = final_state
    while states[state] is not None:
        previous_state, edge_id = states[state]
        edge_ids.append(edge_id)
        state = previous_state
    edge_ids.reverse()

    node_ids = [graph.node(final_state.node_id).node_id]
    if edge_ids:
        node_ids = [graph.edge(edge_ids[0]).from_node]
        node_ids.extend(graph.edge(edge_id).to_node for edge_id in edge_ids)

    geometry: list[tuple[float, float]] = []
    distance_m = 0.0
    duration_s = 0.0
    for edge_id in edge_ids:
        edge = graph.edge(edge_id)
        distance_m += edge.length_m
        duration_s += edge.length_m / (edge.speed_kmh * 1000 / 3600)
        edge_geometry = edge.geometry
        if not edge_geometry:
            edge_geometry = (
                (graph.node(edge.from_node).lon, graph.node(edge.from_node).lat),
                (graph.node(edge.to_node).lon, graph.node(edge.to_node).lat),
            )
        append_geometry(geometry, edge_geometry)

    for previous_id, current_id in zip(edge_ids, edge_ids[1:]):
        rule = graph.turn_rules.get((previous_id, current_id))
        if rule is not None and not rule.forbidden:
            duration_s += rule.penalty_s
    return edge_ids, node_ids, tuple(geometry), distance_m, duration_s


def plan_route(
    graph: Graph,
    source: int,
    target: int,
    *,
    algorithm: str = "astar",
    cost_model: CostModel | None = None,
) -> RouteResult:
    """规划 source 到 target 的路线。

    搜索状态包含上一条边，因此能够正确处理转向限制和转向惩罚。
    algorithm 可选 dijkstra 或 astar。
    """

    if source not in graph.nodes or target not in graph.nodes:
        raise ValueError("source and target nodes must exist")
    algorithm = algorithm.lower()
    if algorithm not in {"dijkstra", "astar"}:
        raise ValueError("algorithm must be 'dijkstra' or 'astar'")
    model = cost_model or CostModel()
    started = perf_counter()
    start_state = _State(None, source)
    best: dict[_State, float] = {start_state: 0.0}
    parent: dict[_State, tuple[_State, int] | None] = {start_state: None}
    queue: list[tuple[float, float, _State]] = []
    target_node = graph.node(target)
    start_priority = 0.0
    if algorithm == "astar":
        start_priority = model.heuristic(graph, graph.node(source), target_node)
    heappush(queue, (start_priority, 0.0, start_state))
    expanded_states = 0
    queue_pushes = 1
    final_state: _State | None = None

    while queue:
        _, current_cost, state = heappop(queue)
        if current_cost != best.get(state):
            continue
        expanded_states += 1
        if state.node_id == target:
            final_state = state
            break

        previous_edge = graph.edges.get(state.previous_edge_id)
        for edge in graph.out_edges(state.node_id):
            edge_cost = model.edge_cost(edge)
            if edge_cost == inf:
                continue
            turn_cost = model.transition_cost(graph, previous_edge, edge)
            if turn_cost == inf:
                continue
            next_state = _State(edge.edge_id, edge.to_node)
            new_cost = current_cost + edge_cost + turn_cost
            if new_cost >= best.get(next_state, inf):
                continue
            best[next_state] = new_cost
            parent[next_state] = (state, edge.edge_id)
            priority = new_cost
            if algorithm == "astar":
                priority += model.heuristic(graph, graph.node(edge.to_node), target_node)
            heappush(queue, (priority, new_cost, next_state))
            queue_pushes += 1

    elapsed_ms = (perf_counter() - started) * 1000
    if final_state is None:
        raise NoRouteError(f"no route from {source} to {target}")

    edge_ids, node_ids, geometry, distance_m, duration_s = _reconstruct(graph, parent, final_state)
    return RouteResult(
        status="ok",
        algorithm=algorithm,
        source=source,
        target=target,
        edge_ids=edge_ids,
        node_ids=node_ids,
        geometry=geometry,
        distance_m=distance_m,
        duration_s=duration_s,
        cost=best[final_state],
        expanded_states=expanded_states,
        queue_pushes=queue_pushes,
        planning_ms=elapsed_ms,
    )
