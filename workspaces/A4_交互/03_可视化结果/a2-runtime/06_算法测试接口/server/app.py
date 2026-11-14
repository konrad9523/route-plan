from __future__ import annotations

import csv
import json
import os
import threading
import uuid

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.benchmark_service import BenchmarkService
from core.config import ALLOWED_ALGORITHMS, INTERFACE_DIR


SERVICE_VERSION = "2026-11-04-4"
app = FastAPI(title="A2路径规划性能测试API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
service = BenchmarkService()
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
run_lock = threading.Lock()
active_job_id: str | None = None


class BenchmarkRequest(BaseModel):
    dataset: str = "nanshan"
    algorithms: list[str] = Field(default_factory=lambda: list(ALLOWED_ALGORITHMS))
    query_count: int = Field(300, ge=3, le=10000)
    repeat: int = Field(3, ge=1, le=20)
    seed: int = Field(20261102, ge=0, le=4294967295)


def make_run_id(request: BenchmarkRequest) -> str:
    return (
        f"{request.dataset}/Q{request.query_count}"
        f"/R{request.repeat}/S{request.seed}"
    )


def output_file(name: str):
    path = service.outputs["frontend"] / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="尚未生成前端测试结果")
    return path


def execute(job_id: str, request: BenchmarkRequest) -> None:
    global active_job_id
    def notify(stage: str, percent: int) -> None:
        # The C++ runner emits completed=100 before report generation and
        # atomic publication. Keep the job visibly finalizing until those
        # steps have actually finished.
        visible_stage = "finalizing" if stage == "completed" else stage
        visible_percent = 99 if stage == "completed" else percent
        with jobs_lock:
            jobs[job_id].update(
                status="running", stage=visible_stage, progress=visible_percent
            )

    try:
        with run_lock:
            result = service.run(
                "frontend", request.dataset, request.algorithms,
                request.query_count, request.repeat, request.seed,
                prepare_if_missing=False, notify=notify,
            )
        summary_payload = json.loads(result.read_text(encoding="utf-8"))
        with jobs_lock:
            jobs[job_id].update(
                status="completed", stage="completed", progress=100,
                summary="/api/results/summary",
                table="/api/results/table",
                dashboard="/api/results/dashboard",
                result_file=str(result),
                result=summary_payload,
            )
    except Exception as error:
        with jobs_lock:
            jobs[job_id].update(
                status="failed", stage="failed", progress=0,
                error=str(error), run_id=make_run_id(request),
            )
    finally:
        with jobs_lock:
            if active_job_id == job_id:
                active_job_id = None


@app.get("/api/config")
def get_config() -> dict:
    return {
        "service_version": SERVICE_VERSION,
        "service": {
            "base_url": f"http://127.0.0.1:{os.environ.get('G4_A2_PORT', '8000')}",
            "interface_dir": str(INTERFACE_DIR),
            "data_root": str(service.config["_data_root"]),
            "runtime_root": str(service.runtime),
            "output_dir": str(service.outputs["frontend"]),
        },
        "algorithms": [
            {"id": "dijkstra", "name": "Dijkstra"},
            {"id": "astar", "name": "A*"},
            {"id": "bidirectional_astar", "name": "双向A*"},
            {"id": "ch", "name": "CH"},
        ],
        "datasets": [
            {
                "id": dataset.id,
                "name": dataset.name,
                "level": dataset.level,
                "data_available": dataset.graphml.exists() or os.environ.get("G4_A2_CACHE_ONLY") == "1",
                "cache_ready": service.cache_status(
                    dataset.id, verify_hash=False
                ).get("ready", False),
            }
            for dataset in service.datasets.values()
        ],
        "defaults": service.config["defaults"],
        "cache_policy": {
            "frontend_can_rebuild": False,
            "preprocess_time_source": "cached_first_build",
        },
    }


@app.get("/api/cache/status")
def get_cache_status() -> dict:
    return {
        "datasets": [service.cache_status(dataset_id) for dataset_id in service.datasets]
    }


@app.post("/api/benchmarks", status_code=202)
def create_benchmark(request: BenchmarkRequest) -> dict:
    global active_job_id
    if request.dataset not in service.datasets:
        raise HTTPException(status_code=400, detail="未知数据集")
    selected = list(dict.fromkeys(request.algorithms))
    if not selected or any(name not in ALLOWED_ALGORITHMS for name in selected):
        raise HTTPException(status_code=400, detail="算法参数无效")
    cache = service.cache_status(request.dataset)
    if not cache.get("ready"):
        raise HTTPException(
            status_code=409,
            detail=f"预处理缓存未就绪：{cache.get('reason')}",
        )
    request.algorithms = selected
    job_id = uuid.uuid4().hex
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    with jobs_lock:
        if active_job_id is not None:
            active = jobs.get(active_job_id, {})
            if active.get("status") in {"queued", "running"}:
                raise HTTPException(status_code=409, detail="已有 A2 测试正在运行，请等待完成")
        jobs[job_id] = {
            "job_id": job_id, "status": "queued", "stage": "queued",
            "progress": 0, "request": payload,
            "run_id": make_run_id(request),
        }
        active_job_id = job_id
        response = dict(jobs[job_id])
    threading.Thread(target=execute, args=(job_id, request), daemon=True).start()
    return response


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with jobs_lock:
        if job_id not in jobs:
            raise HTTPException(status_code=404, detail="任务不存在")
        return dict(jobs[job_id])


@app.get("/api/results/summary")
def get_summary() -> dict:
    return json.loads(output_file("summary.json").read_text(encoding="utf-8"))


@app.get("/api/results/table")
def get_table() -> dict:
    with output_file("algorithm_summary.csv").open(
        encoding="utf-8-sig", newline=""
    ) as source:
        return {"rows": list(csv.DictReader(source))}


@app.get("/api/results/queries")
def get_queries(
    offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=10000),
) -> dict:
    with output_file("query_raw.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    return {"total": len(rows), "offset": offset, "rows": rows[offset:offset + limit]}


@app.get("/api/results/dashboard", response_class=FileResponse)
def get_dashboard() -> FileResponse:
    return FileResponse(output_file("performance_dashboard.png"), media_type="image/png")


@app.get("/api/results/table.csv", response_class=FileResponse)
def download_table() -> FileResponse:
    return FileResponse(
        output_file("algorithm_summary.csv"),
        media_type="text/csv", filename="algorithm_summary.csv",
    )
