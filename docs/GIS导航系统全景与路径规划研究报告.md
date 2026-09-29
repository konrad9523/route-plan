# GIS 导航系统全景与路径规划研究报告

## 0. 结论先行

这份 PPT 的主线可以压缩成一句话：

> 把原始空间数据变成可查询的有向路网，再把用户位置和目的地映射到路网，计算一条满足偏好和约束的路线，最后由导航引擎把路线变成地图高亮、转向指令、语音播报和偏航重算。

本组负责的“路径规划”不是孤立地写一个 A* 函数，而是要完成一个可被其他模块调用的路由服务：

~~~
用户起终点/偏好
    ↓
坐标检查与起终点吸附（G3 空间索引）
    ↓
有向路网 + 边属性 + 转向限制（G2 路网模型）
    ↓
Dijkstra 基线 → A* → 双向 A* → 可选 ALT/CH/MLD
    ↓
RouteResult：边序列、几何、距离、时间、状态、诊断信息
    ↓
G5 地图匹配 / G6 导航引擎 / G8 渲染 / 平台适配组
~~~

推荐路线：

1. 先用 Dijkstra 做正确性基线。
2. 再实现 A*，使用不高估的启发式。
3. 加入单行道、通行权限、转向限制、转向代价和多种偏好。
4. 用基准图和真实 OSM 子图比较 Dijkstra、A*、双向 A* 的正确性、访问节点数和耗时。
5. 基础版本稳定后，再选 ALT/Landmark 或 CH/MLD 做进阶优化。

GraphHopper 最适合比较 flexible / hybrid / speed 三类算法模式；OSRM 最适合观察高性能 OSM 路由服务；Valhalla 最适合了解动态 costing、多模式和导航指令；pgRouting 最适合在 PostGIS 中做可解释的数据库实验。

---

## 1. PPT 阅读结果

已完整检查 PPT，共 65 页：

- 没有独立的 Excel 图表、SmartArt 或 Diagram XML。
- 主要内容由可编辑文本框、形状、流程箭头和图标组成。
- 第 1、64 页使用蓝色城市路网背景图，第 6、47 页使用蓝色路径和定位点背景图。
- 所有备注页为空。
- PPT 中的商业规模数字和部分性能数字没有逐项给来源，不能直接当作研究报告事实；答辩时应标为“课程设定/待验证指标”。

### 1.1 逐页主题索引

| 页码 | 内容 | 对本组的意义 |
|---|---|---|
| 1–5 | 课程定位、导航系统主线、核心算法、地面/无人机/AUV | 明确系统边界 |
| 6–10 | 导航定义、发展史、用户旅程、用户体验 | 路径规划只是“路线合理性”一环 |
| 11–15 | 四层架构、模块、数据流、接口原则、方案对比 | 明确 G4 上下游接口 |
| 16–18 | 坐标系、距离方向、矢量与 OSM 数据模型 | 路由输入输出的空间基础 |
| 19–23 | 地面/低空/AUV 差异、工程挑战、课程分组 | 二维道路图和三维运动规划的区别 |
| 24–25 | 项目时间线、工具链 | 可直接转成里程碑 |
| 26–32 | 用户痛点、性能、趋势、安全隐私 | 性能和容错也是工程任务 |
| 33–38 | 学习方法、OSM 标签、标准接口、评分 | 协作和接口约束 |
| 39–43 | FAQ、产品/产业生态、技术栈 | 课程原型与商业产品的差距 |
| 44–46 | 作业、文献、课程小结 | 进一步学习入口 |
| 47–55 | 坐标案例、状态机、渲染、更新、跨平台、AI、容错 | G4 必须支持重规划，但不负责全部 UI |
| 56–65 | 数据生命周期、空间索引、路径规划、引导、测试、优化、演进、总结 | G4 的主要实现和验收依据 |

### 1.2 “十二模块”编号的校正

PPT 有几处把“课程次数、算法组、平台组、功能模块”混在一起。建议统一使用稳定模块名：

