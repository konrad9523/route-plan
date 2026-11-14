# A2 路径规划算法性能测试

本目录实现“预处理提前缓存、前端接口与个人自测分开”。四种算法源码只位于 `../01_实现清单/`，此处不保存算法副本。

## 目录结构

```text
06_算法测试接口/
├─ cpp/                         # C++统一测试器和索引序列化
├─ core/                        # 前端和自测共用的缓存、测试、统计、绘图
├─ server/                      # 只给前端使用的HTTP服务
├─ self_test/                   # 只给个人自测使用的图形界面
├─ assets/                      # 中文图表字体
├─ runtime/
│  ├─ build/                   # 编译结果
│  ├─ cache/<dataset>/         # RGRAPH与A*/双向A*/CH缓存
│  └─ queries/                 # 按数据集、Q和seed复用的固定OD
├─ config.json
├─ prepare_cache.bat            # 后端部署前提前生成缓存
├─ start_server.bat             # 启动前端API
└─ requirements.txt
```

## 缓存逻辑

| 内容 | 缓存文件 | 图表中的预处理时间 |
|---|---|---|
| Dijkstra | 无索引 | 0 |
| A* | `astar.cache` | 首次构建时记录 |
| 双向A* | `bidirectional_astar.cache` | 首次构建时记录 |
| CH | `ch.cache` | 首次构建时记录 |
| 公共路网 | `graph.rgraph` | 不归入某个算法 |

`manifest.json` 记录A1路网SHA-256、算法源码SHA-256、缓存版本和各算法首次预处理耗时。路网、算法或缓存版本变化后，缓存自动判定为失效。

前端正常查询时不重复执行预处理，但图表仍使用缓存首次构建时的耗时：

```text
总成本 = 缓存记录的预处理时间 + 平均查询耗时 × 查询数
```

## 后端部署

1. 确认A1路网位于 `../../A1_数据/01_路网清单/processed/`。
2. 双击 `prepare_cache.bat`，提前生成所有现有数据集的缓存。
3. 双击 `start_server.bat`，默认服务地址为 `http://127.0.0.1:8000`。
4. 前端按 `server/API.md` 调用。

前端不能调用缓存重建；缓存未准备好时，提交测试返回HTTP 409。

## 个人自测

双击 `self_test/run_self_test.bat`。个人界面支持：

- 数据集选择。
- Dijkstra、A*、双向A*、CH多选。
- 查询数、重复次数、随机种子。
- “强制重新生成预处理缓存”选项。

自测缓存缺失时会自动生成，结果只覆盖 `../03_算法对比/self_test/`，不会覆盖前端结果。

## 图表与表格

前端和自测都生成同样的四个文件：

| 文件 | 内容 |
|---|---|
| `performance_dashboard.png` | 2×2图：查询耗时、扩展节点、预处理成本、总成本 |
| `algorithm_summary.csv` | 算法、平均查询耗时、平均扩展节点、预处理时间、总成本 |
| `summary.json` | 前端可直接读取的汇总数据 |
| `query_raw.csv` | 每种所选算法、每组OD的原始数据 |

## 交付给前端

前端开发人员只需要：

1. `server/API.md`。
2. 接口地址。
3. `../03_算法对比/frontend/` 中的四个示例结果文件。

负责Electron或服务器部署的人员另外需要：`server/`、`core/`、C++可执行程序、`runtime/cache/`和 `config.json`。

## 环境要求

- Python 3.10+。
- C++17编译器：Visual Studio C++ Build Tools + CMake，或MinGW-w64 `g++`。
- Python依赖：FastAPI、Uvicorn、Matplotlib。

首次运行 `prepare_cache.bat` 会自动编译C++程序。如果电脑上没有C++17编译环境，需先安装后再生成缓存。

