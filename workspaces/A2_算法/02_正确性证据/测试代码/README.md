# 正确性测试代码

本目录每个脚本单独运行一个测试，不会自动启动其他测试。图表和 CSV 保存在上一级 `results/<路网名>/`。

## 目录结构

测试代码/
├── _common/
│   ├── test_support.py        # 公共支持模块
│   └── networks.py            # 路网注册表
├── 1.小图三方对拍——暴力枚举_Dijkstra_Astra.py
├── 2.真实路网对拍.py
├── 3.可采纳性扫描.py
├── 4一致性扫描.py
├── 5.不可采纳反例.py
├── 6.边界情况.py
└── test_graphml_loader.py     # GraphML 加载器单元测试

## 测试清单

| 测试 | 脚本 | 图来源 | 数据量 | 内容 |
|---|---|---|---|---|
| T1 | 1.小图三方对拍——暴力枚举_Dijkstra_Astra.py | 构造图（随机小图） | 30 张图，150 对起终点 | 暴力枚举 vs Dijkstra vs A* 三方对拍 |
| T2 | 2.真实路网对拍.py | 真实路网 | 1000 对起终点 | Dijkstra 与 A* 代价一致性 |
| T3 | 3.可采纳性扫描.py | 真实路网 | 20 个终点 × 全图节点 | Haversine 启发值可采纳性扫描 |
| T4 | 4一致性扫描.py | 真实路网 | 20 个终点 × 全图边 | Haversine 启发值一致性扫描 |
| T5 | 5.不可采纳反例.py | 构造图 | 4 节点小图，1 对起终点 | 人为放大启发值，验证 A* 返回次优路径 |
| T6 | 6.边界情况.py | 构造图（极小图） | 10 类用例 | 边界输入和异常处理 |

T1、T5、T6 用构造图：T1 需要暴力枚举，T5 需要构造“地理远但边权便宜”的特殊场景，T6 需要精确控制边界输入。

T2、T3、T4 用真实路网：验证真实数据上的正确性和理论性质。

## 选择路网

真实路网测试支持切换路网，通过 `--network` 参数选择。

可选路网（在 `_common/networks.py` 中登记）：

| 路网名 | 标签 | 路网文件 |
|---|---|---|
| shenzhen | 深圳 | workspaces/A1_数据/01_路网清单/processed/shenzhen_driving_optimized.graphml |
| washington | 华盛顿 | workspaces/A1_数据/01_路网清单/processed/washington_driving_optimized.graphml |

默认路网：`shenzhen`（可在 `_common/networks.py` 里改 `DEFAULT_NETWORK`）。

结果目录：按路网自动分文件夹，互不覆盖。

results/
├── 深圳/
│   ├── T2_真实路网对拍.csv
│   ├── T2_真实路网散点图.png
│   └── T2_summary.json
└── 华盛顿/
    ├── T2_真实路网对拍.csv
    ├── T2_真实路网散点图.png
    └── T2_summary.json

用法：

    # 默认深圳，结果写到 results/深圳/
    python .\workspaces\A2_算法\02_正确性证据\测试代码\2.真实路网对拍.py

    # 指定深圳
    python .\workspaces\A2_算法\02_正确性证据\测试代码\2.真实路网对拍.py --network shenzhen

    # 指定华盛顿，结果写到 results/华盛顿/
    python .\workspaces\A2_算法\02_正确性证据\测试代码\2.真实路网对拍.py --network washington

    # 临时直接指定 GraphML（覆盖 --network）
    python .\workspaces\A2_算法\02_正确性证据\测试代码\2.真实路网对拍.py --graphml "某个路网.graphml"

新增路网：在 `_common/networks.py` 的 `NETWORKS` 里加一条即可，所有脚本自动支持。

    NETWORKS = {
        "washington": {...},
        "shenzhen": {...},
        "beijing": {
            "graphml": DATA_DIR / "beijing_driving_optimized.graphml",
            "label": "北京",
        },
    }

## 辅助文件

### `_common/test_support.py`

公共支持模块，所有测试脚本共用。主要功能：

