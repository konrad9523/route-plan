"""A3 武汉实验的本机数据与输出路径；不依赖临时工作区。"""

from __future__ import annotations

import os
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CODE_DIR.parents[3]
WORKSPACE_DATA = Path(
    os.environ.get("ROUTE_PLAN_DATA_DIR") or PROJECT_ROOT / "cache" / "a3_wuhan"
).expanduser().resolve()
RESULT_DIR = PROJECT_ROOT / "cache" / "a3_wuhan" / "runs"


def data_dir() -> Path:
    if not WORKSPACE_DATA.is_dir():
        raise FileNotFoundError(
            f"数据目录不存在：{WORKSPACE_DATA}。请先下载/建图，"
            "或设置 ROUTE_PLAN_DATA_DIR 指向含 processed/graph.pkl 的可信本机数据目录。"
        )
    return WORKSPACE_DATA


def processed_dir() -> Path:
    return WORKSPACE_DATA / "processed"


def osm_path(city: str = "wuhan") -> Path:
    return WORKSPACE_DATA / f"{city}_drive.osm"


def _self_check() -> None:
    """不下载城市数据；守护迁移后的路径、导入、对拍和建图输出。"""
    import ast
    import importlib
    import math
    import pickle
    import tempfile
    from unittest.mock import patch

    for source in CODE_DIR.glob("*.py"):
        ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    benchmarks = [
        importlib.import_module(name)
        for name in (
            "wuhan_dijkstra_benchmark", "wuhan_dijkstra_layered_ablation",
            "wuhan_dijkstra_layered_ablation_v3", "wuhan_astar_layered_ablation",
            "wuhan_alt_landmark_ablation",
        )
    ]
    for benchmark in benchmarks:
        if hasattr(benchmark, "DATA_FILE"):
            assert benchmark.DATA_FILE == processed_dir() / "graph.pkl"
            assert benchmark.RESULT_FILE.parent == RESULT_DIR
    assert RESULT_DIR != CODE_DIR

    import astar as original_astar
    import dijkstra as original_dijkstra
    import improved_algorithms as work
    import astar_alt
    import build_graph
    import _paths as paths

    graph = {
        0: [(1, 5.0, 0), (1, 1.0, 1), (2, 10.0, 3)],
        1: [(2, 2.0, 2)], 2: [(0, 4.0, 4)], 3: [],
    }
    pairs = {u: [(v, w) for v, w, _ in edges] for u, edges in graph.items()}
    positions = {u: (0.0, 0.0) for u in graph}
    assert original_dijkstra.dijkstra(pairs, 0, 2)[1] == 3.0
    assert original_astar.astar(graph, positions, 0, 2)[2] == 3.0
    alt = astar_alt.LandmarkALT(graph, positions, [0, 1, 2], 2)
    for result in (
        work.dijkstra(graph, positions, 0, 2),
        work.astar(graph, positions, 0, 2),
        work.bidirectional_astar(graph, positions, 0, 2),
        alt.astar(0, 2, include_plane=False),
    ):
        assert result.distance == 3.0
        assert result.node_path == [0, 1, 2] and result.edge_path == [1, 2]
    assert work.dijkstra(graph, positions, 0, 0).distance == 0.0
    assert not work.dijkstra(graph, positions, 0, 3).found
    experiment = importlib.import_module("wuhan_dijkstra_layered_ablation")
    for name in ("triple_input_control", "layer1_edge_ids", "layer2_settled_set",
                 "layer3_route_outcome", "layer4_validated_input"):
        assert experiment.unpack(getattr(experiment, name)(graph, 0, 2))[0] == 3.0

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="a3-self-check-", dir=RESULT_DIR) as temp_dir:
        sample = Path(temp_dir)
        sample.joinpath("wuhan_drive.osm").write_text(
            '<osm version="0.6">'
            '<node id="1" lon="114" lat="30"/>'
            '<node id="2" lon="114.001" lat="30"/>'
            '<node id="3" lon="114.002" lat="30"/>'
            '<way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/>'
            '<tag k="highway" v="residential"/></way></osm>',
            encoding="utf-8",
        )
        with patch.object(paths, "WORKSPACE_DATA", sample):
            assert paths.data_dir() == sample
            assert build_graph.main() == 0
            with paths.processed_dir().joinpath("graph.pkl").open("rb") as fh:
                snapshot = pickle.load(fh)  # Only load the fixture built above.
            assert snapshot["n_nodes"] == 2 and len(snapshot["edges"]) == 2
            assert len(snapshot["indptr"]) == 3
            assert all(math.isfinite(w) and w > 0 for w in snapshot["weights"])
        with patch.object(paths, "WORKSPACE_DATA", sample / "missing"):
            try:
                paths.data_dir()
            except FileNotFoundError:
                pass
            else:
                raise AssertionError("Missing data directory must be rejected")
    print("A3 self-check: PASS (syntax, imports, paths, shortest paths, build output)")


if __name__ == "__main__":
    _self_check()
