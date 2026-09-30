"""SearchTrace 的测试：搜索过程记录、状态重建、降采样、开销。"""

import _bootstrap  # noqa: F401  (把 src/ 加入 sys.path)

import json
import unittest
from pathlib import Path

from path_planning.costs import CostModel, Preference
from path_planning.models import Edge, Graph, Node
from path_planning.router import plan_route
from path_planning.search_trace import SearchTrace, TraceRecorder

GRAPHML = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "campus_552.graphml"
)


def build_small_graph() -> Graph:
    """一条链：1-2-3-4，外加一条 1->4 的直达长边。"""

    graph = Graph()
    for node_id in range(1, 5):
        graph.add_node(Node(node_id, 0.001 * node_id, 0.0))
    graph.add_edge(Edge(1, 1, 2, 100.0, 30.0))
    graph.add_edge(Edge(2, 2, 3, 100.0, 30.0))
    graph.add_edge(Edge(3, 3, 4, 100.0, 30.0))
    graph.add_edge(Edge(4, 1, 4, 900.0, 30.0))
    return graph


class RecorderTests(unittest.TestCase):
    """记录器本身的行为——不依赖 router。"""

    def test_disabled_recorder_records_nothing(self):
        recorder = TraceRecorder(False)
        recorder.record_pop(1, 0.0, None)
        recorder.record_discover(2)
        recorder.finish(
            expanded_states=0, queue_pushes=0, path_nodes=[], path_edges=[], goal_step=None
        )
        self.assertEqual(recorder.trace.pop_order, [])
        self.assertEqual(recorder.trace.discovered_order, [])

    def test_enabled_recorder_records_in_order(self):
        recorder = TraceRecorder(True, algorithm="astar", preference="shortest")
        recorder.record_pop(1, 0.0, None)
        recorder.record_discover(2)
        recorder.record_pop(2, 5.0, 7)
        self.assertEqual(recorder.trace.pop_order, [1, 2])
        self.assertEqual(recorder.trace.settled_cost_values, [0.0, 5.0])
        self.assertEqual(recorder.trace.discovered_order, [2])
        # 发现记录的是"从第几步开始算已发现"。节点 2 是在处理第 1 步的过程中
        # 被发现的，所以从第 2 步（= 已完成 pop 次数 + 1）开始算。
        self.assertEqual(recorder.trace.discovered_after_steps, [2])
        self.assertEqual(recorder.trace.settled_via_edge, {2: 7})

    def test_duplicate_discovery_is_recorded_once(self):
        """同一节点被多次松弛，只能记一次发现。"""

        recorder = TraceRecorder(True)
        recorder.record_pop(1, 0.0, None)
        recorder.record_discover(2)
        recorder.record_pop(2, 5.0, 1)
        recorder.record_discover(2)  # 重复
        self.assertEqual(recorder.trace.discovered_order, [2])


class StateReconstructionTests(unittest.TestCase):
    """已访问 / 边界 / 路径 的重建。"""

    def test_state_at_step_zero_is_empty(self):
        graph = build_small_graph()
        result = plan_route(graph, 1, 4, algorithm="dijkstra", trace=True)
        state = result.trace.state_at(0)
        self.assertEqual(state["visited"], [])
        self.assertEqual(state["frontier"], [])
        self.assertEqual(state["path"], [])

    def test_final_state_contains_path(self):
        graph = build_small_graph()
        result = plan_route(graph, 1, 4, algorithm="dijkstra", trace=True)
        trace = result.trace
        state = trace.state_at(len(trace.pop_order))
        self.assertEqual(state["path"], result.node_ids)

    def test_frontier_appears_after_the_step_that_discovered_it(self):
        """边界的出现时机：晚于"发现它的那一步"。

        时序细节：节点是在**处理第 k 步的过程中**被松弛出来的。
        所以站在第 k 步时，`visited` 里只有刚取出的那个节点，
        而它的邻居要到第 k+1 步才出现在 `frontier` 里。
        这个"慢一拍"是真实时序，不是 bug。
        """

        graph = build_small_graph()
        result = plan_route(graph, 1, 4, algorithm="dijkstra", trace=True)
        trace = result.trace
        self.assertEqual(trace.pop_order[:2], [1, 2])

        # 第 1 步：只取出了起点 1，它的邻居还没进入边界
        at_one = trace.state_at(1)
        self.assertEqual(at_one["visited"], [1])
        self.assertEqual(at_one["frontier"], [])

        # 第 2 步：起点处理完了，邻居 4（直达长边）出现在边界里
        at_two = trace.state_at(2)
        self.assertIn(4, at_two["frontier"])

    def test_frontier_empties_at_the_end(self):
        graph = build_small_graph()
        result = plan_route(graph, 1, 4, algorithm="dijkstra", trace=True)
        trace = result.trace
        final = trace.state_at(len(trace.pop_order))
        self.assertEqual(final["frontier"], [])

    def test_frontier_is_monotonic_in_discovery(self):
        """边界里的节点一旦出现，要么继续留在边界，要么被取出——不会凭空消失。"""

        graph = build_small_graph()
        result = plan_route(graph, 1, 4, algorithm="dijkstra", trace=True)
        trace = result.trace
        seen_frontier: set[int] = set()
        for step in range(len(trace.pop_order) + 1):
            state = trace.state_at(step)
            current = set(state["frontier"])
            # 之前出现过的边界节点，现在只允许"被取出"这一种消失方式
            gone = seen_frontier - current
            for node in gone:
                self.assertIn(
                    node, state["visited"], f"节点 {node} 从边界消失却没有被取出"
                )
            seen_frontier |= current

    def test_visited_and_frontier_never_overlap(self):
        """边界是"已发现但未确定"，因此绝不能和已访问集合重叠。"""

        graph = build_small_graph()
        result = plan_route(graph, 1, 4, algorithm="dijkstra", trace=True)
        trace = result.trace
        for step in range(len(trace.pop_order) + 1):
            state = trace.state_at(step)
            self.assertEqual(set(state["visited"]) & set(state["frontier"]), set())

    def test_pop_order_matches_expanded_states(self):
        graph = build_small_graph()
        result = plan_route(graph, 1, 4, algorithm="dijkstra", trace=True)
        self.assertEqual(len(result.trace.pop_order), result.expanded_states)


