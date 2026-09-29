"""无需外部数据即可运行的路径规划示例。"""

from __future__ import annotations

import json

from .costs import CostModel, Preference
from .models import Edge, Graph, Node, TurnRule
from .router import plan_route


def build_demo_graph() -> Graph:
    graph = Graph()
    for node_id, lon, lat in [
        (1, 114.3000, 30.5000),
        (2, 114.3100, 30.5000),
        (3, 114.3000, 30.5100),
        (4, 114.3100, 30.5100),
    ]:
        graph.add_node(Node(node_id, lon, lat))

    edges = [
        Edge(101, 1, 2, 1000, 30, geometry=((114.3000, 30.5000), (114.3100, 30.5000))),
        Edge(102, 2, 4, 1000, 30, geometry=((114.3100, 30.5000), (114.3100, 30.5100))),
        Edge(103, 1, 3, 1300, 80, road_type="motorway", toll=True, geometry=((114.3000, 30.5000), (114.3000, 30.5100))),
        Edge(104, 3, 4, 1300, 80, road_type="motorway", toll=True, geometry=((114.3000, 30.5100), (114.3100, 30.5100))),
    ]
    for edge in edges:
        graph.add_edge(edge)
    graph.add_turn_rule(TurnRule(101, 102, penalty_s=5))
    return graph


def main() -> None:
    graph = build_demo_graph()
    for preference in (Preference.FASTEST, Preference.SHORTEST, Preference.NO_HIGHWAY):
        result = plan_route(graph, 1, 4, cost_model=CostModel(preference=preference))
        print(preference.value, json.dumps(result.to_geojson(), ensure_ascii=False))


if __name__ == "__main__":
    main()
