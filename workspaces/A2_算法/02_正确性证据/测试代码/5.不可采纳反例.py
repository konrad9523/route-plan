"""T5：故意高估启发值，验证 A* 返回次优路径。

构造一张小图：B 的地理位置离 G 很远，但 B→G 的边权很便宜。
把启发值乘 1.5 后，A* 会高估 B 的剩余代价，从而先走 A，返回次优路径。
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common.test_support import *


def t5_inadmissible_counterexample(dijkstra, astar, output_dir):
    graph = {
        "S": [("A", 1.0, "sa"), ("B", 2.0, "sb")],
        "A": [("G", 100.0, "ag")],
        "B": [("G", 2.0, "bg")],
        "G": [],
    }
    # B 在 (0, 10)，G 在 (1, 0)，地理上很远
    positions = {"S": (0.0, 0.0), "A": (1.0, 0.0),
                 "B": (0.0, 10.0), "G": (1.0, 0.0)}

    optimal = dijkstra(graph, "S", "G")
    bad = astar(graph, positions, "S", "G", heuristic_scale=1.5)
    gap = bad[2] - optimal[2]
    passed = math.isfinite(gap) and gap > 0

    save_csv(output_dir / "T5_不可采纳反例.csv", [{
        "起点": "S", "终点": "G",
        "Dijkstra代价": optimal[2],
        "Astar高估启发代价": bad[2],
        "次优差距": gap,
        "Dijkstra路径": "->".join(optimal[0]),
        "Astar路径": "->".join(bad[0]),
        "是否检测到反例": passed,
    }])

    fig, ax = plt.subplots(figsize=(7, 5))
    for u, outgoing in graph.items():
        for v, w, eid in outgoing:
            ax.annotate("", xy=positions[v], xytext=positions[u],
                        arrowprops={"arrowstyle": "->", "color": "#94a3b8", "lw": 1.3})
            mx = (positions[u][0] + positions[v][0]) / 2
            my = (positions[u][1] + positions[v][1]) / 2
            ax.text(mx, my, f"{eid}: {w:g}", fontsize=8)

    for path, color, label in [
        (optimal[0], "#16a34a", f"Dijkstra 最优={optimal[2]:g}"),
        (bad[0], "#dc2626", f"A*（不安全启发）={bad[2]:g}"),
    ]:
        ax.plot([positions[n][0] for n in path],
                [positions[n][1] for n in path],
                color=color, lw=3, marker="o", label=label)

    for n, (x, y) in positions.items():
        ax.text(x, y, n, fontsize=11, ha="right", va="bottom")

    ax.set_title("T5：故意高估启发值，A* 返回次优路径")
    ax.set_xlabel("类经度坐标")
    ax.set_ylabel("类纬度坐标")
    ax.legend()
    ax.grid(alpha=.2)
    fig.tight_layout()
    fig.savefig(output_dir / "T5_不可采纳反例.png", dpi=160)
    plt.close(fig)

    return {"T5": {
        "最优代价": optimal[2],
        "不安全A*代价": bad[2],
        "次优差距": gap,
        "最优路径": "->".join(optimal[0]),
        "A*路径": "->".join(bad[0]),
        "是否检测到反例": passed,
    }}


def main():
    parser = add_common_arguments(
        argparse.ArgumentParser(description="T5 不可采纳启发函数反例"),
        Path(__file__).resolve().parents[1] / "results")
    args = parser.parse_args()

    args = resolve_args(args, Path(__file__).resolve().parents[1] / "results")  # ← 加这一行

    dijkstra, astar, _, _ = load_algorithms(args.algorithm_dir)
    result = t5_inadmissible_counterexample(dijkstra, astar, args.output_dir)
    print_result("T5", result, args.output_dir)


if __name__ == "__main__":
    main()