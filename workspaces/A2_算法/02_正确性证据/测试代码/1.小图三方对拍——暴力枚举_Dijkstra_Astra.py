"""T1：小图三方对拍——暴力枚举 vs Dijkstra vs A*。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common.test_support import *


def random_small_graph(rng, node_count):
    nodes = list(range(node_count))
    graph = {n: [] for n in nodes}
    for i in range(1, node_count):
        j = rng.randint(0, i - 1)
        w = round(rng.uniform(1.0, 10.0), 2)
        graph[j].append((i, w, f"e{j}_{i}"))
    extra = rng.randint(0, node_count)
    for _ in range(extra):
        u, v = rng.sample(nodes, 2)
        w = round(rng.uniform(1.0, 10.0), 2)
        if all(nxt != v for nxt, _, _ in graph[u]):
            graph[u].append((v, w, f"e{u}_{v}"))
    return graph


def brute_force_shortest(graph, start, goal):
    best = [math.inf, None]

    def dfs(node, seen, cost, path):
        if node == goal:
            if cost < best[0]:
                best[0], best[1] = cost, list(path)
            return
        for nxt, w, _ in graph[node]:
            if nxt not in seen:
                seen.add(nxt)
                path.append(nxt)
                dfs(nxt, seen, cost + w, path)
                path.pop()
                seen.remove(nxt)

    dfs(start, {start}, 0.0, [start])
    return best[0], best[1]


def _small_graph_scale(graph, positions, haversine):
    """为小图计算安全比例 alpha。"""
    scale = math.inf
    for u, outgoing in graph.items():
        for v, w, _ in outgoing:
            d = haversine(positions, u, v)
            if d > 0:
                scale = min(scale, w / d)
    return 0.0 if math.isinf(scale) else max(0.0, scale * (1 - 1e-12))


def t1_three_way(dijkstra, astar, haversine, graph_count, pairs_per_graph, output_dir, rng):
    rows = []
    for gid in range(graph_count):
        n = rng.randint(5, 10)
        graph = random_small_graph(rng, n)
        nodes = list(graph)

        # 为小图生成坐标（用于 A* 的 Haversine）
        positions = {i: (rng.uniform(-0.01, 0.01), rng.uniform(-0.01, 0.01))
                     for i in nodes}
        scale = _small_graph_scale(graph, positions, haversine)

        pair_count = 0
        attempts = 0
        while pair_count < pairs_per_graph and attempts < pairs_per_graph * 10:
            attempts += 1
            start, goal = rng.sample(nodes, 2)
            brute_cost, _ = brute_force_shortest(graph, start, goal)
            if not math.isfinite(brute_cost):
                continue

            d = dijkstra(graph, start, goal)
            a = astar(graph, positions, start, goal, heuristic_scale=scale)

            d_ok = math.isclose(d[2], brute_cost, rel_tol=1e-9)
            a_ok = math.isclose(a[2], brute_cost, rel_tol=1e-9)

            rows.append({
                "图编号": gid, "节点数": n, "起点": start, "终点": goal,
                "暴力枚举代价": brute_cost,
                "Dijkstra代价": d[2], "Astar代价": a[2],
                "Dijkstra一致": d_ok, "Astar一致": a_ok,
            })
            pair_count += 1
        print(f"T1：图 {gid+1}/{graph_count}", flush=True)

    save_csv(output_dir / "T1_小图三方对拍.csv", rows)

    fig, ax = plt.subplots(figsize=(7, 7))
    x = [r["暴力枚举代价"] for r in rows]
    y_d = [r["Dijkstra代价"] for r in rows]
    y_a = [r["Astar代价"] for r in rows]
    ax.scatter(x, y_d, s=18, alpha=.6, label="Dijkstra", color="#2563eb")
    ax.scatter(x, y_a, s=18, alpha=.6, label="A*", color="#f59e0b", marker="^")
    lo, hi = min(min(x), min(y_d), min(y_a)), max(max(x), max(y_d), max(y_a))
    ax.plot([lo, hi], [lo, hi], "r--", lw=1, label="y=x 参考线")
    ax.set_xlabel("暴力枚举最短代价")
    ax.set_ylabel("算法代价")
    ax.set_title(f"T1：{graph_count} 张随机小图，{len(rows)} 对起终点三方对拍")
    ax.legend()
    ax.grid(alpha=.2)
    fig.tight_layout()
    fig.savefig(output_dir / "T1_小图三方对拍.png", dpi=160)
    plt.close(fig)

    d_ok = sum(r["Dijkstra一致"] for r in rows)
    a_ok = sum(r["Astar一致"] for r in rows)
    return {"T1": {
        "图数": graph_count, "对拍总数": len(rows),
        "Dijkstra通过": d_ok, "Astar通过": a_ok,
        "是否通过": d_ok == len(rows) and a_ok == len(rows),
    }}


def main():
    parser = add_common_arguments(
        argparse.ArgumentParser(description="T1 小图三方对拍"),
        Path(__file__).resolve().parents[1] / "results")
    parser.add_argument("--graphs", type=int, default=30)
    parser.add_argument("--pairs-per-graph", type=int, default=5)
    args = parser.parse_args()

    args = resolve_args(args, Path(__file__).resolve().parents[1] / "results")

    dijkstra, astar, _, haversine = load_algorithms(args.algorithm_dir)
    result = t1_three_way(dijkstra, astar, haversine,
                          args.graphs, args.pairs_per_graph,
                          args.output_dir, random.Random(args.seed))
    print_result("T1", result, args.output_dir)


if __name__ == "__main__":
    main()