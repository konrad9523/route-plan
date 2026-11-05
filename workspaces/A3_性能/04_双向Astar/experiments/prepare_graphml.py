"""Stream a directed A1 GraphML road network into the local benchmark format."""

from __future__ import annotations

import argparse
import array
import json
import math
import struct
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def convert(source: Path, destination: Path) -> dict[str, object]:
    if sys.byteorder != "little":
        raise RuntimeError("the benchmark binary format currently requires little-endian")
    started = time.perf_counter()
    node_index: dict[str, int] = {}
    coordinates = array.array("d")
    keys: dict[str, str] = {}
    directed = True
    element_stack: list[ET.Element] = []
    output = None
    edge_count = 0
    edge_record = struct.Struct("<iid")
    edge_buffer = bytearray()

    try:
        for event, element in ET.iterparse(source, events=("start", "end")):
            name = local_name(element.tag)
            if event == "start":
                element_stack.append(element)
                if name == "graph":
                    directed = element.attrib.get("edgedefault", "directed") == "directed"
                    if not directed:
                        raise ValueError("the A3 algorithms require a directed GraphML graph")
                continue

            parent = element_stack[-2] if len(element_stack) > 1 else None

            if name == "key":
                key_id = element.attrib.get("id")
                attr_name = element.attrib.get("attr.name")
                if key_id and attr_name:
                    keys[key_id] = attr_name
            elif name == "node":
                if output is not None:
                    raise ValueError("GraphML must list all nodes before its edges")
                node_id = element.attrib.get("id")
                if not node_id or node_id in node_index:
                    raise ValueError(f"missing or duplicate node ID: {node_id!r}")
                attrs = {
                    keys.get(child.attrib.get("key", ""), child.attrib.get("key", "")):
                    child.text
                    for child in element
                    if local_name(child.tag) == "data"
                }
                try:
                    lon, lat = float(attrs["x"]), float(attrs["y"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"node {node_id} is missing numeric x/y coordinates") from exc
                if not (math.isfinite(lon) and math.isfinite(lat)
                        and -180 <= lon <= 180 and -90 <= lat <= 90):
                    raise ValueError(f"node {node_id} has invalid longitude/latitude")
                node_index[node_id] = len(node_index)
                coordinates.extend((lon, lat))
            elif name == "edge":
                if output is None:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    output = destination.open("wb")
                    output.write(struct.pack("<QQ", len(node_index), 0))
                    coordinates.tofile(output)
                source_id = element.attrib.get("source")
                target_id = element.attrib.get("target")
                attrs = {
                    keys.get(child.attrib.get("key", ""), child.attrib.get("key", "")):
                    child.text
                    for child in element
                    if local_name(child.tag) == "data"
                }
                try:
                    source_node = node_index[source_id]
                    target_node = node_index[target_id]
                    weight = float(attrs["length"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"edge {element.attrib.get('id')} has invalid endpoints/length") from exc
                if not math.isfinite(weight) or weight < 0:
                    raise ValueError(f"edge {element.attrib.get('id')} has invalid length")
                edge_buffer.extend(edge_record.pack(source_node, target_node, weight))
                edge_count += 1
                if len(edge_buffer) >= 1 << 20:
                    output.write(edge_buffer)
                    edge_buffer.clear()

            if name in {"key", "node", "edge"}:
                element.clear()
                if parent is not None:
                    parent.remove(element)
            if name == "graph":
                pass
            element_stack.pop()

        if output is None:
            raise ValueError("GraphML has no edges")
        if edge_buffer:
            output.write(edge_buffer)
        output.seek(8)
        output.write(struct.pack("<Q", edge_count))
        output.close()
        output = None
    finally:
        if output is not None:
            output.close()

    metadata = {
        "source_graphml": str(source.resolve()),
        "binary_file": str(destination.resolve()),
        "node_count": len(node_index),
        "directed_edge_count": edge_count,
        "node_index_policy": "GraphML node element order, zero-based",
        "edge_id_policy": "GraphML edge element order, zero-based internal benchmark ID",
        "weight": "GraphML length in meters",
        "coordinate_order": "longitude, latitude",
        "conversion_seconds": time.perf_counter() - started,
    }
    destination.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graphml", type=Path)
    parser.add_argument("binary", type=Path)
    args = parser.parse_args()
    report = convert(args.graphml, args.binary)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
