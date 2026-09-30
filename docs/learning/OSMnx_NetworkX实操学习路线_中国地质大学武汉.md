# OSMnx + NetworkX 实操学习路线

> **本文性质：教学资料（学习路线），不是进度报告。**
> 它把"从 OSM 数据到路径规划"拆成 15 步，其中**很多步骤是刻意留给你自己动手做的**——
> 所以文中"下一步做 X"不代表 X 还没做，而是"这一步该由你来练"。
>
> **入门建议**：先读 `docs/learning/notes/学习笔记_01~04`（从读懂自研内核到接通真实路网），
> 再按本文做 OSMnx 侧的练习。两者的分工是：
> **学习笔记讲"我们自己的引擎怎么做"，本文讲"OSMnx/NetworkX 这条官方路线怎么走"。**
>
> 最后核对：2026-09-18

## 实验主题

> 使用中国地质大学（武汉）及周边道路，逐步完成从 OpenStreetMap 数据获取到多目标路径规划的学习项目。

本路线不是让你直接阅读一个大型导航引擎的全部源代码，而是把真实导航系统拆成一组可以运行、可以修改、可以验证的小实验。

最终要完成：

~~~text
OSM 数据
  → 道路网络
  → 图结构
  → Dijkstra
  → A*
  → 不同交通主体
  → 多目标权重
  → 地图展示
  → GPS 轨迹与重规划
  → DEM 应急路线
  → FastAPI 服务
  → 路径规划智能体
~~~

---

## 1. 先明确这个项目中每个开源库负责什么

| 组件 | 负责什么 | 暂时不要把它误认为 |
|---|---|---|
| OpenStreetMap | 提供现实世界地图数据 | 不是已经完成的路径规划系统 |
| OSMnx | 下载 OSM 数据、构建和分析道路网络 | 不是完整导航 App |
| NetworkX | 处理图和最短路算法 | 不是 GIS 数据库 |
| GeoPandas/Shapely | 处理矢量空间数据和几何 | 不是路线算法本身 |
| PyProj | 坐标系转换 | 不是地图渲染器 |
| Folium | 把结果显示成 HTML 地图 | 不是路径规划算法 |
| QGIS/GDAL | 检查和处理 GIS 数据、DEM | 不是在线导航服务 |
| FastAPI | 把算法封装成接口 | 不是图算法 |
| LangGraph 等 | 编排工具和智能体流程 | 不能替代确定性的路径算法 |

学习时始终记住：

~~~text
OSMnx 负责数据和路网
NetworkX 负责图算法
我们自己负责理解、修改和组合
~~~

## 2. 当前项目目录

目前已经创建了：

~~~text
docs/learning/osmnx_demo/
├── README.md
├── requirements.txt
├── route_demo.py
└── output/
    ├── route_demo.html
    ├── graph.graphml
    └── route_summary.json
~~~

核心文件：

- route_demo.py：主程序；
- README.md：运行说明；
- requirements.txt：依赖；
- output/route_demo.html：路线地图；
- output/graph.graphml：保存后的道路图；
- output/route_summary.json：路线统计。

现有程序已经实现：

- 中国地质大学（武汉）周边路网下载；
- 以学校为中心、半径 1800 米抓取道路；
- drive、bike、walk 等交通网络类型；
- 道路长度权重；
- 旅行时间权重；
- NetworkX Dijkstra；
- 路线地图绘制；
- GraphML 和 JSON 输出；
- 有向图强连通分量选择。

## 3. 第零步：准备 Python 环境

### 3.1 使用虚拟环境

建议每个人使用独立环境：

~~~powershell
python -m venv .venv
.venv/Scripts/Activate.ps1
~~~

如果当前电脑使用 Miniconda，也可以直接使用已有解释器。

### 3.2 安装依赖

~~~powershell
python -m pip install -r docs/learning/osmnx_demo/requirements.txt
~~~

依赖主要包括：

- osmnx；
- networkx；
- folium；
- geopandas；
- shapely；
- pyproj；
- pyogrio。

### 3.3 检查安装

~~~powershell
python -c "import osmnx, networkx, folium; print(osmnx.__version__, networkx.__version__, folium.__version__)"
~~~

如果输出版本号，说明基础环境正常。

## 4. 第一步：第一次运行项目

在项目根目录执行：

