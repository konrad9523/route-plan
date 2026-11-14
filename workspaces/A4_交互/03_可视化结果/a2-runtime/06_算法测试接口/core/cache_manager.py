from __future__ import annotations

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

from .config import ALGORITHM_DIR, ALLOWED_ALGORITHMS, CPP_DIR, Dataset, INTERFACE_DIR


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
        ALGORITHM_DIR / "graph_types.hpp",
        ALGORITHM_DIR / "algorithms.hpp",
        ALGORITHM_DIR / "dijkstra.cpp",
        ALGORITHM_DIR / "astar.cpp",
        ALGORITHM_DIR / "bidirectional_astar.cpp",
        ALGORITHM_DIR / "ch.cpp",
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
        cache_only = os.environ.get("G4_A2_CACHE_ONLY") == "1"
        if not dataset.graphml.exists() and not cache_only:
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
        if verify_hash and not cache_only:
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
            subprocess.run(
                [
                    sys.executable,
                    str(INTERFACE_DIR / "core" / "graphml_to_rgraph.py"),
                    str(dataset.graphml), str(graph),
                ],
                check=True,
            )
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

