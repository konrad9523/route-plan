from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import folium
import networkx as nx
import osmnx as ox


# 默认练习区域：中国地质大学（武汉）校园及周边
DEFAULT_PLACE = "China University of Geosciences, Wuhan, China"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用 OSMnx + NetworkX 下载小区域道路并计算路线"
    )
    parser.add_argument(
        "--place",
        default=DEFAULT_PLACE,
        help="OSM 可识别的区域名称，建议使用小区域",
    )
    parser.add_argument(
        "--network-type",
        default="drive",
        choices=["drive", "walk", "bike", "all_public"],
        help="交通主体对应的道路网络类型",
    )
    parser.add_argument(
        "--weight",
        default="travel_time",
        choices=["length", "travel_time"],
        help="路线优化目标：道路长度或预计通行时间",
    )
    parser.add_argument(
        "--dist",
        type=int,
        default=1800,
        help="以地点中心向外抓取的道路半径，单位为米",
    )
    return parser.parse_args()


def load_graph(place: str, network_type: str, dist: int) -> nx.MultiDiGraph:
    ox.settings.use_cache = True
    ox.settings.log_console = True
    ox.settings.requests_timeout = 180

    center = ox.geocode(place)
    print(f"正在下载道路网络：{place} / {network_type} / 半径 {dist} 米")
    graph = ox.graph_from_point(
        center,
        dist=dist,
        dist_type="bbox",
        network_type=network_type,
        simplify=True,
    )

    # 小区域 OSM 数据可能没有 maxspeed 标签。
    # 这里显式设置回退速度，避免时间最短模式因缺失属性失败。
    graph = ox.add_edge_speeds(graph, fallback=30)
    graph = ox.add_edge_travel_times(graph)
    return graph


def choose_demo_endpoints(graph: nx.MultiDiGraph) -> tuple[int, int]:
    nodes = ox.graph_to_gdfs(graph, nodes=True, edges=False)

    if len(nodes) < 2:
        raise RuntimeError("道路网络节点数量不足，无法选择起点和终点")

    # 有向图中，弱连通不代表可以沿道路方向互相到达。
    # 在最大强连通分量中选择端点，避免演示时因单行道导致无路可达。
    components = list(nx.strongly_connected_components(graph))
    component = max(components, key=len)
    if len(component) < 2:
        raise RuntimeError("道路网络没有足够大的强连通分量")

    ordered = nodes.loc[list(component)].sort_values(["y", "x"])
    origin = int(ordered.index[0])
    destination = int(ordered.index[-1])

    if origin == destination:
        destination = int(ordered.index[len(ordered) // 2])

    return origin, destination


def calculate_route(
    graph: nx.MultiDiGraph,
    origin: int,
    destination: int,
    weight: str,
) -> list[int]:
    try:
        return nx.shortest_path(
            graph,
            origin,
            destination,
            weight=weight,
            method="dijkstra",
        )
    except nx.NetworkXNoPath as exc:
        raise RuntimeError("起点和终点之间没有可达路线") from exc


def route_summary(
    graph: nx.MultiDiGraph,
    route: list[int],
    weight: str,
) -> dict[str, Any]:
    edge_rows = ox.routing.route_to_gdf(graph, route)
    length_m = float(edge_rows["length"].fillna(0).sum())

    if "travel_time" in edge_rows:
        travel_time_s = float(edge_rows["travel_time"].fillna(0).sum())
    else:
        travel_time_s = None

    return {
        "algorithm": "networkx_dijkstra",
        "weight": weight,
        "node_count": len(route),
        "edge_count": len(edge_rows),
        "distance_m": round(length_m, 2),
        "duration_s": None if travel_time_s is None else round(travel_time_s, 2),
        "origin_node": int(route[0]),
        "destination_node": int(route[-1]),
    }


def save_map(
    graph: nx.MultiDiGraph,
    route: list[int],
    output_path: Path,
) -> None:
    nodes = ox.graph_to_gdfs(graph, nodes=True, edges=False)
    center_lat = float(nodes["y"].mean())
    center_lon = float(nodes["x"].mean())

    route_map = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=15,
        tiles="OpenStreetMap",
    )

    route_edges = ox.routing.route_to_gdf(graph, route)
    for _, edge in route_edges.iterrows():
        geometry = edge.geometry
        if geometry is not None and hasattr(geometry, "coords"):
            coordinates = [(lat, lon) for lon, lat in geometry.coords]
        else:
            coordinates = [
                (graph.nodes[int(edge["u"])] ["y"], graph.nodes[int(edge["u"])] ["x"]),
                (graph.nodes[int(edge["v"])] ["y"], graph.nodes[int(edge["v"])] ["x"]),
            ]

        folium.PolyLine(
            coordinates,
            color="#e63946",
            weight=6,
            opacity=0.85,
        ).add_to(route_map)

    origin_node = route[0]
    destination_node = route[-1]

    folium.Marker(
        [graph.nodes[origin_node]["y"], graph.nodes[origin_node]["x"]],
        tooltip="Origin",
        icon=folium.Icon(color="green"),
    ).add_to(route_map)

    folium.Marker(
        [
            graph.nodes[destination_node]["y"],
            graph.nodes[destination_node]["x"],
        ],
        tooltip="Destination",
        icon=folium.Icon(color="red"),
    ).add_to(route_map)

    route_map.save(output_path)


def main() -> None:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    graph = load_graph(args.place, args.network_type, args.dist)
    origin, destination = choose_demo_endpoints(graph)
    route = calculate_route(graph, origin, destination, args.weight)

    summary = route_summary(graph, route, args.weight)
    summary["place"] = args.place
    summary["network_type"] = args.network_type
    summary["graph_node_count"] = graph.number_of_nodes()
    summary["graph_edge_count"] = graph.number_of_edges()

    graph_path = OUTPUT_DIR / "graph.graphml"
    summary_path = OUTPUT_DIR / "route_summary.json"
    map_path = OUTPUT_DIR / "route_demo.html"

    ox.save_graphml(graph, graph_path)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    save_map(graph, route, map_path)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"地图已保存：{map_path}")
    print(f"路网已保存：{graph_path}")
    print(f"统计已保存：{summary_path}")


if __name__ == "__main__":
    main()
