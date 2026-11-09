"""A2 路径规划性能测试：接口、缓存、测试执行、出图、自测界面全部集中在本文件。

HTTP 路由：
  GET  /api/config           算法、路网、默认参数
  GET  /api/cache/status     缓存可用性与原因
  POST /api/benchmarks       提交测试
  GET  /api/jobs/{job_id}    轮询进度
  GET  /api/results/summary  汇总
  GET  /api/results/table    五列表 JSON
  GET  /api/results/table.csv  CSV
  GET  /api/results/dashboard PNG
  GET  /api/results/queries  OD 明细

命令行：python api.py --prepare | --gui | --serve
"""


# ============ 配置与路径 ============
import json
from dataclasses import dataclass
from pathlib import Path


INTERFACE_DIR = Path(__file__).resolve().parent
CPP_DIR = INTERFACE_DIR / "cpp"
A2_DIR = INTERFACE_DIR.parent
PUBLIC_DIR = A2_DIR / "算法"
ALGORITHM_SOURCES = {
    "dijkstra": A2_DIR / "算法" / "dijkstra.cpp",
    "astar": A2_DIR / "算法" / "astar.cpp",
    "bidirectional_astar": A2_DIR / "算法" / "bidirectional_astar.cpp",
    "ch": A2_DIR / "算法" / "ch.cpp",
}
ALGORITHM_HEADERS = (PUBLIC_DIR / "algorithms.hpp", PUBLIC_DIR / "graph_types.hpp")
CONFIG_PATH = INTERFACE_DIR / "config.json"
ALLOWED_ALGORITHMS = ("dijkstra", "astar", "bidirectional_astar", "ch")


@dataclass(frozen=True)
class Dataset:
    id: str
    name: str
    level: str
    graphml: Path


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (INTERFACE_DIR / path).resolve()


def load_config() -> dict:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    payload["_runtime_root"] = resolve_path(payload["runtime_root"])
    payload["_data_root"] = resolve_path(payload["data_root"])
    payload["_outputs"] = {
        key: resolve_path(value) for key, value in payload["outputs"].items()
    }
    return payload


def load_datasets(config: dict) -> dict[str, Dataset]:
    data_root: Path = config["_data_root"]
    datasets: dict[str, Dataset] = {}
    configured: set[Path] = set()
    for item in config.get("datasets", []):
        graphml = (data_root / item["file"]).resolve()
        datasets[item["id"]] = Dataset(
            item["id"], item.get("name", item["id"]),
            item.get("level", "custom"), graphml,
        )
        configured.add(graphml)
    if config.get("auto_discover_graphml", True) and data_root.exists():
        for graphml in sorted(data_root.glob("*.graphml")):
            resolved = graphml.resolve()
            if resolved in configured:
                continue
            dataset_id = graphml.stem
            datasets[dataset_id] = Dataset(dataset_id, graphml.stem, "custom", resolved)
    return datasets


# ============ GraphML 转 RGRAPH ============
"""将项目GraphML转换为C++性能测试使用的紧凑二进制RGRAPH1。

只转换拓扑、WGS84坐标和非负边权。GraphML读取不计入算法预处理时间；
同一路网只需转换一次，后续测试直接复用.rgraph缓存。
"""

import argparse
import json
import math
import shutil
import struct
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


