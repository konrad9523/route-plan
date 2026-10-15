"""T3：Haversine 启发值与真实剩余代价的紧度对比（出图 + 终端结果）。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "02_正确性证据" / "测试代码"))
from _common.test_support import *


def run_t3(graph, nodes, positions, haversine, scale,
           output_dir, rng, node_sample_count, target_count):
    targets = rng.sample(list(nodes), min(target_count, len(nodes)))
    rows = []
    for target in targets:
        true_dist = reverse_dijkstra(graph, target)
        candidates = [n for n in nodes if n in true_dist and true_dist[n] > 1e-9]
        rng.shuffle(candidates)
        for node in candidates[:node_sample_count]:
            h = haversine(positions, node, target) * scale
            hstar = true_dist[node]
            rows.append({
                "节点": node, "终点": target,
                "启发值h": h, "真实h*": hstar,
                "紧度比值": h / hstar,
            })

    fig, axs = plt.subplots(1, 2, figsize=(12, 4.8))
    if rows:
        x = [r["真实h*"] for r in rows]
        y = [r["启发值h"] for r in rows]
        axs[0].scatter(x, y, s=8, alpha=.35)
        m = max(max(x), max(y))
        axs[0].plot([0, m], [0, m], "r--", lw=1)
        axs[0].set_xlabel("真实剩余代价 h*（米）")
        axs[0].set_ylabel("Haversine 启发值 h（米）")
        axs[0].set_title("T3：启发值与真实值对比")
        axs[1].boxplot([r["紧度比值"] for r in rows], showfliers=True)
    axs[1].set_ylabel("h / h*")
    axs[1].set_title("T3：紧度比值分布")
    for ax in axs:
        ax.grid(alpha=.2)
    fig.tight_layout()
    fig.savefig(output_dir / "T3_紧度.png", dpi=160)
    plt.close(fig)

    if rows:
        mean_ratio = statistics.mean(r["紧度比值"] for r in rows)
        max_ratio = max(r["紧度比值"] for r in rows)
    else:
        mean_ratio = max_ratio = None

    print(f"T3 启发函数紧度：样本数 {len(rows)}，终点数 {len(targets)}，"
          f"平均紧度比值 {mean_ratio:.4f}，最大紧度比值 {max_ratio:.4f}")
    print(f"图已保存：{output_dir / 'T3_紧度.png'}")


def main():
    parser = add_common_arguments(
        argparse.ArgumentParser(description="T3 启发函数紧度"),
        Path(__file__).resolve().parents[1] / "results")
    parser.add_argument("--nodes-per-target", type=int, default=100)
    parser.add_argument("--targets", type=int, default=20)
    args = parser.parse_args()
    args = resolve_args(args, Path(__file__).resolve().parents[1] / "results")
    graph, positions, _, _, _, haversine, scale, _ = load_runtime(
        args.graphml, args.algorithm_dir)
    run_t3(graph, list(graph), positions, haversine, scale,
           args.output_dir, random.Random(args.seed),
           args.nodes_per_target, args.targets)


if __name__ == "__main__":
    main()