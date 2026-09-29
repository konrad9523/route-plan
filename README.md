# 路径规划引擎（route-plan）

> **G4「路径规划引擎组」课程项目**
> 一个可独立运行的路径规划引擎与可视化演示系统。

支持四种路径规划算法（**Dijkstra / A\* / 双向 A\* / CH 收缩层次**），
在真实 OSM 路网上规划路线，并把**搜索过程**可视化。

---

## 快速开始

需要 Python 3.10 以上。核心算法**零第三方依赖**，只用标准库。

```powershell
# 1. 跑测试（56 项）
python -m unittest discover -s tests -v

# 2. 跑最小演示（4 节点假地图，打印 3 行路线 JSON）
python -m path_planning.demo

# 3. 启动可视化服务
python -m uvicorn api.main:app --port 8077
```

第 3 步之后，浏览器打开 **<http://127.0.0.1:8077>**：

1. 在地图上点**两下**选起点和终点
2. 点「开始」计算路线
3. 点「播放」看搜索过程动画

> 界面上的三层配色：**深灰 = 已访问节点**，**橙色 = 边界节点（待扩展）**，**绿色 = 最终路径**。

---

## 当前进度

| 能力 | 状态 |
|---|---|
| 真实 OSM 路网加载（552 节点 / 1400 边） | ✅ |
| Dijkstra（优先队列，等代价平局稳定） | ✅ |
| A\*（Haversine 启发式 + 一致性校验） | ✅ |
| 搜索过程记录与动画（`SearchTrace`） | ✅ |
| HTTP 接口 + 浏览器可视化 | ✅ |
| 4 种偏好（最快 / 最短 / 避开收费 / 避开高速） | ✅ |
| 地标启发式（ALT） | ⬜ 计划中 |
| 双向 A\*、CH 收缩层次 | ⬜ 计划中 |
| 多路径、交通模拟 | ⬜ 计划中 |

**测试：56 项全部通过。**

---

## 目录结构

```text
path_planning/      规划内核（纯标准库）
  models.py         Node / Edge / Graph / RouteResult
  costs.py          4 种偏好 + 启发式
  router.py         Dijkstra / A* + 启发式一致性校验
  search_trace.py   搜索过程记录（动画数据源）
  osm_loader.py     GraphML → Graph
  geo.py            Haversine 距离

api/                HTTP 服务（FastAPI）
web/                前端页面（Leaflet，无 Python 依赖）
tests/              测试（56 项）
data/               共享路网数据与说明
docs/               项目文档（见 docs/README.md）
workspaces/         五个角色的成果区
tools/              自检脚本（文档结构、接口冒烟）
learning_osmnx_networkx/  教学脚本与数据获取脚本
```

**详细说明**：

- 文档导航 → [`docs/README.md`](docs/README.md)
- 代码现状与已知限制 → [`docs/development/路径规划模块开发说明.md`](docs/development/路径规划模块开发说明.md)
- 数据说明 → [`data/README.md`](data/README.md)
- 协作规范 → [`docs/operations/团队协作与项目管理原则.md`](docs/operations/团队协作与项目管理原则.md)

---

## 会用到的命令

```powershell
# 全部测试
python -m unittest discover -s tests -v

# 只跑某个测试文件
python -m unittest tests.test_router -v

# 启动 / 换端口（8077 被占用时）
python -m uvicorn api.main:app --port 8080

# 检查一张路网适不适合用 A*
python -c "from path_planning import load_graphml, check_heuristic_consistency; g=load_graphml('data/campus_552.graphml'); print(len(check_heuristic_consistency(g)))"

# 端到端接口冒烟测试（真实 HTTP，覆盖前端依赖的每个字段）
python tools/smoke_api.py

# 文档自检（代码围栏是否配对、角色目录树是否与磁盘一致）
python tools/check_docs.py
```

> ⚠️ **命令必须在仓库根目录执行**。`path_planning` 不是已安装的包，
> 只有在根目录下 Python 才能导入它；在别处运行会报 `ModuleNotFoundError`。

---

## 数据来源与许可

- 路网数据来自 **OpenStreetMap**，经 OSMnx 抓取。
- OSM 数据采用 **ODbL 1.0** 许可，© OpenStreetMap contributors。
- 使用的地图底图瓦片由 OpenStreetMap 在线提供，界面中保留署名。

各数据集的规模、来源、生成命令与已知特征见 [`data/README.md`](data/README.md)
和机器可读的 [`data/graph_meta.json`](data/graph_meta.json)。

---

## 参与开发

本项目由五人小组分工协作，角色划分为 **A1 数据 / A2 算法 / A3 性能与测试 / A4 交互 / A5 演示材料**。

**动手之前请先读** [`docs/operations/团队协作与项目管理原则.md`](docs/operations/团队协作与项目管理原则.md)，
其中有三条核心提交规则和双层工作区制度。

- 各角色的成果 → [`workspaces/`](workspaces/)
- 任务与 Issue 模板 → [`.github/ISSUE_TEMPLATE/task.md`](.github/ISSUE_TEMPLATE/task.md)
- 版本变化 → [`CHANGELOG.md`](CHANGELOG.md)
