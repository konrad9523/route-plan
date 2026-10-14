"""T5：大规模路网压力测试，按起终点直线距离观察性能。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "02_正确性证据" / "测试代码"))
from _common.test_support import *


def run_t5(graph, positions, nodes, dijkstra, astar, scale, haversine,
           output_dir, rng, pair_count):
    candidate_count = max(pair_count * 3, pair_count)
    pairs = sample_reachable_pairs(graph, nodes, dijkstra, rng,
                                   candidate_count, max_attempts=candidate_count * 35)
    if not pairs:
        raise RuntimeError("T5：找不到可达的起终点对")

    pairs.sort(key=lambda pair: haversine(positions, pair[0], pair[1]))
    if len(pairs) > pair_count:
        pairs = [pairs[round(i * (len(pairs) - 1) / (pair_count - 1))]
                 for i in range(pair_count)] if pair_count > 1 else [pairs[len(pairs) // 2]]

    rows = []
    for i, (s, g) in enumerate(pairs):
        t0 = time.perf_counter(); d = dijkstra(graph, s, g)
        dms = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter(); a = astar(graph, positions, s, g, heuristic_scale=scale)
        ams = (time.perf_counter() - t0) * 1000
        rows.append({
            "查询编号": i, "起点": s, "终点": g,
            "直线距离m": haversine(positions, s, g),
            "Dijkstra代价": d[2], "Astar代价": a[2],
            "Dijkstra扩展节点数": d[3], "Astar扩展节点数": a[3],
            "Dijkstra耗时ms": dms, "Astar耗时ms": ams,
        })
    save_csv(output_dir / "T5_压力测试.csv", rows)

    distances = [r["直线距离m"] for r in rows]
    sorted_d = sorted(distances)
    cuts = [sorted_d[min(len(sorted_d) - 1, int(len(sorted_d) * q))] for q in (1/3, 2/3)]
    bins = ["短途" if d <= cuts[0] else "中途" if d <= cuts[1] else "长途" for d in distances]

    grouped = defaultdict(list)
    for r, b in zip(rows, bins):
        grouped[(b, "Dijkstra")].append(r["Dijkstra耗时ms"])
        grouped[(b, "A*")].append(r["Astar耗时ms"])

    labels = ["短途", "中途", "长途"]
    means = [[statistics.mean(grouped[(b, a)]) if grouped[(b, a)] else float("nan")
              for b in labels] for a in ("Dijkstra", "A*")]

    fig, axs = plt.subplots(1, 2, figsize=(12, 4.7))
    for alg, color, key in (("Dijkstra", "#4c78a8", "Dijkstra耗时ms"),
                            ("A*", "#f58518", "Astar耗时ms")):
        by = defaultdict(list)
        for r in rows:
            by[bins[r["查询编号"]]].append(r)
        xs, ys = [], []
        for b in labels:
            subset = by[b]
            if subset:
                xs.append(statistics.mean(r["直线距离m"] for r in subset) / 1000)
                ys.append(statistics.mean(r[key] for r in subset))
        axs[0].plot(xs, ys, marker="o", label=alg, color=color)
    axs[0].set_xlabel("起终点直线距离（公里）")
    axs[0].set_ylabel("平均查询耗时（毫秒）")
    axs[0].set_title("T5：耗时随距离变化")
    axs[0].legend()

    im = axs[1].imshow(means, aspect="auto", cmap="YlOrRd")
    axs[1].set_xticks(range(3), labels)
    axs[1].set_yticks(range(2), ["Dijkstra", "A*"])
    axs[1].set_title("T5：平均耗时热力图")
    for y, row in enumerate(means):
        for x, val in enumerate(row):
            axs[1].text(x, y, f"{val:.1f}" if math.isfinite(val) else "n/a",
                        ha="center", va="center")
    fig.colorbar(im, ax=axs[1], label="毫秒")
    fig.tight_layout()
    fig.savefig(output_dir / "T5_压力测试.png", dpi=160)
    plt.close(fig)

    node_count = len(nodes)
    edge_count = sum(map(len, graph.values()))
    return {"T5": {
        "查询数": len(rows),
        "图来源": "A1 处理后的华盛顿路网",
        "节点数": node_count,
        "边数": edge_count,
        "说明": f"本数据集为 A1 处理后的华盛顿路网，节点数 {node_count:,}，"
                f"边数 {edge_count:,}，满足大规模路网压力测试要求。",
    }}


def main():
    parser = add_common_arguments(
        argparse.ArgumentParser(description="T5 大规模路网压力测试"),
        Path(__file__).resolve().parents[1] / "results")
    parser.add_argument("--pairs", type=int, default=100)
    args = parser.parse_args()
    args = resolve_args(args, Path(__file__).resolve().parents[1] / "results")
    graph, positions, _, dijkstra, astar, haversine, scale, _ = load_runtime(
        args.graphml, args.algorithm_dir)
    result = run_t5(graph, positions, list(graph), dijkstra, astar, scale,
                    haversine, args.output_dir, random.Random(args.seed), args.pairs)
    print_result("T5", result, args.output_dir)


if __name__ == "__main__":
    main()