# 接口

测试接口目录。**接口、缓存、测试执行、出图、自测界面全部写在 `api.py` 一个文件里**；`cpp/` 只放 C++ 测试器；`runtime/`（build / cache / queries）首次运行时自动生成，不在包内。

四个算法源码和共享头文件都在 `../算法/`。

## 目录

```text
接口/
├─ api.py                # 接口 + 缓存 + 测试执行 + 出图 + 自测，全部在这一个文件
├─ 接口说明.md            # 前端调用说明：端点、参数、返回、错误码
├─ cpp/                  # C++ 统一测试器 + 索引序列化
├─ assets/               # 中文字体说明（字体不入库）
├─ config.json
└─ requirements.txt
```

## 三分钟跑通（`api.py` 自带命令行入口）

```powershell
# 1. 生成缓存（首次自动编译 C++；广东 CH 约 128 秒）
python api.py --prepare

# 2. 启动接口
python api.py --serve

# 3. 浏览器打开 http://127.0.0.1:8000/docs
#    POST /api/benchmarks 提交 → GET /api/jobs/{job_id} 轮询 → GET /api/results/* 取结果
```

## 缓存逻辑

| 内容 | 缓存文件 | 图表中的预处理时间 |
|---|---|---|
| Dijkstra | 无索引 | 0 |
| A* | `astar.cache` | 首次构建时记录 |
| 双向 A* | `bidirectional_astar.cache` | 首次构建时记录 |
| CH | `ch.cache` | 首次构建时记录 |
| 公共路网 | `graph.rgraph` | 不归入某个算法 |

`manifest.json` 记录 A1 路网 SHA-256、算法源码 SHA-256、缓存版本与各算法首次预处理耗时；路网、算法或缓存变化后自动失效。

前端查询不重复预处理，但图表仍用缓存首次构建的耗时：

```text
总成本 = 缓存记录的预处理时间 + 平均查询耗时 × 查询数
```

## 个人自测

运行 `python api.py --gui`，支持数据集、算法多选、查询数、重复次数、随机种子和“强制重建缓存”。

结果写到 `../结果/self_test/`，不会覆盖 `../结果/self_test/南山区（100对）` 等归档。

## 接口一览

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/config` | 算法、路网、默认参数 |
| GET | `/api/cache/status` | 缓存可用性与原因 |
| POST | `/api/benchmarks` | 提交测试，返回 job_id |
| GET | `/api/jobs/{job_id}` | 状态、阶段、百分比 |
| GET | `/api/results/summary` | 汇总与校验信息 |
| GET | `/api/results/table` | 五列汇总表 JSON |
| GET | `/api/results/table.csv` | 下载 CSV |
| GET | `/api/results/dashboard` | 2×2 中文图 PNG |
| GET | `/api/results/queries` | 分页 OD 明细 |

完整字段、参数与错误码见 `接口说明.md`。

## 输出文件

每次运行生成四个文件到 `../结果/self_test/`（接口调用为 `../结果/frontend/`，运行时自动创建）：

| 文件 | 内容 |
|---|---|
| `performance_dashboard.png` | 查询耗时、扩展节点、预处理成本、总成本 |
| `algorithm_summary.csv` | 算法、平均耗时、平均扩展、预处理、总成本 |
| `summary.json` | 前端可直接读取的汇总数据 |
| `query_raw.csv` | 每条 OD × 每个算法的原始记录 |

## 前端交付

1. `接口说明.md`（9 个端点、参数、返回字段、错误码）。
2. 接口地址 `http://127.0.0.1:8000`。
3. 示例结果：`../结果/` 中任选一组四个文件。

## 环境要求

- Python 3.10+，依赖 FastAPI、Uvicorn、Matplotlib。
- C++17 编译器：VS Build Tools + CMake，或 MinGW-w64 `g++`。
- 中文字体：`assets/NotoSansSC-Regular.ttf` 不入库，缺失时自动退回系统中文字体。
- `runtime/queries/` 的固定 OD 首次运行自动生成。




