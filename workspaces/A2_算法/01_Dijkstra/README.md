# Dijkstra 最短路径算法

**实现文件：** [`dijkstra.cpp`](dijkstra.cpp)  
**定位：** 四种算法的基础最短路径方法，也是性能对比的基准。

## 算法原理

在边权非负的有向路网上，从起点出发逐步确定到各节点的最短距离。优先队列按当前累计代价 `g(v)` 升序弹出节点；对出边执行松弛，直至终点被确定或队列为空。**不使用启发函数，也不需要预处理索引**。

## 本项目实现

1. 使用最小优先队列管理待搜索节点，并用 `settled` 标记已确定最短距离的节点。
2. 采用惰性删除：跳过队列中已过期的较差距离记录，不必频繁修改堆内元素。
3. 通过 `parent` 和 `parent_edge` 记录前驱节点及原始道路边 ID，搜索完成后反向恢复路径。
4. 统计扩展节点数和入队次数，供四算法统一性能比较。

## 对外函数

```cpp
route_cpp17::PathResult route_cpp17::dijkstra(
    const RoadGraph& graph, int start, int goal,
    bool validate_input = true);
```

`graph` 为路网，`start/goal` 为**路网节点索引**（不是经纬度）；返回的 `PathResult` 包含路径节点 `nodes`、道路边 ID `edges`、总权重 `cost`、扩展节点 `expanded` 和入队次数 `queue_pushes`。不可达时返回空路径。

**相关内容：** 公共类型位于 [`../include/`](../include/)；三种路网的实验结果见 [`../06_实验结果/`](../06_实验结果/)。
