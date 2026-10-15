"""T4：搜索空间可视化，静态图和 A* 搜索动画（出图 + 终端结果）。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "02_正确性证据" / "测试代码"))
from _common.test_support import *


def run_t4(graph, positions, geometries, dijkstra, astar,
           scale, output_dir, rng):
    pairs = sample_reachable_pairs(graph, graph.keys(), dijkstra, rng, 1)
    if not pairs:
        raise RuntimeError("T4：找不到可达的起终点对")
    s, g = pairs[0]

    tracked_d = TrackingGraph(graph)
    rd = dijkstra(tracked_d, s, g)
    tracked_a = TrackingGraph(graph)
    ra = astar(tracked_a, positions, s, g, heuristic_scale=scale)

    for order, result, tracked in ((tracked_d.expansion_order, rd, tracked_d),
                                   (tracked_a.expansion_order, ra, tracked_a)):
        if result[0] and result[0][-1] not in order:
            order.append(result[0][-1])

    exp_d = set(tracked_d.expansion_order)
    exp_a = set(tracked_a.expansion_order)
    frontier_d = {v for u in exp_d for v, _, _ in graph[u]} - exp_d
    frontier_a = {v for u in exp_a for v, _, _ in graph[u]} - exp_a

    fig, axs = plt.subplots(1, 2, figsize=(13, 6))
    draw_road_map(axs[0], graph, positions, geometries,
                  expanded=exp_d, frontier=frontier_d, path_nodes=rd[0],
                  title=f"Dijkstra：扩展 {len(exp_d):,} 个节点", zoom_nodes=[s, g])
    draw_road_map(axs[1], graph, positions, geometries,
                  expanded=exp_a, frontier=frontier_a, path_nodes=ra[0],
                  title=f"A*：扩展 {len(exp_a):,} 个节点", zoom_nodes=[s, g])
    fig.suptitle(f"T4：搜索空间对比（{s} → {g}），橙色为邻接边界近似")
    fig.tight_layout()
    fig.savefig(output_dir / "T4_搜索空间.png", dpi=170)
    plt.close(fig)

    order = tracked_a.expansion_order
    frames = min(30, max(2, len(order)))
    fig, ax = plt.subplots(figsize=(7, 6))
    draw_road_map(ax, graph, positions, geometries, path_nodes=[],
                  title=f"A* 扩展过程（0/{len(order):,}）（{s} → {g}）",
                  zoom_nodes=set(order) | {s, g})
    frontier_artist = ax.scatter([], [], s=8, c="#f59e0b", alpha=.75,
                                 label="邻接边界近似", zorder=3)
    expanded_artist = ax.scatter([], [], s=8, c="#60a5fa", alpha=.60,
                                 label="已扩展", zorder=4)

    def update(frame):
        upto = max(1, math.ceil(len(order) * (frame + 1) / frames))
        expanded = set(order[:upto])
        frontier = {v for u in expanded for v, _, _ in graph[u]} - expanded
        exp_xy = [positions[n] for n in expanded if n in positions]
        front_xy = [positions[n] for n in frontier if n in positions]
        expanded_artist.set_offsets(exp_xy if exp_xy else [[float("nan"), float("nan")]])
        frontier_artist.set_offsets(front_xy if front_xy else [[float("nan"), float("nan")]])
        ax.set_title(f"A* 扩展 {min(upto, len(order)):,}/{len(order):,}（{s} → {g}）")
        return frontier_artist, expanded_artist

    ani = FuncAnimation(fig, update, frames=frames, interval=150,
                        blit=False, repeat=False)
    ani.save(output_dir / "T4_Astar搜索动画.gif", writer=PillowWriter(fps=6))
    plt.close(fig)

    print(f"T4 搜索空间可视化：起点 {s}，终点 {g}，"
          f"Dijkstra 扩展节点数 {len(exp_d):,}，A* 扩展节点数 {len(exp_a):,}")
    print(f"静态图：{output_dir / 'T4_搜索空间.png'}")
    print(f"动画：{output_dir / 'T4_Astar搜索动画.gif'}")


def main():
    parser = add_common_arguments(
        argparse.ArgumentParser(description="T4 搜索空间可视化"),
        Path(__file__).resolve().parents[1] / "results")
    args = parser.parse_args()
    args = resolve_args(args, Path(__file__).resolve().parents[1] / "results")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    graph, positions, geometries, dijkstra, astar, _, scale, _ = load_runtime(
        args.graphml, args.algorithm_dir)
    run_t4(graph, positions, geometries, dijkstra, astar,
           scale, args.output_dir, random.Random(args.seed))


if __name__ == "__main__":
    main()