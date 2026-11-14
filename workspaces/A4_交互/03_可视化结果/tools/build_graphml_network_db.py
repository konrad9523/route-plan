"""Convert a large directed GraphML road graph into a bbox-queryable SQLite database.

The database is a server-side artifact. The browser receives only a small
OSM-like subset for the requested map area.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path


GRAPHML_TAG = re.compile(r"\{[^}]+\}(.*)")
LINESTRING = re.compile(r"[-+0-9.eE]+\s+[-+0-9.eE]+")
DRIVING_HIGHWAYS = {
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link",
}


def local_name(tag: str) -> str:
    match = GRAPHML_TAG.fullmatch(tag)
    return match.group(1) if match else tag


def parse_data(element: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in element:
        if local_name(child.tag) == "data":
            values[child.attrib.get("key", "")] = (child.text or "").strip()
    return values


def parse_linestring(value: str) -> list[tuple[float, float]]:
    if not value:
        return []
    return [tuple(float(part) for part in item.split()) for item in LINESTRING.findall(value)]


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=MEMORY;
        CREATE TABLE nodes (
            node_id TEXT PRIMARY KEY,
            lon REAL NOT NULL,
            lat REAL NOT NULL
        );
        CREATE TABLE edges (
            edge_id INTEGER PRIMARY KEY,
            source TEXT NOT NULL,
            target TEXT NOT NULL,
            length_m REAL NOT NULL,
            speed_kph REAL,
            highway TEXT NOT NULL,
            name TEXT,
            geometry TEXT NOT NULL,
            min_lon REAL NOT NULL,
            max_lon REAL NOT NULL,
            min_lat REAL NOT NULL,
            max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE edge_rtree USING rtree(
            edge_id, min_lon, max_lon, min_lat, max_lat
        );
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )


def convert(source: Path, output: Path, batch_size: int = 5000) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    connection = sqlite3.connect(output)
    create_schema(connection)
    node_count = edge_count = skipped_edges = 0
    bounds: list[float] | None = None
    node_batch: list[tuple[str, float, float]] = []
    edge_batch: list[tuple[int, str, str, float, float | None, str, str, str, float, float, float, float]] = []

    def flush_nodes() -> None:
        nonlocal node_batch
        if node_batch:
            connection.executemany("INSERT OR REPLACE INTO nodes VALUES (?, ?, ?)", node_batch)
            node_batch = []

    def flush_edges() -> None:
        nonlocal edge_batch
        if not edge_batch:
            return
        connection.executemany(
            "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            edge_batch,
        )
        connection.executemany(
            "INSERT INTO edge_rtree VALUES (?, ?, ?, ?, ?)",
            [(row[0], row[8], row[9], row[10], row[11]) for row in edge_batch],
        )
        edge_batch = []

    try:
        for _, element in ET.iterparse(source, events=("end",)):
            kind = local_name(element.tag)
            if kind == "node":
                data = parse_data(element)
                try:
                    node_batch.append((element.attrib["id"], float(data["x"]), float(data["y"])))
                    node_count += 1
                except (KeyError, ValueError):
                    pass
                if len(node_batch) >= batch_size:
                    flush_nodes()
                    if node_count % 100000 < batch_size:
                        print(f"nodes={node_count:,}", flush=True)
                element.clear()
            elif kind == "edge":
                data = parse_data(element)
                highway = data.get("highway", "").strip()
                if highway not in DRIVING_HIGHWAYS:
                    skipped_edges += 1
                    element.clear()
                    continue
                try:
                    geometry = parse_linestring(data.get("geometry", ""))
                    if len(geometry) < 2:
                        raise ValueError("edge geometry is empty")
                    coordinates = [(float(lon), float(lat)) for lon, lat in geometry]
                    min_lon = min(item[0] for item in coordinates)
                    max_lon = max(item[0] for item in coordinates)
                    min_lat = min(item[1] for item in coordinates)
                    max_lat = max(item[1] for item in coordinates)
                    row = (
                        edge_count,
                        element.attrib["source"],
                        element.attrib["target"],
                        float(data.get("length") or 0),
                        float(data["speed_kph"]) if data.get("speed_kph") else None,
                        highway,
                        data.get("name", ""),
                        json.dumps(coordinates, separators=(",", ":")),
                        min_lon, max_lon, min_lat, max_lat,
                    )
                    edge_batch.append(row)
                    edge_count += 1
                    if bounds is None:
                        bounds = [min_lon, min_lat, max_lon, max_lat]
                    else:
                        bounds = [
                            min(bounds[0], min_lon), min(bounds[1], min_lat),
                            max(bounds[2], max_lon), max(bounds[3], max_lat),
                        ]
                except (KeyError, ValueError):
                    skipped_edges += 1
                if len(edge_batch) >= batch_size:
                    flush_edges()
                    connection.commit()
                    if edge_count % 100000 < batch_size:
                        print(f"edges={edge_count:,}", flush=True)
                element.clear()

        flush_nodes()
        flush_edges()
        dataset_id = output.stem.removesuffix("-roads")
        connection.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            [
                ("source", str(source)),
                ("dataset", dataset_id),
                ("bbox", json.dumps(bounds, separators=(",", ":")) if bounds else "[]"),
                ("highway_types", json.dumps(sorted(DRIVING_HIGHWAYS))),
                ("node_count", str(node_count)),
                ("edge_count", str(edge_count)),
                ("skipped_edges", str(skipped_edges)),
            ],
        )
        connection.commit()
        connection.execute("CREATE INDEX idx_edges_highway ON edges(highway)")
        connection.commit()
        print(json.dumps({"output": str(output), "nodes": node_count, "edges": edge_count, "skipped": skipped_edges, "bbox": bounds}, ensure_ascii=False))
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    convert(args.source, args.output)


if __name__ == "__main__":
    main()