| 层级 | 模块 | 职责 |
|---|---|---|
| 总纲 | 系统架构与接口 | 四层架构、数据流、容错、版本 |
| G1 | 数据生产 | OSM/PBF 解析、清洗、标准化 |
| G2 | 路网模型 | 节点/边、有向化、拓扑、转向限制 |
| G3 | 空间索引 | 最近边、范围查询、候选边 |
| G4 | 路径规划 | Dijkstra、A*、偏好、约束、备选路线、重规划 |
| G5 | 定位与地图匹配 | GNSS/IMU 融合、HMM、偏航检测 |
| G6 | 导航引擎 | 状态机、事件、引导、重算触发 |
| G7 | 数据存储 | SQLite/SpatiaLite、PostGIS、离线包、更新 |
| G8 | 地图渲染 | MVT/GeoJSON、路线和位置显示 |
| 额外 | 语音交互 | 导航语义、TTS |
| 额外 | 跨平台适配 | C++ 核心库和平台绑定 |
| 额外 | AI 辅助 | 交通预测、异常检测、开发辅助 |

如果只数 G1–G8、语音、跨平台、AI，得到的是 11 个功能组；第 1 讲的架构总纲或平台/容错被算作第 12 个课程主题时，才与“12 次课”一致。答辩时直接使用模块名和接口版本，不要纠结编号。

---

## 2. 全系统怎么串起来

### 2.1 四层架构

~~~
应用层：搜索框、地图、路线选择、开始/结束导航、语音、到达页
        ↑
引擎层：状态机、事件循环、模块调度、偏航检测、引导、异常处理
        ↑
算法层：坐标变换、空间索引、路径规划、地图匹配、定位融合、转向语义
        ↑
数据层：OSM/POI/路网/瓦片、GNSS/IMU、交通、轨迹、缓存
~~~

边界原则：

- 数据层提供可追溯数据，不偷偷改变算法语义。
- 算法层提供可测试服务，不能直接操作 UI。
- 引擎层管理时序和状态，不把状态机逻辑散落在 A*、渲染和 TTS 中。
- 应用层表达用户意图和显示结果，不直接修改路网权重。

### 2.2 三条链路

离线生产：

~~~
OSM PBF/XML / POI
 → 解析过滤
 → 标签清洗和坐标统一
 → 拓扑构建、道路分段、有向边
 → 转向限制、速度、通行权限
 → 空间索引和路由预处理
 → PostGIS/SQLite/二进制/离线包
~~~

按需规划：

~~~
搜索结果或地图点击
 → CRS 检查
 → 起终点吸附
 → 选择模式和偏好
 → G4 路径规划
 → 合法性检查
 → RouteResult
 → G8 画路线，G6 保存会话
~~~

实时导航：

~~~
GNSS/IMU
 → 定位融合
 → G3 候选道路
 → G5 HMM 地图匹配
 → G6 判断下一转向和偏航
 → 需要时调用 G4 重规划
 → G8 高亮 + 语音播报
~~~

### 2.3 用户旅程

搜索目的地 → POI/地理编码返回经纬度 → G3 找候选边 → G4 计算路线 → G8 展示 → G6 建立导航会话 → G5 每个周期输出匹配边 → G6 生成引导语义 → TTS/地图展示 → 偏航后重新调用 G4 → 到达后保存轨迹。

---

## 3. 模块和工具地图

### 3.1 数据获取与生产

| 工具 | 形态 | 模块 | 输入 → 输出 | 语言/API | 类似工具 |
|---|---|---|---|---|---|
| OpenStreetMap | 在线地图、Node/Way/Relation、标签 | G1/G2 | XML/PBF → 道路、POI、标签 | Web API、PBF、Overpass | 商业地图、政府路网 |
| Geofabrik | 区域下载站 | G1 | 区域 → osm.pbf | HTTP | BBBike Extract |
| Overpass | OSM 查询服务 | G1/POI | Overpass QL → XML/JSON | HTTP | 适合小范围，批量下载用 PBF |
| osmium-tool | 命令行数据处理工具 | G1 | PBF/XML → extract/filter/sort/统计 | C++ CLI | Osmosis、pyosmium |
| GDAL/OGR | CLI + C/C++ 库 + Python 绑定 | G1/G7 | 多种矢量/栅格格式互转 | C/C++、Python | QGIS Processing |
| QGIS | 桌面 GIS：图层面板、地图画布、属性表、工具箱 | 质检/可视化 | 矢量/栅格/数据库 → 地图 | C++、PyQGIS | ArcGIS Pro，功能强但商业授权 |

第一次实践建议：下载武汉或校园 PBF，用 osmium 统计和裁剪，用 QGIS 检查断路、单行道、桥隧和道路标签。

