"""T2：真实路网随机起终点，Dijkstra vs A* 对拍。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common.test_support import *


def t2_real_network(dijkstra, astar, graph, positions, scale,
                    output_dir, rng, count_pairs):
    nodes = list(graph)
    rows, mismatches, finite_pairs = [], [], []
    for i in range(count_pairs):
        start, goal = rng.choice(nodes), rng.choice(nodes)
        d = dijkstra(graph, start, goal)
        a = astar(graph, positions, start, goal, heuristic_scale=scale)

        both_inf = math.isinf(d[2]) and math.isinf(a[2])
        same = both_inf or math.isclose(d[2], a[2], rel_tol=1e-9, abs_tol=1e-6)

        row = {
            "查询编号": i, "起点": start, "终点": goal,
            "Dijkstra代价": d[2], "Astar代价": a[2],
            "代价差": (a[2] - d[2]) if math.isfinite(a[2]) and math.isfinite(d[2]) else "",
            "Dijkstra扩展节点数": d[3], "Astar扩展节点数": a[3],
            "是否一致": same,
        }
        rows.append(row)
        if not same:
            mismatches.append(row)
        if math.isfinite(d[2]) and math.isfinite(a[2]):
            finite_pairs.append((d[2], a[2]))

        if (i + 1) % 100 == 0:
            print(f"T2：{i+1}/{count_pairs} 对", flush=True)

    save_csv(output_dir / "T2_真实路网对拍.csv", rows)
    save_csv(output_dir / "T2_不一致用例.csv", mismatches,
             ["查询编号", "起点", "终点", "Dijkstra代价", "Astar代价",
              "代价差", "Dijkstra扩展节点数", "Astar扩展节点数", "是否一致"])

    agreement = sum(bool(r["是否一致"]) for r in rows) / len(rows) if rows else 1.0

    fig, ax = plt.subplots(figsize=(6.5, 6))
    if finite_pairs:
        x, y = zip(*finite_pairs)
        ax.scatter(x, y, s=10, alpha=.5, label="起终点对")
        lo, hi = min(min(x), min(y)), max(max(x), max(y))
        ax.plot([lo, hi], [lo, hi], "r--", lw=1, label="y=x 参考线")
    ax.set_xlabel("Dijkstra 路径代价（米）")
    ax.set_ylabel("A* 路径代价（米）")
    ax.set_title(f"T2：真实路网一致率={agreement:.2%}（{len(rows)} 对起终点）")
    ax.legend()
    ax.grid(alpha=.2)
    fig.tight_layout()
    fig.savefig(output_dir / "T2_真实路网散点图.png", dpi=160)
    plt.close(fig)

    return {"T2": {
        "对拍总数": len(rows),
        "可达对数": len(finite_pairs),
        "一致率": agreement,
        "不一致数": len(mismatches),
        "是否通过": not mismatches,
    }}


def main():
    parser = add_common_arguments(
        argparse.ArgumentParser(description="T2 真实路网 Dijkstra/A* 对拍"),
        Path(__file__).resolve().parents[1] / "results")
    parser.add_argument("--pairs", type=int, default=1000, help="随机起终点对数")
    args = parser.parse_args()
    args = resolve_args(args, Path(__file__).resolve().parents[1] / "results")

    graph, positions, _, dijkstra, astar, _, scale, _ = load_runtime(
        args.graphml, args.algorithm_dir)
    result = t2_real_network(dijkstra, astar, graph, positions, scale,
                             args.output_dir, random.Random(args.seed), args.pairs)
    print_result("T2", result, args.output_dir)


if __name__ == "__main__":
    main()