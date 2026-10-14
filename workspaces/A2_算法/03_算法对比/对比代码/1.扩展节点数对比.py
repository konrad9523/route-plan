"""T1：Dijkstra 与 A* 扩展节点数对比（出图 + 终端结果）。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "02_正确性证据" / "测试代码"))
from _common.test_support import *


def run_t1(dijkstra, astar, graph, positions, scale, output_dir, rng, pair_count):
    pairs = sample_reachable_pairs(graph, list(graph), dijkstra, rng, pair_count)
    if not pairs:
        raise RuntimeError("无法抽到可达的起终点对")

    rows = []
    for index, (source, target) in enumerate(pairs):
        d = dijkstra(graph, source, target)
        a = astar(graph, positions, source, target, heuristic_scale=scale)
        rows.append({
            "查询编号": index, "起点": source, "终点": target,
            "Dijkstra代价": d[2], "Astar代价": a[2],
            "Dijkstra扩展节点数": d[3], "Astar扩展节点数": a[3],
            "代价一致": math.isclose(d[2], a[2], rel_tol=1e-9, abs_tol=1e-6),
        })

    d_counts = [r["Dijkstra扩展节点数"] for r in rows]
    a_counts = [r["Astar扩展节点数"] for r in rows]

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    axes[0].bar(["Dijkstra", "A*"],
                [statistics.mean(d_counts), statistics.mean(a_counts)],
                color=["#4c78a8", "#f58518"])
    axes[0].set_ylabel("平均扩展节点数")
    axes[0].set_title("T1：平均扩展节点数")

    axes[1].boxplot([d_counts, a_counts], tick_labels=["Dijkstra", "A*"], showfliers=True)
    axes[1].set_ylabel("扩展节点数")
    axes[1].set_title("T1：扩展节点数分布")

    for row in rows:
        axes[2].plot([0, 1],
                     [row["Dijkstra扩展节点数"], row["Astar扩展节点数"]],
                     color="#4c78a8", alpha=.22, lw=.7)
    axes[2].set_xticks([0, 1], ["Dijkstra", "A*"])
    axes[2].set_ylabel("扩展节点数")
    axes[2].set_title("T1：逐查询配对对比")

    for axis in axes:
        axis.grid(axis="y", alpha=.2)
    fig.tight_layout()
    fig.savefig(output_dir / "T1_扩展节点数.png", dpi=160)
    plt.close(fig)

    mismatches = sum(not r["代价一致"] for r in rows)
    print(f"T1 扩展节点数对比：查询数 {len(rows)}，"
          f"Dijkstra 平均扩展 {statistics.mean(d_counts):.2f}，"
          f"A* 平均扩展 {statistics.mean(a_counts):.2f}，"
          f"代价不一致数 {mismatches}")
    print(f"图已保存：{output_dir / 'T1_扩展节点数.png'}")


def main():
    parser = add_common_arguments(
        argparse.ArgumentParser(description="T1 扩展节点数对比"),
        Path(__file__).resolve().parents[1] / "results")
    parser.add_argument("--pairs", type=int, default=100)
    args = parser.parse_args()
    args = resolve_args(args, Path(__file__).resolve().parents[1] / "results")
    graph, positions, _, dijkstra, astar, _, scale, _ = load_runtime(
        args.graphml, args.algorithm_dir)
    run_t1(dijkstra, astar, graph, positions, scale,
           args.output_dir, random.Random(args.seed), args.pairs)


if __name__ == "__main__":
    main()