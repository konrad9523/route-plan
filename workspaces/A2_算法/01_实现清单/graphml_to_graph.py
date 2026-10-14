"""Load the processed A1 road GraphML as adjacency lists for the A2 algorithms.

Default input (resolved from the repository root):
    workspaces/A1_数据/01_路网清单/processed/dc_driving_optimized.graphml

Returned structures:
    graph[node] = [(neighbor, length_m, edge_id), ...]
    positions[node] = (longitude, latitude)
    geometries[edge_id] = [(longitude, latitude), ...]
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GRAPHML = (
    PROJECT_ROOT
    / "workspaces"
    / "A1_数据"
    / "01_路网清单"
    / "processed"
    / "dc_driving_optimized.graphml"
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_linestring(wkt: str) -> list[tuple[float, float]]:
    match = re.fullmatch(r"\s*LINESTRING\s*\((.*)\)\s*", wkt, flags=re.IGNORECASE)
    if not match:
        return []
    result = []
    for pair in match.group(1).split(","):
        fields = pair.strip().split()
        if len(fields) < 2:
            return []
        lon, lat = float(fields[0]), float(fields[1])
        if not (math.isfinite(lon) and math.isfinite(lat)):
            raise ValueError("edge geometry contains a non-finite coordinate")
        result.append((lon, lat))
    return result


def load_graphml(path: Path | str = DEFAULT_GRAPHML):
    """Read a directed GraphML network into the standalone A2 algorithm format."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"GraphML road network not found: {path}")

    keys: dict[str, str] = {}
    graph: dict[str, list[tuple[str, float, str]]] = {}
    positions: dict[str, tuple[float, float]] = {}
    geometries: dict[str, list[tuple[float, float]]] = {}
    edge_ids: set[str] = set()
    graph_is_directed = True

    context = ET.iterparse(path, events=("start", "end"))
    try:
        _, root = next(context)
    except StopIteration as exc:
        raise ValueError("GraphML file is empty") from exc

    for event, element in context:
        name = _local_name(element.tag)
        if event == "start" and name == "graph":
            graph_is_directed = element.attrib.get("edgedefault", "directed") == "directed"
            if not graph_is_directed:
                raise ValueError("A2 algorithms require a directed road graph")
        elif event == "end" and name == "key":
            key_id = element.attrib.get("id")
            attr_name = element.attrib.get("attr.name")
            if key_id and attr_name:
                keys[key_id] = attr_name
            element.clear()
        elif event == "end" and name == "node":
            node_id = element.attrib.get("id")
            if not node_id:
                raise ValueError("GraphML node is missing an id")
            attrs = {
                keys.get(child.attrib.get("key", ""), child.attrib.get("key", "")): child.text
                for child in element
                if _local_name(child.tag) == "data"
            }
            try:
                lon, lat = float(attrs["x"]), float(attrs["y"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"node {node_id} must have numeric x/y coordinates") from exc
            if not (math.isfinite(lon) and math.isfinite(lat)):
                raise ValueError(f"node {node_id} has a non-finite coordinate")
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError(f"node {node_id} coordinates are not longitude/latitude")
            if node_id in graph:
                raise ValueError(f"duplicate GraphML node id: {node_id}")
            positions[node_id] = (lon, lat)
            graph[node_id] = []
            element.clear()
        elif event == "end" and name == "edge":
            edge_id = element.attrib.get("id")
            source, target = element.attrib.get("source"), element.attrib.get("target")
            if edge_id is None or source is None or target is None:
                raise ValueError("GraphML edges must have id, source, and target")
            if edge_id in edge_ids:
                raise ValueError(f"duplicate GraphML edge id: {edge_id}")
            attrs = {
                keys.get(child.attrib.get("key", ""), child.attrib.get("key", "")): child.text
                for child in element
                if _local_name(child.tag) == "data"
            }
            try:
                weight = float(attrs["length"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"edge {edge_id} must have numeric 'length' in meters") from exc
            if not math.isfinite(weight) or weight < 0:
                raise ValueError(f"edge {edge_id} has an invalid length")
            edge_ids.add(edge_id)
            graph.setdefault(source, []).append((target, weight, edge_id))
            graph.setdefault(target, [])
            if attrs.get("geometry"):
                points = _parse_linestring(attrs["geometry"])
                if points:
                    geometries[edge_id] = points
            element.clear()

    missing = set(graph) - set(positions)
    if missing:
        raise ValueError(f"{len(missing)} edge endpoint(s) have no coordinate nodes")
    return graph, positions, geometries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graphml", nargs="?", type=Path, default=DEFAULT_GRAPHML,
                        help="A1 processed GraphML path (defaults to the repository's A1 file)")
    args = parser.parse_args()
    try:
        graph, positions, geometries = load_graphml(args.graphml)
    except (OSError, ValueError, ET.ParseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print("GRAPHML LOAD OK")
    print(f"input: {args.graphml}")
    print(f"nodes: {len(graph):,}")
    print(f"directed edges: {sum(map(len, graph.values())):,}")
    print(f"nodes with coordinates: {len(positions):,}")
    print(f"edges with line geometry: {len(geometries):,}")
    print("edge weight: length in meters")
    print("coordinates: longitude, latitude")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
