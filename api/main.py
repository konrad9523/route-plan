"""路径规划引擎的 HTTP 服务（FastAPI）。

提供三件事：
* ``GET  /``            演示页面
* ``GET  /api/meta``    路网元信息（节点数、边数、边界框、可用偏好与算法）
* ``POST /api/route``   规划路线，返回 GeoJSON + 可选搜索过程

设计原则：**前端只消费 JSON，不 import 任何 Python**。
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from path_planning import CostModel, Graph, NoRouteError, Preference, load_graphml, plan_route

ROOT = Path(__file__).resolve().parent.parent
GRAPHML_PATH = ROOT / "learning_osmnx_networkx" / "output" / "graph.graphml"
WEB_DIR = ROOT / "web"

app = FastAPI(
    title="路径规划引擎 API",
    description="G4 路径规划引擎组的演示服务",
    version="0.1.0",
)

# 路网与派生信息在首次请求时构建一次，之后复用
_graph: Graph | None = None
_bbox: dict[str, float] = {}


def get_graph() -> Graph:
    """惰性加载路网。避免模块导入时就做 I/O。"""

    global _graph, _bbox
    if _graph is None:
        if not GRAPHML_PATH.exists():
            raise HTTPException(
                status_code=503,
                detail=f"路网数据缺失：{GRAPHML_PATH}",
            )
        _graph = load_graphml(GRAPHML_PATH)
        lons = [node.lon for node in _graph.nodes.values()]
        lats = [node.lat for node in _graph.nodes.values()]
        _bbox = {
            "min_lon": min(lons),
            "min_lat": min(lats),
            "max_lon": max(lons),
            "max_lat": max(lats),
        }
    return _graph


class RouteRequest(BaseModel):
    """一次路线规划请求。"""

    source: int = Field(..., description="起点路口 ID")
    target: int = Field(..., description="终点路口 ID")
    algorithm: str = Field("astar", description="dijkstra 或 astar")
    preference: str = Field("fastest", description="fastest / shortest / avoid_tolls / no_highway")
    trace: bool = Field(False, description="是否返回搜索过程（可视化用）")
    max_steps: int = Field(600, ge=0, description="搜索过程最多保留多少步；0 表示不降采样")


def _parse_preference(value: str) -> Preference:
    try:
        return Preference(value)
    except ValueError as exc:
        allowed = [p.value for p in Preference]
        raise HTTPException(status_code=400, detail=f"preference 必须是 {allowed} 之一") from exc


@app.get("/api/meta")
def meta() -> dict:
    """路网元信息，供前端初始化地图。"""

    graph = get_graph()
    return {
        "graph_version": "campus-552-v1",
        "source": str(GRAPHML_PATH.name),
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "bbox": _bbox,
        "algorithms": ["dijkstra", "astar"],
        "preferences": [p.value for p in Preference],
    }


@app.get("/api/nodes")
def nodes() -> dict:
    """所有路口的坐标。前端画底图和时间轴都要用。"""

    graph = get_graph()
    return {
        "ids": list(graph.nodes.keys()),
        "lons": [round(n.lon, 7) for n in graph.nodes.values()],
        "lats": [round(n.lat, 7) for n in graph.nodes.values()],
    }


@app.post("/api/route")
def route(request: RouteRequest) -> dict:
    """规划路线。"""

    graph = get_graph()
    model = CostModel(preference=_parse_preference(request.preference))

    try:
        result = plan_route(
            graph,
            request.source,
            request.target,
            algorithm=request.algorithm.lower(),
            cost_model=model,
            trace=request.trace,
        )
    except NoRouteError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload: dict = {
        "status": result.status,
        "algorithm": result.algorithm,
        "preference": request.preference,
        "source": result.source,
        "target": result.target,
        "distance_m": round(result.distance_m, 2),
        "duration_s": round(result.duration_s, 2),
        "cost": round(result.cost, 3),
        "edge_ids": result.edge_ids,
        "node_ids": result.node_ids,
        "geometry": [list(point) for point in result.geometry],
        "stats": {
            "expanded_states": result.expanded_states,
            "queue_pushes": result.queue_pushes,
            "planning_ms": round(result.planning_ms, 3),
        },
    }

    if request.trace and result.trace is not None:
        trace = result.trace
        if request.max_steps and len(trace.pop_order) > request.max_steps:
            trace = trace.downsample(request.max_steps)
        payload["trace"] = trace.to_compact()

    return payload


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """演示页面。"""

    page = WEB_DIR / "index.html"
    if not page.exists():
        raise HTTPException(status_code=503, detail=f"页面缺失：{page}")
    return page.read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "graph_loaded": _graph is not None}
