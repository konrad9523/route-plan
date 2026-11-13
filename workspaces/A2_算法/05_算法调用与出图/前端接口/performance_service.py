"""A2 公开 Python 接口：采用 A3 的轻量函数式入口方式。

公开：run_performance_comparison(params)、read_performance_result(summary_file)。
不提供 HTTP 路由，浏览器由前端同学的 Python 后端转发。
本次仓库整理不需要运行任何算法。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from performance_comparison import (
    run_performance_comparison as _run,
    read_performance_result as _read,
)


def run_performance_comparison(params: dict[str, Any]) -> dict[str, Any]:
    """统一运行入口，具体实现由 performance_comparison.py 调用现有 A2 核心。"""
    return _run(params)


def read_performance_result(summary_file: str | Path) -> dict[str, Any]:
    """仅读取已有 JSON/CSV 性能成果，不触发 C++ 编译或算法测试。"""
    return _read(summary_file)
