"""共享工具：供 A2 正确性测试独立使用。"""
from __future__ import annotations

import argparse
import csv
import heapq
import importlib.util
import json
import math
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter
    from matplotlib.collections import LineCollection
    from matplotlib import font_manager
except ImportError as exc:  # pragma: no cover
    raise SystemExit("请先安装绘图依赖：python -m pip install matplotlib pillow") from exc


# ---------- 中文字体自动检测 ----------
def _setup_chinese_font() -> str:
    """按优先级寻找系统可用的中文字体，设置到 matplotlib。

    返回实际选中的字体名。若一个中文字体都没有，退回 DejaVu Sans 并打印警告。
    """
    candidates = [
        # Windows
        "Microsoft YaHei", "SimHei", "SimSun", "KaiTi", "FangSong",
        # macOS
        "PingFang SC", "Hiragino Sans GB", "STHeiti", "Arial Unicode MS",
        # Linux
        "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei",
        "WenQuanYi Zen Hei", "Droid Sans Fallback",
        # 兜底
        "DejaVu Sans",
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = [name for name in candidates if name in available]
    if not chosen:
        chosen = ["DejaVu Sans"]
        print("[警告] 未找到任何中文字体，中文可能显示为方框。"
              "请安装微软雅黑 / 黑体 / Noto Sans CJK 等字体。")
    else:
        print(f"[字体] 使用中文字体：{chosen[0]}")
    matplotlib.rcParams["font.sans-serif"] = chosen
    matplotlib.rcParams["axes.unicode_minus"] = False
    return chosen[0]


CHINESE_FONT = _setup_chinese_font()


A2_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = A2_ROOT.parents[1]
LOADER_DIR = A2_ROOT / "01_实现清单"
sys.path.insert(0, str(LOADER_DIR))
from graphml_to_graph import load_graphml

# 路网注册表
sys.path.insert(0, str(Path(__file__).resolve().parent))
from networks import NETWORKS, DEFAULT_NETWORK, get_network, results_dir


def save_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def load_algorithms(directory: Path):
    """从指定目录加载 dijkstra.py 和 astar.py（或 astra.py）。"""
    directory = directory.resolve()
    sys.path.insert(0, str(directory))
    try:
        from dijkstra import dijkstra
        from astar import astar, estimate_heuristic_scale, haversine_distance
    except Exception as exc:
        raise RuntimeError(
            f"无法从 {directory} 导入 dijkstra.py 和 astar.py：{exc}"
        ) from exc
    return dijkstra, astar, estimate_heuristic_scale, haversine_distance


def load_runtime(graphml: Path, algorithm_dir: Path):
    graph, positions, geometries = load_graphml(graphml)
    dijkstra, astar, estimate_scale, haversine = load_algorithms(algorithm_dir)
    started = time.perf_counter()
    scale = estimate_scale(graph, positions)
    scale_ms = (time.perf_counter() - started) * 1000
    print(f"路网已加载：{len(graph):,} 个节点，{sum(map(len, graph.values())):,} 条有向边")
    print(f"Haversine 启发系数：{scale:.12g}，计算耗时 {scale_ms:.2f} ms")
    return graph, positions, geometries, dijkstra, astar, haversine, scale, scale_ms


def add_common_arguments(parser: argparse.ArgumentParser,
                         default_output: Path) -> argparse.ArgumentParser:
    parser.add_argument("--network", type=str, default=DEFAULT_NETWORK,
                        choices=list(NETWORKS), help="选择路网")
    parser.add_argument("--graphml", type=Path, default=None,
                        help="直接指定 GraphML 路径（覆盖 --network）")
    parser.add_argument("--algorithm-dir", type=Path,
                        default=PROJECT_ROOT / "src" / "path_planning",
                        help="包含 dijkstra.py 和 astar.py 的目录")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="测试结果输出目录（不传时按路网自动命名）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    return parser


def resolve_args(args, default_output_base: Path):
    """把 --network / --graphml / --output-dir 解析成最终值。

    - --graphml 显式指定时优先用它。
    - 否则用 --network 对应的路网文件。
    - --output-dir 不传时，用 default_output_base / <路网名>。
    """
    if args.graphml is None:
        info = get_network(args.network)
        args.graphml = info["graphml"]
    if args.output_dir is None:
        args.output_dir = results_dir(default_output_base, args.network)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    return args


def reverse_graph(graph):
    rev = {node: [] for node in graph}
    for u, outgoing in graph.items():
        for v, weight, edge_id in outgoing:
            rev[v].append((u, weight, edge_id))
    return rev


def reverse_dijkstra(graph, target):
    """反向图上的 Dijkstra，计算所有节点到 target 的真实最短距离。"""
    rev = reverse_graph(graph)
    dist = {target: 0.0}
    queue = [(0.0, 0, target)]
    serial = 1
    while queue:
        d, _, u = heapq.heappop(queue)
        if d != dist.get(u):
            continue
        for v, weight, _ in rev[u]:
            nd = d + weight
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                heapq.heappush(queue, (nd, serial, v))
                serial += 1
    return dist


class TrackingGraph(dict):
    """记录搜索算法读取过邻接表的节点。"""
    def __init__(self, source):
        super().__init__(source)
        self.expansion_order: list[str] = []

    def __getitem__(self, key):
        self.expansion_order.append(key)
        return super().__getitem__(key)


def draw_road_map(ax, graph, positions, geometries, *, expanded=None, frontier=None,
                  path_nodes=None, title="", zoom_nodes=None):
    expanded = set(expanded or [])
    frontier = set(frontier or []) - expanded
    path_nodes = list(path_nodes or [])
    focus = set(zoom_nodes or []) | expanded | frontier | set(path_nodes)
    if focus:
        xs = [positions[n][0] for n in focus if n in positions]
        ys = [positions[n][1] for n in focus if n in positions]
    else:
        xs = [p[0] for p in positions.values()]
        ys = [p[1] for p in positions.values()]
    if not xs:
        return
    dx = max(max(xs) - min(xs), 0.003)
    dy = max(max(ys) - min(ys), 0.003)
    xmin, xmax = min(xs) - dx * .25, max(xs) + dx * .25
    ymin, ymax = min(ys) - dy * .25, max(ys) + dy * .25
    lines = []
    for points in geometries.values():
        if len(points) >= 2 and any(xmin <= x <= xmax and ymin <= y <= ymax
                                    for x, y in points):
            lines.append(points)
    if not lines:
        for u, outgoing in graph.items():
            if u not in positions:
                continue
            for v, _, _ in outgoing:
                if v in positions and (u in focus or v in focus):
                    lines.append([positions[u], positions[v]])
    if lines:
        ax.add_collection(LineCollection(lines, colors="#cbd5e1", linewidths=.45,
                                         alpha=.55, zorder=1))
    for group, color, label in ((frontier, "#f59e0b", "未扩展边界邻居（近似）"),
                                (expanded, "#60a5fa", "已扩展")):
        xy = [positions[n] for n in group if n in positions]
        if xy:
            ax.scatter([p[0] for p in xy], [p[1] for p in xy], s=8, c=color,
                       alpha=.65, label=label, zorder=3)
    xy = [positions[n] for n in path_nodes if n in positions]
    if xy:
        ax.plot([p[0] for p in xy], [p[1] for p in xy], color="#dc2626", linewidth=2,
                marker="o", markersize=2.5, label="最终路径", zorder=5)
        ax.scatter([xy[0][0], xy[-1][0]], [xy[0][1], xy[-1][1]],
                   c=["#16a34a", "#7c3aed"], s=42, zorder=6)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("经度")
    ax.set_ylabel("纬度")
    ax.set_title(title)
    ax.grid(alpha=.15)
    if expanded or frontier or path_nodes:
        ax.legend(loc="best", fontsize=7)


def sample_reachable_pairs(graph, nodes, dijkstra, rng, desired, max_attempts=None):
    nodes = list(nodes)
    pairs = []
    max_attempts = max_attempts or desired * 30
    for _ in range(max_attempts):
        source, target = rng.choice(nodes), rng.choice(nodes)
        if source == target:
            continue
        if math.isfinite(dijkstra(graph, source, target)[2]):
            pairs.append((source, target))
        if len(pairs) >= desired:
            break
    return pairs


def print_result(test_id: str, result: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / f"{test_id}_summary.json", result)
    print(f"\n{test_id} 结果：")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"结果文件夹：{output_dir}")