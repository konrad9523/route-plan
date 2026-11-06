# 算法调用与出图

## 目录

- `前端接口/`：Python 调用入口、单路线结果整理和性能比较 runner。
- `cpp/`：被性能比较 runner 调用的 C++ 程序及构建脚本。
- `notebooks/`：单路线调用演示、三规模性能表和报告静态图。科研绘图代码直接放在性能 Notebook 中。
- `examples/`：命令行输出演示；`tests/`：路径规划与输出整理的测试。

## Python 文件职责

- `前端接口/performance_service.py`：性能对比的公开入口，接收路网、查询数、算法勾选、轮数和随机种子，返回可直接 JSON 序列化的汇总表与绘图数据。五个定稿算法都从这里选择。
- `前端接口/performance_comparison.py`：性能入口内部使用的 runner，调用 C++ runner 并汇总查询耗时与展开节点数；前端不需要直接调用它。
- `前端接口/route_planner.py`：单起终点路径规划调用，适合地图选点后请求一条路线。
- `前端接口/route_output.py`：把单条路线整理成节点、路段、距离和估算时间等统一结果。
- `cpp/performance_comparison.cpp`：五种定稿算法的 C++ 批量性能执行器；构建脚本会把它编译到本地 `.build/`。

性能对比和单路线规划是两种调用场景，所以入口分别是 `run_performance_comparison()` 与 `RoutePlanner`；Notebook 只用于演示、表格和报告绘图，不作为前端运行依赖。这里提供 Python 调用模块，不包含 HTTP 服务或前端页面。

## 前端后端调用

前端同学的后端导入 `前端接口/performance_service.py` 中的 `run_performance_comparison()`；浏览器不直接导入 Python。该入口只暴露五种定稿配置：Dijkstra L4、A* L4 + MAX-8、双向 A* L4 BAE* + MAX-8、双向 Dijkstra B1、CH。

```python
import sys
from pathlib import Path

interface_dir = Path("workspaces/A3_性能/06_算法调用与出图/前端接口")
sys.path.insert(0, str(interface_dir.resolve()))
from performance_service import run_performance_comparison

result = run_performance_comparison({
    "networks": ["nanshan", "shenzhen", "guangdong"],
    "query_count": 30,
    "algorithms": ["dijkstra", "astar", "bidirectional_astar", "bidirectional_dijkstra", "ch"],
    "rounds": 3,
    "seed": None,
})

rows = result["summary_table"]
chart_data = result["chart_data"]
```

返回值可直接 JSON 序列化。`summary_table` 是用于表格的汇总行；`chart_data` 含每个路网、算法的中位数、Q1–Q3 和逐查询耗时，前端用它绘制交互图。Notebook 用同一批结果绘制报告静态图。接口不生成 PNG，也不接收优化层或启发函数参数。

每次请求都会在 C++ runner 中从当前路网的最大强连通分量现场生成指定数量的不同起终点对，并由所有勾选算法共用。`seed` 可复现实次抽样，省略时服务端生成种子并写入响应。这样生成的点对保证彼此可达，也满足 ALT 地标启发式的连通性要求。接口响应会返回本次实际使用的节点 ID。

A* 和双向 A* 的 8 个 ALT 地标也在最大强连通分量内按地理最远点规则现场确定；地标选择耗时与 ALT 距离表预处理耗时分开报告。查询生成和地标选择都不计入单次查询耗时。

## 单路线调用

`前端接口/route_planner.py` 提供 `RoutePlanner`，`前端接口/route_output.py` 统一整理节点、边、距离和时间信息。小图示例在 `notebooks/路径规划调用与展示.ipynb`；命令行示例在 `examples/demo_route_output.py`。

## 运行条件

- 根目录 `data/` 下需有清单中列出的三张 GraphML；路网大文件不提交 Git。
- 首次运行性能比较需有 Visual Studio 2022 C++ 工具链；构建结果和缓存放在本目录 `.build/`。
- 起终点和 ALT 地标均由 C++ runner 根据当前图现场生成，不依赖随仓库提交的查询或地标 CSV。
- CH 首次在某张图上运行会建立索引；之后从 `.build/ch_index/` 读取。预处理耗时与查询耗时分别记录。
- 安装 Notebook 绘图依赖：`python -m pip install -e ".[a3-performance]"`。

实验 CSV、查询运行记录、汇总和图表统一放在 `07_实验结果/`，该目录中的实验产物由 A3 `.gitignore` 排除，不会和算法源码一起提交。
