"""T4：Haversine 启发值一致性全边扫描。

对真实路网上的每条有向边 (u, v)，检查
    h(u) <= w(u, v) + h(v)
是否成立。任何正残差都是一致性违反。
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common.test_support import *


def t4_consistency(graph, positions, haversine, scale,
                   output_dir, rng, target_count=3):
    nodes = list(graph)
    targets = rng.sample(nodes, min(target_count, len(nodes)))

    all_rows, all_residuals = [], []
    for ti, target in enumerate(targets, 1):
        h = {node: haversine(positions, node, target) * scale for node in graph}
        for u, outgoing in graph.items():
            for v, w, eid in outgoing:
                residual = h[u] - w - h[v]
                all_residuals.append(residual)
                if residual > 1e-6:
                    all_rows.append({
                        "终点": target, "边编号": eid,
                        "起点": u, "终点节点": v,
                        "h(u)": h[u], "边权w": w, "h(v)": h[v],
                        "残差": residual,
                    })
        print(f"T4：终点 {ti}/{len(targets)} 完成", flush=True)

    save_csv(output_dir / "T4_一致性违反.csv", all_rows,
             ["终点", "边编号", "起点", "终点节点", "h(u)", "边权w", "h(v)", "残差"])

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(all_residuals, bins=80, color="#4c78a8", alpha=.85, label="一致性残差")
    ax.axvline(0, color="red", ls="--", label="零线（大于 0 为违反）")
    ax.set_xlabel("h(u) - w(u,v) - h(v)（米）")
    ax.set_ylabel("边数量")
    ax.set_title(f"T4：{len(all_residuals):,} 条有向边的一致性残差")
    ax.legend()
    ax.grid(alpha=.15)
    fig.tight_layout()
    fig.savefig(output_dir / "T4_一致性直方图.png", dpi=160)
    plt.close(fig)

    return {"T4": {
        "抽样终点数": len(targets),
        "检查边数": len(all_residuals),
        "违反数": len(all_rows),
        "最大残差": max(all_residuals, default=0.0),
        "是否通过": not all_rows,
    }}


def main():
    parser = add_common_arguments(
        argparse.ArgumentParser(description="T4 Haversine 一致性扫描"),
        Path(__file__).resolve().parents[1] / "results")
    parser.add_argument("--targets", type=int, default=20,
                        help="抽样终点数量（每个终点都扫全图）")
    args = parser.parse_args()
    args = resolve_args(args, Path(__file__).resolve().parents[1] / "results")

    graph, positions, _, _, _, haversine, scale, _ = load_runtime(
        args.graphml, args.algorithm_dir)
    result = t4_consistency(graph, positions, haversine, scale,
                            args.output_dir, random.Random(args.seed),
                            args.targets)
    print_result("T4", result, args.output_dir)


if __name__ == "__main__":
    main()