# 前端性能测试API契约

默认地址：`http://127.0.0.1:8000`

## 基本流程

1. `GET /api/config`：读取数据集、算法和默认参数。
2. `GET /api/cache/status`：确认预处理缓存已准备好。
3. `POST /api/benchmarks`：提交测试。
4. `GET /api/jobs/{job_id}`：轮询进度。
5. 完成后读取图表、表格和汇总数据。

## 提交测试

`POST /api/benchmarks`

```json
{
  "dataset": "nanshan",
  "algorithms": ["dijkstra", "astar", "bidirectional_astar", "ch"],
  "query_count": 300,
  "repeat": 3,
  "seed": 20261102
}
```

前端不能重建缓存。如果缓存不可用，返回HTTP `409`，由后端管理员运行 `prepare_cache.bat`。

## 返回结果

| 接口 | 内容 |
|---|---|
| `GET /api/results/summary` | 路网、查询参数、缓存来源和各算法汇总值 |
| `GET /api/results/table` | 五列汇总表JSON |
| `GET /api/results/table.csv` | 下载五列CSV |
| `GET /api/results/dashboard` | 中文2×2综合图 |
| `GET /api/results/queries` | 分页读取原始查询行 |

图表中的预处理时间来自当前缓存首次构建时的记录；前端查询时不会重复执行预处理。
