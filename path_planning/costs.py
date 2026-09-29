"""边、转向和启发式代价模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import inf

from .geo import haversine_m
from .models import Edge, Graph, Node


class Preference(str, Enum):
    FASTEST = "fastest"
    SHORTEST = "shortest"
    AVOID_TOLLS = "avoid_tolls"
    NO_HIGHWAY = "no_highway"


@dataclass(frozen=True, slots=True)
class CostModel:
    """可解释的静态道路代价。

    avoid_tolls 使用惩罚而不是硬禁行，便于展示“有收费但明显更快”的路线；
    no_highway 对 motorway/trunk 直接禁用，适合课程 demo。
    """

    preference: Preference = Preference.FASTEST
    mode: str = "car"
    toll_penalty_s: float = 900.0
    max_speed_kmh: float = 130.0

    def edge_cost(self, edge: Edge) -> float:
        if edge.closed or self.mode not in edge.allowed_modes:
            return inf
        if self.preference is Preference.NO_HIGHWAY and edge.road_type in {"motorway", "trunk"}:
            return inf
        if self.preference is Preference.SHORTEST:
            return edge.length_m
        travel_time_s = edge.length_m / (edge.speed_kmh * 1000 / 3600)
        if self.preference is Preference.AVOID_TOLLS and edge.toll:
            travel_time_s += self.toll_penalty_s
        return travel_time_s

    def transition_cost(self, graph: Graph, previous: Edge | None, current: Edge) -> float:
        if previous is None:
            return 0.0
        rule = graph.turn_rules.get((previous.edge_id, current.edge_id))
        if rule is None:
            return 0.0
        if rule.forbidden:
            return inf
        # shortest 的主代价单位是米，不能直接叠加以秒计的转向惩罚。
        # 时间型偏好才把 turn penalty_s 纳入搜索代价。
        if self.preference is Preference.SHORTEST:
            return 0.0
        return rule.penalty_s

    def heuristic(self, graph: Graph, node: Node, target: Node) -> float:
        straight_m = haversine_m((node.lon, node.lat), (target.lon, target.lat))
        if self.preference is Preference.SHORTEST:
            return straight_m
        # 以全图允许的最大速度换算为时间下界，保证不会因为道路绕行而高估。
        return straight_m / (self.max_speed_kmh * 1000 / 3600)
