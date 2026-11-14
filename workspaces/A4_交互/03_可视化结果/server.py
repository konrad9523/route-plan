"""Local server for the G4 vehicle-navigation demo.

The server keeps the three regional road indexes on the server side and exposes
only the requested bounding box to the browser. It intentionally uses the
Python standard library so the project can be started with one double click.
"""

from __future__ import annotations

import gzip
import heapq
import json
import math
import os
import sqlite3
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from a3_route_backend import close_backends, get_backend


ROOT = Path(__file__).resolve().parent
DATASET_DB_FILES = {
    "guangdong": ROOT / "data" / "server" / "guangdong-roads.sqlite",
    "shenzhen": ROOT / "data" / "server" / "shenzhen-roads.sqlite",
    "nanshan": ROOT / "data" / "server" / "nanshan-roads.sqlite",
}
DATASET_NAMES = {
    "guangdong": "广东省路网",
    "shenzhen": "深圳市路网",
    "nanshan": "南山区路网",
}
CH_EVENT_FILES = {
    "guangdong": ROOT / "data" / "ch-events-guangdong.json",
}
GRAPH_CACHE: dict[str, dict] = {}
CH_REPLAY_CACHE: dict[str, dict] = {}
HOST = os.environ.get("G4_HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
PORT = int(os.environ.get("PORT", "5173"))
SERVICE_VERSION = "2026-11-12-3"
def load_sqlite_metadata(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT key, value FROM metadata").fetchall()
    return dict(rows)


def load_ch_replay(dataset: str) -> dict:
    """Return sampled CH events with node IDs resolved to WGS84 coordinates."""
    if dataset in CH_REPLAY_CACHE:
        return CH_REPLAY_CACHE[dataset]
    event_file = CH_EVENT_FILES.get(dataset)
    database = DATASET_DB_FILES.get(dataset)
    if not event_file or not event_file.exists():
        raise ValueError(f"{DATASET_NAMES.get(dataset, dataset)}暂无 CH 预处理回放数据")
    if not database or not database.exists():
        raise ValueError(f"{DATASET_NAMES.get(dataset, dataset)}路网数据库不可用")

    payload = json.loads(event_file.read_text(encoding="utf-8"))
    events = payload.get("events", [])
    node_ids: set[str] = set()
    for event in events:
        contracted = event.get("contracted_node") or {}
        if isinstance(contracted, dict) and contracted.get("id") is not None:
            node_ids.add(str(contracted["id"]))
        for shortcut in event.get("shortcuts_added", []):
            for key in ("from_id", "to_id"):
                if shortcut.get(key) is not None:
                    node_ids.add(str(shortcut[key]))

    coordinates: dict[str, dict[str, float]] = {}
    with sqlite3.connect(database) as connection:
        node_list = list(node_ids)
        for offset in range(0, len(node_list), 900):
            chunk = node_list[offset:offset + 900]
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"SELECT node_id, lon, lat FROM nodes WHERE node_id IN ({placeholders})",
                chunk,
            ).fetchall()
            coordinates.update({
                str(node_id): {"lat": float(lat), "lon": float(lon)}
                for node_id, lon, lat in rows
            })

    result = dict(payload)
    result["schema_version"] = 2
    result["coordinate_system"] = "WGS84"
    result["nodes"] = coordinates
    result["resolved_nodes"] = len(coordinates)
    result["unresolved_nodes"] = len(node_ids) - len(coordinates)
    CH_REPLAY_CACHE[dataset] = result
    return result


def geographic_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    radius = 6371008.8
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1])
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


