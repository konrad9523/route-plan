# 双向 A* 最短路径算法

**实现文件：** [`bidirectional_astar.cpp`](bidirectional_astar.cpp)  
**定位：** 以起点和终点为两端协同搜索，并通过平衡势函数缩小搜索范围。

## 核心原理

本实现**不是简单地同时运行两个普通 A***。它将经纬度映射到三维单位球坐标，用**球面弦长**构造起点、终点两侧的距离下界，再建立平衡势函数：

\[
p(v)=rac{lpha}{2}\left[d_{\mathrm{chord}}(v,t)-d_{\mathrm{chord}}(s,v)ight]
\]

其中 `α` 是由路网边权估计的安全比例，`s/t` 分别为起点与终点。搜索采用势函数重标定的非负边权，优先队列维护**重标定距离**，而不是直接比较普通 A* 的 `f=g+h`。

## 本项目实现流程

1. **准备索引：** `prepare_bidirectional_astar()` 构建反向邻接表、球面坐标和启发缩放系数，供多组 OD 复用。
2. **双向扩展：** 前向沿原图出边搜索，后向沿反向邻接搜索；每轮选择队列最小键值较小的一侧扩展。
3. **更新候选路径：** 两侧访问到同一节点时，利用两侧已知距离更新 `best` 和会合节点。
4. **停止搜索：** 已找到候选路径后，当两侧剩余最小**重标定距离**之和不小于同口径的 `best` 时终止（源码中为 `min_forward + min_backward >= best`）。
5. **恢复原路：** 拼接前向前驱与后向后继链，逐边核对并重新累计**原始路网权重**，输出节点与道路边 ID。

## 对外函数

```cpp
route_cpp17::BidirectionalAStarIndex index =
    route_cpp17::prepare_bidirectional_astar(graph);

route_cpp17::PathResult result =
    route_cpp17::bidirectional_astar(graph, index, start, goal);
```

另有不需要显式提供 `index` 的一次性查询重载。批量查询中使用预先构建的索引更合适。`PathResult` 与其他算法采用相同输出字段。

**区别提醒：** 球面弦长不等于 Haversine 球面弧长；`best` 和队列键值的比较须在相同的重标定代价口径下进行。
