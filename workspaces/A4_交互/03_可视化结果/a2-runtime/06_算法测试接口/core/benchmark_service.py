from __future__ import annotations

import csv
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from .cache_manager import CacheManager
from .config import (
    ALGORITHM_DIR,
    ALLOWED_ALGORITHMS,
    CPP_DIR,
    Dataset,
    load_config,
    load_datasets,
)
from .report import generate_dashboard


Notify = Callable[[str, int], None]


@contextmanager
def accessible_staging_directory(prefix: str):
    """Create a Windows-writable staging directory for the C++ runner."""

    staging = Path(tempfile.gettempdir()) / f"{prefix}{uuid.uuid4().hex}"
    staging.mkdir(parents=False, exist_ok=False)
    try:
        yield staging
    finally:
        # A failed cleanup must not turn a completed benchmark into a failed job.
        shutil.rmtree(staging, ignore_errors=True)


class BenchmarkService:
    def __init__(self) -> None:
        self.config = load_config()
        self.runtime: Path = self.config["_runtime_root"]
        self.outputs: dict[str, Path] = {
            target: self._writable_output(path, target)
            for target, path in self.config["_outputs"].items()
        }
        self.datasets: dict[str, Dataset] = load_datasets(self.config)
        self.cache = CacheManager(self.config, self.datasets)

    @staticmethod
    def _writable_output(configured: Path, target: str) -> Path:
        """Use the configured output, with a runtime-only fallback if needed."""

        try:
            configured.mkdir(parents=True, exist_ok=True)
            probe = configured / f".write-probe-{uuid.uuid4().hex}"
            probe.write_bytes(b"")
            probe.unlink()
            return configured
        except OSError:
            fallback = Path(tempfile.gettempdir()) / "g4-a2-output" / target
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback

    def executable(self) -> Path:
        candidates = [
            self.runtime / "build" / "Release" / "route_benchmark.exe",
            self.runtime / "build" / "route_benchmark.exe",
            self.runtime / "build" / "route_benchmark",
        ]

        for path in candidates:
            if path.exists():
                return path

        return candidates[0] if os.name == "nt" else candidates[-1]

    @staticmethod
    def build_inputs() -> list[Path]:
        return [
            *(
                ALGORITHM_DIR / name
                for name in (
                    "dijkstra.cpp",
                    "astar.cpp",
                    "bidirectional_astar.cpp",
                    "ch.cpp",
                    "algorithms.hpp",
                    "graph_types.hpp",
                )
            ),
            *(
                CPP_DIR / name
                for name in (
                    "benchmark_main.cpp",
                    "cache_io.cpp",
                    "cache_io.hpp",
                    "rgraph_io.cpp",
                    "rgraph_io.hpp",
                    "query_io.cpp",
                    "query_io.hpp",
                    "CMakeLists.txt",
                )
            ),
        ]

    def ensure_executable(self, rebuild: bool = False) -> Path:
        """检查并生成最新的C++算法测试程序。"""

        executable = self.executable()
        sources = self.build_inputs()

        current = (
            executable.exists()
            and all(path.exists() for path in sources)
            and max(path.stat().st_mtime for path in sources)
            <= executable.stat().st_mtime
        )

        if current and not rebuild:
            return executable

        build_dir = self.runtime / "build"
        build_dir.mkdir(parents=True, exist_ok=True)

        def run_build(
            command: list[str],
            stage: str,
            cwd: Path | None = None,
        ) -> None:
            result = subprocess.run(
                command,
                cwd=str(cwd) if cwd else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            if result.returncode != 0:
                detail = (
                    result.stdout.strip()
                    or "编译器没有输出详细信息"
                )

                raise RuntimeError(
                    f"{stage}失败：\n\n{detail}"
                )

        if shutil.which("cmake"):
            run_build(
                [
                    "cmake",
                    "-S",
                    str(CPP_DIR),
                    "-B",
                    str(build_dir),
                    "-DCMAKE_BUILD_TYPE=Release",
                ],
                "CMake配置",
            )

            run_build(
                [
                    "cmake",
                    "--build",
                    str(build_dir),
                    "--config",
                    "Release",
                ],
                "CMake编译",
            )

        else:
            compiler = (
                shutil.which("g++")
                or shutil.which("clang++")
            )

            if not compiler:
                raise RuntimeError(
                    "未找到C++编译环境。\n\n"
                    "请安装以下任意一种环境：\n"
                    "1. CMake + Visual Studio C++ Build Tools\n"
                    "2. MinGW-w64 g++\n"
                    "3. MSYS2 UCRT64 g++"
                )

            output_name = (
                "route_benchmark.exe"
                if os.name == "nt"
                else "route_benchmark"
            )

            command = [
                compiler,
                "-std=c++17",
                "-O3",
                f"-I{ALGORITHM_DIR}",
                f"-I{CPP_DIR}",

                str(ALGORITHM_DIR / "dijkstra.cpp"),
                str(ALGORITHM_DIR / "astar.cpp"),
                str(ALGORITHM_DIR / "bidirectional_astar.cpp"),
                str(ALGORITHM_DIR / "ch.cpp"),

                str(CPP_DIR / "benchmark_main.cpp"),
                str(CPP_DIR / "cache_io.cpp"),
                str(CPP_DIR / "rgraph_io.cpp"),
                str(CPP_DIR / "query_io.cpp"),

                "-o",
                output_name,
            ]

            if os.name == "nt":
                command.append("-municode")

            run_build(
                command,
                "C++测试程序编译",
                cwd=build_dir,
            )

        executable = self.executable()

        if not executable.exists():
            candidates = [
                self.runtime
                / "build"
                / "Release"
                / "route_benchmark.exe",

                self.runtime
                / "build"
                / "route_benchmark.exe",

                self.runtime
                / "build"
                / "route_benchmark",
            ]

            checked = "\n".join(
                str(path) for path in candidates
            )

            raise FileNotFoundError(
                "编译已经结束，但没有找到route_benchmark。\n\n"
                "检查过以下位置：\n"
                + checked
            )

        return executable

    def cache_status(
        self,
        dataset_id: str,
        *,
        verify_hash: bool = True,
    ) -> dict:
        return self.cache.status(
            dataset_id,
            verify_hash=verify_hash,
        )

    def prepare_cache(
        self,
        dataset_id: str,
        *,
        force: bool = False,
        notify: Notify | None = None,
    ) -> dict:
        executable = self.ensure_executable()

        return self.cache.prepare(
            executable,
            dataset_id,
            force=force,
            notify=notify,
        )

    def query_path(
        self,
        dataset_id: str,
        query_count: int,
        seed: int,
    ) -> Path:
        return (
            self.runtime
            / "queries"
            / f"{dataset_id}_Q{query_count}_S{seed}.csv"
        )

    @staticmethod
    def _validation_count(query_csv: Path) -> int:
        with query_csv.open(
            encoding="utf-8",
            newline="",
        ) as source:
            return sum(
                1
                for row in csv.DictReader(source)
                if row["valid"] != "true"
            )

    @staticmethod
    def _publish(
        staging: Path,
        output: Path,
    ) -> None:
        output.mkdir(
            parents=True,
            exist_ok=True,
        )

        for name in (
            "summary.json",
            "query_raw.csv",
            "algorithm_summary.csv",
            "performance_dashboard.png",
        ):
            source = staging / name
            temporary = output / f".{name}.tmp"

            shutil.copy2(
                source,
                temporary,
            )

            os.replace(
                temporary,
                output / name,
            )

    @staticmethod
    def _run_process(
        command: list[str],
        notify: Notify | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        assert process.stdout is not None

        progress = re.compile(r"^PROGRESS\s+(\S+)\s+(\d+)")
        output: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            try:
                for line in process.stdout:
                    output.put(line)
            finally:
                output.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        lines: list[str] = []
        started = time.monotonic()

        while True:
            try:
                line = output.get(timeout=0.25)
            except queue.Empty:
                if process.poll() is not None and not reader.is_alive():
                    break
                if time.monotonic() - started > timeout_seconds:
                    process.kill()
                    reader.join(timeout=1)
                    raise RuntimeError(
                        f"性能测试超过{timeout_seconds // 60}分钟，已终止测试程序。"
                        "请检查C++测试程序和运行库。"
                    )
                continue

            if line is None:
                if process.poll() is not None:
                    break
                continue

            lines.append(line)
            match = progress.match(line.strip())
            if match and notify:
                notify(match.group(1), int(match.group(2)))

        return_code = process.wait()
        if return_code:
            detail = "".join(lines[-40:]).strip()
            if not detail:
                detail = (
                    f"测试程序退出码：{return_code}。"
                    "如果退出码为 -1073741515，请安装或补齐 C++ 运行库。"
                )
            raise RuntimeError("性能测试失败：\n" + detail)

    def run(
        self,
        target: str,
        dataset_id: str,
        algorithms: Iterable[str],
        query_count: int = 300,
        repeat: int = 3,
        seed: int = 20261102,
        *,
        rebuild_cache: bool = False,
        prepare_if_missing: bool = False,
        notify: Notify | None = None,
    ) -> Path:
        if target not in self.outputs:
            raise ValueError(
                "target必须是frontend或self_test"
            )

        if dataset_id not in self.datasets:
            raise KeyError(
                f"未知数据集：{dataset_id}"
            )

        selected = list(
            dict.fromkeys(algorithms)
        )

        if (
            not selected
            or any(
                name not in ALLOWED_ALGORITHMS
                for name in selected
            )
        ):
            raise ValueError(
                "至少选择一种有效算法"
            )

        if not 3 <= query_count <= 10000:
            raise ValueError(
                "查询数必须在3到10000之间"
            )

        if not 1 <= repeat <= 20:
            raise ValueError(
                "重复次数必须在1到20之间"
            )

        status = self.cache_status(dataset_id)

        if (
            rebuild_cache
            or (
                prepare_if_missing
                and not status.get("ready")
            )
        ):
            status = self.prepare_cache(
                dataset_id,
                force=rebuild_cache,
                notify=notify,
            )

        if not status.get("ready"):
            raise RuntimeError(
                f"数据集{dataset_id}的预处理缓存未就绪："
                f"{status.get('reason')}"
            )

        executable = self.ensure_executable()

        configured_queries = self.query_path(
            dataset_id,
            query_count,
            seed,
        )

        self.runtime.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Staging is disposable; keep it in the OS temp directory instead of
        # the runtime tree, which may contain stale folders with restrictive
        # ACLs left by an earlier elevated process.  Use Path.mkdir rather
        # than tempfile.TemporaryDirectory because this Windows environment
        # creates the latter with an unusable ACL.
        with accessible_staging_directory("g4_a2_run_") as staging:
            # Reuse prepared queries when available. New query counts are
            # generated in the writable staging directory so the C++ runner
            # never needs to create files in a read-only E: runtime tree.
            queries = (
                configured_queries
                if configured_queries.is_file()
                else staging / configured_queries.name
            )

            command = [
                str(executable),
                "--graph",
                str(self.cache.graph_path(dataset_id)),
                "--cache-dir",
                str(self.cache.dataset_dir(dataset_id)),
                "--queries",
                str(queries),
                "--output",
                str(staging),
                "--dataset",
                dataset_id,
                "--algorithms",
                ",".join(selected),
                "--generate-queries",
                str(query_count),
                "--repeat",
                str(repeat),
                "--seed",
                str(seed),
                "--ch-event-stride",
                "0",
            ]

            self._run_process(
                command,
                notify,
            )

            invalid = self._validation_count(
                staging / "query_raw.csv"
            )

            if invalid:
                raise RuntimeError(
                    f"后台Dijkstra对拍失败："
                    f"{invalid}条结果不一致"
                )

            summary_path = (
                staging / "summary.json"
            )

            summary = json.loads(
                summary_path.read_text(
                    encoding="utf-8"
                )
            )

            executed = list(selected)

            if "dijkstra" not in executed:
                executed.insert(
                    0,
                    "dijkstra",
                )

            summary["run"] = {
                "run_id": f"{dataset_id}/Q{query_count}/R{repeat}/S{seed}",
                "target": target,
                "query_count": query_count,
                "repeat": repeat,
                "seed": seed,
                "selected_algorithms": selected,
                "executed_algorithms": executed,
                "reference_algorithm": "dijkstra",
                "created_at": datetime.now()
                .astimezone()
                .isoformat(timespec="seconds"),
            }

            summary["cache"] = {
                "ready": True,
                "created_at": status.get(
                    "created_at"
                ),
                "preprocess_time_source":
                    "cached_first_build",
                "note":
                    "预处理时间来自当前缓存首次构建时的记录",
            }

            summary["validation"] = {
                "passed": True,
                "reference": "dijkstra",
                "mismatch_count": 0,
            }

            summary_path.write_text(
                json.dumps(
                    summary,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            generate_dashboard(
                staging,
                selected,
                show=False,
            )

            self._publish(
                staging,
                self.outputs[target],
            )

        return (
            self.outputs[target]
            / "summary.json"
        )
