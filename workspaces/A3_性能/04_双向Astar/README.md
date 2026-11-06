# 双向 A*

## 代码文件

- `cpp/bidirectional_astar_received.cpp`：收到的 C++ 原版，保留作基线，不直接改写。
- `cpp/bidirectional_astar_variants.hpp/.cpp`：A3 双向 A* 实验接口和版本实现。图、边和结果类型复用 `workspaces/A2_算法/algorithms.hpp`；A3 的实验层接口不写回 A2 共享头文件。
- `python/bidirectional_astar_received.py`：收件箱 Python 原版。
- `python/bidirectional_astar.py`：当前 Python 双向实现，供对照。

## 当前 C++ 实验层

| 版本 | 改动 |
|---|---|
| L0 | 调用收件 C++ 实现，平衡球面弦长势函数 |
| L1 | 在 L0 搜索逻辑上，清理陈旧堆顶后遇到任一搜索队列耗尽即结束 |
| L2 | MM：优先级 `max(g+h, 2g)`，并用 min-pr/min-f/min-g 下界终止 |
| L3 | MMε：在 MM 的中点项加入当前方向节点的局部最小可用边权 `ε(n)` |
| L4 | BAE*：按 `b_D = 2g_D + h_D - h_\bar{D}` 排序，交替扩展方向，以两侧最小 b 值的均值作下界 |
| L5 | BAE* + `min_f` 组合下界：保持 L4 的排序和扩展方向，以 `max((b_min,F+b_min,B)/2, min_f,F, min_f,B)` 停止 |

L1 保留原版的重标权停止判断 `min_forward + min_backward >= best`，并补上队列耗尽结束。MM 和 MMε 维护辅助 min-f/min-g 堆，避免每轮扫描整个 OPEN；BAE* 使用它自己的 b-bound。L2、L3、L4 是不同的研究算法对照，编号表示实验顺序，不代表后层累积前层的全部算法公式。

L5 是本项目在 L4 上增加的实验性停止界：`min_f` 来自两侧 OPEN 的辅助堆，取多个可采纳下界的最大值仍可采纳。L5 是否减少展开以及是否值得其维护开销，见 [2026-11-04 搜索优化实验结果](../07_实验结果/双向Astar/search_optimization_2026-11-04/README.md)。

启发式与层次分开配置：

- `H0`：当前球面弦长下界。
- `ALT`：有向地标下界。
- `MAX`：分别对起点侧和终点侧取 `max(H0, ALT)`。

L1 还可选 `LAZY_DUPLICATES`（默认懒堆）或 `INDEXED_BINARY_HEAP`（带 decrease-key 的索引堆）；该队列实验只作用于 L1，见本次实验结果。

ALT 预处理只支持同一强连通分量中的查询。传入的地标必须属于同一个分量，查询起点和终点也必须处于该分量；搜索跳过离开该分量的边，避免对不可达地标距离作不安全处理。预处理耗时保存在 `alt_preprocess_ns`，不计入单次查询。

查询时必须传入用于构建 `BidirectionalAStarVariantIndex` 的同一张、未修改的图；当前接口只检查图和索引的尺寸，不比较整张图的内容。

当前收件 C++ 版在每次距离标签改善时，都会检查同节点的对侧标签。因此显式增加跨边候选不会产生更小的 `best`，本轮不把它作为独立改进层。对原弧 `u→v`，`dF(v) ≤ dF(u)+w'(u,v)`；当 `dB(v)` 有限时，同节点候选 `dF(v)+dB(v)` 不大于跨边候选。现有 `03_Astar/cpp/astar_cpp.cpp` 使用不同的相遇检查时机，那里已有跨边候选；它保留为独立对照，不由本实验文件覆盖。

论文依据、方法选择、每层公式、三图实验方法及完整文献见 [`研究依据与实现层级.md`](研究依据与实现层级.md)。

小图正确性测试位于 `tests/bidirectional_astar_cpp_smoke.cpp`，包括 20 张随机有向图上所有起终点与独立 Dijkstra 的对拍，以及平行边、edge ID、H0/ALT/MAX、L5、索引堆、同起终点、不可达图和队列耗尽用例。

三张 A1 路网的复现实验脚本位于 `experiments/`：`prepare_graphml.py` 流式转换 GraphML，`benchmark.cpp` 对 L0–L4 运行论文算法层实验；`benchmark_search_optimizations.cpp` 和 `run_search_optimizations.ps1` 运行 ALT/队列/L5 组合下界实验，`summarize_search_optimizations.py` 汇总配对结果。GraphML 文件由本地 `data/` 目录提供；转换后的临时二进制放在 `%TEMP%`，实验输出写入 `07_实验结果/双向Astar/`，不会与算法源码混放。

L0 复用收件版接口，因此只能读取其已有的总展开节点数和堆推入次数；L1–L5 额外记录双向展开数、扫描边数、松弛次数等统计项。若做层间统计对比，L0 不应把未提供的细分计数解释为 0。

## 运行与集成边界

Notebook 负责图数据、固定查询、计时和结果分析，不复制算法实现。A2 头文件使用 `std::vector` 等 C++ 类型，不能直接作为 `ctypes` ABI 调用；若要从 Notebook 调用本实验模块，需要通过固定宽度类型和缓冲区提供 C ABI 包装。当前 `RoutePlanner` 使用的 C++ A* 后端仍在 `03_Astar/cpp/astar_cpp.cpp`。

`algorithms.hpp` 中声明了 `astar_haversine_distance` 和 `estimate_astar_haversine_scale`，但 A2 目录目前没有对应 C++ 实现。本实验翻译单元提供这两个实现，使收件 C++ 文件可以与版本代码一起链接；如果 A2 后续新增实现，构建时应只保留一份定义。

MSVC 构建需使用 C++17 和 `/utf-8`，并将 A2 头文件目录加入 include path；编译时同时链接 `bidirectional_astar_received.cpp` 与 `bidirectional_astar_variants.cpp`。Notebook 的 C ABI 适配仍未接入本实验模块。
