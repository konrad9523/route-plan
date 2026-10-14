"""T2：Dijkstra 与 A* 查询耗时对比，含启发系数一次性计算成本（出图 + 终端结果）。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "02_正确性证据" / "测试代码"))
from _common.test_support import *


def run_t2(dijkstra, astar, graph, positions, scale, scale_ms, haversine,
           output_dir, rng, pair_count, repeats):
    pairs = sample_reachable_pairs(graph, list(graph), dijkstra, rng, pair_count)
    if not pairs:
        raise RuntimeError("无法抽到可达的起终点对")

    rows = []
    for index, (source, target) in enumerate(pairs):
        d = dijkstra(graph, source, target)
        a = astar(graph, positions, source, target, heuristic_scale=scale)
        d_times, a_times = [], []
        for _ in range(repeats):
            t0 = time.perf_counter(); dijkstra(graph, source, target)
            d_times.append((time.perf_counter() - t0) * 1000)
            t0 = time.perf_counter(); astar(graph, positions, source, target, heuristic_scale=scale)
            a_times.append((time.perf_counter() - t0) * 1000)
        rows.append({
            "查询编号": index, "起点": source, "终点": target,
            "直线距离m": haversine(positions, source, target),
            "Dijkstra代价": d[2], "Astar代价": a[2],
            "Dijkstra耗时中位数ms": statistics.median(d_times),
            "Astar耗时中位数ms": statistics.median(a_times),
            "代价一致": math.isclose(d[2], a[2], rel_tol=1e-9, abs_tol=1e-6),
        })

    d_ms = [r["Dijkstra耗时中位数ms"] for r in rows]
    a_ms = [r["Astar耗时中位数ms"] for r in rows]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    axes[0].bar(["Dijkstra", "A*"], [statistics.mean(d_ms), statistics.mean(a_ms)],
                color=["#4c78a8", "#f58518"])
    axes[0].set_ylabel("平均查询耗时（毫秒）")
    axes[0].set_title("T2：平均查询耗时")

    axes[1].plot(range(len(rows)), d_ms, label="Dijkstra", lw=1)
    axes[1].plot(range(len(rows)), a_ms, label="A*", lw=1)
    axes[1].set_xlabel("查询编号")
    axes[1].set_ylabel("耗时（毫秒）")
    axes[1].set_title("T2：逐查询耗时")
    axes[1].legend()
    for axis in axes:
        axis.grid(alpha=.2)
    fig.tight_layout()
    fig.savefig(output_dir / "T2_查询耗时.png", dpi=160)
    plt.close(fig)

    query_total_d, query_total_a = sum(d_ms), sum(a_ms)
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    ax.bar(["Dijkstra", "A*"], [query_total_d, query_total_a],
           color=["#4c78a8", "#f58518"])
    ax.bar(["Dijkstra", "A*"], [0, scale_ms],
           bottom=[query_total_d, query_total_a], color="#e45756",
           label="启发系数一次性计算")
    ax.set_ylabel(f"{len(rows)} 次查询总耗时（毫秒）")
    ax.set_title("T2：含一次性预处理的总成本")
    ax.legend()
    ax.grid(axis="y", alpha=.2)
    fig.tight_layout()
    fig.savefig(output_dir / "T2_总成本.png", dpi=160)
    plt.close(fig)

    mismatches = sum(not r["代价一致"] for r in rows)
    print(f"T2 查询耗时对比：查询数 {len(rows)}，每查询重复 {repeats} 次，"
          f"Dijkstra 平均耗时 {statistics.mean(d_ms):.2f} ms，"
          f"A* 平均耗时 {statistics.mean(a_ms):.2f} ms，"
          f"启发系数预处理 {scale_ms:.2f} ms，"
          f"代价不一致数 {mismatches}")
    print(f"图已保存：{output_dir / 'T2_查询耗时.png'} 和 {output_dir / 'T2_总成本.png'}")


def main():
    parser = add_common_arguments(
        argparse.ArgumentParser(description="T2 查询耗时对比"),
        Path(__file__).resolve().parents[1] / "results")
    parser.add_argument("--pairs", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    args = resolve_args(args, Path(__file__).resolve().parents[1] / "results")
    graph, positions, _, dijkstra, astar, haversine, scale, scale_ms = load_runtime(
        args.graphml, args.algorithm_dir)
    run_t2(dijkstra, astar, graph, positions, scale, scale_ms, haversine,
           args.output_dir, random.Random(args.seed), args.pairs, args.repeats)


if __name__ == "__main__":
    main()