~~~powershell
python docs/learning/osmnx_demo/route_demo.py
~~~

程序会：

1. 将中国地质大学（武汉）转换为地理坐标；
2. 以该点为中心建立 1800 米范围；
3. 向 Overpass API 请求道路数据；
4. 构建 OSMnx 有向图；
5. 添加道路长度；
6. 为缺少限速的道路补充默认速度；
7. 计算旅行时间；
8. 在图上选择可达的起点和终点；
9. 调用 NetworkX Dijkstra；
10. 生成 HTML 地图和统计文件。

打开：

~~~text
docs/learning/osmnx_demo/output/route_demo.html
~~~

第一次运行不需要急着修改代码，先观察结果。

### 4.1 记录第一次实验

把结果写进自己的学习记录：

~~~text
实验区域：中国地质大学（武汉）及周边
抓取半径：1800 米
交通网络：drive
算法：Dijkstra
目标：travel_time
图节点数：
图边数：
路线节点数：
路线边数：
总距离：
预计时间：
~~~

### 4.2 为什么第一次运行可能失败

常见原因：

- Overpass API 临时超时；
- OSM 数据没有 maxspeed；
- 起点和终点沿单行道不可达；
- Python GIS 动态库加载失败；
- 网络或代理问题；
- OSMnx 版本不同导致 API 变化。

这些错误不应该直接跳过，而要记录：

~~~text
错误现象
→ 错误原因
→ 修复方式
→ 修复后结果
~~~

## 5. 第二步：阅读 route_demo.py

不要从第一行逐字背代码，按照数据流阅读。

### 5.1 parse_args

负责读取命令行参数：

~~~powershell
python docs/learning/osmnx_demo/route_demo.py --network-type bike
python docs/learning/osmnx_demo/route_demo.py --weight length
python docs/learning/osmnx_demo/route_demo.py --dist 2500
~~~

你应该理解：

- place：区域名称；
- network-type：交通主体对应的路网；
- weight：路径优化目标；
- dist：抓取半径。

### 5.2 load_graph

关键逻辑：

~~~text
地点名称
  → 地理编码
  → 中心点坐标
  → graph_from_point
  → OSM 道路图
  → add_edge_speeds
  → add_edge_travel_times
~~~

重点观察：

- 图的类型是 MultiDiGraph；
- 节点保存 x、y 等坐标；
- 边保存 length、highway、maxspeed 等属性；
- 一条道路可能因为方向或平行道路存在多条边。

### 5.3 choose_demo_endpoints

当前代码不是直接选择图中任意两个节点，而是在最大强连通分量中选点。

原因：

~~~text
弱连通：忽略方向后可以连通
强连通：沿有向边可以相互到达
~~~

导航图有单行道，因此弱连通并不保证路线可达。

### 5.4 calculate_route

核心调用：

~~~python
nx.shortest_path(
    graph,
    origin,
    destination,
    weight=weight,
    method="dijkstra",
)
~~~

其中：

- graph 是道路图；
- origin 是起点节点；
- destination 是终点节点；
- weight 决定优化什么；
- method 决定使用什么算法。

### 5.5 route_summary

负责把算法结果变成用户能理解的统计：

- 总距离；
- 总时间；
- 经过节点数；
- 经过边数；
- 图规模；
- 起点和终点。

### 5.6 save_map

负责把路线边序列转换成地图上的坐标线。

重要关系：

~~~text
图搜索结果：n1 → n8 → n12 → n21
道路几何结果：一系列 [经度, 纬度]
地图结果：HTML 中的折线
~~~

## 6. 第三步：查看真实路网数据

在程序中临时加入下面的调试代码：

~~~python
nodes = ox.graph_to_gdfs(graph, nodes=True, edges=False)
edges = ox.graph_to_gdfs(graph, nodes=False, edges=True)

print(nodes.head())
print(edges.head())
print(edges.columns.tolist())
~~~

观察：

- 节点的 x、y；
- 边的 u、v、key；
- length；
- highway；
- maxspeed；
- oneway；
- geometry；
- travel_time。

也可以统计道路类型：

~~~python
print(edges["highway"].value_counts().head(20))
~~~

这一步的目标是建立认识：

> 路径算法不是直接操作“道路名称”，而是操作带有属性的有向边。

## 7. 第四步：实验不同交通网络

依次运行：

