"""osm_loader 的测试：把真实 GraphML 读成 path_planning.Graph。"""

import _bootstrap  # noqa: F401  (把 src/ 加入 sys.path)

import unittest
from pathlib import Path

from path_planning.costs import CostModel, Preference
from path_planning.osm_loader import _first_road_type, load_graphml, parse_wkt_linestring
from path_planning.router import plan_route

GRAPHML = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "campus_552.graphml"
)


class WktTests(unittest.TestCase):
    def test_parse_wkt_linestring(self):
        text = "LINESTRING (114.4119831 30.539114, 114.4120067 30.5391427)"
        self.assertEqual(
            parse_wkt_linestring(text),
            ((114.4119831, 30.539114), (114.4120067, 30.5391427)),
        )

    def test_parse_wkt_handles_empty(self):
        self.assertEqual(parse_wkt_linestring("not a linestring"), ())


class RoadTypeTests(unittest.TestCase):
    """highway 属性可能是列表字面量——真实数据里确实存在这种边。"""

    def test_plain_value(self):
        self.assertEqual(_first_road_type("residential"), "residential")

    def test_none_falls_back(self):
        self.assertEqual(_first_road_type(None), "residential")
        self.assertEqual(_first_road_type(""), "residential")

    def test_list_literal_takes_first_entry(self):
        # 这是校园路网里真实出现的值（2 条边）
        self.assertEqual(
            _first_road_type("['unclassified', 'residential']"), "unclassified"
        )

    def test_double_quoted_list(self):
        self.assertEqual(_first_road_type('["primary", "secondary"]'), "primary")

    def test_comma_separated(self):
        self.assertEqual(_first_road_type("trunk,primary"), "trunk")


@unittest.skipUnless(GRAPHML.exists(), f"缺少数据文件 {GRAPHML}")
class LoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = load_graphml(GRAPHML)

    def test_loads_expected_scale(self):
        """真实校园路网：552 个路口、1400 条有向边。"""
        self.assertEqual(len(self.graph.nodes), 552)
        self.assertEqual(len(self.graph.edges), 1400)

    def test_edge_ids_are_unique_and_dense(self):
        """GraphML 自带的 edge id 不唯一（大量重复的 0），我们改用连续编号。"""
        self.assertEqual(sorted(self.graph.edges), list(range(1400)))

    def test_edge_endpoints_exist(self):
        for edge in self.graph.edges.values():
            self.assertIn(edge.from_node, self.graph.nodes)
            self.assertIn(edge.to_node, self.graph.nodes)

    def test_geometry_parsed_for_about_half_the_edges(self):
        """只有约一半的边带 geometry；其余靠路口坐标兜底。"""
        with_geometry = sum(1 for e in self.graph.edges.values() if e.geometry)
        self.assertEqual(with_geometry, 731)

    def test_every_edge_has_positive_length_and_speed(self):
        for edge in self.graph.edges.values():
            self.assertGreater(edge.length_m, 0)
            self.assertGreater(edge.speed_kmh, 0)

    def test_runs_on_real_network(self):
        """在真实路网上跑通一次查询。"""
        model = CostModel(preference=Preference.SHORTEST)
        result = plan_route(self.graph, 1280163418, 6508258619, cost_model=model)
        self.assertGreater(result.distance_m, 0)
        self.assertGreater(len(result.edge_ids), 0)
        self.assertEqual(result.node_ids[0], 1280163418)
        self.assertEqual(result.node_ids[-1], 6508258619)


if __name__ == "__main__":
    unittest.main()
