# 算法

四个算法的 C++ 实现和两个共享头文件。`.cpp` 只负责“给定起终点求最短路”，不含 `main`，由 `接口/cpp` 的测试器调用。

```text
算法/
├── dijkstra.cpp
├── astar.cpp
├── bidirectional_astar.cpp
├── ch.cpp
├── algorithms.hpp      # 四个算法的对外入口
└── graph_types.hpp     # 公共类型
```

## 四个算法

| 文件 | 算法 | 入口 |
|---|---|---|
| `dijkstra.cpp` | Dijkstra | `dijkstra(graph, start, goal)` |
| `astar.cpp` | A* | `astar(graph, start, goal, heuristic_scale)` |
| `bidirectional_astar.cpp` | 双向 A* | `prepare_bidirectional_astar(graph)` → `bidirectional_astar(graph, index, start, goal)` |
| `ch.cpp` | CH | `preprocess_ch(graph)` → `ContractionHierarchy::query(start, goal)` |

四个文件都只 `#include "algorithms.hpp"`，不依赖测试器、缓存或文件格式。

## 两个头文件

| 文件 | 内容 |
|---|---|
| `algorithms.hpp` | `dijkstra`、`astar`、`prepare_bidirectional_astar` / `bidirectional_astar`、`preprocess_ch`、`ContractionHierarchy::query`，以及 `estimate_astar_haversine_scale` |
| `graph_types.hpp` | `RoadGraph`（出边、坐标）、`Edge`、`PathResult`（节点、边 ID、cost、扩展数、入队数）、`QueueItem`、`ROUTE_INF` |

依赖方向是单向的：

```text
接口/cpp  ──┐
            ├──> 算法/（.hpp + .cpp）
算法/       ──┘
```

测试器和算法都只依赖这两个头文件，彼此不互相引用。改算法接口时先改 `algorithms.hpp`，再改 `.cpp` 和 `接口/cpp` 的调用点。`ContractionHierarchy` 的存储是 `std::vector<std::vector<int>>`（`upward_out` / `upward_in`）。

## 编译

不单独编译，由 `接口/cpp/CMakeLists.txt` 和 `接口/api.py` 一起编成 `route_benchmark.exe`：

```powershell
cmake -S .\接口\cpp -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
```

替换任一 `.cpp` 或 `.hpp` 后，下次测试会按修改时间自动重新编译；缓存指纹也会变化，需要重新 `python api.py --prepare`。

## 实测（1000 对 OD）

| 算法 | 南山区 | 深圳市 | 广东省 |
|---|---|---|---|
| Dijkstra | 0.782 ms | 6.792 ms | 123.599 ms |
| A* | 0.361 ms | 2.644 ms | 63.859 ms |
| 双向 A* | 0.275 ms | 2.105 ms | 66.520 ms |
| CH | 0.035 ms | 0.196 ms | 2.157 ms |

CH 单次最快，但广东省约 2,074 次查询才回收 128 秒预处理；南山、深圳选双向 A*，广东选 A*。