def point_to_segment_distance(point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    latitude_scale = math.cos(math.radians(point[0]))
    ax, ay = (a[1] - point[1]) * latitude_scale, a[0] - point[0]
    bx, by = (b[1] - point[1]) * latitude_scale, b[0] - point[0]
    denominator = bx * bx + by * by
    ratio = max(0.0, min(1.0, (ax * bx + ay * by) / denominator)) if denominator else 0.0
    projected = (point[0] + by * ratio, point[1] + (bx * ratio) / latitude_scale)
    return geographic_distance(point, projected)


def load_route_graph(dataset: str) -> dict:
    if dataset in GRAPH_CACHE:
        return GRAPH_CACHE[dataset]
    database = DATASET_DB_FILES.get(dataset)
    if not database or not database.exists():
        raise ValueError(f"数据集不可用：{dataset}")
    started = time.perf_counter()
    with sqlite3.connect(database) as connection:
        coordinates = {
            str(node_id): (float(lat), float(lon))
            for node_id, lon, lat in connection.execute("SELECT node_id, lon, lat FROM nodes")
        }
        adjacency: dict[str, list[dict]] = {}
        for source, target, length, highway, name in connection.execute(
            "SELECT source, target, length_m, highway, name FROM edges"
        ):
            source, target = str(source), str(target)
            if source not in coordinates or target not in coordinates:
                continue
            adjacency.setdefault(source, []).append({
                "to": target,
                "distance": float(length or 0),
                "highway": highway or "",
                "name": name or "OSM 道路",
            })
    graph = {"coordinates": coordinates, "adjacency": adjacency, "loaded_ms": (time.perf_counter() - started) * 1000}
    GRAPH_CACHE[dataset] = graph
    return graph


def snap_graph_node(
    dataset: str,
    coords: tuple[float, float],
    *,
    coordinates: dict[str, tuple[float, float]] | None = None,
) -> tuple[str, float]:
    database = DATASET_DB_FILES.get(dataset)
    if not database or not database.exists():
        raise ValueError(f"数据集不可用：{dataset}")
    coordinate_index = coordinates or load_route_graph(dataset)["coordinates"]
    lat, lon = coords
    for span in (0.02, 0.06, 0.2):
        with sqlite3.connect(database) as connection:
            rows = connection.execute(
                """
                SELECT e.source, e.target, e.geometry
                FROM edge_rtree AS r JOIN edges AS e ON e.edge_id = r.edge_id
                WHERE r.max_lon >= ? AND r.min_lon <= ?
                  AND r.max_lat >= ? AND r.min_lat <= ?
                LIMIT 5000
                """,
                (lon - span, lon + span, lat - span, lat + span),
            ).fetchall()
        best: tuple[str, float] | None = None
        for source, target, geometry_json in rows:
            coordinates = json.loads(geometry_json)
            if len(coordinates) < 2:
                continue
            points = [(float(item[1]), float(item[0])) for item in coordinates]
            distance = min(point_to_segment_distance(coords, points[index], points[index + 1]) for index in range(len(points) - 1))
            for node_id in (str(source), str(target)):
                node = coordinate_index.get(node_id)
                if not node:
                    continue
                node_distance = geographic_distance(coords, node)
                candidate = (node_id, node_distance)
                if best is None or candidate[1] < best[1]:
                    best = candidate
        if best:
            return best
    raise ValueError("点击位置附近没有可用道路节点")


def edge_cost(edge: dict, options: dict) -> float:
    if options.get("avoid_highway") and edge["highway"] in {"motorway", "motorway_link", "trunk", "trunk_link"}:
        return math.inf
    distance = edge["distance"]
    mode = options.get("route_mode", "最快")
    if mode == "最快" and edge["highway"] in {"motorway", "trunk"}:
        return distance * 0.86
    if mode == "省油":
        return distance * (0.92 if edge["highway"] in {"motorway", "trunk"} else 1.08)
    return distance


def search_route(
    graph: dict,
    start: str,
    target: str,
    algorithm: str,
    options: dict,
    *,
    capture_snapshots: bool = False,
) -> dict:
    coordinates = graph["coordinates"]
    adjacency = graph["adjacency"]
    heuristic_enabled = algorithm in {"A*", "双向 A*"}
    expanded: list[str] = []
    snapshots: list[dict] = []
    pending: list[str] = []
    g_score = {start: 0.0}
    came_from: dict[str, tuple[str, dict]] = {}
    queue: list[tuple[float, int, str]] = [(0.0, 0, start)]
    sequence = 1
    while queue:
        _, _, current = heapq.heappop(queue)
        if current in expanded:
            continue
        expanded.append(current)
        if capture_snapshots:
            pending.append(current)
        if current == target:
            break
        for edge in adjacency.get(current, []):
            cost = edge_cost(edge, options)
            if not math.isfinite(cost):
                continue
            next_node = edge["to"]
            next_score = g_score[current] + cost
            if next_score >= g_score.get(next_node, math.inf):
                continue
            g_score[next_node] = next_score
            came_from[next_node] = (current, edge)
            heuristic = geographic_distance(coordinates[next_node], coordinates[target]) if heuristic_enabled else 0
            heapq.heappush(queue, (next_score + heuristic, sequence, next_node))
            sequence += 1
        if capture_snapshots and (len(pending) >= 25 or current == target):
            frontier = list(dict.fromkeys(item[2] for item in sorted(queue)[:160] if item[2] not in expanded))
            snapshots.append({"current": current, "expandedDelta": pending, "frontier": frontier, "frontierCount": len(frontier)})
            pending = []
    if capture_snapshots and pending:
        snapshots.append({"current": pending[-1], "expandedDelta": pending, "frontier": [], "frontierCount": 0})
    if target not in came_from and start != target:
        return {"path": [], "edges": [], "snapshots": snapshots, "expanded": len(expanded)}
    path = [target]
    edges: list[dict] = []
    cursor = target
    while cursor != start:
        previous, edge = came_from[cursor]
        path.append(previous)
        edges.append({"distance": edge["distance"], "name": edge["name"], "highway": edge["highway"]})
        cursor = previous
    path.reverse()
    edges.reverse()
    return {"path": path, "edges": edges, "snapshots": snapshots, "expanded": len(expanded)}


DATASET_METADATA = {
    dataset: {**load_sqlite_metadata(path), "dataset": dataset}
    for dataset, path in DATASET_DB_FILES.items()
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_json(self, status: int, payload: dict, *, cache_seconds: int = 0) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        compressed = False
        if len(body) >= 1024 and "gzip" in self.headers.get("Accept-Encoding", "").lower():
            body = gzip.compress(body, compresslevel=6)
            compressed = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Accept, Content-Type")
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Cache-Control", f"public, max-age={cache_seconds}" if cache_seconds else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if parsed.path != "/api/route":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            dataset = payload.get("dataset", "guangdong")
            if dataset != "guangdong":
                raise ValueError("A4 导航固定使用广东省路网")
            start = payload.get("start") or {}
            end = payload.get("end") or {}
            start_coords = (float(start["lat"]), float(start["lon"]))
            end_coords = (float(end["lat"]), float(end["lon"]))
            algorithm = str(payload.get("algorithm", "A*"))
            if algorithm not in {"Dijkstra", "A*", "双向 A*", "CH"}:
                raise ValueError("不支持的搜索算法")
            options = payload.get("options") or {}
            include_snapshots = payload.get("include_snapshots") is True
            use_a3 = (
                algorithm in {"Dijkstra", "A*", "双向 A*", "CH"}
                and options.get("route_mode", "最快") == "最快"
                and not options.get("avoid_highway")
                and not options.get("avoid_traffic")
            )
            started = time.perf_counter()
            if use_a3:
                backend = get_backend(dataset, DATASET_DB_FILES[dataset])
                start_id, start_distance = snap_graph_node(
                    dataset, start_coords, coordinates=backend.coordinates
                )
                end_id, end_distance = snap_graph_node(
                    dataset, end_coords, coordinates=backend.coordinates
                )
                result = backend.plan(start_id, end_id, algorithm, capture_snapshots=include_snapshots)
            else:
                backend = None
                graph = load_route_graph(dataset)
                start_id, start_distance = snap_graph_node(dataset, start_coords)
                end_id, end_distance = snap_graph_node(dataset, end_coords)
                result = search_route(
                    graph, start_id, end_id,
                    algorithm,
                    options,
                    capture_snapshots=include_snapshots,
                )
            if not result["path"]:
                raise ValueError("当前广东路网中没有找到可行路径")
            graph = backend if backend is not None else load_route_graph(dataset)
            coordinate_index = graph.coordinates if backend is not None else graph["coordinates"]
            visible_node_ids = set(result["path"])
            if include_snapshots:
                visible_node_ids.update(
                    node_id
                    for snapshot in result["snapshots"]
                    for node_id in snapshot["expandedDelta"] + snapshot["frontier"]
                )
            result["nodes"] = {
                node_id: {"lat": coordinate_index[node_id][0], "lon": coordinate_index[node_id][1]}
                for node_id in visible_node_ids
                if node_id in coordinate_index
            }
            result["start"] = {"id": start_id, "lat": coordinate_index[start_id][0], "lon": coordinate_index[start_id][1], "snap_distance": start_distance}
            result["end"] = {"id": end_id, "lat": coordinate_index[end_id][0], "lon": coordinate_index[end_id][1], "snap_distance": end_distance}
            result["algorithm"] = algorithm
            result["dataset"] = dataset
            result["server_ms"] = round((time.perf_counter() - started) * 1000, 3)
            result["graph_load_ms"] = round(
                backend.loaded_ms if backend is not None else load_route_graph(dataset)["loaded_ms"], 3
            )
            self.send_json(HTTPStatus.OK, result, cache_seconds=0)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception as error:  # Keep a failed route request JSON-shaped for the UI.
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json(HTTPStatus.OK, {
                "ok": True,
                "service_version": SERVICE_VERSION,
                "default_dataset": "guangdong",
                "datasets": {dataset: bool(metadata) for dataset, metadata in DATASET_METADATA.items()},
            })
            return
        if parsed.path == "/api/datasets":
            self.send_json(HTTPStatus.OK, [
                {
                    "id": dataset_id,
                    "name": DATASET_NAMES[dataset_id],
                    "level": "province" if dataset_id == "guangdong" else "city" if dataset_id == "shenzhen" else "district",
                    "available": bool(DATASET_METADATA.get(dataset_id)),
                    "nodes": int(DATASET_METADATA[dataset_id].get("node_count", 0)) if DATASET_METADATA.get(dataset_id) else 0,
                    "edges": int(DATASET_METADATA[dataset_id].get("edge_count", 0)) if DATASET_METADATA.get(dataset_id) else 0,
                    "bbox": json.loads(DATASET_METADATA[dataset_id].get("bbox", "[]")) if DATASET_METADATA.get(dataset_id) else [],
                }
                for dataset_id in DATASET_NAMES
            ])
            return
        if parsed.path == "/api/ch/events":
            dataset = parse_qs(parsed.query).get("dataset", ["guangdong"])[0]
            try:
                self.send_json(HTTPStatus.OK, load_ch_replay(dataset), cache_seconds=300)
            except ValueError as error:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": str(error)})
            except Exception as error:  # Keep replay failures JSON-shaped for the UI.
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})
            return
        super().do_GET()

    def log_message(self, format: str, *args) -> None:
        print(f"[server] {self.address_string()} - {format % args}")


def main() -> None:
    print(f"G4 导航服务器：http://localhost:{PORT}/")
    print("A4 导航默认使用广东省 SQLite 路网；路线由后端计算后返回搜索轨迹和最终路径。")
    for dataset, metadata in DATASET_METADATA.items():
        if metadata:
            print(f"{DATASET_NAMES[dataset]} SQLite 路网：{DATASET_DB_FILES[dataset]} · {metadata.get('edge_count', '?')} 条有向边")
    # Load the default A4 graph before accepting browser requests. This moves
    # the one-time SQLite -> CSR cost to service startup instead of the first
    # click on “路线”.
    warm_started = time.perf_counter()
    try:
        get_backend("guangdong", DATASET_DB_FILES["guangdong"])
        print(f"广东省 A4 路网已预加载：{(time.perf_counter() - warm_started) * 1000:.1f} ms")
    except Exception as error:
        print(f"广东省 A4 路网预加载失败，将在路线请求时重试：{error}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止")
    finally:
        server.server_close()
        close_backends()


if __name__ == "__main__":
    main()