MAGIC = b"RGRAPH1\0"
HEADER = struct.Struct("<8sQQ")
NODE = struct.Struct("<dd")
EDGE = struct.Struct("<iidq")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def data_values(element: ET.Element, key_names: dict[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in element:
        if local_name(child.tag) != "data":
            continue
        key = child.attrib.get("key", "")
        name = key_names.get(key, key)
        values[name] = (child.text or "").strip()
    return values


def first_number(values: dict[str, str], names: tuple[str, ...]) -> float | None:
    for name in names:
        text = values.get(name)
        if text in (None, ""):
            continue
        try:
            return float(text)
        except ValueError:
            continue
    return None


def convert(input_path: Path, output_path: Path) -> dict[str, object]:
    key_names: dict[str, str] = {}
    node_index: dict[str, int] = {}
    coordinates: list[tuple[float, float]] = []
    edge_count = 0
    skipped_edges = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rgraph_edges_") as temporary:
        edge_path = Path(temporary) / "edges.bin"
        with edge_path.open("wb") as edge_output:
            for _, element in ET.iterparse(input_path, events=("end",)):
                name = local_name(element.tag)
                if name == "key":
                    key_id = element.attrib.get("id")
                    attribute_name = element.attrib.get("attr.name")
                    if key_id and attribute_name:
                        key_names[key_id] = attribute_name
                elif name == "node":
                    node_id = element.attrib.get("id")
                    if node_id is None:
                        raise ValueError("GraphML节点缺少id")
                    values = data_values(element, key_names)
                    lon = first_number(values, ("x", "lon", "longitude"))
                    lat = first_number(values, ("y", "lat", "latitude"))
                    if lon is None:
                        lon = first_number(element.attrib, ("x", "lon", "longitude"))
                    if lat is None:
                        lat = first_number(element.attrib, ("y", "lat", "latitude"))
                    if lon is None or lat is None or not math.isfinite(lon + lat):
                        raise ValueError(f"节点{node_id}缺少有效经纬度")
                    node_index[node_id] = len(coordinates)
                    coordinates.append((lon, lat))
                elif name == "edge":
                    source_id = element.attrib.get("source")
                    target_id = element.attrib.get("target")
                    if source_id not in node_index or target_id not in node_index:
                        raise ValueError("GraphML边出现在对应节点之前或引用了未知节点")
                    values = data_values(element, key_names)
                    weight = first_number(
                        values, ("length", "length_m", "weight", "cost")
                    )
                    if weight is None:
                        weight = first_number(
                            element.attrib, ("length", "length_m", "weight", "cost")
                        )
                    if weight is None or not math.isfinite(weight) or weight < 0:
                        skipped_edges += 1
                        element.clear()
                        continue
                    raw_edge_id = values.get("edge_id", element.attrib.get("id", ""))
                    try:
                        edge_id = int(raw_edge_id)
                    except (TypeError, ValueError):
                        edge_id = edge_count
                    edge_output.write(
                        EDGE.pack(
                            node_index[source_id], node_index[target_id], weight, edge_id
                        )
                    )
                    edge_count += 1
                # data子元素必须保留到父node/edge结束时才能读取；只在完整
                # 处理完较大的GraphML对象后释放内存。
                if name in {"key", "node", "edge"}:
                    element.clear()

        if not coordinates:
            raise ValueError("GraphML中没有读取到节点")
        if not edge_count:
            raise ValueError("GraphML中没有读取到有效边")

        with output_path.open("wb") as output:
            output.write(HEADER.pack(MAGIC, len(coordinates), edge_count))
            for lon, lat in coordinates:
                output.write(NODE.pack(lon, lat))
            with edge_path.open("rb") as edge_input:
                shutil.copyfileobj(edge_input, output, length=8 * 1024 * 1024)

    metadata = {
        "format": "RGRAPH1",
        "source": input_path.name,
        "output": output_path.name,
        "nodes": len(coordinates),
        "edges": edge_count,
        "skipped_invalid_edges": skipped_edges,
        "coordinate_order": "longitude,latitude",
        "weight_unit": "metre or source GraphML cost unit",
    }
    output_path.with_suffix(output_path.suffix + ".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metadata


# ============ 缓存管理 ============
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable



Notify = Callable[[str, int], None]
INDEX_FILES = {
    "astar": "astar.cache",
    "bidirectional_astar": "bidirectional_astar.cache",
    "ch": "ch.cache",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def algorithm_fingerprint() -> str:
    paths = [
        *ALGORITHM_HEADERS,
        *ALGORITHM_SOURCES.values(),
        CPP_DIR / "cache_io.hpp",
        CPP_DIR / "cache_io.cpp",
    ]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


class CacheManager:
    def __init__(self, config: dict, datasets: dict[str, Dataset]) -> None:
        self.config = config
        self.datasets = datasets
        self.runtime: Path = config["_runtime_root"]
        self.root = self.runtime / "cache"

    def dataset_dir(self, dataset_id: str) -> Path:
        return self.root / dataset_id

    def graph_path(self, dataset_id: str) -> Path:
        return self.dataset_dir(dataset_id) / "graph.rgraph"

    def manifest_path(self, dataset_id: str) -> Path:
        return self.dataset_dir(dataset_id) / "manifest.json"

    def _expected_files(self, dataset_id: str) -> list[Path]:
        root = self.dataset_dir(dataset_id)
        return [root / "graph.rgraph", *(root / name for name in INDEX_FILES.values())]

    def status(self, dataset_id: str, *, verify_hash: bool = True) -> dict:
        if dataset_id not in self.datasets:
            return {"dataset": dataset_id, "ready": False, "reason": "未知数据集"}
        dataset = self.datasets[dataset_id]
        if not dataset.graphml.exists():
            return {
                "dataset": dataset_id, "ready": False,
                "reason": f"未找到A1路网：{dataset.graphml}",
            }
        manifest_path = self.manifest_path(dataset_id)
        if not manifest_path.exists():
            return {"dataset": dataset_id, "ready": False, "reason": "尚未生成预处理缓存"}
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"dataset": dataset_id, "ready": False, "reason": "缓存清单损坏"}
        if manifest.get("cache_format_version") != self.config["cache_format_version"]:
            return {"dataset": dataset_id, "ready": False, "reason": "缓存格式已变更"}
        missing = [path.name for path in self._expected_files(dataset_id) if not path.exists()]
        if missing:
            return {
                "dataset": dataset_id, "ready": False,
                "reason": "缺少缓存文件：" + ", ".join(missing),
            }
        if verify_hash:
            if manifest.get("graph_sha256") != sha256_file(dataset.graphml):
                return {"dataset": dataset_id, "ready": False, "reason": "A1路网已变更"}
            if manifest.get("algorithm_sha256") != algorithm_fingerprint():
                return {"dataset": dataset_id, "ready": False, "reason": "算法代码已变更"}
        return {
            "dataset": dataset_id,
            "ready": True,
            "reason": "缓存可用",
            "created_at": manifest.get("created_at"),
            "preprocess_ms": manifest.get("preprocess_ms", {}),
            "graph_sha256": manifest.get("graph_sha256"),
            "algorithm_sha256": manifest.get("algorithm_sha256"),
        }

    @staticmethod
    def _run(command: list[str], notify: Notify | None = None) -> list[str]:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        assert process.stdout is not None
        lines: list[str] = []
        for line in process.stdout:
            lines.append(line)
            parts = line.strip().split()
            if len(parts) == 3 and parts[0] == "PROGRESS" and notify:
                try:
                    notify(parts[1], int(parts[2]))
                except ValueError:
                    pass
        if process.wait():
            raise RuntimeError("缓存构建失败：\n" + "".join(lines[-40:]))
        return lines

    @staticmethod
    def _atomic_copy(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)

    def prepare(
        self,
        executable: Path,
        dataset_id: str,
        *,
        force: bool = False,
        notify: Notify | None = None,
    ) -> dict:
        if dataset_id not in self.datasets:
            raise KeyError(f"未知数据集：{dataset_id}")
        dataset = self.datasets[dataset_id]
        if not dataset.graphml.exists():
            raise FileNotFoundError(f"未找到{dataset.name}：{dataset.graphml}")
        current = self.status(dataset_id)
        if current.get("ready") and not force:
            return current

        self.runtime.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="prepare_", dir=self.runtime) as temporary:
            staging = Path(temporary)
            graph = staging / "graph.rgraph"
            index_dir = staging / "index"
            output_dir = staging / "output"
            index_dir.mkdir()
            output_dir.mkdir()

            if notify:
                notify("converting_graphml", 0)
            convert(dataset.graphml, graph)
            if notify:
                notify("converting_graphml", 100)

            command = [
                str(executable),
                "--graph", str(graph),
                "--cache-dir", str(index_dir),
                "--output", str(output_dir),
                "--dataset", dataset_id,
                "--algorithms", ",".join(ALLOWED_ALGORITHMS),
                "--prepare-only", "--force-rebuild", "--ch-event-stride", "0",
            ]
            self._run(command, notify)

            with (output_dir / "preprocess_summary.csv").open(
                encoding="utf-8", newline=""
            ) as source:
                rows = list(csv.DictReader(source))
            preprocess_ms = {
                row["algorithm"]: float(row["preprocess_ms"]) for row in rows
            }
            manifest = {
                "cache_format_version": self.config["cache_format_version"],
                "dataset": dataset_id,
                "dataset_name": dataset.name,
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "graph_source": dataset.graphml.name,
                "graph_sha256": sha256_file(dataset.graphml),
                "algorithm_sha256": algorithm_fingerprint(),
                "preprocess_ms": preprocess_ms,
                "preprocess_note": "图表使用缓存首次构建时记录的预处理耗时",
                "files": {
                    "graph": "graph.rgraph",
                    **INDEX_FILES,
                },
            }

            destination = self.dataset_dir(dataset_id)
            destination.mkdir(parents=True, exist_ok=True)
            self._atomic_copy(graph, destination / "graph.rgraph")
            graph_meta = graph.with_suffix(graph.suffix + ".json")
            if graph_meta.exists():
                self._atomic_copy(graph_meta, destination / "graph.rgraph.json")
            for filename in INDEX_FILES.values():
                self._atomic_copy(index_dir / filename, destination / filename)
            manifest_temp = destination / ".manifest.json.tmp"
            manifest_temp.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(manifest_temp, destination / "manifest.json")

        result = self.status(dataset_id)
        if not result.get("ready"):
            raise RuntimeError(f"缓存生成后校验失败：{result.get('reason')}")
        return result


# ============ 图表 ============
import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager




COLORS = {
    "dijkstra": "#4C78A8",
    "astar": "#59A14F",
    "bidirectional_astar": "#F28E2B",
    "ch": "#E15759",
}
LABELS = {
    "dijkstra": "Dijkstra",
    "astar": "A*",
    "bidirectional_astar": "双向A*",
    "ch": "CH",
}


def configure_chinese_font() -> None:
    """优先使用自带字体；字体未随仓库提供时退回系统中文字体。"""
    bundled = INTERFACE_DIR / "assets" / "NotoSansSC-Regular.ttf"
    if bundled.exists():
        font_manager.fontManager.addfont(str(bundled))
        family = font_manager.FontProperties(fname=str(bundled)).get_name()
        plt.rcParams["font.sans-serif"] = [family]
    else:
        plt.rcParams["font.sans-serif"] = [
            "Microsoft YaHei", "SimHei", "Noto Sans CJK SC",
            "Source Han Sans SC", "DejaVu Sans",
        ]
    plt.rcParams["axes.unicode_minus"] = False


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def generate_dashboard(
    result_dir: Path,
    selected_algorithms: list[str],
    *,
    show: bool = False,
) -> tuple[Path, Path]:
    """生成一张2×2综合图和一张五列表。"""
    configure_chinese_font()
    summary = json.loads((result_dir / "summary.json").read_text(encoding="utf-8"))
    query_rows = [
        row for row in read_rows(result_dir / "query_raw.csv")
        if row["valid"] == "true" and row["algorithm"] in selected_algorithms
    ]
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in query_rows:
        grouped[row["algorithm"]].append(row)

    algorithms = [name for name in selected_algorithms if grouped.get(name)]
    if not algorithms:
        raise RuntimeError("没有可用于生成图表的有效查询")

    names = [LABELS.get(name, name) for name in algorithms]
    colors = [COLORS.get(name, "#64748B") for name in algorithms]
    stats = summary["algorithms"]
    query_count = int(summary["run"]["query_count"])

    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    axes[0, 0].boxplot(
        [[float(row["query_ms"]) for row in grouped[name]] for name in algorithms],
        showfliers=False,
        patch_artist=True,
        boxprops={"facecolor": "#DDE8F5", "edgecolor": "#4C78A8"},
        medianprops={"color": "#B91C1C", "linewidth": 1.5},
    )
    axes[0, 0].set_xticks(range(1, len(names) + 1), names)
    axes[0, 0].set_title("查询耗时分布")
    axes[0, 0].set_ylabel("毫秒")

    axes[0, 1].bar(
        names, [float(stats[name]["expanded_mean"]) for name in algorithms],
        color=colors,
    )
    axes[0, 1].set_title("平均扩展节点数")
    axes[0, 1].set_ylabel("节点")

    preprocessing = [float(stats[name]["preprocess_ms"]) for name in algorithms]
    axes[1, 0].bar(names, preprocessing, color=colors)
    axes[1, 0].set_title("预处理成本")
    axes[1, 0].set_ylabel("毫秒")

    query_cost = [float(stats[name]["query_mean_ms"]) * query_count for name in algorithms]
    axes[1, 1].bar(names, preprocessing, label="预处理", color="#4C78A8")
    axes[1, 1].bar(
        names, query_cost, bottom=preprocessing,
        label=f"{query_count}组查询", color="#E15759",
    )
    axes[1, 1].set_title(f"{query_count}组查询总成本")
    axes[1, 1].set_ylabel("毫秒")
    axes[1, 1].legend()

    for axis in axes.flat:
        axis.grid(axis="y", alpha=0.2)
        axis.tick_params(axis="x", rotation=0)
    fig.text(
        0.5, 0.006,
        "说明：预处理时间为当前缓存首次构建时记录的耗时",
        ha="center", fontsize=9, color="#475569",
    )
    fig.tight_layout(rect=(0, 0.025, 1, 1), pad=1.4)
    dashboard_path = result_dir / "performance_dashboard.png"
    fig.savefig(dashboard_path, dpi=180, bbox_inches="tight")
    if show:
        plt.show()
    else:
        plt.close(fig)

    table_path = result_dir / "algorithm_summary.csv"
    with table_path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.writer(target)
        writer.writerow([
            "算法", "平均查询耗时(ms)", "平均扩展节点",
            "预处理时间(ms)", "总成本(ms)",
        ])
        for name in algorithms:
            item = stats[name]
            preprocess_ms = float(item["preprocess_ms"])
            total_ms = preprocess_ms + float(item["query_mean_ms"]) * query_count
            writer.writerow([
                LABELS.get(name, name),
                f'{float(item["query_mean_ms"]):.6f}',
                f'{float(item["expanded_mean"]):.2f}',
                f"{preprocess_ms:.6f}",
                f"{total_ms:.6f}",
            ])
    return dashboard_path, table_path


# ============ 测试执行 ============
import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable





Notify = Callable[[str, int], None]


class BenchmarkService:
    def __init__(self) -> None:
        self.config = load_config()
        self.runtime: Path = self.config["_runtime_root"]
        self.outputs: dict[str, Path] = self.config["_outputs"]
        self.datasets: dict[str, Dataset] = load_datasets(self.config)
        self.cache = CacheManager(self.config, self.datasets)

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
            *ALGORITHM_SOURCES.values(),
            *ALGORITHM_HEADERS,
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
                f"-I{PUBLIC_DIR}",
                f"-I{CPP_DIR}",

                *(str(path) for path in ALGORITHM_SOURCES.values()),

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

        progress = re.compile(
            r"^PROGRESS\s+(\S+)\s+(\d+)"
        )

        lines: list[str] = []

        for line in process.stdout:
            lines.append(line)
            match = progress.match(line.strip())

            if match and notify:
                notify(
                    match.group(1),
                    int(match.group(2)),
                )

        if process.wait():
            raise RuntimeError(
                "性能测试失败：\n"
                + "".join(lines[-40:])
            )

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

        queries = self.query_path(
            dataset_id,
            query_count,
            seed,
        )

        queries.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.runtime.mkdir(
            parents=True,
            exist_ok=True,
        )

        with tempfile.TemporaryDirectory(
            prefix="run_",
            dir=self.runtime,
        ) as temporary:
            staging = Path(temporary)

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


# ============ HTTP 接口 ============
"""A2 性能测试接口：全部 9 个端点集中在本文件。

路由一览：
  GET  /api/config                 算法、路网、默认参数
  GET  /api/cache/status           缓存可用性与原因
  POST /api/benchmarks             提交测试，返回 job_id
  GET  /api/jobs/{job_id}          轮询状态与进度
  GET  /api/results/summary        汇总与校验信息
  GET  /api/results/table          五列汇总表 JSON
  GET  /api/results/table.csv      五列汇总表 CSV
  GET  /api/results/dashboard      2×2 中文图 PNG
  GET  /api/results/queries        分页 OD 明细

业务逻辑在 core/，本文件只做 HTTP 路由、参数校验和任务状态。
"""

import csv
import json
import threading
import uuid

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field





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


class BenchmarkRequest(BaseModel):
    dataset: str = "nanshan"
    algorithms: list[str] = Field(default_factory=lambda: list(ALLOWED_ALGORITHMS))
    query_count: int = Field(300, ge=3, le=10000)
    repeat: int = Field(3, ge=1, le=20)
    seed: int = Field(20261102, ge=0, le=4294967295)


def output_file(name: str):
    path = service.outputs["frontend"] / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="尚未生成前端测试结果")
    return path


def execute(job_id: str, request: BenchmarkRequest) -> None:
    def notify(stage: str, percent: int) -> None:
        with jobs_lock:
            jobs[job_id].update(status="running", stage=stage, progress=percent)

    try:
        with run_lock:
            result = service.run(
                "frontend", request.dataset, request.algorithms,
                request.query_count, request.repeat, request.seed,
                prepare_if_missing=False, notify=notify,
            )
        with jobs_lock:
            jobs[job_id].update(
                status="completed", stage="completed", progress=100,
                summary="/api/results/summary",
                table="/api/results/table",
                dashboard="/api/results/dashboard",
                result_file=str(result),
            )
    except Exception as error:
        with jobs_lock:
            jobs[job_id].update(
                status="failed", stage="failed", error=str(error),
            )


@app.get("/api/config")
def get_config() -> dict:
    return {
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
                "data_available": dataset.graphml.exists(),
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
        jobs[job_id] = {
            "job_id": job_id, "status": "queued", "stage": "queued",
            "progress": 0, "request": payload,
        }
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


# ============ 本地自测界面 ============
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path





LABELS = {
    "dijkstra": "Dijkstra", "astar": "A*",
    "bidirectional_astar": "双向A*", "ch": "CH",
}


def open_file(path: Path) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def run_gui() -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    class TestWindow(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title("A2算法性能自测")
            self.resizable(False, False)
            self.service = BenchmarkService()
            self.events: queue.Queue[tuple] = queue.Queue()
            defaults = self.service.config["defaults"]

            panel = ttk.Frame(self, padding=18)
            panel.grid(sticky="nsew")
            ttk.Label(
                panel, text="路径规划算法性能对比",
                font=("Microsoft YaHei UI", 15, "bold"),
            ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 14))

            ttk.Label(panel, text="数据集").grid(row=1, column=0, sticky="w")
            self.dataset_ids = list(self.service.datasets)
            names = [self.service.datasets[item].name for item in self.dataset_ids]
            self.dataset = ttk.Combobox(panel, values=names, state="readonly", width=28)
            default_id = defaults.get("dataset", self.dataset_ids[0])
            self.dataset.current(self.dataset_ids.index(default_id) if default_id in self.dataset_ids else 0)
            self.dataset.grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)

            ttk.Label(panel, text="算法（可多选）").grid(row=2, column=0, sticky="nw", pady=6)
            selected = set(defaults.get("algorithms", ALLOWED_ALGORITHMS))
            self.algorithm_vars: dict[str, tk.BooleanVar] = {}
            for index, name in enumerate(ALLOWED_ALGORITHMS):
                variable = tk.BooleanVar(value=name in selected)
                self.algorithm_vars[name] = variable
                ttk.Checkbutton(panel, text=LABELS[name], variable=variable).grid(
                    row=2 + index // 2, column=1 + index % 2,
                    sticky="w", padx=(0, 18), pady=4,
                )

            ttk.Label(panel, text="查询数").grid(row=4, column=0, sticky="w", pady=4)
            self.query_count = tk.StringVar(value=str(defaults.get("query_count", 300)))
            ttk.Entry(panel, textvariable=self.query_count, width=12).grid(row=4, column=1, sticky="w")
            ttk.Label(panel, text="重复次数").grid(row=4, column=2, sticky="w")
            self.repeat = tk.StringVar(value=str(defaults.get("repeat", 3)))
            ttk.Entry(panel, textvariable=self.repeat, width=12).grid(row=4, column=3, sticky="w")

            ttk.Label(panel, text="随机种子").grid(row=5, column=0, sticky="w", pady=4)
            self.seed = tk.StringVar(value=str(defaults.get("seed", 20261102)))
            ttk.Entry(panel, textvariable=self.seed, width=16).grid(row=5, column=1, sticky="w")
            self.rebuild_cache = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                panel, text="强制重新生成预处理缓存",
                variable=self.rebuild_cache,
            ).grid(row=5, column=2, columnspan=2, sticky="w")

            self.cache_text = tk.StringVar()
            ttk.Label(panel, textvariable=self.cache_text, foreground="#475569").grid(
                row=6, column=0, columnspan=4, sticky="w", pady=(8, 0)
            )
            self.status = tk.StringVar(value="等待开始")
            ttk.Label(panel, textvariable=self.status).grid(
                row=7, column=0, columnspan=4, sticky="w", pady=(12, 4)
            )
            self.progress = ttk.Progressbar(panel, length=500, maximum=100)
            self.progress.grid(row=8, column=0, columnspan=4, sticky="ew")
            self.start_button = ttk.Button(panel, text="开始测试", command=self.start)
            self.start_button.grid(row=9, column=0, columnspan=4, pady=(14, 0))
            self.dataset.bind("<<ComboboxSelected>>", lambda _event: self.update_cache_status())
            self.update_cache_status()
            self.after(100, self.poll_events)

        def selected_dataset(self) -> str:
            return self.dataset_ids[self.dataset.current()]

        def update_cache_status(self) -> None:
            status = self.service.cache_status(self.selected_dataset(), verify_hash=False)
            if status.get("ready"):
                self.cache_text.set(f"缓存已就绪：{status.get('created_at', '')}")
            else:
                self.cache_text.set(f"缓存未就绪：{status.get('reason')}（开始时将自动生成）")

        def start(self) -> None:
            algorithms = [name for name, var in self.algorithm_vars.items() if var.get()]
            if not algorithms:
                messagebox.showwarning("参数错误", "请至少选择一种算法")
                return
            try:
                query_count = int(self.query_count.get())
                repeat = int(self.repeat.get())
                seed = int(self.seed.get())
            except ValueError:
                messagebox.showwarning("参数错误", "查询数、重复次数和随机种子必须是整数")
                return
            self.start_button.configure(state="disabled")
            self.progress["value"] = 0
            self.status.set("正在准备…")
            threading.Thread(
                target=self.worker,
                args=(
                    self.selected_dataset(), algorithms, query_count, repeat, seed,
                    self.rebuild_cache.get(),
                ),
                daemon=True,
            ).start()

        def worker(
            self, dataset: str, algorithms: list[str],
            query_count: int, repeat: int, seed: int, rebuild_cache: bool,
        ) -> None:
            try:
                result = self.service.run(
                    "self_test", dataset, algorithms, query_count, repeat, seed,
                    rebuild_cache=rebuild_cache,
                    prepare_if_missing=True,
                    notify=lambda stage, percent: self.events.put(("progress", stage, percent)),
                )
                self.events.put(("done", result.parent))
            except Exception as error:
                self.events.put(("error", str(error)))

        def poll_events(self) -> None:
            labels = {
                "loading_graph": "读取路网", "converting_graphml": "转换路网缓存",
                "generating_queries": "生成固定OD", "running_queries": "执行查询",
                "preprocessing_dijkstra": "准备Dijkstra",
                "preprocessing_astar": "预处理A*",
                "preprocessing_bidirectional_astar": "预处理双向A*",
                "preprocessing_ch": "预处理CH", "completed": "生成图表",
            }
            try:
                while True:
                    event = self.events.get_nowait()
                    if event[0] == "progress":
                        self.status.set(f"{labels.get(event[1], event[1])}：{event[2]}%")
                        self.progress["value"] = event[2]
                    elif event[0] == "done":
                        output = Path(event[1])
                        self.start_button.configure(state="normal")
                        self.progress["value"] = 100
                        self.status.set(f"完成：{output}")
                        self.update_cache_status()
                        open_file(output / "performance_dashboard.png")
                        messagebox.showinfo("测试完成", f"图表和表格已生成到：\n{output}")
                    elif event[0] == "error":
                        self.start_button.configure(state="normal")
                        self.status.set("测试失败")
                        messagebox.showerror("测试失败", event[1])
            except queue.Empty:
                pass
            self.after(100, self.poll_events)

    TestWindow().mainloop()


def prepare_all(force: bool = False) -> None:
    """提前为所有已配置数据集生成预处理缓存。"""
    for dataset_id in service.datasets:
        dataset = service.datasets[dataset_id]
        if not dataset.graphml.exists():
            print(f"跳过 {dataset.name}：未找到 {dataset.graphml}")
            continue
        print(f"\n正在准备：{dataset.name}")
        status = service.prepare_cache(
            dataset_id,
            force=force,
            notify=lambda stage, percent: print(f"  {stage}: {percent}%"),
        )
        print(f"已完成：{status['created_at']}")
        for name, value in status["preprocess_ms"].items():
            print(f"  {name}: {value:.6f} ms")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="A2 路径规划性能测试")
    parser.add_argument("--prepare", action="store_true", help="生成预处理缓存")
    parser.add_argument("--force", action="store_true", help="强制重建缓存")
    parser.add_argument("--gui", action="store_true", help="启动本地自测界面")
    parser.add_argument("--serve", action="store_true", help="启动 HTTP 接口")
    args = parser.parse_args()
    if args.prepare:
        prepare_all(args.force)
    elif args.gui:
        run_gui()
    else:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()

