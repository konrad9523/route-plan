import json
import pickle
import tempfile
import unittest
from pathlib import Path

import route_planner


def tiny_graph():
    return {
        "n_nodes": 5,
        "indptr": [0, 2, 3, 4, 4, 4],
        "indices": [1, 2, 2, 3],
        "weights": [10.0, 50.0, 10.0, 10.0],
        "edge_ids": [0, 1, 2, 3],
        "lon": [114.0, 114.001, 114.002, 114.003, 115.0],
        "lat": [30.0, 30.0, 30.0, 30.0, 31.0],
        "edges": [
            (0, 1, 10.0, "primary", "a", 36.0),
            (0, 2, 50.0, "primary", "b", 36.0),
            (1, 2, 10.0, "primary", "c", 36.0),
            (2, 3, 10.0, "primary", "d", 36.0),
        ],
    }


class RoutePlannerTests(unittest.TestCase):
    def setUp(self):
        self.planner = route_planner.RoutePlanner(tiny_graph(), max_landmarks=2)

    def tearDown(self):
        self.planner.close()

    def test_python_dijkstra_returns_frontend_route(self):
        route = self.planner.plan(0, 3, algorithm="dijkstra", version="L4")
        self.assertEqual(route["node_ids"], [0, 1, 2, 3])
        self.assertEqual(route["edge_ids"], [0, 2, 3])
        self.assertEqual(route["distance_m"], 30.0)
        self.assertEqual(route["duration_s"], 3.0)
        self.assertEqual(route["geometry"][0], [114.0, 30.0])
        json.dumps(route, allow_nan=False)

    def test_python_astar_variants_return_search_stats(self):
        for version, heuristic in (("L4", "H0"), ("L4", "ALT"), ("B1", "H0")):
            with self.subTest(version=version, heuristic=heuristic):
                route = self.planner.plan(
                    0, 3, algorithm="astar", version=version,
                    heuristic=heuristic, landmark_count=2,
                )
                self.assertEqual(route["distance_m"], 30.0)
                self.assertIsNotNone(route["stats"]["queue_pushes"])

    def test_unreachable_and_same_node_routes(self):
        no_route = self.planner.plan(0, 4)
        self.assertEqual(no_route["status"], "no_route")
        self.assertEqual(no_route["geometry"], [])
        same_node = self.planner.plan(2, 2)
        self.assertEqual(same_node["node_ids"], [2])
        self.assertEqual(same_node["distance_m"], 0.0)

    def test_rejects_unknown_node(self):
        with self.assertRaises(ValueError):
            self.planner.plan(0, 5)

    def test_astar_cpp_default_matches_notebook_build_directory(self):
        expected = route_planner.CODE_DIR / ".build" / "astar_cpp"
        self.assertEqual(route_planner._default_cpp_path("astar").parent, expected)

    def test_from_pickle_loads_maxspeed_from_adjacent_graphml(self):
        with tempfile.TemporaryDirectory(dir=route_planner.CODE_DIR) as directory:
            graph_path = Path(directory) / "graph_v2.pkl"
            graphml_path = Path(directory) / "wuhan_distance_v2.graphml"
            with graph_path.open("wb") as stream:
                pickle.dump(tiny_graph(), stream)
            edges_xml = "".join(
                f'<edge source="{u}" target="{v}"><data key="tags">{tags}</data></edge>'
                for u, v, tags in (
                    (0, 1, '{"highway":"primary","maxspeed":"45"}'),
                    (0, 2, '{"highway":"primary"}'),
                    (1, 2, '{"highway":"primary"}'),
                    (2, 3, '{"highway":"primary"}'),
                )
            )
            graphml_path.write_text(
                '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">'
                '<key id="tags" for="edge" attr.name="source_tags" attr.type="string"/>'
                f'<graph id="G" edgedefault="directed">{edges_xml}</graph></graphml>',
                encoding="utf-8",
            )
            planner = route_planner.RoutePlanner.from_pickle(graph_path)
            try:
                route = planner.plan(0, 3, algorithm="dijkstra")
                self.assertEqual(route["segments"][0]["speed_kmh"], 45.)
                self.assertEqual(route["segments"][0]["speed_source"], "osm_maxspeed")
                self.assertAlmostEqual(route["duration_s"], 2.8)
            finally:
                planner.close()

    def test_cpp_backends_when_compiled_libraries_are_available(self):
        missing = [
            path for path in self.planner._cpp_paths.values() if not path.is_file()
        ]
        if missing:
            self.skipTest(f"C++ 动态库未编译：{missing[0]}")

        for algorithm, options in (
            ("dijkstra", {"version": "L4"}),
            ("astar", {"version": "L4", "heuristic": "H0"}),
            ("astar", {"version": "B1", "heuristic": "ALT", "landmark_count": 2}),
        ):
            with self.subTest(algorithm=algorithm, options=options):
                route = self.planner.plan(0, 3, algorithm=algorithm,
                                          language="cpp", **options)
                self.assertEqual(route["distance_m"], 30.0)
                self.assertEqual(route["edge_ids"], [0, 2, 3])
                json.dumps(route, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