~~~powershell
python docs/learning/osmnx_demo/route_demo.py --network-type drive
python docs/learning/osmnx_demo/route_demo.py --network-type bike
python docs/learning/osmnx_demo/route_demo.py --network-type walk
~~~

每次都记录：

- 节点数；
- 边数；
- 起终点；
- 路线距离；
- 路线时间；
- 路线是否经过不同道路。

### 7.1 需要回答的问题

1. 为什么骑行和驾车路网不同？
2. 为什么步行可能没有机动车道路？
3. 哪些道路只适合某种交通主体？
4. 不同交通主体是否需要不同的速度模型？
5. 同一起终点下，为什么路线不同？

### 7.2 完成标准

你能够解释：

~~~text
交通主体
  → 可通行道路集合
  → 不同边权
  → 不同最优路线
~~~

## 8. 第五步：比较距离最短和时间最短

运行：

~~~powershell
python docs/learning/osmnx_demo/route_demo.py --weight length
python docs/learning/osmnx_demo/route_demo.py --weight travel_time
~~~

当前程序会覆盖 output 中的结果文件。如果要保留两次实验，可以复制：

~~~powershell
Copy-Item docs/learning/osmnx_demo/output/route_demo.html docs/learning/osmnx_demo/output/route_length.html
Copy-Item docs/learning/osmnx_demo/output/route_summary.json docs/learning/osmnx_demo/output/summary_length.json
~~~

然后运行时间最短模式，再复制为 time 版本。

### 8.1 需要理解的区别

距离最短：

~~~text
每条边代价 = 道路长度
~~~

时间最短：

~~~text
每条边代价 = 道路长度 / 速度
~~~

如果道路速度属性缺失，时间最短结果会依赖默认速度。因此默认速度不是事实数据，只是实验假设。

### 8.2 完成标准

你需要能解释：

- 为什么距离短的道路不一定最快；
- 为什么速度估计会影响路线；
- 为什么不同目标要使用不同权重；
- 为什么两个目标有时会产生相同路线。

---

## 9. 第六步：把自动起终点改成手动输入

当前程序自动选择两个节点。下一步增加命令行坐标：

~~~powershell
python docs/learning/osmnx_demo/route_demo.py --origin-lon 114.3938 --origin-lat 30.5253 --destination-lon 114.4050 --destination-lat 30.5300
~~~

实现思路：

~~~text
用户输入经纬度
    ↓
ox.distance.nearest_nodes
    ↓
最近道路节点
    ↓
路径算法
~~~

示例函数：

~~~python
def nearest_node(graph, lon, lat):
    return ox.distance.nearest_nodes(
        graph,
        X=lon,
        Y=lat,
    )
~~~

注意坐标顺序：

~~~text
X = 经度
Y = 纬度
GeoJSON = [经度, 纬度]
Folium Marker = [纬度, 经度]
~~~

### 完成标准

- 用户能指定起点终点；
- 地图上标记的起终点对应用户输入附近；
- 输入道路外的点时，系统能吸附到最近道路；
- 输入范围外坐标时，系统能给出明确错误。

## 10. 第七步：实现 A*

### 10.1 先实现无启发式版本

把 Dijkstra 换成：

~~~python
route = nx.astar_path(
    graph,
    origin,
    destination,
    heuristic=lambda u, v: 0,
    weight=weight,
)
~~~

此时 h(n) 等于 0，结果应与 Dijkstra 一致。

### 10.2 再加入地理距离启发式

~~~python
def heuristic(graph, u, v):
    return ox.distance.great_circle(
        graph.nodes[u]["y"],
        graph.nodes[u]["x"],
        graph.nodes[v]["y"],
        graph.nodes[v]["x"],
    )
~~~

然后：

~~~python
route = nx.astar_path(
    graph,
    origin,
    destination,
    heuristic=lambda u, v: heuristic(graph, u, v),
    weight="length",
)
~~~

### 10.3 必须注意目标一致性

距离最短时，球面距离可以作为距离下界。

时间最短时，不能直接使用距离作为 h(n)。可以使用：

~~~text
h(n) = 直线距离 / 允许的最大速度
~~~

### 10.4 实验记录

| 项目 | Dijkstra | A* |
|---|---:|---:|
| 路线代价 |  |  |
| 路线距离 |  |  |
| 运行时间 |  |  |
| 扩展节点数 |  |  |
| 结果是否一致 |  |  |