class CompactFormatTests(unittest.TestCase):
    """紧凑格式与降采样。"""

    def test_compact_contains_no_dict_keyed_by_node(self):
        """体积关键：不出现以节点 ID 为键的字典。

        允许算法名/偏好/统计量是字符串或字典，其余数据字段必须是数组。
        """

        graph = build_small_graph()
        result = plan_route(graph, 1, 4, algorithm="dijkstra", trace=True)
        compact = result.trace.to_compact()
        non_array = {"algorithm", "preference", "stats"}
        for key, value in compact.items():
            if key in non_array:
                continue
            self.assertIsInstance(value, list, f"{key} 应该是数组，而不是字典")

    def test_compact_is_json_serializable(self):
        graph = build_small_graph()
        result = plan_route(graph, 1, 4, algorithm="dijkstra", trace=True)
        text = json.dumps(result.trace.to_compact(), ensure_ascii=False)
        self.assertGreater(len(text), 0)

    def test_downsample_caps_the_timeline(self):
        graph = build_small_graph()
        result = plan_route(graph, 1, 4, algorithm="dijkstra", trace=True)
        trace = result.trace
        reduced = trace.downsample(2)
        self.assertTrue(reduced.downsampled)
        self.assertLessEqual(len(reduced.pop_order), 2)
        self.assertEqual(reduced.original_steps, len(trace.pop_order))

    def test_downsample_actually_caps_across_many_limits(self):
        """回归：曾经用 `original // max_steps` 当步长，max_steps 较大时
        步长退化成 1，导致"调用了降采样却一步没减"。"""

        graph = build_small_graph()
        result = plan_route(graph, 1, 4, algorithm="dijkstra", trace=True)
        trace = result.trace
        for cap in (2, 3, 5, 10, 50, 1000):
            reduced = trace.downsample(cap)
            if len(trace.pop_order) <= cap:
                self.assertFalse(reduced.downsampled)
                continue
            self.assertLessEqual(
                len(reduced.pop_order), cap,
                f"cap={cap} 时输出 {len(reduced.pop_order)} 步，没有真正压缩",
            )

    def test_downsample_is_noop_when_already_short(self):
        graph = build_small_graph()
        result = plan_route(graph, 1, 4, algorithm="dijkstra", trace=True)
        trace = result.trace
        same = trace.downsample(10_000)
        self.assertFalse(same.downsampled)
        self.assertEqual(len(same.pop_order), len(trace.pop_order))

    def test_downsample_keeps_first_and_last_step(self):
        graph = build_small_graph()
        result = plan_route(graph, 1, 4, algorithm="dijkstra", trace=True)
        trace = result.trace
        reduced = trace.downsample(2)
        self.assertEqual(reduced.pop_order[0], trace.pop_order[0])
        self.assertEqual(reduced.pop_order[-1], trace.pop_order[-1])


class TraceDisabledTests(unittest.TestCase):
    def test_no_trace_by_default(self):
        graph = build_small_graph()
        result = plan_route(graph, 1, 4)
        self.assertIsNone(result.trace)


@unittest.skipUnless(GRAPHML.exists(), f"缺少数据文件 {GRAPHML}")
class RealNetworkTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from path_planning.osm_loader import load_graphml

        cls.graph = load_graphml(GRAPHML)
        cls.source, cls.target = 1260855371, 2864441887

    def test_trace_on_real_network(self):
        model = CostModel(preference=Preference.SHORTEST)
        result = plan_route(self.graph, self.source, self.target, algorithm="astar", cost_model=model, trace=True)
        trace = result.trace
        self.assertEqual(len(trace.pop_order), result.expanded_states)
        self.assertEqual(trace.path_nodes, result.node_ids)
        self.assertIsNotNone(trace.goal_step)
        self.assertLess(trace.goal_step, len(trace.pop_order))

    def test_found_at_reconstruction(self):
        model = CostModel(preference=Preference.SHORTEST)
        result = plan_route(self.graph, self.source, self.target, algorithm="astar", cost_model=model, trace=True)
        found = result.trace.found_at()
        self.assertEqual(len(found), len(result.trace.discovered_order))
        # 每个发现步号都必须小于总步数
        self.assertTrue(all(0 <= v <= len(result.trace.pop_order) for v in found.values()))


if __name__ == "__main__":
    unittest.main()
