"""Generate a compact CH preprocessing replay from the A3 binary index.

The route cache stores the final contraction ranks and shortcut decomposition,
not a browser-sized event log. This tool reconstructs the contraction node for
each shortcut, samples the rank timeline, and writes real coordinates and
shortcut endpoints for the CH replay panel.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import struct
import tempfile
from array import array
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "server" / "guangdong-roads.sqlite"
DEFAULT_OUTPUT = ROOT / "data" / "ch-events-guangdong.json"
MAGIC = b"A3CHIDX1"
HEADER = struct.Struct("<I8Q")
ARC = struct.Struct("<iidqii")


def locate_cache() -> Path:
    candidates = [
        ROOT / "data" / "ch-cache" / "g4-guangdong-ch.cache",
        ROOT / "desktop-release" / "data" / "ch-cache" / "g4-guangdong-ch.cache",
        Path(tempfile.gettempdir()) / "G4RouteCache" / "g4-guangdong-ch.cache",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("找不到广东省 CH 缓存，请先生成 g4-guangdong-ch.cache")


def read_cache(path: Path):
    raw = path.read_bytes()
    if raw[:8] != MAGIC:
        raise ValueError(f"不是 A3 CH 缓存：{path}")
    version, node_count, edge_count, arc_count, out_offset_count, out_arc_count, in_offset_count, in_arc_count, shortcut_count = HEADER.unpack_from(raw, 8)
    if version != 1:
        raise ValueError(f"不支持的 CH 缓存版本：{version}")
    offset = 8 + HEADER.size + 64
    ranks = array("i")
    ranks.frombytes(raw[offset:offset + 4 * node_count])
    offset += 4 * node_count
    sources = array("i")
    targets = array("i")
    weights = array("d")
    lefts = array("i")
    rights = array("i")
    for _ in range(arc_count):
        source, target, weight, _original, left, right = ARC.unpack_from(raw, offset)
        offset += ARC.size
        sources.append(source)
        targets.append(target)
        weights.append(weight)
        lefts.append(left)
        rights.append(right)
    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "shortcut_count": shortcut_count,
        "ranks": ranks,
        "sources": sources,
        "targets": targets,
        "weights": weights,
        "lefts": lefts,
        "rights": rights,
    }


def load_nodes(database: Path):
    with sqlite3.connect(database) as connection:
        edge_rows = connection.execute("SELECT source, target FROM edges").fetchall()
        active = {str(value) for row in edge_rows for value in row}
        rows = connection.execute("SELECT node_id, lon, lat FROM nodes ORDER BY rowid").fetchall()
    rows = [row for row in rows if str(row[0]) in active]
    return [str(row[0]) for row in rows], [(float(row[1]), float(row[2])) for row in rows]


def percent(point, bounds):
    min_lon, min_lat, max_lon, max_lat = bounds
    lon, lat = point
    x = 100.0 * (lon - min_lon) / max(1e-12, max_lon - min_lon)
    y = 100.0 - 100.0 * (lat - min_lat) / max(1e-12, max_lat - min_lat)
    return {"x": round(max(0.0, min(100.0, x)), 3), "y": round(max(0.0, min(100.0, y)), 3)}


def evenly(values, count):
    if len(values) <= count:
        return list(values)
    return [values[round(i * (len(values) - 1) / (count - 1))] for i in range(count)]


def generate(cache_path: Path, database: Path, output: Path, target_events: int = 360) -> None:
    cache = read_cache(cache_path)
    node_ids, coordinates = load_nodes(database)
    if len(node_ids) != cache["node_count"]:
        raise ValueError(f"节点数量不一致：SQLite={len(node_ids)}，CH={cache['node_count']}")

    lons = [point[0] for point in coordinates]
    lats = [point[1] for point in coordinates]
    bounds = (min(lons), min(lats), max(lons), max(lats))
    ranks = cache["ranks"]
    shortcuts_by_node: dict[int, list[tuple[int, int, float]]] = {}
    for arc_id in range(cache["edge_count"], len(cache["sources"])):
        left = cache["lefts"][arc_id]
        right = cache["rights"][arc_id]
        if left < 0 or right < 0:
            continue
        left_ends = {cache["sources"][left], cache["targets"][left]}
        right_ends = {cache["sources"][right], cache["targets"][right]}
        shared = left_ends & right_ends
        if not shared:
            continue
        contracted = min(shared, key=lambda node: ranks[node])
        shortcuts_by_node.setdefault(contracted, []).append(
            (cache["sources"][arc_id], cache["targets"][arc_id], cache["weights"][arc_id])
        )

    rank_order = sorted(range(len(node_ids)), key=ranks.__getitem__)
    shortcut_order = sorted(shortcuts_by_node, key=ranks.__getitem__)
    selected = set(evenly(rank_order, max(1, target_events // 2)))
    selected.update(evenly(shortcut_order, max(1, target_events // 2)))
    selected_order = sorted(selected, key=ranks.__getitem__)
    selected_order = evenly(selected_order, target_events)

    events = []
    for node in selected_order:
        additions = shortcuts_by_node.get(node, [])
        visible_additions = additions[:8]
        events.append({
            "step": int(ranks[node]) + 1,
            "total": len(node_ids),
            "contracted_node": {
                "id": node_ids[node],
                "rank": int(ranks[node]),
                **percent(coordinates[node], bounds),
            },
            "shortcuts_added": [
                {
                    "from_id": node_ids[source],
                    "to_id": node_ids[target],
                    "from": percent(coordinates[source], bounds),
                    "to": percent(coordinates[target], bounds),
                    "weight": round(weight, 2),
                }
                for source, target, weight in visible_additions
            ],
            "shortcut_count": len(additions),
            "shortcuts_truncated": max(0, len(additions) - len(visible_additions)),
        })

    payload = {
        "source": "A3 C++ CH cache",
        "dataset": "guangdong",
        "dataset_name": "广东省路网",
        "cache_file": cache_path.name,
        "total_nodes": len(node_ids),
        "total_edges": cache["edge_count"],
        "total_arcs": len(cache["sources"]),
        "total_shortcuts": cache["shortcut_count"],
        "sampled_events": len(events),
        "events": events,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"CH replay written: {output} ({len(events)} events, {output.stat().st_size} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--events", type=int, default=360)
    args = parser.parse_args()
    generate(args.cache or locate_cache(), args.database, args.output, max(20, args.events))


if __name__ == "__main__":
    main()