### 完成标准

- A* 和 Dijkstra 的最优路线代价一致；
- A* 通常扩展更少的节点；
- 能解释 g(n)、h(n)、f(n)；
- 能解释启发式函数为什么不能高估。

## 11. 第八步：增加不走高速和道路过滤

先统计道路类型：

~~~python
for highway, count in edges["highway"].value_counts().items():
    print(highway, count)
~~~

然后设置自定义边权：

~~~python
def add_custom_cost(graph):
    for u, v, key, data in graph.edges(keys=True, data=True):
        road_type = str(data.get("highway", ""))

        if "motorway" in road_type:
            data["custom_cost"] = float("inf")
        else:
            data["custom_cost"] = float(data.get("travel_time", 1))
~~~

调用：

~~~python
route = nx.shortest_path(
    graph,
    origin,
    destination,
    weight="custom_cost",
)
~~~

更好的做法是把禁止道路直接删除或设置为不可用，而不是让它参与普通权重。

### 完成标准

- 选择不走高速后，路线不包含 motorway；
- 如果不走高速导致无路可达，系统能明确提示；
- 能通过日志说明哪些道路被过滤。

## 12. 第九步：增加红绿灯代价

红绿灯可以有两种处理方式。

### 方法一：路口惩罚

如果能获取信号灯节点，就给经过这些节点的路线增加等待时间：

~~~text
路线代价 =
    道路通行时间
  + 红绿灯数量 × 平均等待时间
~~~

### 方法二：节点扩展

把转弯或进入路口的代价作为状态转移代价。这比给普通边加权更准确，但需要知道前一条边和后一条边。

### 推荐学习顺序

~~~text
先给信号灯附近道路增加固定代价
    → 再统计路线经过的信号灯节点
    → 最后实现转向状态代价
~~~

### 完成标准

- 输出路线经过的红绿灯数量；
- 增大红绿灯惩罚后，路线有可能变化；
- 能解释“少红绿灯”不是简单地删除所有路口。

## 13. 第十步：实现多路线对比

最开始不需要实现复杂的 K 最短路，可以先运行多种目标：

~~~text
路线 A：距离最短
路线 B：时间最短
路线 C：少红绿灯
路线 D：不走高速
~~~

统一输出：

~~~json
{
  "name": "fastest",
  "distance_m": 5200,
  "duration_s": 500,
  "traffic_lights": 6,
  "warnings": []
}
~~~

前端用不同颜色显示路线。

### 完成标准

- 一次请求返回至少两条路线；
- 每条路线有完整统计；
- 能说明每条路线适合什么用户；
- 路线解释和代价一致。

## 14. 第十一步：比较自己的算法和 NetworkX

这一阶段要把 OSMnx 图转换给当前已有的 path_planning 模块。

比较：

~~~text
NetworkX Dijkstra
NetworkX A*
我们的 Dijkstra
我们的 A*
~~~

统一测试：

- 同一起终点；
- 同一张图；
- 同一条边权；
- 同一组禁行规则。

比较：

- 节点序列；
- 总距离；
- 总时间；
- 运行时间；
- 扩展节点数；
- 无路可达的错误处理。

### 学习目标

这一步是从“会用开源库”变成“理解开源库做了什么”。

## 15. 第十二步：加入 FastAPI

路径算法完成后，封装成接口：

~~~text
POST /route
POST /route/alternatives
POST /route/reroute
GET /health
~~~

请求示例：

~~~json
{
  "origin": [114.3938, 30.5253],
  "destination": [114.4050, 30.5300],
  "mode": "car",
  "objective": "travel_time",
  "avoid_highway": true
}
~~~

响应示例：

~~~json
{
  "algorithm": "astar",
  "distance_m": 5267.5,
  "duration_s": 503.8,
  "geometry": {
    "type": "LineString",
    "coordinates": []
  },
  "steps": [],
  "warnings": []
}
~~~

### 完成标准

- 浏览器或 Postman 能请求路线；
- 错误输入有清晰响应；
- 输出能直接给前端地图使用；
- 算法模块和服务模块分离。

## 16. 第十三步：地图渲染和轨迹回放

先使用现有的 Folium HTML。

然后再做网页前端：

~~~text
FastAPI
  → JSON / GeoJSON
  → Leaflet 或 MapLibre
  → 路线、起终点、轨迹显示
