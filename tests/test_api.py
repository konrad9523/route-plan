"""API 的测试：用 FastAPI TestClient，不需要真的起服务器。"""

import _bootstrap  # noqa: F401  (把 src/ 加入 sys.path)

import unittest

from fastapi.testclient import TestClient

from api.main import app


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ok")

    def test_meta(self):
        res = self.client.get("/api/meta")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["node_count"], 552)
        self.assertEqual(data["edge_count"], 1400)
        self.assertIn("dijkstra", data["algorithms"])
        self.assertIn("astar", data["algorithms"])
        for key in ("min_lon", "min_lat", "max_lon", "max_lat"):
            self.assertIn(key, data["bbox"])

    def test_nodes_payload_is_parallel_arrays(self):
        res = self.client.get("/api/nodes")
        data = res.json()
        n = len(data["ids"])
        self.assertEqual(n, 552)
        self.assertEqual(len(data["lons"]), n)
        self.assertEqual(len(data["lats"]), n)

    def test_route_without_trace(self):
        res = self.client.post(
            "/api/route",
            json={"source": 1260855371, "target": 2864441887, "algorithm": "astar", "preference": "shortest"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        self.assertGreater(data["distance_m"], 0)
        self.assertGreater(len(data["edge_ids"]), 0)
        self.assertGreater(len(data["geometry"]), 1)
        self.assertNotIn("trace", data)
        self.assertIn("expanded_states", data["stats"])

    def test_route_with_trace(self):
        res = self.client.post(
            "/api/route",
            json={
                "source": 1260855371,
                "target": 2864441887,
                "algorithm": "astar",
                "preference": "shortest",
                "trace": True,
            },
        )
        data = res.json()
        self.assertIn("trace", data)
        trace = data["trace"]
        self.assertEqual(len(trace["pop_order"]), data["stats"]["expanded_states"])
        # 紧凑格式：都是数组
        for key in ("pop_order", "settled_cost_values", "discovered_order", "discovered_after_steps"):
            self.assertIsInstance(trace[key], list)
        self.assertEqual(trace["path_nodes"], data["node_ids"])

    def test_route_trace_respects_max_steps(self):
        res = self.client.post(
            "/api/route",
            json={
                "source": 1260855371,
                "target": 2864441887,
                "algorithm": "dijkstra",
                "preference": "shortest",
                "trace": True,
                "max_steps": 20,
            },
        )
        trace = res.json()["trace"]
        self.assertLessEqual(len(trace["pop_order"]), 20)
        self.assertTrue(trace["stats"]["downsampled"])

    def test_bad_preference_returns_400(self):
        res = self.client.post(
            "/api/route",
            json={"source": 1260855371, "target": 2864441887, "preference": "flying"},
        )
        self.assertEqual(res.status_code, 400)

    def test_bad_algorithm_returns_400(self):
        res = self.client.post(
            "/api/route",
            json={"source": 1260855371, "target": 2864441887, "algorithm": "floyd"},
        )
        self.assertEqual(res.status_code, 400)

    def test_unknown_node_returns_400(self):
        res = self.client.post(
            "/api/route",
            json={"source": 1, "target": 2},
        )
        self.assertEqual(res.status_code, 400)

    def test_index_serves_html(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("路径规划引擎", res.text)
        self.assertIn("leaflet", res.text.lower())


if __name__ == "__main__":
    unittest.main()
