"""Extract Wuhan major roads from an OSM PBF for the local navigation server.

Usage:
    py tools/build_wuhan_network.py --pbf E:\\G4-A4数据\\hubei-latest.osm.pbf

The source PBF is intentionally kept outside the repository. Only the Wuhan
major-road extract is written into data/server/.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import osmium


# A padded administrative envelope for Wuhan. The padding keeps boundary roads
# connected when a route starts near the city edge.
WUHAN_BBOX = (29.93, 113.63, 30.93, 115.12)  # south, west, north, east
HIGHWAYS = {
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link",
}


def in_bbox(lat: float, lon: float) -> bool:
    south, west, north, east = WUHAN_BBOX
    return south <= lat <= north and west <= lon <= east


class RoadHandler(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.ways: list[dict] = []
        self.nodes: dict[int, dict] = {}

    def way(self, way: osmium.osm.Way) -> None:
        tags = {tag.k: tag.v for tag in way.tags}
        if tags.get("highway") not in HIGHWAYS:
            return
        geometry = []
        refs = []
        for node in way.nodes:
            if not node.location.valid():
                continue
            lat = float(node.location.lat)
            lon = float(node.location.lon)
            geometry.append({"lat": lat, "lon": lon})
            refs.append(int(node.ref))
        if len(geometry) < 2 or not any(in_bbox(item["lat"], item["lon"]) for item in geometry):
            return
        self.ways.append({
            "type": "way",
            "id": int(way.id),
            "nodes": refs,
            "geometry": geometry,
            "tags": tags,
        })
        for ref, item in zip(refs, geometry):
            self.nodes[ref] = {
                "type": "node",
                "id": ref,
                "lat": item["lat"],
                "lon": item["lon"],
            }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbf", type=Path, required=True, help="湖北或武汉 OSM .osm.pbf 文件")
    parser.add_argument("--output", type=Path, default=Path("data/server/wuhan-main-roads.json"))
    args = parser.parse_args()
    if not args.pbf.exists():
        raise SystemExit(f"找不到 PBF 文件：{args.pbf}")

    handler = RoadHandler()
    print(f"正在提取武汉范围主要道路：{args.pbf}")
    handler.apply_file(str(args.pbf), locations=True)
    elements = list(handler.nodes.values()) + handler.ways
    if len(handler.ways) < 100:
        raise SystemExit(f"提取结果过少：{len(handler.ways)} 段道路，请检查 PBF 和范围")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 0.6,
        "elements": elements,
        "g4_metadata": {
            "source": "OpenStreetMap PBF extract",
            "bbox": ",".join(str(value) for value in WUHAN_BBOX),
            "highway_types": sorted(HIGHWAYS),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "license": "ODbL 1.0",
            "attribution": "© OpenStreetMap contributors",
            "note": "武汉范围主要道路服务器缓存；前端按 bbox 请求，不会下载整份数据。",
        },
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"已保存 {len(handler.ways):,} 段道路、{len(handler.nodes):,} 个节点：{args.output}")


if __name__ == "__main__":
    main()
