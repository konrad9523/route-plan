"""路网注册表：集中管理可选路网及其结果目录名。

路网文件放在 workspaces/A1_数据/01_路网清单/processed/。
新增路网时，在 NETWORKS 里加一条即可。
"""
from pathlib import Path

A2_ROOT = Path(__file__).resolve().parents[3]          # .../workspaces/A2_算法
WORKSPACES_ROOT = A2_ROOT.parent                        # .../workspaces
DATA_DIR = WORKSPACES_ROOT / "A1_数据" / "01_路网清单" / "processed"

NETWORKS = {
    "washington": {
        "graphml": DATA_DIR / "dc_driving_optimized.graphml",
        "label": "华盛顿",
    },
    "shenzhen": {
        "graphml": DATA_DIR / "shenzhen_driving_optimized.graphml",
        "label": "深圳",
    },
}

DEFAULT_NETWORK = "shenzhen"


def get_network(name: str):
    """按名称取路网信息，校验文件存在。"""
    if name not in NETWORKS:
        raise ValueError(f"未知路网：{name}，可选：{list(NETWORKS)}")
    info = NETWORKS[name]
    if not info["graphml"].exists():
        raise FileNotFoundError(f"路网文件不存在：{info['graphml']}")
    return info


def results_dir(base: Path, network_name: str) -> Path:
    """结果目录按路网分文件夹，例如 results/深圳/。"""
    label = NETWORKS[network_name]["label"]
    return base / label