"""针对两个已修复缺陷的回归测试。

缺陷 1：等代价时 heapq 比较 _State 对象 → TypeError
缺陷 2：A* 在几何不自洽的图上静默返回次优路径
"""

import unittest

from path_planning.costs import CostModel, Preference
from path_planning.models import Edge, Graph, Node
from path_planning.router import check_heuristic_consistency, plan_route


def build_equal_cost_diamond() -> Graph:
    """等权菱形图：上下两条路代价完全相同。

    修复前：heapq 在 (priority, cost) 相同时会去比较 _State，
    而 _State 没有定义 __lt__，直接抛 TypeError。
    """
    graph = Graph()
    for node_id, (lon, lat) in {
        1: (0.000, 0.000),
        2: (0.010, 0.000),
        3: (0.000, 0.010),
        4: (0.010, 0.010),
    }.items():
        graph.add_node(Node(node_id, lon, lat))

    for edge in [
        Edge(1, 1, 2, 1000.0, 40.0),
        Edge(2, 1, 3, 1000.0, 40.0),
        Edge(3, 2, 4, 1000.0, 40.0),
        Edge(4, 3, 4, 1000.0, 40.0),
    ]:
        graph.add_edge(edge)
    return graph


def build_geometrically_inconsistent_graph() -> Graph:
    """边权与节点坐标矛盾的图：50 米的边连着相距 2 公里的两个点。

    这种图会让"直线距离/最大速度"这个启发式失去一致性，
    A* 的最优性前提不成立。
    """
    graph = Graph()
    for node in [
        Node(0, 0.0195311472, 0.0146099158),
        Node(1, 0.0045234602, 0.0009070060),
        Node(2, 0.0077187505, 0.0193188345),
        Node(3, 0.0195231710, 0.0189524505),
        Node(4, 0.0106378135, 0.0001391472),
    ]:
        graph.add_node(node)

    for edge in [
        Edge(1, 1, 2, 200.0, 5.0, road_type="trunk"),
        Edge(2, 2, 1, 50.0, 5.0, road_type="trunk"),
        Edge(3, 3, 0, 50.0, 50.0, road_type="trunk"),
        Edge(4, 4, 1, 800.0, 20.0, road_type="primary"),
        Edge(5, 4, 2, 200.0, 20.0, road_type="motorway"),
    ]:
        graph.add_edge(edge)
    return graph


class EqualCostTieTests(unittest.TestCase):
    """缺陷 1 的回归。"""

    def test_dijkstra_does_not_crash_on_equal_costs(self):
        graph = build_equal_cost_diamond()
        result = plan_route(
            graph, 1, 4, algorithm="dijkstra", cost_model=CostModel(Preference.SHORTEST)
        )
        self.assertAlmostEqual(result.cost, 2000.0)

    def test_astar_does_not_crash_on_equal_costs(self):
        graph = build_equal_cost_diamond()
        result = plan_route(
            graph, 1, 4, algorithm="astar", cost_model=CostModel(Preference.SHORTEST)
        )
        self.assertAlmostEqual(result.cost, 2000.0)

    def test_both_algorithms_agree_on_cost(self):
        """两条路代价相同时，算法可以各选一条，但代价必须一致。"""
        graph = build_equal_cost_diamond()
        model = CostModel(Preference.SHORTEST)
        dijkstra = plan_route(graph, 1, 4, algorithm="dijkstra", cost_model=model)
        astar = plan_route(graph, 1, 4, algorithm="astar", cost_model=model)
        self.assertAlmostEqual(dijkstra.cost, astar.cost)

    def test_many_identical_edges_do_not_crash(self):
        """大量等权边：制造密集的代价平局。"""
        graph = Graph()
        for node_id in range(1, 8):
            graph.add_node(Node(node_id, 0.001 * node_id, 0.0))
        for node_id in range(1, 7):
            graph.add_edge(Edge(node_id, node_id, node_id + 1, 100.0, 30.0))
        for node_id in range(1, 6):
            graph.add_edge(Edge(100 + node_id, node_id, node_id + 2, 200.0, 30.0))
        for algorithm in ("dijkstra", "astar"):
            result = plan_route(
                graph, 1, 7, algorithm=algorithm, cost_model=CostModel(Preference.SHORTEST)
            )
            self.assertAlmostEqual(result.cost, 600.0)


class HeuristicConsistencyTests(unittest.TestCase):
    """缺陷 2 的回归：把"数据是否适合 A*"变成可检测的。"""

    def test_real_network_has_no_violations(self):
        """真实校园路网是几何自洽的，因此没有一致性违反。

        这条测试同时是"为什么可以用 A*"的证据。
        """
        from pathlib import Path

        from path_planning.osm_loader import load_graphml

        graphml = (
            Path(__file__).resolve().parent.parent
            / "learning_osmnx_networkx"
            / "output"
            / "graph.graphml"
        )
        if not graphml.exists():
            self.skipTest("缺少真实路网数据")
        graph = load_graphml(graphml)
        violations = check_heuristic_consistency(graph)
        self.assertEqual(violations, [], f"真实路网出现一致性违反: {violations[:5]}")

    def test_detects_geometrically_inconsistent_edges(self):
        """校验器必须能抓出边权与坐标矛盾的图。"""
        graph = build_geometrically_inconsistent_graph()
        violations = check_heuristic_consistency(graph)
        self.assertGreater(len(violations), 0, "校验器漏报了不一致的边")
        # 返回项：(edge_id, 目标节点, 高估量, 边长)
        for edge_id, _target, excess, length in violations:
            self.assertGreater(excess, 0)
            self.assertIn(edge_id, graph.edges)

    def test_dijkstra_is_optimal_even_on_inconsistent_graph(self):
        """Dijkstra 不受影响——它没有启发式，因此始终是最优基准。"""
        graph = build_geometrically_inconsistent_graph()
        result = plan_route(
            graph, 4, 1, algorithm="dijkstra", cost_model=CostModel(Preference.SHORTEST)
        )
        self.assertAlmostEqual(result.cost, 250.0)


if __name__ == "__main__":
    unittest.main()
