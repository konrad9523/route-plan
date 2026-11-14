# A*

## 文件

- `python/astar_variants.py`：单向 L0、缓存比例版、L1–L5，以及几何/ALT 启发式准备工具。
- `cpp/astar_cpp.cpp`：C++ ABI 后端，当前同一翻译单元还保留 B1 版本号以兼容原调用接口。
- `python/astar_received_baseline.py`：收件箱原始基线副本，保留其来源；不是当前基准的默认基线。

L0 基线直接使用仓库内 `workspaces/A2_算法/01_实现清单/astar.py`，A3 不复制维护第二份基线。

## 逐层版本

| 版本 | 改动 |
|---|---|
| L0 | A2 原始基线，每次查询计算安全比例 |
| L0-CachedScale | 缓存安全比例 |
| L1 | 预检后用字典状态搜索 |
| L2 | 距离/访问状态改用稠密数组 |
| L3 | 前驱改用稠密数组 |
| L4 | 使用 CSR 邻接遍历 |
| L5 | 在 L4 上缓存启发值 |

H0、PLANE、ALT、MAX、MAX_PLANE 是启发式选择，与 L0–L5 版本层次分开。双向版本见 [`04_双向Astar/`](../04_双向Astar/README.md)。
