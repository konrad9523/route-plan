"""将项目GraphML转换为C++性能测试使用的紧凑二进制RGRAPH1。

只转换拓扑、WGS84坐标和非负边权。GraphML读取不计入算法预处理时间；
同一路网只需转换一次，后续测试直接复用.rgraph缓存。
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


MAGIC = b"RGRAPH1\0"
HEADER = struct.Struct("<8sQQ")
NODE = struct.Struct("<dd")
EDGE = struct.Struct("<iidq")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def data_values(element: ET.Element, key_names: dict[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in element:
        if local_name(child.tag) != "data":
            continue
        key = child.attrib.get("key", "")
        name = key_names.get(key, key)
        values[name] = (child.text or "").strip()
    return values


def first_number(values: dict[str, str], names: tuple[str, ...]) -> float | None:
    for name in names:
        text = values.get(name)
        if text in (None, ""):
            continue
        try:
            return float(text)
        except ValueError:
            continue
    return None


def convert(input_path: Path, output_path: Path) -> dict[str, object]:
    key_names: dict[str, str] = {}
    node_index: dict[str, int] = {}
    coordinates: list[tuple[float, float]] = []
    edge_count = 0
    skipped_edges = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rgraph_edges_") as temporary:
        edge_path = Path(temporary) / "edges.bin"
        with edge_path.open("wb") as edge_output:
            for _, element in ET.iterparse(input_path, events=("end",)):
                name = local_name(element.tag)
                if name == "key":
                    key_id = element.attrib.get("id")
                    attribute_name = element.attrib.get("attr.name")
                    if key_id and attribute_name:
                        key_names[key_id] = attribute_name
                elif name == "node":
                    node_id = element.attrib.get("id")
                    if node_id is None:
                        raise ValueError("GraphML节点缺少id")
                    values = data_values(element, key_names)
                    lon = first_number(values, ("x", "lon", "longitude"))
                    lat = first_number(values, ("y", "lat", "latitude"))
                    if lon is None:
                        lon = first_number(element.attrib, ("x", "lon", "longitude"))
                    if lat is None:
                        lat = first_number(element.attrib, ("y", "lat", "latitude"))
                    if lon is None or lat is None or not math.isfinite(lon + lat):
                        raise ValueError(f"节点{node_id}缺少有效经纬度")
                    node_index[node_id] = len(coordinates)
                    coordinates.append((lon, lat))
                elif name == "edge":
                    source_id = element.attrib.get("source")
                    target_id = element.attrib.get("target")
                    if source_id not in node_index or target_id not in node_index:
                        raise ValueError("GraphML边出现在对应节点之前或引用了未知节点")
                    values = data_values(element, key_names)
                    weight = first_number(
                        values, ("length", "length_m", "weight", "cost")
                    )
                    if weight is None:
                        weight = first_number(
                            element.attrib, ("length", "length_m", "weight", "cost")
                        )
                    if weight is None or not math.isfinite(weight) or weight < 0:
                        skipped_edges += 1
                        element.clear()
                        continue
                    raw_edge_id = values.get("edge_id", element.attrib.get("id", ""))
                    try:
                        edge_id = int(raw_edge_id)
                    except (TypeError, ValueError):
                        edge_id = edge_count
                    edge_output.write(
                        EDGE.pack(
                            node_index[source_id], node_index[target_id], weight, edge_id
                        )
                    )
                    edge_count += 1
                # data子元素必须保留到父node/edge结束时才能读取；只在完整
                # 处理完较大的GraphML对象后释放内存。
                if name in {"key", "node", "edge"}:
                    element.clear()

        if not coordinates:
            raise ValueError("GraphML中没有读取到节点")
        if not edge_count:
            raise ValueError("GraphML中没有读取到有效边")

        with output_path.open("wb") as output:
            output.write(HEADER.pack(MAGIC, len(coordinates), edge_count))
            for lon, lat in coordinates:
                output.write(NODE.pack(lon, lat))
            with edge_path.open("rb") as edge_input:
                shutil.copyfileobj(edge_input, output, length=8 * 1024 * 1024)

    metadata = {
        "format": "RGRAPH1",
        "source": input_path.name,
        "output": output_path.name,
        "nodes": len(coordinates),
        "edges": edge_count,
        "skipped_invalid_edges": skipped_edges,
        "coordinate_order": "longitude,latitude",
        "weight_unit": "metre or source GraphML cost unit",
    }
    output_path.with_suffix(output_path.suffix + ".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="GraphML转RGRAPH1")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    metadata = convert(args.input, args.output)
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == "__main__":
    main()
