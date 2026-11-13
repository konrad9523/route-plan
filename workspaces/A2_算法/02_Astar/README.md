# A* 最短路径算法

**实现文件：** [`astar.cpp`](astar.cpp)  
**定位：** 在 Dijkstra 基础上加入地理启发函数，引导搜索优先接近终点。

## 算法原理

优先队列按照 `f(v) = g(v) + h(v)` 排序，其中 `g(v)` 为起点到节点 `v` 的已知代价，`h(v)` 为到终点的代价下界。本实现使用 **Haversine 球面弧长距离**估计地理直线距离，并乘以安全缩放系数，使启发值不超过路网中的实际最短路径代价。

## 本项目实现

1. `astar_haversine_distance()` 根据经纬度计算两点球面弧长（米）。
2. `estimate_astar_haversine_scale()` 遍历道路边，估计地理距离到路网权重的安全转换系数；批量查询时可提前计算并复用。
3. 查询阶段按 `g+h` 出队，通过松弛更新最短距离与前驱关系，最终恢复原始节点、边 ID 序列。
4. 使用线程局部工作区及带代次的数组，减少多次 OD 查询反复清空大数组的开销。

**注意：** 这里使用的是 **Haversine 弧长**；双向 A* 的平衡势函数使用**球面弦长**，两者不要混淆。

## 对外函数

```cpp
route_cpp17::PathResult route_cpp17::astar(
    const RoadGraph& graph, int start, int goal,
    double heuristic_scale = -1.0,
    bool validate_input = true);
```

`heuristic_scale = -1` 时函数自行估计比例；若已预先估计，可以直接传入。返回 `PathResult`（路径节点、道路边 ID、代价、扩展节点和入队次数）。

**相关内容：** 公共声明见 [`../include/algorithms.hpp`](../include/algorithms.hpp)；性能结果见 [`../06_实验结果/`](../06_实验结果/)。
