"""路径规划所需的最小数据模型。

核心包只依赖 Python 标准库。真实 OSM 数据可以在 G2/G3 适配层转换为这些对象，
规划器本身不关心数据来自 CSV、SQLite、PostGIS 还是 OSMnx。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Mapping

if TYPE_CHECKING:  # 只用于类型标注，避免运行时循环导入
    from .search_trace import SearchTrace

Coordinate = tuple[float, float]


@dataclass(frozen=True, slots=True)
class Node:
    """路网节点。

    lon/lat 使用 WGS84 十进制度。规划核心不强制要求节点有几何之外的属性，
    但保留 tags 便于后续接入 OSM 标签。
    """

    node_id: int
    lon: float
    lat: float
    tags: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Edge:
    """有向道路边。"""

    edge_id: int
    from_node: int
    to_node: int
    length_m: float
    speed_kmh: float
    road_type: str = "residential"
    toll: bool = False
    allowed_modes: frozenset[str] = frozenset({"car"})
    name: str = ""
    geometry: tuple[Coordinate, ...] = ()
    closed: bool = False

    def __post_init__(self) -> None:
        if self.length_m < 0:
            raise ValueError("edge length_m must be non-negative")
        if self.speed_kmh <= 0:
            raise ValueError("edge speed_kmh must be positive")
        if not self.allowed_modes:
            raise ValueError("edge allowed_modes cannot be empty")


@dataclass(frozen=True, slots=True)
class TurnRule:
    """相邻两条边之间的转向限制或转向惩罚。"""

    from_edge: int
    to_edge: int
    forbidden: bool = False
    penalty_s: float = 0.0

    def __post_init__(self) -> None:
        if self.penalty_s < 0:
            raise ValueError("turn penalty_s must be non-negative")


@dataclass(slots=True)
class RouteResult:
    """规划器对外返回的稳定结果对象。"""

    status: str
    algorithm: str
    source: int
    target: int
    edge_ids: list[int] = field(default_factory=list)
    node_ids: list[int] = field(default_factory=list)
    geometry: tuple[Coordinate, ...] = ()
    distance_m: float = 0.0
    duration_s: float = 0.0
    cost: float = 0.0
    expanded_states: int = 0
    queue_pushes: int = 0
    planning_ms: float = 0.0
    #: 搜索过程记录。只有 ``plan_route(..., trace=True)`` 时才填充，
    #: 批量基准测试默认不收集（见 search_trace.TraceRecorder）。
    trace: "SearchTrace | None" = None

    def to_geojson(self) -> dict:
        """返回可直接交给 Leaflet/MapLibre 的 GeoJSON Feature。"""

        return {
            "type": "Feature",
            "properties": {
                "status": self.status,
                "algorithm": self.algorithm,
                "source": self.source,
                "target": self.target,
                "distance_m": self.distance_m,
                "duration_s": self.duration_s,
                "cost": self.cost,
                "edge_ids": self.edge_ids,
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [list(point) for point in self.geometry],
            },
        }


class Graph:
    """内存有向图。

    Graph 负责数据一致性和邻接访问；搜索策略和代价逻辑放在其它模块，便于替换。
    """

    def __init__(self) -> None:
        self.nodes: dict[int, Node] = {}
        self.edges: dict[int, Edge] = {}
        self._out_edges: dict[int, list[int]] = {}
        self.turn_rules: dict[tuple[int, int], TurnRule] = {}

    def add_node(self, node: Node) -> None:
        if node.node_id in self.nodes:
            raise ValueError(f"duplicate node id: {node.node_id}")
        self.nodes[node.node_id] = node
        self._out_edges[node.node_id] = []

    def add_edge(self, edge: Edge) -> None:
        if edge.edge_id in self.edges:
            raise ValueError(f"duplicate edge id: {edge.edge_id}")
        if edge.from_node not in self.nodes or edge.to_node not in self.nodes:
            raise ValueError("edge endpoints must exist before adding an edge")
        self.edges[edge.edge_id] = edge
        self._out_edges[edge.from_node].append(edge.edge_id)

    def add_turn_rule(self, rule: TurnRule) -> None:
        if rule.from_edge not in self.edges or rule.to_edge not in self.edges:
            raise ValueError("turn rule edges must exist before adding a rule")
        from_edge = self.edges[rule.from_edge]
        to_edge = self.edges[rule.to_edge]
        if from_edge.to_node != to_edge.from_node:
            raise ValueError("turn rule edges must be topologically adjacent")
        self.turn_rules[(rule.from_edge, rule.to_edge)] = rule

    def out_edges(self, node_id: int) -> Iterable[Edge]:
        for edge_id in self._out_edges.get(node_id, []):
            yield self.edges[edge_id]

    def edge(self, edge_id: int) -> Edge:
        return self.edges[edge_id]

    def node(self, node_id: int) -> Node:
        return self.nodes[node_id]