| 功能 | 说明 |
|---|---|
| 中文字体自动检测 | 按 Windows / macOS / Linux 候选列表选可用中文字体，避免图表中文显示为方框 |
| 加载算法 | 从 01_实现清单/ 动态加载 dijkstra.py 和 astra.py |
| 加载路网 | 调 load_graphml 解析 GraphML，并计算 Haversine 安全比例 α |
| 反向 Dijkstra | 算所有节点到某终点的真实最短距离，供 T3 可采纳性扫描用 |
| 画路网图 | draw_road_map 画扩展节点、边界、最终路径 |
| 抽样可达起终点 | sample_reachable_pairs 供 03 目录的 T1~T5 用 |
| 保存 CSV / JSON | save_csv、write_json、print_result |
| 参数解析 | add_common_arguments 加 --network、--graphml、--output-dir、--seed |
| 路网解析 | resolve_args 把 --network 解析成路网文件和结果目录 |

### `_common/networks.py`

路网注册表，集中管理可选路网及其结果目录名。

| 功能 | 说明 |
|---|---|
| NETWORKS | 登记所有可选路网，每项含 graphml 路径和 label |
| DEFAULT_NETWORK | 默认路网，不传 --network 时用它 |
| get_network(name) | 按名称取路网信息，校验文件存在 |
| results_dir(base, name) | 返回 base / <路网名>，实现结果按路网分目录 |

### `test_graphml_loader.py`

GraphML 加载器的单元测试，验证 load_graphml 能正确解析路网文件。

load_graphml 是所有真实路网测试的入口。T2~T6 都依赖它把 GraphML 文件解析成 graph、positions、geometries。如果加载器有 bug，后面所有测试都不可信。

该单元测试用最小 GraphML 样本验证两件事：

| 测试 | 内容 | 预期 |
|---|---|---|
| test_loads_directed_edges_coordinates_and_line_geometry | 加载一个含两个节点、一条有向边、带线几何的 GraphML | graph 正确解析出边、positions 正确解析出经纬度、geometries 正确解析出线几何 |
| test_rejects_undirected_graphml | 加载 edgedefault="undirected" 的 GraphML | 抛 ValueError，提示必须是 directed |

为什么需要它：

- 它是整个测试链的最底层验证。加载器正确，后续测试才可信。
- 换路网时先跑它，确认新文件格式没问题，再跑大测试。
- 答辩时能回答“你怎么保证路网加载没问题”。

运行方式：

    python -m unittest .\workspaces\A2_算法\02_正确性证据\测试代码\test_graphml_loader.py

预期输出 OK，2 项测试通过。

## 运行

从项目根目录执行，例如：

    # 构造图测试（不依赖路网）
    python .\workspaces\A2_算法\02_正确性证据\测试代码\1.小图三方对拍——暴力枚举_Dijkstra_Astra.py
    python .\workspaces\A2_算法\02_正确性证据\测试代码\5.不可采纳反例.py
    python .\workspaces\A2_算法\02_正确性证据\测试代码\6.边界情况.py

    # 真实路网测试（默认深圳）
    python .\workspaces\A2_算法\02_正确性证据\测试代码\2.真实路网对拍.py --pairs 1000
    python .\workspaces\A2_算法\02_正确性证据\测试代码\3.可采纳性扫描.py --targets 20
    python .\workspaces\A2_算法\02_正确性证据\测试代码\4一致性扫描.py --targets 20

    # 真实路网测试（指定华盛顿）
    python .\workspaces\A2_算法\02_正确性证据\测试代码\2.真实路网对拍.py --network washington --pairs 1000
    python .\workspaces\A2_算法\02_正确性证据\测试代码\3.可采纳性扫描.py --network washington --targets 20
    python .\workspaces\A2_算法\02_正确性证据\测试代码\4一致性扫描.py --network washington --targets 20

    # GraphML 加载器单元测试
    python -m unittest .\workspaces\A2_算法\02_正确性证据\测试代码\test_graphml_loader.py

## 常用参数

| 参数 | 说明 | 适用 |
|---|---|---|
| --network | 选择路网，默认 shenzhen | T2、T3、T4 |
| --graphml | 直接指定 GraphML 路径，覆盖 --network | T2、T3、T4 |
| --pairs | 随机起终点对数，默认 1000 | T2 |
| --targets | 抽样终点数量，默认 20 | T3、T4 |
| --seed | 随机种子，默认 42 | 全部 |
| --output-dir | 输出目录，不传时按路网自动命名 | 全部 |

## 依赖

- 核心算法零第三方依赖。
- 画图需要：python -m pip install matplotlib pillow