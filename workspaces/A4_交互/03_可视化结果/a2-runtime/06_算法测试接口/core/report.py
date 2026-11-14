from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

from .config import INTERFACE_DIR


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
    bundled = INTERFACE_DIR / "assets" / "NotoSansSC-Regular.ttf"
    if not bundled.exists():
        raise RuntimeError(f"缺少中文图表字体：{bundled}")
    font_manager.fontManager.addfont(str(bundled))
    family = font_manager.FontProperties(fname=str(bundled)).get_name()
    plt.rcParams["font.sans-serif"] = [family]
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
