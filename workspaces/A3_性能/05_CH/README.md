# Contraction Hierarchy（CH）

- `cpp/ch.cpp`：CH 预处理与查询实现；算法接口和共用图类型分别声明在 `workspaces/A2_算法/algorithms.hpp` 与 `graph_types.hpp`。
- `cpp/ch_c_api.cpp`：C ABI 边界；只传 CSR 数组、定长整数和输出缓冲区，不跨 DLL 传递 C++ 容器。
- `cpp/build_ch.py`：在 Visual Studio Developer Command Prompt 中构建 `06_算法调用与出图/.build/ch_cpp/` 下的版本化 DLL；Notebook 首次运行时会调用它，源码或头文件更新后生成新版本。
- 当前查询采用双向上行搜索、shortcut 解压和 stall-on-demand；本轮尚未运行正确性或性能验证。
- 预处理包含动态节点排序、受限 witness search 和平行弧去重；后续优化逐层记录 shortcut 数、构建成本、查询工作量与耗时。
- Python 调用入口是 `06_算法调用与出图/前端接口/route_planner.py`：`planner.plan(source, target, algorithm="ch", language="cpp")`。每个 `RoutePlanner` 只预处理一次，并在结果 `stats` 返回预处理耗时、层级弧数、shortcut 数、查询耗时和扩展节点数。
