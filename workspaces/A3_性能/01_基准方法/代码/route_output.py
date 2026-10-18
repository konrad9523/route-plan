"""整理距离最短路的输出；不改变搜索四元组，不计入算法基准耗时。"""

from collections.abc import Mapping
from math import fsum, inf, isclose, isfinite
from operator import index

# Keep the existing DSH speed profile; these are estimates, not OSM observations.
ROAD_CLASS_ESTIMATED_SPEED_KMH = {
    "motorway": 100, "motorway_link": 60,
    "trunk": 80, "trunk_link": 50,
    "primary": 60, "primary_link": 40,
    "secondary": 50, "secondary_link": 35,
    "tertiary": 40, "tertiary_link": 30,
    "unclassified": 30, "residential": 30,
    "living_street": 15, "service": 20,
}

_DURATION_SEMANTICS = (
    "距离最短路线上的估算行驶时间；OSM maxspeed 按平均车速使用，道路等级回退值为估算速度；"
    "不含拥堵、信号灯、转向或停车等待。"
)


def _nonnegative(value, name):
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} 必须为有限非负数")
    return value


def _positive_speed(value):
    value = _nonnegative(value, "speed_kmh")
    if value == 0:
        raise ValueError("speed_kmh 必须大于零")
    return value


def build_route_output(result, edge_records, source, target, *, algorithm,
                       planning_ms=None, assumed_speed_kmh=None,
                       edge_speed_overrides=None):
    """将 (nodes, edge_ids, distance_m, expanded_nodes) 整理为可 JSON 序列化的字典。

    edge_records 为武汉边表 [(u,v,length_m,road_type,name,speed_kmh), ...]，
    或 {edge_id: {from_node,to_node,length_m,speed_kmh?,travel_time_s?,...}}。
    边权必须为米；时间权重或含惩罚的搜索结果不能直接传入。
    OSM maxspeed 覆盖值、边速度、道路等级估算速度依次用于计算边时间。
    assumed_speed_kmh 仅作为未映射道路等级的最后回退。时间只累计边行驶时间。
    """
    nodes, edge_ids, cost, expanded = result
    nodes = [index(node) for node in nodes]
    edge_ids = [index(edge_id) for edge_id in edge_ids]
    source, target, expanded = index(source), index(target), index(expanded)
    if any(value < 0 for value in [source, target, expanded, *nodes, *edge_ids]):
        raise ValueError("节点、边编号及展开节点数必须为非负整数")
    if not isinstance(algorithm, str) or not algorithm.strip():
        raise ValueError("algorithm 不能为空")
    if planning_ms is not None:
        planning_ms = _nonnegative(planning_ms, "planning_ms")
    if assumed_speed_kmh is not None:
        assumed_speed_kmh = _positive_speed(assumed_speed_kmh)
    if edge_speed_overrides is not None and not isinstance(edge_speed_overrides, Mapping):
        raise TypeError("edge_speed_overrides 必须是 edge_id 到速度的映射")
    cost = float(cost)
    output = {
        "schema_version": "a3.route.v1", "status": "ok", "algorithm": algorithm,
        "source": source, "target": target, "node_ids": nodes, "edge_ids": edge_ids,
        "distance_m": None, "duration_s": None, "duration_status": "not_applicable",
        "duration_scope": "edge_travel_only", "cost": None, "cost_unit": "m",
        "expanded_nodes": expanded, "planning_ms": planning_ms,
        "duration_semantics": _DURATION_SEMANTICS,
        "segments": [], "warnings": [],
    }
    if not nodes:
        if edge_ids or cost != inf or source == target:
            raise ValueError("不可达结果必须为：空节点、空边、正无穷代价，且起终点不同")
        output["status"] = "no_route"
        return output
    cost = _nonnegative(cost, "distance cost")
    if nodes[0] != source or nodes[-1] != target or len(nodes) != len(edge_ids) + 1:
        raise ValueError("路径的起终点或节点/边数量不匹配")

    for sequence, (u, v, edge_id) in enumerate(zip(nodes, nodes[1:], edge_ids), 1):
        try:
            record = edge_records[edge_id]
        except (KeyError, IndexError) as exc:
            raise ValueError(f"找不到 edge_id={edge_id} 的边属性") from exc
        if not isinstance(record, Mapping):
            a, b, length, road_type, name, speed = record
            record = dict(from_node=a, to_node=b, length_m=length,
                          road_type=road_type, name=name, speed_kmh=speed)
        if index(record["from_node"]) != u or index(record["to_node"]) != v:
            raise ValueError(f"edge_id={edge_id} 与路径中的有向端点不符")
        length = _nonnegative(record["length_m"], "length_m")
        speed = record.get("speed_kmh")
        if speed is not None:
            speed = _positive_speed(speed)
        speed_source = record.get("speed_source")
        duration = record.get("travel_time_s")
        if duration is not None:
            duration = _nonnegative(duration, "travel_time_s")
            duration_source = "provided_travel_time_s"
        elif edge_speed_overrides and edge_id in edge_speed_overrides:
            speed = _positive_speed(edge_speed_overrides[edge_id])
            speed_source = "osm_maxspeed"
            duration = length / speed * 3.6
            duration_source = speed_source
        elif speed is not None:
            speed_source = speed_source or "edge_speed_kmh"
            duration = length / speed * 3.6
            duration_source = speed_source
        elif (
            isinstance(record.get("road_type"), str)
            and record["road_type"] in ROAD_CLASS_ESTIMATED_SPEED_KMH
        ):
            speed = ROAD_CLASS_ESTIMATED_SPEED_KMH[record["road_type"]]
            speed_source = "road_class_estimate"
            duration = length / speed * 3.6
            duration_source = speed_source
        elif assumed_speed_kmh is not None:
            speed = assumed_speed_kmh
            speed_source = "assumed_speed_kmh"
            duration = length / speed * 3.6
            duration_source = speed_source
        elif length == 0:
            duration, duration_source, speed_source = 0.0, "zero_length", None
        else:
            duration, duration_source, speed_source = None, "missing", None
        if duration is not None and not isfinite(duration):
            raise ValueError("由速度计算的通行时间溢出")
        output["segments"].append({
            "sequence": sequence, "edge_id": edge_id, "from_node": u, "to_node": v,
            "length_m": length, "speed_kmh": speed, "duration_s": duration,
            "speed_source": speed_source, "duration_source": duration_source,
            "road_type": record.get("road_type", ""), "name": record.get("name", ""),
        })
    distance = fsum(segment["length_m"] for segment in output["segments"])
    if not isclose(distance, cost, rel_tol=1e-9, abs_tol=1e-5):
        raise ValueError("边长度之和与搜索代价不一致：请检查边版本、单位及 edge_id")
    missing = sum(segment["duration_s"] is None for segment in output["segments"])
    assumed = sum(segment["duration_source"] == "assumed_speed_kmh"
                  for segment in output["segments"])
    estimated = sum(segment["duration_source"] == "road_class_estimate"
                    for segment in output["segments"])
    output.update(distance_m=distance, cost=cost,
                  duration_status="missing" if missing else "complete",
                  duration_s=None if missing else fsum(
                      segment["duration_s"] for segment in output["segments"]))
    if missing:
        output["warnings"].append(f"{missing} 条路段缺少时间或速度，总通行时间不可用；未用部分之和代替总时间。")
    if assumed:
        output["warnings"].append(f"{assumed} 条路段使用显式假设速度 {assumed_speed_kmh:g} km/h，不代表真实交通耗时。")
    if estimated:
        output["warnings"].append(
            f"{estimated} 条路段使用道路等级回退估算速度；总时间是距离最短路线的估算值，不是时间最短路线。"
        )
    return output
