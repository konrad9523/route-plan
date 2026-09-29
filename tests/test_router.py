import unittest

from path_planning.costs import CostModel, Preference
from path_planning.demo import build_demo_graph
from path_planning.models import Edge, Graph, Node, TurnRule
from path_planning.router import NoRouteError, plan_route


class RouterTests(unittest.TestCase):
    def test_astar_matches_dijkstra_for_fastest_route(self):
        graph = build_demo_graph()
        model = CostModel(preference=Preference.FASTEST)
        dijkstra = plan_route(graph, 1, 4, algorithm="dijkstra", cost_model=model)
        astar = plan_route(graph, 1, 4, algorithm="astar", cost_model=model)
        self.assertEqual(dijkstra.edge_ids, astar.edge_ids)
        self.assertAlmostEqual(dijkstra.cost, astar.cost)

    def test_shortest_and_fastest_can_choose_different_routes(self):
        graph = build_demo_graph()
        shortest = plan_route(graph, 1, 4, cost_model=CostModel(Preference.SHORTEST))
        fastest = plan_route(graph, 1, 4, cost_model=CostModel(Preference.FASTEST))
        self.assertEqual(shortest.edge_ids, [101, 102])
        self.assertAlmostEqual(shortest.cost, 2000.0)
        self.assertEqual(fastest.edge_ids, [103, 104])

    def test_no_highway_avoids_motorway(self):
        graph = build_demo_graph()
        result = plan_route(graph, 1, 4, cost_model=CostModel(Preference.NO_HIGHWAY))
        self.assertEqual(result.edge_ids, [101, 102])

    def test_forbidden_turn_is_respected(self):
        graph = build_demo_graph()
        graph.add_node(Node(5, 114.3200, 30.5100))
        graph.add_edge(Edge(105, 2, 5, 500, 30))
        graph.add_edge(Edge(106, 5, 4, 500, 30))
        graph.add_turn_rule(TurnRule(101, 102, forbidden=True))
        result = plan_route(graph, 1, 4, cost_model=CostModel(Preference.SHORTEST))
        self.assertEqual(result.edge_ids, [101, 105, 106])

    def test_no_route_raises_explicit_error(self):
        graph = Graph()
        graph.add_node(Node(1, 114.3, 30.5))
        graph.add_node(Node(2, 114.4, 30.5))
        with self.assertRaises(NoRouteError):
            plan_route(graph, 1, 2)

    def test_geojson_contains_route_geometry(self):
        result = plan_route(build_demo_graph(), 1, 4)
        feature = result.to_geojson()
        self.assertEqual(feature["geometry"]["type"], "LineString")
        self.assertGreaterEqual(len(feature["geometry"]["coordinates"]), 2)

    def test_geometry_falls_back_to_node_coordinates(self):
        graph = Graph()
        graph.add_node(Node(1, 114.3, 30.5))
        graph.add_node(Node(2, 114.4, 30.5))
        graph.add_edge(Edge(1, 1, 2, 100, 30))
        feature = plan_route(graph, 1, 2).to_geojson()
        self.assertEqual(feature["geometry"]["coordinates"], [[114.3, 30.5], [114.4, 30.5]])


if __name__ == "__main__":
    unittest.main()
