# 双向 Dijkstra

- `python/bidirectional_dijkstra.py`：B1 双向搜索。它复用单向模块的端点校验和前驱恢复小函数，算法主体独立放在本目录。
- 现有 C++ ABI 后端的 `B1` 仍由 [`01_Dijkstra/cpp/dijkstra_cpp.cpp`](../01_Dijkstra/cpp/dijkstra_cpp.cpp) 统一导出，暂不复制整份 C++ 文件。
- 回归入口在 [`06_算法调用与出图/tests/`](../06_算法调用与出图/README.md)。
