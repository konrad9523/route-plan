"""T5：在真实 GraphML 路网上随机寻找 10 倍 Haversine A* 次优路线。

调用方式与 T2/T4 一致：load_runtime(graphml, algorithm_dir) 加载真实图、坐标、
Dijkstra、A*、Haversine 函数和算法默认启发系数。图中显示真实 OSM 道路几何。

本测试故意将默认 Haversine 启发值乘以 10；它验证测试框架能抓到不可采纳启发值
导致的次优结果，不表示默认 A* 会返回错误路径。
"""
from pathlib import Path
import math
import random
import re
import sys

import networkx as nx
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common.test_support import *

HEURISTIC_MULTIPLIER = 10.0
DEFAULT_TRIALS = 600
MIN_STRAIGHT_DISTANCE_M = 1500.0
MAX_STRAIGHT_DISTANCE_M = 15000.0


def _parse_wkt_line(value, fallback):
    """把 OSM GraphML 的 LINESTRING 几何转成 (lon, lat) 点列。"""
    if value is not None:
        pairs = re.findall(
            r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s+"
            r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)",
            str(value),
        )
        coords = []
        for x, y in pairs:
            lon, lat = float(x), float(y)
            if -180 <= lon <= 180 and -90 <= lat <= 90:
                coords.append((lon, lat))
        if len(coords) >= 2:
            return coords
    return list(fallback)


def _load_geometry_maps(graphml_path, positions):
    """读取实际道路折线；同时按边 ID 与 (u,v) 建索引，兼容 GraphML 多重边。"""
    raw = nx.read_graphml(graphml_path, force_multigraph=True)
    by_id = {}
    by_pair = {}
    for u, v, key, attrs in raw.edges(keys=True, data=True):
        start = positions.get(u)
        end = positions.get(v)
        # 不同 loader 可能把数字节点 ID 转为 int，统一再尝试字符串键。
        if start is None:
            start = positions.get(str(u))
        if end is None:
            end = positions.get(str(v))
        if start is None or end is None:
            continue
        line = _parse_wkt_line(attrs.get("geometry"), (start, end))
        ids = {str(key)}
        if attrs.get("id") is not None:
            ids.add(str(attrs["id"]))
        for eid in ids:
            by_id[eid] = line
        by_pair.setdefault((str(u), str(v)), []).append(line)
    return by_id, by_pair


def _graph_records(graph, positions, geometry_by_id, geometry_by_pair):
    records = {}
    pair_ids = {}
    directed = nx.DiGraph()
    directed.add_nodes_from(graph)
    edge_count = 0
    geometry_count = 0
    for u, outgoing in graph.items():
        for v, weight, eid in outgoing:
            if u not in positions or v not in positions:
                continue
            try:
                weight = float(weight)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(weight) or weight < 0:
                continue
            line = geometry_by_id.get(str(eid))
            if line is None:
                candidates = geometry_by_pair.get((str(u), str(v)), [])
                line = candidates[0] if candidates else [positions[u], positions[v]]
            records[eid] = {"u": u, "v": v, "weight": weight, "geometry": line}
            pair_ids.setdefault((u, v), []).append(eid)
            directed.add_edge(u, v)
            edge_count += 1
            if len(line) > 2 or line != [positions[u], positions[v]]:
                geometry_count += 1
    return records, pair_ids, directed, edge_count, geometry_count


def _path_edges(result, graph, records, pair_ids):
    node_path = result[0]
    if len(result) > 1:
        edge_ids = result[1]
        if isinstance(edge_ids, (tuple, list)) and len(edge_ids) == len(node_path) - 1:
            if all(eid in records for eid in edge_ids):
                return list(edge_ids)
            # Loader and algorithm may differ only in int-vs-string edge ID type.
            mapped = []
            for eid in edge_ids:
                match = next((rid for rid in records if str(rid) == str(eid)), None)
                if match is None:
                    mapped = []
                    break
                mapped.append(match)
            if mapped:
                return mapped
    # Fallback for algorithms that return only node paths: select minimum parallel edge.
    result_ids = []
    for u, v in zip(node_path, node_path[1:]):
        candidates = pair_ids.get((u, v), [])
        if not candidates:
            raise ValueError(f"无法恢复路线边：{u} -> {v}")
        result_ids.append(min(candidates, key=lambda eid: records[eid]["weight"]))
    return result_ids


def _xy(lonlat, lon0, lat0):
    lon, lat = lonlat
    return ((lon - lon0) * math.cos(math.radians(lat0)), lat - lat0)


