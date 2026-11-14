"""A2 性能比较内部执行与结果整理。

这是 A3 风格前端接口文件夹下的内部实现；外部请导入 performance_service.py。
保留原有 BenchmarkService、缓存和 C++ 测试器调用方式。
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from statistics import median
from typing import Any

# 可直接用 sys.path 插入本目录导入，不要求安装成 Python 包。
_INTERFACE_ROOT = Path(__file__).resolve().parents[1]
if str(_INTERFACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INTERFACE_ROOT))

from core.benchmark_service import BenchmarkService
from core.config import ALLOWED_ALGORITHMS


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    data = sorted(values)
    pos = (len(data) - 1) * p
    left, right = math.floor(pos), math.ceil(pos)
    return data[left] + (data[right] - data[left]) * (pos - left)


def _collect(summary_file: Path) -> dict[str, Any]:
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    folder = summary_file.parent
    requested = summary["run"]["selected_algorithms"]
    selected = set(requested)
    timings: dict[str, list[float]] = {name: [] for name in requested}
    with (folder / "query_raw.csv").open(encoding="utf-8", newline="") as stream:
        for item in csv.DictReader(stream):
            if item["algorithm"] in selected and item["valid"] == "true":
                timings[item["algorithm"]].append(float(item["query_ms"]))
    network = summary["dataset"]["id"]
    count = summary["run"]["query_count"]
    rows, charts = [], []
    for name in requested:
        stats = summary["algorithms"][name]
        prepare = float(stats["preprocess_ms"])
        query_mean = float(stats["query_mean_ms"])
        times = timings[name]
        rows.append({
            "network": network,
            "algorithm": name,
            "query_mean_ms": query_mean,
            "expanded_mean": float(stats["expanded_mean"]),
            "preprocess_ms": prepare,
            "total_cost_ms": prepare + query_mean * count,
            "valid_queries": int(stats["valid_queries"]),
        })
        charts.append({
            "network": network,
            "algorithm": name,
            "query_ms_median": median(times) if times else None,
            "query_ms_q1": _percentile(times, 0.25),
            "query_ms_q3": _percentile(times, 0.75),
            "query_ms_values": times,
            "expanded_mean": float(stats["expanded_mean"]),
            "preprocess_ms": prepare,
            "total_cost_ms": prepare + query_mean * count,
        })
    return {
        "summary_table": rows,
        "chart_data": charts,
        "run": summary["run"],
        "validation": summary.get("validation", {}),
        "files": {
            "summary": str(summary_file),
            "table_csv": str(folder / "algorithm_summary.csv"),
            "query_csv": str(folder / "query_raw.csv"),
            "dashboard_png": str(folder / "performance_dashboard.png"),
        },
    }


def read_performance_result(summary_file: str | Path) -> dict[str, Any]:
    """只读解析历史结果，便于不运行 C++ 就演示前端表格。"""
    return _collect(Path(summary_file))


def run_performance_comparison(params: dict[str, Any]) -> dict[str, Any]:
    """运行选定路网的四算法性能比较。

    参数：networks 或 network；query_count；algorithms；rounds；seed；
    prepare_cache（默认 False）；force_rebuild（默认 False）。

    输出：summary_table / chart_data / runs，均可直接 JSON 序列化。
    预处理索引需先准备；只有明确设置 prepare_cache=True 才允许现场生成。
    """
    service = BenchmarkService()
    if "networks" in params:
        network_arg = params["networks"]
    else:
        network_arg = [params.get("network", service.config["defaults"]["dataset"])]
    if isinstance(network_arg, str):
        networks = [network_arg]
    else:
        networks = list(network_arg)
    networks = list(dict.fromkeys(networks))
    if not networks or any(n not in service.datasets for n in networks):
        raise ValueError(f"路网必须取自：{', '.join(service.datasets)}")
    algorithms = list(dict.fromkeys(params.get("algorithms", ALLOWED_ALGORITHMS)))
    if not algorithms or any(a not in ALLOWED_ALGORITHMS for a in algorithms):
        raise ValueError(f"算法必须取自：{', '.join(ALLOWED_ALGORITHMS)}")
    query_count = int(params.get("query_count", 100))
    rounds = int(params.get("rounds", 3))
    seed = int(params.get("seed", 20261102))
    if not (3 <= query_count <= 10000 and 1 <= rounds <= 20 and 0 <= seed <= 4294967295):
        raise ValueError("query_count范围3..10000，rounds范围1..20，seed为0..4294967295")
    prepare = bool(params.get("prepare_cache", False))
    force = bool(params.get("force_rebuild", False))
    if force and not prepare:
        raise ValueError("force_rebuild=True时必须设置prepare_cache=True")
    all_rows: list[dict] = []
    all_charts: list[dict] = []
    runs: list[dict] = []
    for network in networks:
        output = service.run(
            "frontend", network, algorithms, query_count, rounds, seed,
            rebuild_cache=force, prepare_if_missing=prepare,
        )
        result = _collect(output)
        all_rows.extend(result["summary_table"])
        all_charts.extend(result["chart_data"])
        runs.append({"network": network, "run": result["run"],
                     "validation": result["validation"], "files": result["files"]})
    return {"summary_table": all_rows, "chart_data": all_charts, "runs": runs}
