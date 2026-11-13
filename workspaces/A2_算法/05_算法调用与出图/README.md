# 算法调用与出图接口

本目录按 A3 的方式，将**对外 Python 函数**与**内部结果封装**分开。这里只保存 A2 已有接口代码，用于说明性能对比的数据输入输出，不包含旧版 HTTP 服务和本地测试执行工程。

## 文件说明

| 文件 | 作用 |
|---|---|
| [`前端接口/performance_service.py`](前端接口/performance_service.py) | 面向调用方的统一入口，导出两个公开函数 |
| [`前端接口/performance_comparison.py`](前端接口/performance_comparison.py) | 负责参数整理、调用既有测试服务以及将结果转换为表格和图表数据 |
| `前端接口/__init__.py` | Python 模块标识 |

## 公开接口

```python
from performance_service import run_performance_comparison, read_performance_result

# 性能比较：路网 × 算法 × OD 数量
result = run_performance_comparison({
    "networks": ["nanshan", "shenzhen", "guangdong"],
    "algorithms": ["dijkstra", "astar", "bidirectional_astar", "ch"],
    "query_count": 1000,
    "rounds": 3,
    "seed": 20261102,
})

# 已有结果的读取接口
saved = read_performance_result("某组结果/summary.json")
```

| 函数 | 输入 | 主要输出 |
|---|---|---|
| `run_performance_comparison(params)` | `networks`、`algorithms`、`query_count`、`rounds`、`seed` 等 | `summary_table`、`chart_data`、`runs` |
| `read_performance_result(summary_file)` | 某组的 `summary.json` 路径 | `summary_table`、`chart_data`、`run`、`validation`、`files` |

**返回字段：** `summary_table` 按算法记录 `network`、`algorithm`、`query_mean_ms`（平均查询毫秒）、`expanded_mean`（平均扩展节点数）、`preprocess_ms`（预处理毫秒）、`total_cost_ms`（总成本毫秒）、`valid_queries`；`chart_data` 另外提供查询耗时分布与分位数，供前端绘图。

`total_cost_ms = preprocess_ms + query_mean_ms × query_count`；预处理成本不等于每次查询都重新进行预处理。

## 与已有成果的关系

`06_实验结果/` 中保留了南山区、深圳市和广东省分别采用 100、1000 对 OD 的六组 CSV、JSON 和综合图。这些是**已经生成的实验结果**，不是在本次整理过程中生成的。

**存档说明：** 两个 Python 源文件原样保留，其中 `performance_comparison.py` 仍引用原工程的 `core/`。本 GitHub 记录包未包含该运行依赖，不承诺直接执行；本次只整理接口和现有成果，不重新运行算法，也不另行构造静态替代接口。
