"""把 OSM XML 建成可路由的有向图，并做 ID 稠密化 + CSR 压缩。

管线
----
1. 解析 OSM XML，取所有 `highway` way 及其引用到的节点坐标。
2. **拓扑化简（关键步）**：只把"路口节点"保留为图的顶点。
   一条 way 上中间那些度为 2 的纯几何点应当合并成一条边——
   否则图规模会膨胀数倍，而且与"节点=路口"的直觉不符。
   路口判定：被 ≥2 条 way 引用的节点，或是某条 way 的首/尾节点。
3. 按 way 顺序把相邻路口之间的折线合并为一条边，长度 = 各段大圆距离之和。
4. 单向处理：oneway=yes 只加正向；oneway=-1 只加反向；no/缺失则双向。
5. 节点 ID 稠密化：OSM 的 ID 是 9626752368 这种大数，映射为 0..N-1，
   使后续可以用数组/CSR 而不是 dict。
6. 生成 CSR（压缩稀疏行）邻接结构：indptr / indices / weights / edge_ids。

输出（data/processed/）
    nodes.json    稠密 id -> {osm_id, lon, lat}
    edges.json    边表（含 from/to/长度/道路类型/单向等）
    graph.pkl     二进制快照（CSR + 元信息），供后续算法直接加载
    meta.json     规模与统计
"""

from __future__ import annotations

import json
import math
import pickle
import time
import xml.etree.ElementTree as ET
from array import array
from collections import Counter, defaultdict
from pathlib import Path

EARTH_RADIUS_M = 6371000.0
_DEG2RAD = math.pi / 180.0

# 各类道路的默认限速（km/h）。OSM 里 maxspeed 覆盖率极低（实测 639/55006），
# 因此必须按等级兜底；这些取值参考中国城市道路的一般设计速度。
DEFAULT_SPEED = {
    "motorway": 100, "motorway_link": 60,
    "trunk": 80, "trunk_link": 50,
    "primary": 60, "primary_link": 40,
    "secondary": 50, "secondary_link": 35,
    "tertiary": 40, "tertiary_link": 30,
    "unclassified": 30, "residential": 30,
    "living_street": 15, "service": 20,
}

# 可通行等级（与下载查询保持一致，这里再兜一层）
DRIVABLE = set(DEFAULT_SPEED)


def haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """两点大圆距离（米）。与项目既有的实现保持同一公式，便于对拍。"""

    p1, p2 = lat1 * _DEG2RAD, lat2 * _DEG2RAD
    dphi = (lat2 - lat1) * _DEG2RAD
    dlam = (lon2 - lon1) * _DEG2RAD
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    a = min(1.0, max(0.0, a))
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def parse_osm(osm_path: Path):
    """第一遍：读出 way 定义与所有被引用节点的坐标。

    返回 (ways, coords)
        ways   = [(way_id, [node_id, ...], tags_dict), ...]
        coords = {node_id: (lon, lat)}
    """

    ways: list[tuple[int, list[int], dict[str, str]]] = []
    needed: set[int] = set()
    coords: dict[int, tuple[float, float]] = {}

    t0 = time.time()
    # 先扫一遍收集 way，并把 way 用到的节点 id 全部记下
    for _, elem in ET.iterparse(str(osm_path), events=("end",)):
        if elem.tag == "way":
            tags: dict[str, str] = {}
            refs: list[int] = []
            for child in elem:
                if child.tag == "nd":
                    refs.append(int(child.get("ref")))
                elif child.tag == "tag":
                    tags[child.get("k")] = child.get("v")
            if tags.get("highway") in DRIVABLE and len(refs) >= 2:
                ways.append((int(elem.get("id")), refs, tags))
                needed.update(refs)
            elem.clear()
    print(f"  第一遍：{len(ways):,} 条可通行 way，涉及 {len(needed):,} 个节点"
          f"（{time.time() - t0:.1f}s）")

    # 第二遍只取需要的节点坐标，避免把无关节点读进内存
    t0 = time.time()
    for _, elem in ET.iterparse(str(osm_path), events=("end",)):
        if elem.tag == "node":
            nid = int(elem.get("id"))
            if nid in needed:
                coords[nid] = (float(elem.get("lon")), float(elem.get("lat")))
            elem.clear()
    print(f"  第二遍：取得 {len(coords):,} 个节点坐标（{time.time() - t0:.1f}s）")
    return ways, coords


