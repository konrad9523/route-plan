# A3 性能与算法优化

A3 保存最短路算法源码、调用接口、实验 Notebook 和方法说明。目录按算法与用途分开；算法实现不放在 Notebook 中，Notebook 负责调用、记录实验和绘制报告图。

## 目录

- `01_Dijkstra/`：单向 Dijkstra 优化与 C++ 实现。
- `02_双向Dijkstra/`：双向 Dijkstra 实现。
- `03_Astar/`：A* 优化、启发函数与 C++ 实现。
- `04_双向Astar/`：双向 A* 实现、优化实验脚本与方法说明。
- `05_CH/`：Contraction Hierarchies 实现及构建代码。
- `06_算法调用与出图/`：Python 调用接口、C++ 性能执行器、Notebook、示例和测试；具体调用见其 README。
- `07_实验结果/`：本机保存逐轮 CSV、日志、表格和图片；Git 只保留目录说明。
- `08_文档报告/`：路网清单、统一路径输出规范和算法调研文档。

## 基线与共享代码

Dijkstra、A* 的 Python 基线以 A2 中的文件为唯一来源：[`dijkstra.py`](../A2_算法/01_实现清单/dijkstra.py) 和 [`astar.py`](../A2_算法/01_实现清单/astar.py)。A3 的路线接口按仓库相对路径加载它们。共享 C++ 类型定义位于 `workspaces/A2_算法/`。

## 路网与运行输入

三张路网的文件名、规模和 SHA-256 见仓库根目录的 [`a3_network_manifest.json`](../../data/a3_network_manifest.json)。GraphML 大文件不提交；运行性能接口前需将对应文件放在仓库根目录 `data/`。固定查询池和地标 ID 属于小型运行配置，随 A3 保存在 `06_算法调用与出图/前端接口/查询配置/`。

## 实验结果与本机文件

实验结果集中写入 `07_实验结果/`，A3 的 `.gitignore` 排除其中的实验产物。`.build/`、编译出的 DLL/EXE、图缓存和 CH 索引也只保留在本机。`09_AI使用说明/` 可在本机记录过程，但不纳入远端版本。
