"""T3：Haversine 启发值可采纳性全图扫描。

对每个抽样终点，用反向 Dijkstra 算出所有节点到该终点的真实最短距离 h*，
再检查 Haversine 启发值 h 是否满足 h <= h*。任何违反都是可采纳性被破坏。
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common.test_support import *


def t3_admissibility(graph, positions, haversine, scale,
                     output_dir, rng, goal_count):
    nodes = list(graph)
    targets = rng.sample(nodes, min(goal_count, len(nodes)))

    matrix, violations = [], []
    for i, target in enumerate(targets, 1):
        true_dist = reverse_dijkstra(graph, target)
        row_values = []
        for node in nodes:
            h = haversine(positions, node, target) * scale
            actual = true_dist.get(node, math.inf)
            if math.isfinite(actual):
                gap = actual - h
                row_values.append(gap)
                if gap < -1e-6:
                    violations.append({
                        "终点": target, "节点": node,
                        "启发值h": h, "真实h*": actual, "h*-h": gap,
                    })
            else:
                row_values.append(float("nan"))
        matrix.append(row_values)
        print(f"T3：终点 {i}/{len(targets)} 完成", flush=True)

    save_csv(output_dir / "T3_可采纳性违反.csv", violations,
             ["终点", "节点", "启发值h", "真实h*", "h*-h"])

    # 热力图：横轴节点编号，纵轴抽样终点，颜色为 h* - h
    fig, ax = plt.subplots(figsize=(14, 5))
    im = ax.imshow(matrix, aspect="auto", interpolation="nearest",
                   cmap="RdYlGn", vmin=0)
    ax.set_xlabel("节点编号（按图顺序）")
    ax.set_ylabel("抽样终点编号")
    ax.set_title("T3：真实剩余代价 h* 减去 Haversine 启发值 h（负值为违反）")
    fig.colorbar(im, ax=ax, label="h* - h（米）")
    fig.tight_layout()
    fig.savefig(output_dir / "T3_可采纳性热力图.png", dpi=170)
    plt.close(fig)

    return {"T3": {
        "抽样终点数": len(targets),
        "检查节点数": len(targets) * len(nodes),
        "违反数": len(violations),
        "是否通过": not violations,
    }}


def main():
    parser = add_common_arguments(
        argparse.ArgumentParser(description="T3 Haversine 可采纳性扫描"),
        Path(__file__).resolve().parents[1] / "results")
    parser.add_argument("--targets", type=int, default=20, help="抽样终点数量")
    args = parser.parse_args()
    args = resolve_args(args, Path(__file__).resolve().parents[1] / "results")

    graph, positions, _, _, _, haversine, scale, _ = load_runtime(
        args.graphml, args.algorithm_dir)
    result = t3_admissibility(graph, positions, haversine, scale,
                              args.output_dir, random.Random(args.seed),
                              args.targets)
    print_result("T3", result, args.output_dir)


if __name__ == "__main__":
    main()