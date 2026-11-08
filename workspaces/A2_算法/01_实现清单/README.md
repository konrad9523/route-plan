# C++ 算法源码

此处是性能测试使用的唯一算法源码位置：

| 算法 | 源文件 | 对外入口 |
|---|---|---|
| Dijkstra | `dijkstra.cpp` | `dijkstra(...)` |
| A* | `astar.cpp` | `astar(...)` |
| 双向 A* | `bidirectional_astar.cpp` | `prepare_bidirectional_astar(...)` + `bidirectional_astar(...)` |
| CH | `ch.cpp` | `preprocess_ch(...)` + `ContractionHierarchy::query(...)` |

- `graph_types.hpp`：图、边、路径结果和查询工作区类型。
- `algorithms.hpp`：测试器与四种算法共用的 C++17 契约。
- `../06_算法测试接口/`：直接引用这些文件，不再保存算法副本。

替换任一 `.cpp` 后，下次测试会根据修改时间自动重新编译。