~~~

轨迹回放可以先使用模拟 GPS：

~~~text
路线节点序列
  → 每隔若干秒发送当前位置
  → 地图上移动车辆图标
  → 计算车辆到路线的距离
  → 判断是否偏航
~~~

### 偏航判断

简单版本：

~~~text
当前位置到规划路线的最短距离 > 阈值
且连续多次成立
→ 判断偏航
~~~

不要只根据一次 GPS 点重规划，避免 GPS 抖动导致路线频繁变化。

## 17. 第十四步：DEM 应急路线

### 17.1 选择应急场景

建议先选：

> 暴雨后，消防车从消防站前往事故点，避开低洼和高汇流风险道路。

### 17.2 DEM 处理链

~~~text
DEM GeoTIFF
  → QGIS/GDAL 裁剪和重投影
  → 生成坡度
  → 生成汇流累积
  → 道路采样
  → 写入 edge 属性
  → 修改应急代价
  → 规划主路线和备用路线
~~~

### 17.3 应急边代价

~~~text
emergency_cost =
    response_time
  + slope_penalty
  + flood_risk_penalty
  + road_failure_penalty
~~~

### 17.4 完成标准

- 能显示 DEM；
- 能显示坡度或低洼区域；
- 道路边有地形属性；
- 模拟部分道路封闭；
- 能生成主路线和备用路线；
- 能解释路线避开了哪些风险。

注意：DEM 不是洪水预测。课程项目应该使用“DEM 派生地形风险 + 模拟封路事件”的表述。

## 18. 第十五步：路径规划智能体

智能体应该最后实现。

用户输入：

~~~text
暴雨后帮我给消防车规划一条最快路线，避开低洼道路，再给一条备用路线。
~~~

智能体解析为：

~~~json
{
  "scenario": "emergency_rescue",
  "mode": "fire_truck",
  "objective": "minimum_response_time",
  "avoid": ["lowland", "high_flood_risk"],
  "return_backup_route": true
}
~~~

然后调用：

~~~text
需求解析工具
  → 地理编码工具
  → DEM 风险工具
  → 道路事件工具
  → 路径规划工具
  → 路线验证工具
  → 路线解释工具
~~~

核心原则：

~~~text
AI 负责理解和编排
路径算法负责计算
验证器负责检查
地图负责展示
~~~

不要让大模型直接生成未经验证的道路序列。

## 19. 推荐的 14 天学习安排

### 第 1 天：运行项目

- 安装依赖；
- 下载中国地质大学（武汉）路网；
- 打开 HTML 地图；
- 记录节点、边、距离和时间。

### 第 2 天：阅读路网结构

- 打印 nodes；
- 打印 edges；
- 查看 highway、length、maxspeed；
- 理解 MultiDiGraph。

### 第 3 天：交通主体

- 运行 drive；
- 运行 bike；
- 运行 walk；
- 比较道路图和路线。

### 第 4 天：距离和时间

- 比较 length；
- 比较 travel_time；
- 记录默认速度对结果的影响。

### 第 5 天：手动起终点

- 增加经纬度参数；
- 使用 nearest_nodes；
- 在地图上检查吸附位置。

### 第 6 天：A*

- 先使用 h(n)=0；
- 再使用地理距离；
- 比较 Dijkstra 和 A*。

### 第 7 天：道路限制

- 不走高速；
- 避免收费；
- 处理单行道；
- 处理无路可达。

### 第 8 天：红绿灯和多目标

- 增加信号灯惩罚；
- 输出最快、最短、少红绿灯路线；
- 地图上多颜色显示。

### 第 9 天：自己的算法

- 将 OSMnx 图转换为自定义图；
- 和 path_planning 代码对照；
- 比较结果。

### 第 10 天：FastAPI

- 封装 route API；
- 返回 GeoJSON；
- 添加错误处理。

### 第 11 天：地图和轨迹

- 前端绘制路线；
- 模拟车辆移动；
- 实现偏航判断。

### 第 12 天：DEM

- 使用 QGIS 打开 DEM；
- 生成坡度；
- 生成低洼或汇流风险。

### 第 13 天：应急路线

- 给道路增加风险属性；
- 模拟封路；
- 生成消防车主路线和备用路线。

### 第 14 天：智能体

