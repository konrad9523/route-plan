"""轻量级地理计算，仅用于启发式和演示。"""

from __future__ import annotations

import math

from .models import Coordinate

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(a: Coordinate, b: Coordinate) -> float:
    """计算 WGS84 经纬度点之间的球面近似距离。"""

    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, hav)))


def append_geometry(target: list[Coordinate], geometry: tuple[Coordinate, ...]) -> None:
    """拼接边几何，并删除相邻边重复的连接点。"""

    if not geometry:
        return
    if not target:
        target.extend(geometry)
        return
    if target[-1] == geometry[0]:
        target.extend(geometry[1:])
    else:
        target.extend(geometry)
