# A2 第二次作业：双向 A*、CH 与四算法测试

本目录按“算法 / 接口 / 结果 / 报告”分开：

```text
第二次作业/
├── 代码说明.md            # 每个代码文件的作用、调用关系、数据流
├── 算法/                  # 四个 .cpp + 两个 .hpp
│   ├── dijkstra.cpp
│   ├── astar.cpp
│   ├── bidirectional_astar.cpp
│   ├── ch.cpp
│   ├── algorithms.hpp
│   ├── graph_types.hpp
│   └── README.md
├── 接口/                  # 测试接口
│   ├── api.py             # 接口 + 缓存 + 测试执行 + 出图 + 自测，全部在这一个文件
│   ├── 接口说明.md
│   ├── cpp/               # C++ 测试器
│   ├── config.json
│   └── requirements.txt
├── 结果/                  # 6 组归档（self_test/）
├── 报告/                  # 3 份 docx
└── AI使用说明/            # AI日志.docx
```

每个代码文件的详细说明见 [`代码说明.md`](代码说明.md)。

## 算法

| 算法 | 源文件 | 入口 |
|---|---|---|
| Dijkstra | `算法/dijkstra.cpp` | `dijkstra(...)` |
| A* | `算法/astar.cpp` | `astar(...)` |
| 双向 A* | `算法/bidirectional_astar.cpp` | `prepare_bidirectional_astar(...)` + `bidirectional_astar(...)` |
| CH | `算法/ch.cpp` | `preprocess_ch(...)` + `ContractionHierarchy::query(...)` |

四个 `.cpp` 只依赖同目录的 `algorithms.hpp` 和 `graph_types.hpp`；预处理（α、反向索引、CH shortcut）建一次，供所有查询复用。说明见 `算法/README.md`。

## 接口

**9 个接口全部写在 `接口/api.py` 一个文件里**，说明和字段见 `接口/接口说明.md`：

- `GET /api/config`、`GET /api/cache/status`
- `POST /api/benchmarks`、`GET /api/jobs/{job_id}`
- `GET /api/results/{summary, table, table.csv, dashboard, queries}`

`接口/cpp/` 是 C++ 测试器：`benchmark_main.cpp` 主程序、`rgraph_io` 读路网、`cache_io` 读写三种算法缓存、`query_io` 生成/读 OD。`api.py` 负责调度它并出图。

## 运行

以下命令在 `第二次作业/` 目录执行：

```powershell
# 生成预处理缓存（首次自动编译 C++；广东 CH 约 128 秒）
python .\接口\api.py --prepare

# 启动接口
python .\接口\api.py --serve

# 本地自测（图形界面）
python .\接口\api.py --gui
```

接口启动后打开 `http://127.0.0.1:8000/docs` 调试。

## 结果

1000 对 OD，单位 ms：

| 算法 | 南山区 | 深圳市 | 广东省 |
|---|---|---|---|
| Dijkstra | 0.782 | 6.792 | 123.599 |
| A* | 0.361 | 2.644 | 63.859 |
| 双向 A* | 0.275 | 2.105 | 66.520 |
| CH | 0.035 | 0.196 | 2.157 |

CH 单次最快，但广东省约 2,074 次查询才回收 128 秒预处理；南山、深圳选双向 A*，广东选 A*。

## 说明

- 测试器对每条 OD 额外跑一次 Dijkstra 校验，`mismatch_count` 全为 0。
- 缓存、编译产物、固定 OD 和中文字体都不入库；字体缺失时自动用系统中文字体。
- 报告在 `报告/`，AI 记录在 `AI使用说明/`。