- 定义 RouteRequest；
- 添加路线工具；
- 让智能体解析自然语言；
- 输出路线解释。


---

## 20. 每个阶段的验收标准

### 基础阶段

- 能下载武汉区域路网；
- 能说明节点和边；
- 能生成路线地图；
- 能解释距离权重和时间权重。

### 算法阶段

- Dijkstra 路线正确；
- A* 路线代价和 Dijkstra 一致；
- 单行道方向有效；
- 不可达时有明确错误。

### 多主体阶段

- drive、bike、walk 路线不同；
- 道路过滤规则有效；
- 不走高速有效；
- 至少返回两条候选路线。

### GIS 阶段

- 能读取 DEM；
- 能生成坡度；
- 能把栅格值采样到道路；
- 能规划应急路线。

### 系统阶段

- API 可调用；
- GeoJSON 可显示；
- 轨迹可回放；
- 偏航可检测；
- 路线可重新规划。

### 智能体阶段

- 自然语言能转成结构化参数；
- 智能体能调用路线工具；
- 路线结果经过验证；
- 能生成路线解释和警告。

## 21. 常见问题处理

### Overpass 超时

处理方式：

- 减小 dist；
- 使用缓存；
- 更换 Overpass 实例；
- 不要一开始抓整个武汉；
- 先用 1000 到 2500 米范围。

### 没有 maxspeed

处理方式：

- 设置 fallback 速度；
- 按 highway 类型设置默认速度；
- 在实验报告中说明速度是假设值。

### 起终点不可达

可能原因：

- 单行道；
- 路网不连通；
- 起终点属于不同强连通分量；
- 过滤条件过于严格。

处理方式：

- 选择最大强连通分量；
- 检查道路方向；
- 放宽过滤条件；
- 输出可解释错误。

### 坐标位置错误

检查：

~~~text
X = 经度
Y = 纬度
GeoJSON = [经度, 纬度]
Folium Marker = [纬度, 经度]
~~~

### 路线结果和预期不同

先不要马上认为算法错误，依次检查：

1. 权重是不是正确；
2. 速度是不是默认值；
3. 道路是否单行；
4. 是否存在收费或高速限制；
5. 起终点是否吸附到了错误道路；
6. 图是否含有错误或缺失属性。

## 22. 学习时应该怎样记录

每次实验至少记录：

~~~text
实验编号：
实验目的：
使用数据：
区域：
交通主体：
算法：
权重：
参数：
结果：
出现的问题：
问题原因：
解决办法：
下一步：
~~~

推荐建立：

~~~text
docs/learning/osmnx_demo/
├── notes/
│   ├── 01_first_run.md
│   ├── 02_graph_structure.md
│   ├── 03_weight_compare.md
│   ├── 04_astar.md
│   ├── 05_multi_mode.md
│   ├── 06_dem_emergency.md
│   └── 07_agent.md
~~~

不要只保存最终代码。错误日志和实验对比也是学习成果。

## 23. 最后要形成的项目成果

完成后，项目应该包含：

~~~text
1. 数据获取脚本
2. 路网构建脚本
3. Dijkstra 实现
4. A* 实现
5. 交通主体 profile
6. 多目标权重
7. 路线后处理
8. GeoJSON 接口
9. 地图展示
10. GPS 轨迹模拟
11. 偏航重规划
12. DEM 应急路线
13. FastAPI 服务
14. 路径规划智能体
15. 实验记录和测试报告
~~~

最重要的学习顺序是：

> 先看数据，再看图；先跑 Dijkstra，再写 A*；先完成普通路线，再加入多目标；先完成确定性算法，再封装 AI 智能体。

当前第一步就是运行：

~~~powershell
python docs/learning/osmnx_demo/route_demo.py
~~~

然后开始修改起点终点，而不是马上跳到 DEM 或智能体。

## 24. 与现有材料的关系

- 本文是个人实操路线，解决“每天具体做什么”；
- docs/project/初步了解本组任务.md 是组员共享方案，解决“项目要做什么和如何分工”；
- docs/project/GIS导航系统全景与路径规划研究报告.md 是资料和架构报告，解决“为什么这样设计”；
- docs/development/路径规划模块开发说明.md 是当前自研算法代码说明；
- `docs/learning/osmnx_demo/` 是真实 OSM 数据练习项目（`route_demo.py` 与配套说明）。

