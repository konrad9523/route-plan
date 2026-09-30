# 路径规划引擎（route-plan）

> **G4「路径规划引擎组」课程项目**
> 一个可独立运行的路径规划引擎与可视化演示系统。

在真实 OSM 路网上规划路线，并把**搜索过程**可视化。
核心算法零第三方依赖，只用 Python 标准库。

---

## 快速开始

需要 Python 3.10 以上。**下面的命令都在仓库根目录执行**。

```powershell
python -m unittest discover -s tests -v          # 跑测试（56 项）
python -m uvicorn api.main:app --port 8077       # 启动可视化服务
```

然后浏览器打开 <http://127.0.0.1:8077>：点两下选起终点 → 点「开始」算路 → 点「播放」看搜索动画。

> 启动服务需要在根目录，是因为 `api/` 在根目录下；
> 而 `path_planning` 在 `src/` 下，测试与脚本已通过
> [`tests/_bootstrap.py`](tests/_bootstrap.py) 自动处理，不必手工设 `PYTHONPATH`。

---

## 当前进度

| 已完成 | 计划中 |
|---|---|
| 真实 OSM 路网加载（552 节点 / 1400 边） | 地标启发式（ALT） |
| Dijkstra 与 A\*（含启发式一致性校验） | 双向 A\*、CH 收缩层次 |
| 搜索过程记录与动画（`SearchTrace`） | 多路径、交通模拟 |
| HTTP 接口 + 浏览器可视化 | |
| 4 种偏好（最快 / 最短 / 避开收费 / 避开高速） | |

---

## 目录结构

```text
src/path_planning/   规划内核（纯标准库，算法的唯一正式位置）
api/                 HTTP 服务（FastAPI）
web/                 前端页面（Leaflet）
tests/               测试
tools/               自检脚本
data/                路网数据
docs/                项目文档
docs/learning/osmnx_demo/   OSMnx 教学脚本（真实 OSM 数据练习）
workspaces/          五个角色的成果区
```

> **为什么 `path_planning` 在 `src/` 下**：源码与文档、数据、脚本混在根目录时
> 分不清哪些是"产品代码"。放进 `src/` 后根目录只剩四类东西——
> **源码、测试、数据、文档**。
>
> 包名没有变（`import path_planning` 照旧），但**它不在仓库根目录了**，
> 所以测试与脚本需要先让 `src/` 进入 `sys.path`：
> 测试已统一通过 [`tests/_bootstrap.py`](tests/_bootstrap.py) 处理，无需你操心。

---

## 更多信息

- **文档导航** → [`docs/README.md`](docs/README.md)
- **代码现状与已知限制** → [`docs/development/路径规划模块开发说明.md`](docs/development/路径规划模块开发说明.md)
- **数据说明** → [`data/README.md`](data/README.md)
- **协作规范** → [`docs/operations/团队协作与项目管理原则.md`](docs/operations/团队协作与项目管理原则.md)
- **版本变化** → [`CHANGELOG.md`](CHANGELOG.md)

> 路网数据来自 **OpenStreetMap**（ODbL 1.0，© OpenStreetMap contributors）。
> 本项目自研代码与文档采用 MIT 许可，详见 [`LICENSE`](LICENSE)。