def build_graph(ways, coords):
    """建图：路口抽取 -> 合并折线为边 -> 单向处理。

    返回 (node_ids, node_xy, edges)
        node_ids  稠密 id -> osm id
        node_xy   稠密 id -> (lon, lat)
        edges     [(u, v, length_m, road_type, name, speed_kmh), ...] 稠密 id
    """

    # --- 1. 统计每个节点被多少条 way 引用；way 的首尾也算路口 ---
    ref_count: Counter[int] = Counter()
    for _wid, refs, _tags in ways:
        ref_count.update(refs)

    is_junction: set[int] = set()
    for _wid, refs, _tags in ways:
        for nid in refs:
            if ref_count[nid] >= 2:
                is_junction.add(nid)
        is_junction.add(refs[0])
        is_junction.add(refs[-1])

    # --- 2. 稠密化：只给路口分配紧凑 id ---
    junction_sorted = sorted(is_junction)
    osm_to_dense = {osm: i for i, osm in enumerate(junction_sorted)}
    dense_to_osm = junction_sorted
    node_xy = [coords[osm] for osm in junction_sorted]
    n_nodes = len(junction_sorted)
    print(f"  路口节点 {n_nodes:,}（占路网节点的 "
          f"{n_nodes / max(len(coords), 1):.1%}）")

    # --- 3. 沿每条 way 走，遇到路口就结一段边 ---
    edges: list[tuple[int, int, float, str, str, float]] = []
    edge_seen: set[tuple[int, int]] = set()
    skipped_missing = 0

    def add_edge(u_osm: int, v_osm: int, length: float, road: str,
                 name: str, speed: float, forward: bool) -> None:
        nonlocal skipped_missing
        if u_osm not in osm_to_dense or v_osm not in osm_to_dense:
            skipped_missing += 1
            return
        u, v = osm_to_dense[u_osm], osm_to_dense[v_osm]
        if u == v or length <= 0:
            return
        if forward:
            if (u, v) not in edge_seen:
                edge_seen.add((u, v))
                edges.append((u, v, length, road, name, speed))
        else:
            if (v, u) not in edge_seen:
                edge_seen.add((v, u))
                edges.append((v, u, length, road, name, speed))

    for _wid, refs, tags in ways:
        road = tags.get("highway", "unclassified")
        name = (tags.get("name") or "")[:80]
        speed = DEFAULT_SPEED.get(road, 30.0)
        ms = tags.get("maxspeed", "").strip()
        if ms:
            num = ""
            for ch in ms:
                if ch.isdigit():
                    num += ch
                else:
                    break
            if num:
                try:
                    speed = float(num)
                except ValueError:
                    pass
        ow = tags.get("oneway", "").strip().lower()

        # 累积当前段的长度
        seg_len = 0.0
        seg_start = None
        prev = None
        for nid in refs:
            if prev is not None:
                a, b = coords.get(prev), coords.get(nid)
                if a is None or b is None:
                    prev = nid
                    seg_start = None
                    continue
                seg_len += haversine(a[0], a[1], b[0], b[1])
                if seg_start is None:
                    seg_start = prev

            if nid in is_junction:
                if seg_start is not None and seg_start != nid:
                    if ow in ("yes", "true", "1"):
                        add_edge(seg_start, nid, seg_len, road, name, speed, True)
                    elif ow in ("-1", "reverse"):
                        add_edge(seg_start, nid, seg_len, road, name, speed, False)
                    else:
                        # 双向：两个方向都加（平行边去重由 edge_seen 负责）
                        add_edge(seg_start, nid, seg_len, road, name, speed, True)
                        add_edge(seg_start, nid, seg_len, road, name, speed, False)
                seg_len = 0.0
                seg_start = nid
            prev = nid

    if skipped_missing:
        print(f"  提示：{skipped_missing:,} 段因端点缺失被跳过")
    print(f"  有向边 {len(edges):,}")
    return dense_to_osm, node_xy, edges


