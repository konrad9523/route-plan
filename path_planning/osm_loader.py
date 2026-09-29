"""把 OSMnx 导出的 GraphML 路网读成 path_planning.Graph。"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .models import Edge, Graph, Node

NS = "{http://graphml.graphdrawing.org/xmlns}"


def _attr_values(element: ET.Element, key_names: dict[str, str]) -> dict[str, str]:
    """把一个 <node>/<edge> 下的所有 <data> 读成 {属性名: 文本}。"""

    values: dict[str, str] = {}
    for data in element.findall(NS + "data"):
        name = key_names.get(data.get("key", ""))
        if name is not None:
            values[name] = data.text or ""
    return values


def parse_wkt_linestring(text: str) -> tuple[tuple[float, float], ...]:
    """解析 WKT 的 LINESTRING，返回 ((lon, lat), ...)。

    输入形如：
        LINESTRING (114.4119831 30.539114, 114.4120067 30.5391427, ...)
    注意 WKT 里是 "经度 纬度"，以空格分隔、逗号断开——和 GeoJSON 一样是 lon 在前。
    """

    match = re.search(r"\((.*)\)", text, re.S)
    if match is None:
        return ()
    points: list[tuple[float, float]] = []
    for pair in match.group(1).split(","):
        parts = pair.split()
        if len(parts) >= 2:
            points.append((float(parts[0]), float(parts[1])))
    return tuple(points)


def load_graphml(path: str | Path) -> Graph:
    """读 GraphML，返回 path_planning 的 Graph。"""

    root = ET.parse(str(path)).getroot()

    # 1. 先读属性名对照表：d14 -> "length"
    key_names = {k.get("id"): (k.get("attr.name") or "") for k in root.iter(NS + "key")}

    graph = Graph()

    # 2. 节点
    for element in root.iter(NS + "node"):
        values = _attr_values(element, key_names)
        graph.add_node(
            Node(
                node_id=int(element.get("id")),
                lon=float(values["x"]),
                lat=float(values["y"]),
            )
        )

    # 3. 边。GraphML 的 edge id 属性在 OSMnx 里不是唯一的（大量重复的 "0"），
    #    所以自己按出现顺序编号，保证每个 Edge.edge_id 唯一。
    next_edge_id = 0
    for element in root.iter(NS + "edge"):
        values = _attr_values(element, key_names)

        from_node = int(element.get("source"))
        to_node = int(element.get("target"))

        length_m = float(values["length"])
        speed_kmh = float(values.get("speed_kph") or 0.0)
        if speed_kmh <= 0:  # Edge 要求速度为正，缺速度的边给个保守默认值
            speed_kmh = 30.0

        geometry_text = values.get("geometry", "")
        geometry = parse_wkt_linestring(geometry_text) if geometry_text else ()

        road_type = (values.get("highway") or "residential").split(",")[0].strip()

        graph.add_edge(
            Edge(
                edge_id=next_edge_id,
                from_node=from_node,
                to_node=to_node,
                length_m=length_m,
                speed_kmh=speed_kmh,
                road_type=road_type,
                geometry=geometry,
                name=(values.get("name") or "")[:60],
            )
        )
        next_edge_id += 1

    return graph
