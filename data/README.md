# 共享数据目录

> **本项目所有共享数据的唯一正式位置。** 不要在别处放数据副本。
>
> 数据说明见本文件；机器可读的元信息见 [`graph_meta.json`](graph_meta.json)。

---

## 数据清单

| 数据集 | 文件 | 规模 | 用途 |
|---|---|---|---|
| 校园路网 | [`campus_552.graphml`](campus_552.graphml) | 552 节点 / 1400 有向边 | 作业 1 的真实路网基础 |

---

## campus_552

### 基本信息

| 项 | 值 |
|---|---|
| 图版本 | `campus-552-v1` |
| 规模 | **552 节点 / 1400 条有向边** |
| 覆盖范围 | 中国地质大学（武汉）周边，约 114.375–114.413°E、30.509–30.541°N |
| 坐标系 | `EPSG:4326`（WGS84 经纬度） |
| 来源 | OpenStreetMap，经 OSMnx 2.0.7 抓取 |
| 抓取时间 | 2026-09-15 |
| 许可 | **ODbL 1.0**，© OpenStreetMap contributors |
| 生成命令 | `python docs/learning/osmnx_demo/route_demo.py --dist 1800` |

### 字段与单位

| 字段 | 单位 | 说明 |
|---|---|---|
| `length_m` | 米 | 道路长度，来自 OSM 几何折线 |
| `speed_kmh` | km/h | 限速；缺失时按道路类型取默认值 |
| `road_type` | — | OSM `highway` 标签（residential / tertiary / trunk 等） |
| `geometry` | WKT LINESTRING | 道路真实折线，坐标顺序是 **`经度 纬度`** |
| `lon` / `lat` | 十进制度 | 节点坐标，顺序是 **`(lon, lat)`** |

> ⚠️ **单位陷阱**：`cost` 在 `shortest` 偏好下是**米**，在其余偏好下是**秒**，
> **不可直接横向比较**。`duration_s` 恒为秒，可以跨偏好比较。

### 已知的数据特征

| 特征 | 数值 | 影响 |
|---|---|---|
| 最大强连通分量 | **527 / 552** | **有 25 个节点无法与主路网双向通达**，演示时点到这些点会"无路可达" |
| 带几何的边 | **731 / 1400（52.2%）** | 其余边用两端路口坐标兜底，路线绘制会是直线段 |
| 几何自洽性 | `min(length / 端点直线距离) = 1.000` | ✅ 没有边比直线还短 |
| 启发式一致性违反 | **0** | ✅ **因此 A\* 在这份数据上保证最优** |
| `road_type` 分布 | residential 852、unclassified 317、tertiary 107、其余 124 | — |

> `length / 端点直线距离` 最小值为 1.000 是一个**重要性质**：
> 它意味着"直线距离 ÷ 最大速度"这个启发式满足一致性，A\* 的最优性有保证。
> 若换成几何不自洽的数据，A\* 会**静默返回次优路径**——
> 用 `path_planning.check_heuristic_consistency()` 可以提前检测。

### 谁在用这份数据

| 使用方 | 位置 | 用途 |
|---|---|---|
| HTTP 服务 | `api/main.py` | 加载路网提供服务 |
| 测试 | `tests/test_osm_loader.py`、`test_router_regressions.py`、`test_search_trace.py` | 真实路网测试 |
| 数据加载器 | `src/path_planning/osm_loader.py` | GraphML → `Graph` |

### 更新这份数据时

1. 重新生成后写入 `data/campus_552.graphml`
2. **同步更新 [`graph_meta.json`](graph_meta.json)**（节点数、边数、连通性、几何覆盖率等）
3. 更新本文件的"已知的数据特征"表
4. 跑一遍测试：`python -m unittest discover -s tests`
5. 在 `CHANGELOG.md` 记一条（数据变更会影响所有下游结论的可比性）

> ⚠️ **换数据等于换了实验基线。** 性能数字、路径对比、算法评估全部依赖这份数据，
> 变更前必须通知 A2/A3/A4/A5。

---

## 关于 `docs/learning/osmnx_demo/output/`

那个目录里的 `graph.graphml` 是**下载脚本的原始产出**，与 `data/campus_552.graphml` 内容相同。

**正式使用请读 `data/campus_552.graphml`。** 脚本产出目录保留为生成过程的痕迹。
