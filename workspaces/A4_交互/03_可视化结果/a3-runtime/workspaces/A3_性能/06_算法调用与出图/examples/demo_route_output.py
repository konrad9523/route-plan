"""直接演示统一输出；也可读取本项目生成的可信武汉 graph_v2.pkl。"""

import argparse
import json
import pickle
import sys
from pathlib import Path
from time import perf_counter

CODE_DIR = Path(__file__).resolve().parents[1]
A3_DIR = CODE_DIR.parent
sys.path[:0] = [
    str(A3_DIR / "01_Dijkstra" / "python"),
    str(A3_DIR / "02_双向Dijkstra" / "python"),
    str(A3_DIR / "03_Astar" / "python"),
    str(A3_DIR / "04_双向Astar" / "python"),
    str(CODE_DIR / "前端接口"),
]

from astar_variants import (build_csr, estimate_heuristic_scale, prevalidate_graph,
                            run_astar)
from dijkstra_variants import dijkstra_l4
from route_output import build_route_output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--algorithm", choices=("dijkstra", "astar"), default="dijkstra")
    parser.add_argument("--graph-pickle", type=Path,
                        help="仅限可信的项目自产 pickle；加载不可信 pickle 可执行恶意代码")
    parser.add_argument("--source", type=int, default=0)
    parser.add_argument("--target", type=int, default=2)
    parser.add_argument("--assumed-speed-kmh", type=float, default=None,
                        help="显式为缺失时间的边假设速度，单位 km/h；默认不假设")
    parser.add_argument("--output", type=Path, help="另存 JSON，不覆盖已有文件")
    args = parser.parse_args()
    if args.graph_pickle:
        with args.graph_pickle.open("rb") as stream:
            data = pickle.load(stream)
        n = int(data["n_nodes"])
        graph = {u: [(int(data["indices"][i]), float(data["weights"][i]),
                      int(data["edge_ids"][i]))
                     for i in range(data["indptr"][u], data["indptr"][u + 1])]
                 for u in range(n)}
        positions = {u: (data["lon"][u], data["lat"][u]) for u in range(n)}
        records = data["edges"]
    else:
        graph = {0: [(1, 100.0, 0), (2, 500.0, 2)], 1: [(2, 200.0, 1)], 2: [], 3: []}
        positions = {u: (114.0 + u * .0001, 30.0) for u in graph}
        records = [(0, 1, 100.0, "residential", "路段甲", 36.0),
                   (1, 2, 200.0, "primary", "路段乙", 72.0),
                   (0, 2, 500.0, "primary", "直达路段", 90.0)]
    prevalidate_graph(graph, positions)
    csr = build_csr(graph)
    csr_dict = dict(n_nodes=len(graph), indptr=csr[0], indices=csr[1],
                    weights=csr[2], edge_ids=csr[3])
    scale = estimate_heuristic_scale(graph, positions) if args.algorithm == "astar" else None
    start = perf_counter()
    if args.algorithm == "dijkstra":
        result = dijkstra_l4(csr_dict, args.source, args.target)
    else:
        result = run_astar("L4", graph, positions, args.source, args.target,
                           csr=csr, heuristic_scale=scale)
    planning_ms = (perf_counter() - start) * 1000
    output = build_route_output(result, records, args.source, args.target,
                                algorithm=f"{args.algorithm}-L4", planning_ms=planning_ms,
                                assumed_speed_kmh=args.assumed_speed_kmh)
    text = json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    print(text, end="")


if __name__ == "__main__":
    main()
