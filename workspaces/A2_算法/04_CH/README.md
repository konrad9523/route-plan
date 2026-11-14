# CH（Contraction Hierarchies）最短路径算法

**实现文件：** [`ch.cpp`](ch.cpp)  
**定位：** 通过预处理构建节点层级与 Shortcut，将计算成本前移，从而提高大量 OD 查询的速度。

## 算法原理

CH 将节点按重要性逐步**收缩**。当删除中间节点可能使最短路长度发生变化时，增加连接其前驱与后继的 **Shortcut（捷径边）**，记录该捷径由哪两条弧组成。经过预处理，最短路可在层级图中以“**低层 → 高层 → 低层**”的形式查询。

## 本项目实现

1. **节点重要性：** 结合活动入度/出度、预计 Shortcut 数量及已收缩邻居数动态确定收缩优先级，并局部更新受影响节点。
2. **Witness Search：** 收缩时搜索不经过当前节点的替代路径。找不到不长于候选路径的替代路径时，添加 Shortcut；源码为见证搜索设置了访问数量上限。
3. **分层查询：** 建立 `rank` 和正反向的上行弧表，分别从起点和终点搜索并维护最优会合代价。
4. **还原路径：** 将查询所得 Shortcut **迭代展开**为原始道路边，返回完整节点序列和边 ID，而不是只返回压缩后的路径。

## 对外函数

```cpp
route_cpp17::ContractionHierarchy ch =
    route_cpp17::preprocess_ch(graph);

route_cpp17::PathResult result = ch.query(start, goal);
```

`preprocess_ch()` 可选接收进度回调；`query()` 接受路网节点索引。输出与其他算法一致，含 `nodes`、`edges`、`cost`、`expanded`、`queue_pushes`。

**性能特点：** CH 通常查询最快，但层级与 Shortcut 构建成本较高；比较“总成本”时要同时考虑预处理时间和 OD 查询数量。具体比较结果见 [`../06_实验结果/`](../06_实验结果/)。
