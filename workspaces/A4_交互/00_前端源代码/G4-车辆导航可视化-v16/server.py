"""Local server for the G4 vehicle-navigation demo.

The server keeps the full Wuhan OSM extract on the server side and exposes
only the requested bounding box to the browser. It intentionally uses the
Python standard library so the project can be started with one double click.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data" / "server" / "wuhan-main-roads.json"
HOST = os.environ.get("G4_HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
PORT = int(os.environ.get("PORT", "5173"))
ROAD_TYPES = {
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link",
}


def road_points(way: dict, nodes: dict) -> list[tuple[float, float]]:
    geometry = way.get("geometry") or []
    if geometry:
        return [(float(item["lat"]), float(item["lon"])) for item in geometry if "lat" in item and "lon" in item]
    return [nodes[str(node_id)] for node_id in way.get("nodes", []) if str(node_id) in nodes]


def bounds(points: list[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    if not points:
        return None
    lats = [point[0] for point in points]
    lons = [point[1] for point in points]
    return min(lats), min(lons), max(lats), max(lons)


def intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def load_network() -> dict:
    path = DATA_FILE
    if not path.exists():
        raise FileNotFoundError(f"未找到完整武汉服务器路网：{DATA_FILE}。请先准备服务器数据")
    payload = json.loads(path.read_text(encoding="utf-8"))
    elements = payload.get("elements", [])
    node_map = {
        str(element["id"]): (float(element["lat"]), float(element["lon"]))
        for element in elements
        if element.get("type") == "node" and element.get("lat") is not None and element.get("lon") is not None
    }
    ways = []
    for element in elements:
        if element.get("type") != "way":
            continue
        if (element.get("tags") or {}).get("highway") not in ROAD_TYPES:
            continue
        road_bounds = bounds(road_points(element, node_map))
        if road_bounds:
            ways.append({"element": element, "bounds": road_bounds})
    return {
        "path": str(path),
        "ways": ways,
        "metadata": payload.get("g4_metadata", {}),
        "element_count": len(elements),
    }


NETWORK = load_network()


def parse_bbox(raw: str | None) -> tuple[float, float, float, float]:
    if not raw:
        raise ValueError("缺少 bbox 参数")
    values = [float(value) for value in raw.split(",")]
    if len(values) != 4:
        raise ValueError("bbox 应为 south,west,north,east")
    south, west, north, east = values
    if not south < north or not west < east:
        raise ValueError("bbox 范围无效")
    if north - south > 1.2 or east - west > 1.5:
        raise ValueError("单次请求范围过大，请按地图区域请求")
    return south, west, north, east


@lru_cache(maxsize=128)
def network_for_bbox(bbox: tuple[float, float, float, float]) -> dict:
    south, west, north, east = bbox
    margin_lat = max(0.006, (north - south) * 0.08)
    margin_lon = max(0.006, (east - west) * 0.08)
    requested = (south - margin_lat, west - margin_lon, north + margin_lat, east + margin_lon)
    selected = [item["element"] for item in NETWORK["ways"] if intersects(item["bounds"], requested)]
    metadata = {
        **NETWORK["metadata"],
        "server_query_bbox": ",".join(f"{value:.5f}" for value in bbox),
        "server_total_roads": len(NETWORK["ways"]),
        "server_returned_roads": len(selected),
    }
    return {"version": 0.6, "elements": selected, "g4_metadata": metadata}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json(HTTPStatus.OK, {
                "ok": True,
                "source": NETWORK["path"],
                "roads": len(NETWORK["ways"]),
                "elements": NETWORK["element_count"],
                "metadata": NETWORK["metadata"],
            })
            return
        if parsed.path == "/api/network":
            try:
                bbox = parse_bbox(parse_qs(parsed.query).get("bbox", [None])[0])
                self.send_json(HTTPStatus.OK, network_for_bbox(bbox))
            except ValueError as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            except Exception as error:
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})
            return
        super().do_GET()

    def log_message(self, format: str, *args) -> None:
        print(f"[server] {self.address_string()} - {format % args}")


def main() -> None:
    print(f"G4 导航服务器：http://localhost:{PORT}/")
    print(f"服务器路网：{NETWORK['path']} · {len(NETWORK['ways']):,} 段主要道路")
    print("前端通过 /api/network?bbox=south,west,north,east 按区域读取路网。")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
