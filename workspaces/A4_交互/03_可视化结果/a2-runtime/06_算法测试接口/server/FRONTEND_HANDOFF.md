# 前端交付说明

前端开发只需要本文档、`API.md`、接口地址和一份示例结果。不需要读取C++算法、A1路网或预处理缓存。

## 页面参数

| 控件 | 参数 |
|---|---|
| 数据集下拉框 | `dataset` |
| 算法多选 | `dijkstra` / `astar` / `bidirectional_astar` / `ch` |
| 查询数 | `query_count` |
| 重复次数 | `repeat` |
| 随机种子 | `seed` |

## 页面流程

1. 读取 `GET /api/config`。
2. 用户选参数后提交 `POST /api/benchmarks`。
3. 轮询 `GET /api/jobs/{job_id}`。
4. 完成后同时展示 `GET /api/results/dashboard` 和 `GET /api/results/table`。

缓存不可用时后端返回HTTP 409，前端只需提示“预处理缓存尚未准备”，不要提供重建缓存按钮。

示例结果中：

- `performance_dashboard.png`：可直接用于完成页面布局。
- `algorithm_summary.csv`：五列表格。
- `summary.json`：汇总数值和缓存说明。
- `query_raw.csv`：每组OD的原始测试记录。
