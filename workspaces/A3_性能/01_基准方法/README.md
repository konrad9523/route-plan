# 当前算法

| 文件（位于 `代码/`） | 用途 |
|---|---|
| `dijkstra_variants.py` | Dijkstra 分层优化与双向版本 |
| `astar_variants.py` | A* 分层优化、几何/地标启发式 |
| `dijkstra_cpp.cpp`、`astar_cpp.cpp` | C++ 实现 |
| `route_planner.py` | 应用入口：复用 `RoutePlanner`，查询调用 `plan()` |
| `route_output.py` | 路径、距离与估算行驶时间的统一输出 |
| `test_route_output.py`、`test_route_planner.py` | 配套测试 |

A2 基线从 `workspaces/A2_算法/01_实现清单/` 加载，不使用归档中的旧基线代替。规划入口需要 NumPy；C++ 后端还需要匹配源码的本机 DLL，存放在 `代码/.build/`。

从仓库根目录测试：

```powershell
python -B -m unittest discover -s 'workspaces/A3_性能/01_基准方法/代码' -p 'test_route_*.py' -v
```

[输出字段与时间估算边界](../05_文档报告/统一路径信息输出说明.md) · [完整实验入口](../03_实验结果/实验入口/算法优化实验说明.md) · [旧实验归档](../07_历史结果归档/README.md)