def _draw_real_network(graph, positions, records, pair_ids,
                       optimal, bad, output_dir, graphml_path, scale_used):
    ids_d = _path_edges(optimal, graph, records, pair_ids)
    ids_a = _path_edges(bad, graph, records, pair_ids)
    lines_d = [records[eid]["geometry"] for eid in ids_d]
    lines_a = [records[eid]["geometry"] for eid in ids_a]
    all_route_points = [p for line in lines_d + lines_a for p in line]
    lon0 = sum(p[0] for p in all_route_points) / len(all_route_points)
    lat0 = sum(p[1] for p in all_route_points) / len(all_route_points)
    projected_d = [[_xy(p, lon0, lat0) for p in line] for line in lines_d]
    projected_a = [[_xy(p, lon0, lat0) for p in line] for line in lines_a]
    projected_all = [p for line in projected_d + projected_a for p in line]
    minx, maxx = min(p[0] for p in projected_all), max(p[0] for p in projected_all)
    miny, maxy = min(p[1] for p in projected_all), max(p[1] for p in projected_all)
    span = max(maxx - minx, maxy - miny, 0.003)
    pad = max(0.002, span * 0.20)
    bounds = (minx - pad, maxx + pad, miny - pad, maxy + pad)

    fig, ax = plt.subplots(figsize=(12, 9), facecolor="#f8fafc")
    ax.set_facecolor("#f8fafc")
    # 画真实 GraphML 道路几何作底图，只截取两条路线附近区域。
    for record in records.values():
        line = [_xy(p, lon0, lat0) for p in record["geometry"]]
        bx0, bx1 = min(p[0] for p in line), max(p[0] for p in line)
        by0, by1 = min(p[1] for p in line), max(p[1] for p in line)
        if bx1 >= bounds[0] and bx0 <= bounds[1] and by1 >= bounds[2] and by0 <= bounds[3]:
            ax.plot([p[0] for p in line], [p[1] for p in line],
                    color="#cbd5e1", lw=0.48, alpha=0.85, zorder=1)

    for lines, color, label, cost in [
        (projected_d, "#159447", "Dijkstra 最优路径", float(optimal[2])),
        (projected_a, "#dc2626", f"A* 次优路径（启发值 × {HEURISTIC_MULTIPLIER:g}）", float(bad[2])),
    ]:
        for line in lines:
            ax.plot([p[0] for p in line], [p[1] for p in line], color=color,
                    lw=3.0, alpha=0.95, solid_capstyle="round", zorder=4)
        ax.plot([], [], color=color, lw=3.0, label=f"{label}：{cost:,.1f} m")

    # 在每条高亮路线最多 8 段上标实际 edge length，避免整张地图被数字遮住。
    for ids, lines, color in [(ids_d, lines_d, "#126b36"), (ids_a, lines_a, "#a91f1f")]:
        step = max(1, math.ceil(len(ids) / 8))
        for i in range(0, len(ids), step):
            line = lines[i]
            mid = _xy(line[len(line) // 2], lon0, lat0)
            ax.text(mid[0], mid[1], f"{records[ids[i]]['weight']:.0f} m",
                    fontsize=7.5, color=color, ha="center", va="center", zorder=6,
                    bbox={"boxstyle": "round,pad=0.18", "fc": "white", "ec": color, "alpha": 0.92})

    source, target = optimal[0][0], optimal[0][-1]
    sx, sy = _xy(positions[source], lon0, lat0)
    tx, ty = _xy(positions[target], lon0, lat0)
    ax.scatter([sx], [sy], s=110, c="#2563eb", edgecolors="white", linewidths=1.8,
               zorder=8, label="起点")
    ax.scatter([tx], [ty], s=150, marker="*", c="#f59e0b", edgecolors="white", linewidths=1.0,
               zorder=8, label="终点")
    ax.annotate("起点", (sx, sy), xytext=(7, 7), textcoords="offset points", fontsize=9, weight="bold")
    ax.annotate("终点", (tx, ty), xytext=(7, 7), textcoords="offset points", fontsize=9, weight="bold")

    gap = float(bad[2]) - float(optimal[2])
    ax.legend(loc="best", frameon=True, framealpha=0.95, fontsize=9)
    ax.set_title(
        f"真实路网：10 倍 Haversine 启发值反例\n"
        f"OD：{source} → {target}；A* 比 Dijkstra 多 {gap:,.1f} m",
        fontsize=13, pad=12,
    )
    ax.text(0.01, 0.01,
            f"{Path(graphml_path).name}｜灰线为真实道路几何｜边标签为路段长度（m）｜A* 系数={scale_used:.6g}",
            transform=ax.transAxes, fontsize=8, color="#475569", ha="left", va="bottom")
    ax.set_xlim(bounds[0], bounds[1])
    ax.set_ylim(bounds[2], bounds[3])
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    fig.tight_layout()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / "T5_不可采纳反例.png"
    fig.savefig(image_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return image_path, ids_d, ids_a


def t5_real_network_counterexample(graph, positions, dijkstra, astar, haversine,
                                   base_scale, graphml_path, output_dir, rng,
                                   trials=DEFAULT_TRIALS, seed=None):
    geometry_by_id, geometry_by_pair = _load_geometry_maps(graphml_path, positions)
    records, pair_ids, directed, edge_count, geometry_count = _graph_records(
        graph, positions, geometry_by_id, geometry_by_pair)
    components = [c for c in nx.strongly_connected_components(directed) if len(c) > 1]
    if not components:
        raise ValueError("路网没有包含至少两个节点的强连通分量，无法保证随机 OD 可达。")
    nodes = list(max(components, key=len))
    inflated_scale = float(base_scale) * HEURISTIC_MULTIPLIER
    found = None

    call_errors = []
    for attempt in range(1, trials + 1):
        source, target = rng.sample(nodes, 2)
        straight = float(haversine(positions, source, target))
        if not (MIN_STRAIGHT_DISTANCE_M <= straight <= MAX_STRAIGHT_DISTANCE_M):
            continue
        try:
            optimal = dijkstra(graph, source, target)
            bad = astar(graph, positions, source, target, heuristic_scale=inflated_scale)
        except Exception as exc:
            # 记录接口/算法异常，避免把错误伪装成“随机没找到反例”。
            if len(call_errors) < 5:
                call_errors.append(f"第 {attempt} 次（{source}->{target}）：{type(exc).__name__}: {exc}")
            continue
        if not optimal or not bad or len(optimal) < 3 or len(bad) < 3:
            continue
        cost_d, cost_a = float(optimal[2]), float(bad[2])
        if not (math.isfinite(cost_d) and math.isfinite(cost_a)):
            continue
        if cost_a > cost_d + max(1e-6, abs(cost_d) * 1e-9):
            found = (attempt, source, target, straight, optimal, bad)
            break

    if found is None:
        error_note = ""
        if call_errors:
            error_note = "\n算法调用异常示例：\n" + "\n".join(call_errors)
        raise RuntimeError(
            f"随机抽样 {trials} 次，没有找到 10 倍 Haversine A* 的次优结果。"
            "可增加 --trials；程序不会改用示意图伪造反例。"
            + error_note
        )

    attempt, source, target, straight, optimal, bad = found
    image_path, ids_d, ids_a = _draw_real_network(
        graph, positions, records, pair_ids, optimal, bad,
        output_dir, graphml_path, inflated_scale,
    )
    gap = float(bad[2]) - float(optimal[2])
    print(f"T5 真实路网随机搜索 [FOUND]：第 {attempt} 次抽样，随机种子 {seed}")
    print(f"启发值：base_scale={base_scale:g}，A* 实际 scale={inflated_scale:g}（×{HEURISTIC_MULTIPLIER:g}）")
    print(f"起点={source}，终点={target}，Haversine={straight:.1f} m")
    print(f"Dijkstra：{float(optimal[2]):.1f} m，{len(ids_d)} 条边；路径={optimal[0]}")
    print(f"A* ×10：{float(bad[2]):.1f} m，{len(ids_a)} 条边；路径={bad[0]}")
    print(f"差值：{gap:.1f} m（{gap / float(optimal[2]) * 100:.3f}%）")
    print(f"GraphML 边数={edge_count}，含道路折线几何边数={geometry_count}")
    if call_errors:
        print(f"提示：搜索期间有 {len(call_errors)} 次算法调用异常；首例：{call_errors[0]}")
    print(f"真实路网对比图：{image_path}")
    return image_path


def main():
    parser = add_common_arguments(
        argparse.ArgumentParser(description="真实路网 T5：随机搜索 10 倍 Haversine 次优路线"),
        Path(__file__).resolve().parents[1] / "results",
    )
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS,
                        help=f"随机 OD 抽样次数，默认 {DEFAULT_TRIALS}")
    args = parser.parse_args()
    args = resolve_args(args, Path(__file__).resolve().parents[1] / "results")

    graph, positions, _, dijkstra, astar, haversine, scale, _ = load_runtime(
        args.graphml, args.algorithm_dir)
    rng = random.Random(args.seed)
    t5_real_network_counterexample(
        graph=graph,
        positions=positions,
        dijkstra=dijkstra,
        astar=astar,
        haversine=haversine,
        base_scale=scale,
        graphml_path=args.graphml,
        output_dir=args.output_dir,
        rng=rng,
        trials=args.trials,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