OSM PBF 是面向处理的二进制格式。OSM 对象包括 Node、Way、Relation；highway、oneway、maxspeed、access、bridge、tunnel 和 restriction 对路由尤其重要。参考：[OSM PBF](https://wiki.openstreetmap.org/wiki/PBF)、[Osmium Manual](https://docs.osmcode.org/osmium/latest/)。

### 3.2 坐标和空间计算

| 概念 | 用途 |
|---|---|
| WGS84 / EPSG:4326 | GNSS、OSM、全球交换 |
| Web Mercator / EPSG:3857 | Web 瓦片和显示，不适合高精度测量 |
| UTM/地方投影 | 以米为单位的局部几何 |
| GCJ-02/BD-09 | 某些中国地图服务的坐标适配边界 |
| Haversine | 球面近似直线距离和启发式 |
| 点到线段投影 | 起终点吸附、地图匹配 |
| bearing | 方向角和转向语义 |

PROJ 是通用坐标转换软件和 API，PyProj 是 Python 接口，参考：[PROJ](https://proj.org/en/stable/)。

每个几何对象必须带 CRS 或明确坐标约定。坐标系错了，距离、最近边、空间索引、渲染和规划可能一起错，而且程序未必报错。

### 3.3 路网和空间索引

建议的最小结构：

~~~
road_nodes(node_id, lon, lat, x, y, level, flags, geom)

road_edges(
  edge_id, from_node, to_node, length_m,
  speed_kmh, travel_time_s, road_type,
  oneway, access, toll, geom, source_way_id
)

turn_restrictions(
  restriction_id, from_edge, via_node,
  to_edge, type, penalty_s, conditional_rule
)
~~~

要点：

- 单行道转换为有向边，双向路通常生成两条边。
- 道路在路口、属性变化和转向限制位置分段。
- 转向限制不能只用节点表示；搜索状态至少要知道 incoming_edge 和 current_node。
- 桥、隧道、立交的几何相交不代表车辆可转弯。
- maxspeed、默认速度和实时估计速度要分开保存。

G3 只负责快速找附近道路，不负责最短路：

- R-tree：范围/相交查询。
- 网格：简单且适合均匀分布。
- KD-tree：点集合最近邻。
- H3/Geohash：分片和缓存。
- PostGIS GiST：空间数据库索引。

接口建议：

~~~python
range_query(lon, lat, radius_m) -> list[edge_id]
nearest_edges(lon, lat, k) -> list[(edge_id, distance_m)]
~~~

参考：[OSMnx](https://osmnx.readthedocs.io/en/stable/getting-started.html)、[PostGIS spatial indexes](https://postgis.net/documentation/faq/spatial-indexes/)。

### 3.4 定位与地图匹配

| 技术 | 作用 | 工具 |
|---|---|---|
| GNSS/GPS/北斗 | 绝对位置、时间、速度 | 手机 Location API、NMEA、RTKLIB |
| IMU | 高频短时运动变化 | Android/iOS 传感器 |
| EKF/卡尔曼 | 融合位置、速度、姿态 | 自研、robot_localization |
| 几何匹配 | 最近道路投影 | Shapely/GEOS/PostGIS |
| HMM 匹配 | 多候选道路序列 | GraphHopper、Valhalla、自研 Viterbi |

HMM 中，GPS 点是观测，附近道路位置是候选状态，发射概率反映点到路的距离，转移概率反映道路网络距离和 GPS 位移的一致性，Viterbi 选出最可能序列。经典来源：[Newson & Krumm 2009](https://www.microsoft.com/en-us/research/publication/hidden-markov-map-matching-noise-sparseness/)。

### 3.5 引导与语音

G4 输出边序列、几何和原始转向事件；G6 或专门的引导模块再把它变成自然语言：

~~~
边序列 + 道路名 + 交叉口拓扑
 → 转向类型/环岛出口/立交语义
 → 距离和播报时机
 → “前方 300 米右转”
 → TTS/视觉引导
~~~

Valhalla 把路由、costing、路径构建和 narrative generation 拆成组件，说明规划和播报应解耦。参考：[Valhalla route overview](https://valhalla.github.io/valhalla/api/turn-by-turn/overview/)。

### 3.6 存储、渲染、平台和 AI

| 模块 | 推荐工具 | 说明 |
|---|---|---|
| 空间数据库 | PostgreSQL + PostGIS | 路网、POI、空间查询、更新 |
| 移动端 | SQLite + SpatiaLite/GeoPackage | 离线图、缓存、轨迹 |
| 路由服务 | OSRM/GraphHopper/Valhalla | 真实 OSM 路由 |
| Web 地图 | MapLibre GL JS | WebGL、矢量瓦片、样式 |
| 轻量二维 | Leaflet | 简单 GeoJSON/瓦片 |
| 专业 Web GIS | OpenLayers | OGC、投影、MVT |
| 三维/无人机 | CesiumJS | 地形、3D Tiles、空域 |
| 语音 | 系统 TTS、Piper、eSpeak NG、Coqui | 文本到语音 |
| 跨平台 | C++ + CMake + vcpkg | 一套核心多端调用 |
| AI | PyTorch/TensorFlow/OpenCV | 交通预测、异常、视觉定位 |

MapLibre GL JS 是 TypeScript + WebGL 的开源矢量瓦片地图库，参考：[MapLibre GL JS](https://maplibre.org/maplibre-gl-js/docs/)。

---

## 4. 路径规划模块详细方案

### 4.1 输入输出边界

输入：

~~~json
{
  "start": {"lon": 114.36, "lat": 30.52, "crs": "EPSG:4326"},
  "end": {"lon": 114.42, "lat": 30.51, "crs": "EPSG:4326"},
  "mode": "car",
  "preference": "fastest",
  "avoid": ["toll"],
  "algorithm": "astar",
  "graph_version": "wuhan-demo-v1"
}
~~~

输出：

~~~json
{
  "status": "ok",
  "algorithm": "astar",
  "edge_ids": [101, 205, 333],
  "node_ids": [12, 31, 44, 57],
  "geometry": {"type": "LineString", "coordinates": [[114.36,30.52],[114.42,30.51]]},
  "distance_m": 7340.2,
  "duration_s": 1128.6,
  "graph_version": "wuhan-demo-v1",
  "diagnostics": {
    "expanded_nodes": 1842,
    "planning_ms": 8.4,
    "start_snap_distance_m": 12.1
  }
}
~~~

algorithm、graph_version、diagnostics 对性能实验和问题复现很重要。

### 4.2 起终点吸附

1. 检查坐标范围和 CRS。
2. G3 查询一定半径内的候选边。
3. 把点投影到候选边几何线上。
4. 过滤模式不允许、方向不合法或封闭的边。
5. 创建虚拟节点，或计算第一条/最后一条边的部分代价。
6. 保存吸附距离；超过阈值返回 SNAP_TOO_FAR。

不要简单地把点吸到最近路口，否则短路线、单行道、高架和起步方向会出错。

### 4.3 权重

~~~
travel_time(e) = length_m(e) / effective_speed_mps(e)

cost(path) =
    α · total_time
  + β · total_distance
  + γ · toll_cost
  + δ · turn_penalty
  + ε · risk_penalty
~~~

禁行或硬约束用不可用边/转移表示。权重逻辑封装成 CostModel，不要把大量业务判断写进 A* 主循环。

~~~python
class CostModel:
    def edge_cost(self, edge, arrival_time=None):
        if not edge.allowed:
            return float("inf")
        speed = edge.speed_kmh * 1000 / 3600
        return edge.length_m / max(speed, 0.1)

    def transition_cost(self, prev_edge, next_edge):
        if (prev_edge.id, next_edge.id) in self.forbidden_turns:
            return float("inf")
        return self.turn_penalties.get((prev_edge.id, next_edge.id), 0.0)
~~~

### 4.4 Dijkstra 基线

Dijkstra 在非负边权下用优先队列逐步确定最小代价。PPT 将它称为“广度优先搜索”不够准确：BFS 是等权特殊情形，带时间/距离权重时应使用优先队列。

~~~python
from heapq import heappush, heappop

def dijkstra(graph, source, target, cost_model):
    dist = {source: 0.0}
    parent = {}
    pq = [(0.0, source)]

    while pq:
        g, u = heappop(pq)
        if g != dist.get(u):
            continue
        if u == target:
            return rebuild_path(parent, target), g

        for edge in graph.out_edges(u):
            w = cost_model.edge_cost(edge)
            if w == float("inf"):
                continue
            cand = g + w
            if cand < dist.get(edge.to_node, float("inf")):
                dist[edge.to_node] = cand
                parent[edge.to_node] = (u, edge.id)
                heappush(pq, (cand, edge.to_node))

    return None, float("inf")
~~~

有转向限制时，搜索键要扩展为 incoming_edge_id 和 node_id，不能只以 node 为状态。

### 4.5 A* 核心

A* 使用：

~~~
f(n) = g(n) + h(n)
~~~

g 是已知代价，h 是剩余代价下界。启发式不高估时才能保留最优性保证。经典论文：[Hart, Nilsson & Raphael 1968](https://www.cs.auckland.ac.nz/courses/compsci709s2c/resources/Mike.d/astarNilsson.pdf)。

- 优化距离：h 为球面直线距离。
- 优化时间：h 为球面直线距离除以全图允许的最大速度。
- 不能无条件把直线距离当成时间启发式，否则可能高估并破坏最优性。

~~~python
def astar(graph, source, target, cost_model, heuristic):
    g_score = {source: 0.0}
    parent = {}
    pq = [(heuristic(source, target), 0.0, source)]

    while pq:
        f, g, u = heappop(pq)
        if g != g_score.get(u):
            continue
        if u == target:
            return rebuild_path(parent, target), g

        for edge in graph.out_edges(u):
            w = cost_model.edge_cost(edge)
            if w == float("inf"):
                continue
            v = edge.to_node
            new_g = g + w
            if new_g < g_score.get(v, float("inf")):
                g_score[v] = new_g
                parent[v] = (u, edge.id)
                heappush(pq, (new_g + heuristic(v, target), new_g, v))

    return None, float("inf")
~~~

### 4.6 转向限制和搜索状态

如果 A→B 后不能左转到 B→C，只保存 B 不够，因为到达 B 的前一条边不同，允许的下一步可能不同。建议：

~~~
state = (previous_edge_id, current_node_id)
transition = (previous_edge_id, next_edge_id)
~~~

这样：

- g_score 的键是状态而不是 node。
- parent 保存前驱状态。
- 扩展相邻边时计算 turn penalty。
- 启发式仍使用当前位置到目标的下界，不随意加入无法证明的转向估计。

### 4.7 算法路线

| 算法 | 优点 | 局限 | 项目定位 |
|---|---|---|---|
| Dijkstra | 易证明、保证最优 | 搜索范围大 | 正确性 oracle |
| A* | 少扩展很多节点 | 需要可靠启发式 | 第一阶段主算法 |
| 双向 A* | 点到点更快 | 停止和路径拼接复杂 | 第二阶段 |
| ALT/Landmark | 预处理后快且灵活 | 额外存储和预处理 | 进阶教学 |
| CH | 静态路网极快 | 预处理重，动态修改不灵活 | 工程优化 |
| MLD | 分区后支持 customize | 构建复杂 | 大路网和动态权重 |
| 时间依赖最短路 | 表示早晚高峰 | 需要时间函数和一致性条件 | 交通进阶 |
| Yen KSP | 备选路线 | K 增大会变慢、路线可能重叠 | 备选路线 |
| Pareto 多目标 | 表达真实偏好 | 标签可能爆炸 | 研究扩展 |
| D* Lite | 局部变化可增量更新 | 实现复杂 | 动态图研究 |

GraphHopper 官方把 flexible、hybrid、speed 分别对应 Dijkstra/A*、Landmarks、CH。参考：[GraphHopper routing](https://github.com/graphhopper/graphhopper/blob/master/docs/core/routing.md)。

OSRM 官方提供 CH 和 MLD 预处理，route、table、match、trip、nearest、tile 等服务；MLD 可通过 customize 更新边速度和转向代价。参考：[OSRM API](https://project-osrm.org/docs/)、[OSRM tools](https://project-osrm.org/docs/v26.4.0/tools)。

Valhalla 使用分块路网、动态 costing、双向 A*、多模式和时间依赖，适合动态导航研究，但工程复杂度高。参考：[Valhalla](https://valhalla.github.io/valhalla/)、[Thor](https://valhalla.github.io/valhalla/thor/)。

### 4.8 多偏好和备选路线

课程阶段先用可解释的 CostModel：

~~~
fastest      → 最小 travel_time
shortest     → 最小 length_m
avoid_tolls  → toll 边禁用或高惩罚
no_highway   → highway 边禁用或高惩罚
~~~

不要把加权和直接称为严格“多目标最优”，更准确的说法是“在给定 CostModel 下求单目标最短路”。

备选路线需要控制与主路线的边重叠率，否则几条路线可能只是局部不同。可加入 overlap(route_i, route_best) 小于阈值。

### 4.9 偏航重规划

1. G5 输出当前位置、匹配边和置信度。
2. G6 判断匹配边是否在当前路线的允许窗口内。
3. 连续若干次偏离或距离路线超过阈值，确认偏航。
4. 重新吸附和规划。
5. 规划期间继续显示旧路线或“正在重新规划”。
6. 新路线成功后原子替换导航会话中的路线。

道路封闭可改边权或可用性。局部图变化可以研究 D* Lite；实时交通全局变化更适合重新计算或使用 CH/MLD customization。

---

## 5. 开源项目对比

| 项目 | 语言/形态 | 核心能力 | 数据/接口 | 最适合怎么学 |
|---|---|---|---|---|
| GraphHopper | Java 库 + Web 服务 | Dijkstra、A*、Landmark、CH、车辆 profile、匹配、指令 | OSM XML/PBF、GTFS、HTTP/Java | 算法模式切换和 CostModel |
| OSRM | C++ 服务 | CH/MLD、高性能机动车路由、矩阵、匹配 | PBF → .osrm，HTTP/Node/Python | 生产级预处理和性能 |
| Valhalla | C++ 分层服务 | 动态 costing、多模式、时间依赖、匹配、语义指令 | OSM/GTFS/tiles，JSON/Protobuf | 复杂导航系统组件化 |
| pgRouting | PostgreSQL 扩展 | Dijkstra、A*、双向搜索、KSP、TSP | PostGIS 路网表 + SQL | 图算法与空间数据库 |
| openrouteservice | 完整 GIS 路由平台 | 路由、矩阵、等时圈、吸附、导出 | REST | 快速获得服务能力 |
| Neo4j GDS | 图数据库算法库 | Dijkstra、A*、Yen 等 | 属性图 + Cypher | 图算法实验和可视化 |
| OSMnx + NetworkX | Python 库 | 下载、清洗、分析、基础最短路 | GeoDataFrame + MultiDiGraph | 小规模实验和画图 |

本组应同时维护：

~~~
自研 Dijkstra/A*：解释原理、可控、可测试
GraphHopper/OSRM：真实 OSM 结果和性能对照
Valhalla/pgRouting：动态 costing 或数据库参考
~~~

公共演示服务器不应作为稳定依赖；应固定本地数据版本、软件版本、下载时间和许可信息。

---

## 6. 项目落地方案

### 6.1 MVP

~~~
固定 OSM 子图
 → 标准化有向边表
 → 最近边吸附
 → Dijkstra oracle
 → A* 主算法
 → shortest/fastest
 → RouteResult JSON/GeoJSON
 → Leaflet/MapLibre 展示
 → 偏航后重新规划
~~~

MVP 必须能回答：

- 路线是否在有向路网中连续？
- A* 和 Dijkstra 的代价是否一致？
- A* 少访问了多少节点？
- 坐标系和起终点吸附是否正确？
- 不可达时是否返回明确错误而不是崩溃？

### 6.2 第二阶段

- 单行道、通行权限、边内吸附。
- 转向限制和 turn penalty。
- fastest、shortest、avoid_tolls、no_highway。
- 错误码：INVALID_COORDINATE、SNAP_TOO_FAR、NO_ROUTE。
- HTTP/Python API。
- p50/p95 规划耗时和扩展节点数。

### 6.3 第三阶段

- 双向 A* 或 ALT 二选一。
- K 条低重叠备选路线。
- 动态边权和偏航重算。
- 路线几何简化、转向点提取。
- 离线子图或端云协同。

不建议一开始做全国级 CH/MLD、实时交通采集、全模式导航、无人机/AUV、或把 AI 直接放进最短路循环。

---

## 7. 接口协议

G2 → G4：

~~~
road_nodes.csv
road_edges.csv
turn_restrictions.csv
graph_meta.json
~~~

元数据至少包含：

~~~json
{
  "graph_version": "wuhan-demo-v1",
  "crs": "EPSG:4326",
  "distance_unit": "m",
  "time_unit": "s",
  "speed_unit": "km/h",
  "vehicle_modes": ["car"],
  "source_pbf": "wuhan-2026-09.osm.pbf"
}
~~~

G3 → G4：

~~~python
nearest_edges(lon, lat, k=8, mode="car")
    -> [(edge_id, projected_lon, projected_lat, distance_m, heading)]
~~~

G4 → G5/G6/G8：

~~~python
plan_route(request: RouteRequest) -> RouteResult
~~~

RouteResult 应包含：

~~~text
status
edge_ids
node_ids
geometry
distance_m
duration_s
maneuvers_raw
graph_version
diagnostics
~~~

G4 输出原始转向事件即可；自然语言和 TTS 由 G6/语音模块处理。

---

## 8. 测试和验收

必测案例：

1. 三节点链：唯一最短路。
2. 两条备选路径：距离/时间切换。
3. 单行道：反向不可达。
4. 禁止左转：禁止转移不能出现。
5. 起终点在同一条边。
6. 起点附近没有边。
7. 两个分离连通分量。
8. 起点终点相同。
9. CRS 或坐标范围错误。
10. 图版本变化和缓存污染。

交叉验证：

- 小图手工答案。
- 随机非负权图，以 NetworkX Dijkstra 为 oracle。
- A* 的代价与 Dijkstra 相同。
- 真实 OSM 子图与 GraphHopper/OSRM 对照，但记录不同 profile、速度和转向模型。

| 指标 | 建议目标 |
|---|---:|
| 正确性 | A* 与 Dijkstra 代价一致 |
| 规划耗时 | 小城市 p95 < 100 ms，需实测 |
| 偏航重算 | demo 图 p95 < 500 ms，需实测 |
| 路径连续性 | 100% 相邻边可连接 |
| 可行性 | 不走禁行、反向和禁转 |
| 失败处理 | 明确错误码、不崩溃 |
| 备选路线 | 记录边重叠率 |
| 复现性 | 固定图版本、机器、软件和查询集 |

PPT 中的性能数字只能作为课程目标，不能脱离数据和硬件直接宣称已达到。

---

## 9. 五人分工

| 成员 | 主责 | 交付 |
|---|---|---|
| 1 | 组长/接口与数据契约 | RouteRequest/Result、版本、错误码、README、集成 |
| 2 | 图加载与 Dijkstra | 邻接表、数据读取、Dijkstra、路径合法性 |
| 3 | A* 与性能 | 启发式、双向 A*、基准和 profiling |
| 4 | 约束与偏好 | 单行道、权限、转向限制、CostModel |
| 5 | 服务/展示/QA | API、GeoJSON、地图 demo、测试流水线 |

共同约束：

- 成员 2 的 Dijkstra 是全组 oracle。
- 成员 3 的每次 A* 改动都必须和 Dijkstra 对拍。
- 成员 4 的约束必须有最小反例图。
- 成员 5 的 API 不能改变算法核心返回语义。
- 成员 1 维护接口，不替代其他成员完成实现。

所有人共同掌握：

1. Git、代码评审和冲突解决。
2. Python、pytest、日志和虚拟环境。
3. 图论、优先队列、复杂度和最短路。
4. CRS、EPSG、投影、点线面、空间索引。
5. OSM Node/Way/Relation 和核心标签。
6. JSON/CSV/GeoJSON/SQLite/PBF。
7. HTTP API、错误码、缓存和异步。
8. 单元测试、基准测试、边界测试。
9. OSM ODbL、地图服务条款和位置隐私。
10. 阅读官方文档、论文和开源代码。

### 9.1 12 周节奏

| 周 | 目标 |
|---|---|
| 1 | 接口、标准小图、错误码、测试数据 |
| 2 | 图加载、邻接表、Dijkstra |
| 3 | A*、启发式和对拍 |
| 4 | 接入 G2/G3，完成数据层里程碑 |
| 5 | 起终点吸附、单行道、通行权限 |
| 6 | 转向限制和 turn penalty |
| 7 | 多偏好、GeoJSON、服务接口 |
| 8 | 双向 A* 或 ALT |
| 9 | G5/G6/G8 集成、偏航重算 |
| 10 | profiling、缓存、错误降级 |
| 11 | 真实 OSM 案例、演示和图表 |
| 12 | 回归测试、文档、答辩 |

---

## 10. PPT 中需谨慎的表述

1. Dijkstra 不是普通 BFS；带权图应强调优先队列。
2. A* 启发式必须匹配目标函数；最快路线不能直接用直线距离。
3. A*、CH 和 HMM 的性能数字取决于数据、硬件和实现。
4. 高德、百度、Google 的商业规模数字需要来源。
5. 坐标转换必须明确方向、区域、来源和服务条款。
6. Haversine 误差不是固定小于某个百分比。
7. “路网缺失用直线引导”不适合直接作为驾驶安全策略，应提示无可靠路线或引导到最近已知道路。
8. G4 输出路径和原始转向事件，G6/语音模块负责自然语言、时机和 TTS。
9. 平台适配组消费统一接口，不应复制核心算法。
10. AI 先用于预测、异常和开发辅助，不能替代可解释的图模型和约束。

---

## 11. 建议阅读顺序和资料

基础资料：

- [OSM PBF Format](https://wiki.openstreetmap.org/wiki/PBF)
- [Osmium Manual](https://docs.osmcode.org/osmium/latest/)
- [GDAL/OGR](https://gdal.org/en/stable/)
- [QGIS](https://qgis.org/project/overview/)
- [PROJ](https://proj.org/en/stable/)
- [OSMnx](https://osmnx.readthedocs.io/en/stable/)
- [OSRM](https://project-osrm.org/docs/)
- [GraphHopper](https://github.com/graphhopper/graphhopper)
- [Valhalla](https://valhalla.github.io/valhalla/)
- [pgRouting](https://docs.pgrouting.org/latest/en/)
- [MapLibre GL JS](https://maplibre.org/maplibre-gl-js/docs/)
- [PostGIS spatial indexes](https://postgis.net/documentation/faq/spatial-indexes/)

经典论文：

- [Hart, Nilsson & Raphael, A*](https://www.cs.auckland.ac.nz/courses/compsci709s2c/resources/Mike.d/astarNilsson.pdf)
- [Newson & Krumm, HMM Map Matching](https://www.microsoft.com/en-us/research/publication/hidden-markov-map-matching-noise-sparseness/)
- [Geisberger et al., Contraction Hierarchies](https://i11www.iti.kit.edu/extra/publications/gssd-chfsh-08.pdf)
- [Guttman, R-trees](https://www.cs.princeton.edu/courses/archive/fall08/cos597B/papers/rtrees.pdf)

### 11.1 一套可直接落地的原型栈

建议先采用：

~~~text
Geofabrik OSM PBF
  → OSMnx/NetworkX 有向路网
  → 自研 Dijkstra/A*
  → FastAPI 路由服务
  → GeoJSON
  → MapLibre GL JS
~~~

地理编码只负责“地点名 → 经纬度”，不负责道路连通性和路线。Nominatim 适合低频、缓存或自建服务；公共服务有使用政策和限速要求，不能在演示程序中无节制批量调用。正式演示应准备固定地址测试集，或使用本地 Nominatim/Photon。参考：[Nominatim Search API](https://nominatim.org/release-docs/develop/api/Search/)、[Nominatim Usage Policy](https://operations.osmfoundation.org/policies/nominatim/)。

前端只消费 RouteResult 中的 GeoJSON、距离、时间、边属性和原始转向事件；它不应复制 A* 或偷偷改变 CostModel。OSRM、GraphHopper、Valhalla 和 pgRouting 作为独立对照，分别观察高性能预处理、算法模式、自定义 costing、多模式导航和空间数据库集成。

---

## 12. 最终落地判断

第一版目标不是“像高德一样完整”，而是做出一条能被证明、能被测试、能被替换的 G4：

~~~
固定 OSM 子图
 → 标准化有向边表
 → 最近边吸附
 → Dijkstra oracle
 → A* 主算法
 → 单行道/转向限制/偏好
 → RouteResult JSON/GeoJSON
 → 地图展示
 → 偏航后重规划
~~~

完成这个闭环后，再做双向 A*、ALT、CH/MLD、动态交通、K 条路线和多目标优化。你们真正要交付的不是一个高级算法名，而是一条能从数据到路线、从路线到导航、从异常回到重规划的可解释数据链路。
