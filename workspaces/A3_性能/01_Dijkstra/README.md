# Dijkstra

## 文件

- `python/dijkstra_variants.py`：单向 L1–L4。
- `cpp/dijkstra_cpp.cpp`：C++ ABI 后端，当前同一翻译单元还保留 B1 版本号以兼容原调用接口。

L0 基线直接使用仓库内 `workspaces/A2_算法/01_实现清单/dijkstra.py`，A3 不复制维护第二份基线。

## 逐层版本

| 版本 | 改动 |
|---|---|
| L0 | A2 原始基线 |
| L1 | 图校验移出查询计时；字典距离/前驱与堆 |
| L2 | 距离和 settled 状态使用稠密数组 |
| L3 | 前驱节点和 edge ID 也使用稠密数组 |
| L4 | 在 L3 上直接遍历 CSR |

双向版本见 [`02_双向Dijkstra/`](../02_双向Dijkstra/README.md)。
