"""基于边状态的 Dijkstra/A* 路径规划。"""

from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from math import inf
from time import perf_counter

from .costs import CostModel
from .geo import append_geometry
from .models import Edge, Graph, RouteResult
from .search_trace import TraceRecorder


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


def check_heuristic_consistency(
    graph: Graph,
    *,
    cost_model: CostModel | None = None,
    limit: int = 20,
) -> list[tuple[int, int, float, float]]:
    """检查启发式是否满足一致性：``cost(u→v) + h(v) >= h(u)``。

    为什么需要这个检查：
        A* 只在启发式**一致**时才保证最优。而启发式是"直线距离 / 最高速度"，
        这暗含一个前提——**每条边的长度不能比它两端点的直线距离还短**。
        外部数据（抽稀过的路网、手工构造的测试图、估算的边权）经常违反这一点，
        此时 A* 会**静默返回次优路径**，不报任何错。

    返回违反一致性的边列表，每项为 ``(edge_id, target_node, 违反量, 边长)``。
    列表为空表示这张图适合用 A*。
    """

    model = cost_model or CostModel()
    violations: list[tuple[int, int, float, float]] = []
    for edge in graph.edges.values():
        if edge.from_node not in graph.nodes or edge.to_node not in graph.nodes:
            continue
        edge_cost = model.edge_cost(edge)
        if edge_cost == inf:
            continue
        h_from = model.heuristic(graph, graph.node(edge.from_node), graph.node(edge.to_node))
        # 以边的终点为目标时 h(终点)=0，于是一致性条件化简为 cost >= h(from)
        if edge_cost + 1e-9 < h_from:
            violations.append((edge.edge_id, edge.to_node, h_from - edge_cost, edge.length_m))
            if len(violations) >= limit:
                break
    return violations


def plan_route(
    graph: Graph,
    source: int,
    target: int,
    *,
    algorithm: str = "astar",
    cost_model: CostModel | None = None,
    trace: bool = False,
) -> RouteResult:
    """规划 source 到 target 的路线。

    搜索状态包含上一条边，因此能够正确处理转向限制和转向惩罚。
    algorithm 可选 dijkstra 或 astar。

    实现上有两个必须注意的细节（都是踩过坑之后加的）：

    1. 堆元素带一个自增序号 ``tie``。
       ``_State`` 没有定义大小比较，一旦两项的 (priority, cost) 完全相同，
       heapq 就会退化成比较 ``_State``，直接抛 TypeError。
       真实路网上等代价的路段很常见，所以这不是理论问题。

    2. 终止条件不是"弹到终点就停"，而是"队列里的最优优先级已经不可能
       再改进已知的终点代价"。
       当启发式满足可采纳性但不满足一致性时（例如边长与节点坐标不自洽的图），
       "弹到终点就停"会返回次优路径——而且不报任何错。
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
    queue: list[tuple[float, float, int, _State]] = []
    tie_breaker = count()
    target_node = graph.node(target)
    start_priority = 0.0
    if algorithm == "astar":
        start_priority = model.heuristic(graph, graph.node(source), target_node)
    heappush(queue, (start_priority, 0.0, next(tie_breaker), start_state))
    expanded_states = 0
    queue_pushes = 1
    final_state: _State | None = None
    best_goal_cost = inf
    # 未启用时 record_* 会立刻返回，热路径几乎没有开销
    recorder = TraceRecorder(trace, algorithm=algorithm, preference=str(model.preference.value))
    recorder.record_discover(source)
    goal_step: int | None = None

    while queue:
        priority, current_cost, _, state = heappop(queue)
        if current_cost > best.get(state, inf):
            continue
        # 终止条件：只有当队列里的最优优先级还能改进已知的终点代价时才继续。
        # 对"一致"(consistent) 的启发式，终点状态的 priority 就等于它的真实代价，
        # 因此这个条件在第一次弹到终点时即成立。
        if priority > best_goal_cost:
            break
        recorder.record_pop(state.node_id, current_cost, state.previous_edge_id)
        expanded_states += 1
        if state.node_id == target:
            # 注意：不能无条件覆盖，否则后弹出的、代价更高的终点状态会冲掉好答案。
            if current_cost < best_goal_cost:
                final_state = state
                best_goal_cost = current_cost
                goal_step = len(recorder.trace.pop_order) - 1
            continue

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
            # 只在"首次发现某个路口"时记一步。可视化只关心边界在哪，
            # 重复松弛同一条边不必重复记录，否则事件数会翻好几倍。
            recorder.record_discover(edge.to_node)
            priority = new_cost
            if algorithm == "astar":
                priority += model.heuristic(graph, graph.node(edge.to_node), target_node)
            heappush(queue, (priority, new_cost, next(tie_breaker), next_state))
            queue_pushes += 1

    elapsed_ms = (perf_counter() - started) * 1000
    if final_state is None:
        raise NoRouteError(f"no route from {source} to {target}")

    edge_ids, node_ids, geometry, distance_m, duration_s = _reconstruct(graph, parent, final_state)
    recorder.finish(
        expanded_states=expanded_states,
        queue_pushes=queue_pushes,
        path_nodes=node_ids,
        path_edges=edge_ids,
        goal_step=goal_step,
    )
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
        trace=recorder.trace if trace else None,
    )
