import json
import unittest
from copy import deepcopy
from math import inf, nan

from astar_variants import (build_csr, estimate_heuristic_scale, prevalidate_graph,
                            run_astar)
from dijkstra_variants import dijkstra_l1, dijkstra_l2, dijkstra_l3, dijkstra_l4
from route_output import build_route_output


class RouteOutputTests(unittest.TestCase):
    def setUp(self):
        self.rows = [(0, 1, 100., "residential", "路段甲", 36.),
                     (1, 2, 200., "primary", "路段乙", 72.),
                     (0, 1, 400., "primary", "平行边", 36.)]
        self.result = ([0, 1, 2], [0, 1], 300., 3)

    def output(self, result=None, records=None, **kwargs):
        return build_route_output(self.result if result is None else result,
                                  self.rows if records is None else records,
                                  0, 2, algorithm="test", **kwargs)

    def test_distance_time_order_and_json(self):
        route = self.output(planning_ms=1.25)
        self.assertEqual(route["distance_m"], 300.)
        self.assertEqual(route["duration_s"], 20.)
        self.assertEqual(route["duration_status"], "complete")
        self.assertEqual(route["planning_ms"], 1.25)
        self.assertEqual(route["edge_ids"], [0, 1])
        self.assertEqual([s["sequence"] for s in route["segments"]], [1, 2])
        self.assertEqual(route["segments"][0]["speed_source"], "edge_speed_kmh")
        self.assertEqual(json.loads(json.dumps(route, allow_nan=False)), route)

    def test_osm_maxspeed_override_precedes_edge_and_road_class_speeds(self):
        route = self.output(edge_speed_overrides={1: 36.})
        self.assertEqual(route["segments"][1]["speed_kmh"], 36.)
        self.assertEqual(route["segments"][1]["speed_source"], "osm_maxspeed")
        self.assertEqual(route["duration_s"], 30.)

    def test_missing_edge_speed_uses_labeled_road_class_estimate(self):
        self.rows[1] = (1, 2, 200., "primary", "路段乙", None)
        route = self.output()
        self.assertEqual(route["segments"][1]["speed_kmh"], 60.)
        self.assertEqual(route["segments"][1]["speed_source"], "road_class_estimate")
        self.assertEqual(route["duration_s"], 22.)
        self.assertTrue(any("道路等级回退估算速度" in w for w in route["warnings"]))

    def test_mapping_supports_noncontiguous_edge_ids_and_explicit_time(self):
        records = {10: dict(from_node=0, to_node=1, length_m=100.,
                            speed_kmh=36., travel_time_s=15.),
                   30: dict(from_node=1, to_node=2, length_m=200., travel_time_s=25.)}
        route = self.output(([0, 1, 2], [10, 30], 300., 3), records)
        self.assertEqual(route["duration_s"], 40.)
        self.assertEqual(route["segments"][0]["duration_source"], "provided_travel_time_s")

    def test_missing_one_edge_does_not_report_partial_time(self):
        self.rows[1] = (1, 2, 200., "unknown_road", "路段乙", None)
        route = self.output()
        self.assertIsNone(route["duration_s"])
        self.assertEqual(route["duration_status"], "missing")
        self.assertEqual(route["segments"][0]["duration_s"], 10.)
        self.assertIsNone(route["segments"][1]["duration_s"])
        self.assertTrue(route["warnings"])

    def test_assumed_speed_is_opt_in_and_marked(self):
        self.rows[1] = (1, 2, 200., "unknown_road", "路段乙", None)
        route = self.output(assumed_speed_kmh=36.)
        self.assertEqual(route["duration_s"], 30.)
        self.assertEqual(route["segments"][0]["duration_source"], "edge_speed_kmh")
        self.assertEqual(route["segments"][1]["duration_source"], "assumed_speed_kmh")
        self.assertEqual(route["segments"][1]["speed_kmh"], 36.)
        self.assertTrue(route["warnings"])

    def test_same_endpoint_needs_no_speed(self):
        route = build_route_output(([0], [], 0., 1), [], 0, 0, algorithm="test")
        self.assertEqual((route["distance_m"], route["duration_s"]), (0., 0.))
        self.assertEqual(route["segments"], [])

    def test_no_route_is_strict_json_without_infinity(self):
        route = self.output(([], [], inf, 1))
        self.assertEqual(route["status"], "no_route")
        self.assertIsNone(route["distance_m"])
        self.assertIsNone(route["duration_s"])
        self.assertIsNone(route["cost"])
        json.dumps(route, allow_nan=False)

    def test_invalid_path_shapes_are_rejected(self):
        for result in (([1, 2], [1], 200., 2), ([0, 1, 2], [0], 300., 3),
                       ([], [], 0., 1), ([0, 1, 2], [-1, 1], 300., 3)):
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.output(result)

    def test_wrong_edge_direction_or_unknown_edge_is_rejected(self):
        for edges in ([1, 0], [0, 99]):
            with self.subTest(edges=edges), self.assertRaises(ValueError):
                self.output(([0, 1, 2], edges, 300., 3))

    def test_wrong_parallel_edge_or_cost_unit_is_rejected(self):
        for result in (([0, 1, 2], [2, 1], 300., 3),
                       ([0, 1, 2], [0, 1], 20., 3)):
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.output(result)

    def test_invalid_numbers_are_rejected(self):
        for speed in (0., -1., inf, nan):
            with self.subTest(speed=speed), self.assertRaises(ValueError):
                self.output(assumed_speed_kmh=speed)
        for elapsed in (-1., inf, nan):
            with self.subTest(elapsed=elapsed), self.assertRaises(ValueError):
                self.output(planning_ms=elapsed)
        for length in (-1., inf, nan):
            rows = deepcopy(self.rows)
            rows[0] = (0, 1, length, *rows[0][3:])
            with self.subTest(length=length), self.assertRaises(ValueError):
                self.output(records=rows)
        for speed in (0., -1., inf, nan):
            rows = deepcopy(self.rows)
            rows[0] = (*rows[0][:5], speed)
            with self.subTest(edge_speed=speed), self.assertRaises(ValueError):
                self.output(records=rows)

    def test_explicit_time_must_be_finite_and_nonnegative(self):
        for duration in (-1., inf, nan):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                self.output(records={0: dict(from_node=0, to_node=1, length_m=100.,
                                             travel_time_s=duration)})

    def test_zero_length_edge_needs_no_speed(self):
        route = build_route_output(([0, 1], [0], 0., 2),
                                   [(0, 1, 0., "", "", None)], 0, 1, algorithm="test")
        self.assertEqual(route["duration_s"], 0.)

    def test_extreme_speed_does_not_underflow_during_unit_conversion(self):
        route = build_route_output(([0, 1], [0], 5e-324, 2),
                                   [(0, 1, 5e-324, "", "", 5e-324)], 0, 1, algorithm="test")
        self.assertEqual(route["duration_s"], 3.6)
        with self.assertRaises(ValueError):
            build_route_output(([0, 1], [0], 1., 2),
                               [(0, 1, 1., "", "", 5e-324)], 0, 1, algorithm="test")

    def test_input_result_and_metadata_are_not_mutated(self):
        saved = deepcopy((self.result, self.rows))
        self.output()
        self.assertEqual((self.result, self.rows), saved)

    def test_all_python_single_direction_layers_keep_four_tuple_contract(self):
        graph = {0: [(1, 400., 2), (1, 100., 0)], 1: [(2, 200., 1)], 2: []}
        positions = {u: (114. + u * .0001, 30.) for u in graph}
        prevalidate_graph(graph, positions)
        csr = build_csr(graph)
        dcsr = dict(n_nodes=3, indptr=csr[0], indices=csr[1], weights=csr[2], edge_ids=csr[3])
        scale = estimate_heuristic_scale(graph, positions)
        results = [f(graph, 0, 2) for f in (dijkstra_l1, dijkstra_l2, dijkstra_l3)]
        results.append(dijkstra_l4(dcsr, 0, 2))
        results.extend(run_astar(layer, graph, positions, 0, 2, csr=csr,
                                 heuristic_scale=scale)
                       for layer in ("L0", "L0-CachedScale", "L1", "L2", "L3", "L4", "L5"))
        for result in results:
            with self.subTest(result=result):
                self.assertEqual(len(result), 4)
                self.assertEqual(self.output(result)["duration_s"], 20.)


if __name__ == "__main__":
    unittest.main()
