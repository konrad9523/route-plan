"""HTTP adapter for the A3 Python performance interface.

A3 publishes a Python entry point rather than an HTTP server. This small
+adapter keeps the browser contract asynchronous so a first-run C++ build or
GraphML conversion never blocks the web server request thread.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
A3_ROOT = ROOT / "a3-runtime"
INTERFACE_DIR = A3_ROOT / "workspaces" / "A3_性能" / "06_算法调用与出图" / "前端接口"
GRAPHML_DIR = Path(os.environ.get("G4_A3_GRAPHML_DIR", r"E:\路径规划_G4-A4数据\广东省路网"))
MANIFEST_PATH = A3_ROOT / "data" / "a3_network_manifest.json"
HOST = os.environ.get("G4_A3_HOST", "127.0.0.1")
PORT = int(os.environ.get("G4_A3_PORT", "8100"))
SERVICE_VERSION = "2026-11-06-1"
TRACE_INFO = {
    "code_dir": str(INTERFACE_DIR),
    "graphml_dir": str(GRAPHML_DIR),
    "service_url": f"http://{HOST}:{PORT}/api/benchmark",
}

os.environ.setdefault("G4_A3_GRAPHML_DIR", str(GRAPHML_DIR))
os.environ.setdefault("G4_A3_MANIFEST_PATH", str(MANIFEST_PATH))
sys.path.insert(0, str(INTERFACE_DIR))

from performance_service import ALGORITHMS, NETWORKS, run_performance_comparison  # noqa: E402


jobs: dict[str, dict] = {}
last_results: dict[str, dict] = {}
jobs_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="a3-benchmark")


def _json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length).decode("utf-8")
    value = json.loads(raw or "{}")
    if not isinstance(value, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return value


def _run_id(result: dict, request: dict) -> str:
    network = result.get("networks", [{}])[0]
    config = network.get("config", {})
    dataset = network.get("network", {}).get("id") or request["networks"][0]
    query_count = config.get("query_count", request.get("query_count"))
    rounds = config.get("rounds", request.get("rounds"))
    seed = config.get("seed", request.get("seed"))
    return f"{dataset}/Q{query_count}/R{rounds}/S{seed}"


def _execute(job_id: str, request: dict) -> None:
    with jobs_lock:
        jobs[job_id].update(status="running", stage="preparing", progress=10)
    try:
        # A3 creates temporary suite outputs below this directory before its
        # executable build step runs, so initialize it at the adapter boundary.
        (INTERFACE_DIR.parent / ".build").mkdir(parents=True, exist_ok=True)
        result = run_performance_comparison(request, build_if_missing=True)
        run_id = _run_id(result, request)
        with jobs_lock:
            jobs[job_id].update(status="completed", stage="completed", progress=100,
                                 run_id=run_id, result=result)
            for network in result.get("networks", []):
                last_results[network["network"]["id"]] = result
    except Exception as error:  # noqa: BLE001 - return the failure to the UI
        with jobs_lock:
            jobs[job_id].update(status="failed", stage="failed", progress=0,
                                 error=f"{type(error).__name__}: {error}")


def _datasets() -> list[dict]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = {item["filename"]: item for item in manifest.get("files", [])}
    cache_dir = INTERFACE_DIR.parent / ".build" / "graph_cache"
    return [
        {
            "id": network_id,
            "name": network["label"],
            "available": (
                (GRAPHML_DIR / network["graphml"]).is_file()
                or os.environ.get("G4_A3_CACHE_ONLY") == "1"
                and (cache_dir / f"{network_id}_{entries.get(network['graphml'], {}).get('sha256', '')[:12]}.bin").is_file()
            ),
            "nodes": entries.get(network["graphml"], {}).get("nodes", 0),
            "edges": entries.get(network["graphml"], {}).get("directed_edges", 0),
            "runs": [],
        }
        for network_id, network in NETWORKS.items()
    ]


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(HTTPStatus.NO_CONTENT, {})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send(HTTPStatus.OK, {"ok": True, "service": "a3", "service_version": SERVICE_VERSION})
            return
        if parsed.path == "/api/benchmark/datasets":
            self._send(HTTPStatus.OK, _datasets())
            return
        if parsed.path.startswith("/api/benchmark/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            with jobs_lock:
                job = jobs.get(job_id)
                payload = dict(job) if job else None
            if payload is None:
                self._send(HTTPStatus.NOT_FOUND, {"error": "A3 任务不存在"})
            else:
                self._send(HTTPStatus.OK, payload)
            return
        if parsed.path == "/api/benchmark/summary":
            dataset = parse_qs(parsed.query).get("dataset", ["guangdong"])[0]
            with jobs_lock:
                result = last_results.get(dataset)
            if result is None:
                self._send(HTTPStatus.NOT_FOUND, {"error": "该尺度尚未生成 A3 结果"})
            else:
                self._send(HTTPStatus.OK, result)
            return
        self._send(HTTPStatus.NOT_FOUND, {"error": "A3 接口不存在"})

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/benchmark/run":
            self._send(HTTPStatus.NOT_FOUND, {"error": "A3 接口不存在"})
            return
        try:
            body = _json_body(self)
            dataset = body.get("dataset") or (body.get("networks") or ["guangdong"])[0]
            request = {
                "networks": [dataset],
                "query_count": body.get("query_count", 30),
                "algorithms": body.get("algorithms", list(ALGORITHMS)),
                "rounds": body.get("rounds", 3),
                "seed": body.get("seed"),
            }
            if dataset not in NETWORKS:
                raise ValueError(f"unknown dataset ID: {dataset}")
            job_id = uuid.uuid4().hex[:12]
            with jobs_lock:
                jobs[job_id] = {
                    "job_id": job_id, "status": "queued", "stage": "queued",
                    "progress": 0, "request": request, "trace": TRACE_INFO,
                }
            executor.submit(_execute, job_id, request)
            self._send(HTTPStatus.ACCEPTED, {"job_id": job_id, "status": "queued", "request": request})
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def log_message(self, format: str, *args) -> None:
        print(f"[a3] {self.address_string()} - {format % args}")


def main() -> None:
    print(f"A3 性能服务：http://{HOST}:{PORT}/api/benchmark")
    print(f"A3 路网目录：{GRAPHML_DIR}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nA3 服务已停止")
    finally:
        server.server_close()
        executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
