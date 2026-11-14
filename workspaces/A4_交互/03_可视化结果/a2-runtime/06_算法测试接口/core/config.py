from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


INTERFACE_DIR = Path(__file__).resolve().parents[1]
CPP_DIR = INTERFACE_DIR / "cpp"
A2_DIR = INTERFACE_DIR.parent
ALGORITHM_DIR = A2_DIR / "01_实现清单"
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