def build_csr(edges, n_nodes: int):
    """构造 CSR：indptr / indices / weights / edge_ids。

    同时统计出度分布，供后续算法预分配堆容量。
    """

    out_deg = [0] * (n_nodes + 1)
    for u, _v, _l, _r, _n, _s in edges:
        out_deg[u] += 1

    indptr = array("i", [0]) * 1  # 占位，下面重新构造
    indptr = array("i", [0] * (n_nodes + 1))
    acc = 0
    for u in range(n_nodes):
        indptr[u] = acc
        acc += out_deg[u]
    indptr[n_nodes] = acc

    indices = array("i", [0] * acc)
    weights = array("d", [0.0] * acc)
    edge_ids = array("i", [0] * acc)
    cursor = array("i", indptr[:-1])

    for eid, (u, v, length, _r, _n, _s) in enumerate(edges):
        pos = cursor[u]
        indices[pos] = v
        weights[pos] = length
        edge_ids[pos] = eid
        cursor[u] = pos + 1

    return indptr, indices, weights, edge_ids


def main() -> int:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _paths

    # 输入与输出使用同一数据目录，包含环境变量覆盖。
    osm_path = _paths.osm_path("wuhan")
    outdir = _paths.processed_dir()
    outdir.mkdir(parents=True, exist_ok=True)

    if not osm_path.exists():
        raise SystemExit(
            f"找不到 {osm_path}\n请先运行 download_city_network.py 下载数据，"
            f"或设置环境变量 ROUTE_PLAN_DATA_DIR 指向已有数据目录。"
        )

    print("=" * 70)
    print("1. 解析 OSM")
    print("=" * 70)
    ways, coords = parse_osm(osm_path)

    print("=" * 70)
    print("2. 建图（路口抽取 + 折线合并 + 单向处理）")
    print("=" * 70)
    t0 = time.time()
    dense_to_osm, node_xy, edges = build_graph(ways, coords)
    print(f"  用时 {time.time() - t0:.1f}s")

    print("=" * 70)
    print("3. CSR 压缩")
    print("=" * 70)
    n_nodes = len(dense_to_osm)
    indptr, indices, weights, edge_ids = build_csr(edges, n_nodes)
    print(f"  indptr={len(indptr):,}  indices={len(indices):,}")
    print(f"  内存估算：indptr {indptr.buffer_info()[1] * indptr.itemsize / 1e6:.1f} MB，"
          f"indices {indices.buffer_info()[1] * indices.itemsize / 1e6:.1f} MB，"
          f"weights {weights.buffer_info()[1] * weights.itemsize / 1e6:.1f} MB")

    print("=" * 70)
    print("4. 写出")
    print("=" * 70)
    # 单向边统计：正向存在但反向不存在
    directed_pairs = {(u, v) for u, v, *_ in edges}
    oneway_edges = sum(1 for u, v, *_ in edges if (v, u) not in directed_pairs)
    meta = {
        "source": "wuhan_drive.osm",
        "n_nodes": n_nodes,
        "n_edges": len(edges),
        "csr_nnz": len(indices),
        "oneway_edges": oneway_edges,
        "oneway_ratio": round(oneway_edges / max(len(edges), 1), 4),
        "road_type_counts": dict(Counter(e[3] for e in edges).most_common()),
    }
    (outdir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # 节点表：稠密 id -> osm id / 坐标
    with (outdir / "nodes.json").open("w", encoding="utf-8") as fh:
        json.dump(
            {"osm_ids": dense_to_osm,
             "lon": [xy[0] for xy in node_xy],
             "lat": [xy[1] for xy in node_xy]},
            fh,
        )

    # 二进制快照：后续算法直接 pickle.load，避免重复解析
    with (outdir / "graph.pkl").open("wb") as fh:
        pickle.dump({
            "n_nodes": n_nodes,
            "osm_ids": dense_to_osm,
            "lon": [xy[0] for xy in node_xy],
            "lat": [xy[1] for xy in node_xy],
            "indptr": indptr, "indices": indices,
            "weights": weights, "edge_ids": edge_ids,
            "edges": edges,
        }, fh, protocol=pickle.HIGHEST_PROTOCOL)

    print(f"  nodes.json / graph.pkl / meta.json 写入 {outdir}")
    print(f"\n最终规模：{n_nodes:,} 节点 / {len(edges):,} 有向边")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
