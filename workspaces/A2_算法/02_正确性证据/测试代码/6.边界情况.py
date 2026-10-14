"""T6：边界输入和异常处理。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common.test_support import *


def t6_boundaries(dijkstra, astar, output_dir):
    results = []

    def case(name, expected, fn, expected_error=False):
        try:
            actual = fn()
            passed = bool(expected(actual))
            results.append({
                "用例": name, "预期": "按约定返回",
                "实际": repr(actual), "是否通过": passed, "异常": "",
            })
        except Exception as exc:
            passed = expected_error and isinstance(exc, ValueError)
            results.append({
                "用例": name,
                "预期": "抛 ValueError" if expected_error else "按约定返回",
                "实际": "异常",
                "是否通过": passed,
                "异常": f"{type(exc).__name__}: {exc}",
            })

    # 1. 起点等于终点
    case("起点等于终点",
         lambda r: r[0] == [1] and r[1] == [] and r[2] == 0,
         lambda: dijkstra({1: []}, 1, 1))

    # 2. 不可达
    case("不可达",
         lambda r: r[0] == [] and r[1] == [] and math.isinf(r[2]),
         lambda: dijkstra({1: [], 2: []}, 1, 2))

    # 3. 单节点图（A*）
    case("单节点图",
         lambda r: r[0] == [1] and r[2] == 0,
         lambda: astar({1: []}, {1: (0.0, 0.0)}, 1, 1, heuristic_scale=0))

    # 4. 零权边
    case("零权边",
         lambda r: r[2] == 0 and r[0] == [1, 2],
         lambda: dijkstra({1: [(2, 0.0, "z")], 2: []}, 1, 2))

    # 5. 平行边，选最短那条
    case("平行边选最短",
         lambda r: r[2] == 2 and r[1] == ["short"],
         lambda: dijkstra({1: [(2, 5.0, "long"), (2, 2.0, "short")], 2: []}, 1, 2))

    # 6. 自环
    case("自环",
         lambda r: r[2] == 1 and r[0] == [1, 2],
         lambda: dijkstra({1: [(1, 0.0, "loop"), (2, 1.0, "e")], 2: []}, 1, 2))

    # 7. 坐标缺失，A* 应抛 ValueError
    case("坐标缺失",
         lambda _: False,
         lambda: astar({1: [(2, 1.0, "e")], 2: []}, {1: (0.0, 0.0)}, 1, 2),
         expected_error=True)

    # 8. 负权边 Dijkstra，应抛 ValueError
    case("负权边 Dijkstra",
         lambda _: False,
         lambda: dijkstra({1: [(2, -1.0, "neg")], 2: []}, 1, 2),
         expected_error=True)

    # 9. 负权边 A*，应抛 ValueError
    case("负权边 A*",
         lambda _: False,
         lambda: astar({1: [(2, -1.0, "neg")], 2: []},
                       {1: (0.0, 0.0), 2: (0.1, 0.0)}, 1, 2),
         expected_error=True)

    # 10. 孤立节点
    case("孤立节点",
         lambda r: r[0] == [] and math.isinf(r[2]),
         lambda: dijkstra({1: [], 2: [], 3: []}, 1, 3))

    save_csv(output_dir / "T6_边界情况.csv", results,
             ["用例", "预期", "实际", "是否通过", "异常"])

    passed = sum(r["是否通过"] for r in results)

    # 可视化：通过 / 失败 的柱状图
    fig, ax = plt.subplots(figsize=(8, 5))
    names = [r["用例"] for r in results]
    values = [1 if r["是否通过"] else 0 for r in results]
    colors = ["#16a34a" if v else "#dc2626" for v in values]
    ax.barh(names, values, color=colors)
    ax.set_xlim(0, 1.2)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["失败", "通过"])
    ax.set_title(f"T6：边界情况测试，通过 {passed}/{len(results)}")
    ax.grid(alpha=.2, axis="x")
    fig.tight_layout()
    fig.savefig(output_dir / "T6_边界情况.png", dpi=160)
    plt.close(fig)

    return {"T6": {
        "用例数": len(results),
        "通过数": passed,
        "失败数": len(results) - passed,
        "是否通过": passed == len(results),
    }}


def main():
    parser = add_common_arguments(
        argparse.ArgumentParser(description="T6 边界情况"),
        Path(__file__).resolve().parents[1] / "results")
    args = parser.parse_args()

    args = resolve_args(args, Path(__file__).resolve().parents[1] / "results")  # ← 加这一行

    dijkstra, astar, _, _ = load_algorithms(args.algorithm_dir)
    result = t6_boundaries(dijkstra, astar, args.output_dir)
    print_result("T6", result, args.output_dir)


if __name__ == "__main__":
    main()


