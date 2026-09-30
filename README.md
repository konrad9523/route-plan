# 路径规划引擎（route-plan）

> **G4「路径规划引擎组」课程项目**
> 一个可独立运行的路径规划引擎与可视化演示系统。

在真实 OSM 路网上规划路线，并把**搜索过程**可视化。
核心算法零第三方依赖，只用 Python 标准库。

---

## 快速开始

需要 **Python 3.10 以上**。

### 方式一：直接跑（不安装，最少步骤）

**下面两条命令都在仓库根目录执行**：

```powershell
python -m unittest discover -s tests -v          # 跑测试（56 项）
python -m uvicorn api.main:app --port 8077       # 启动可视化服务
```

然后浏览器打开 <http://127.0.0.1:8077>：点两下选起终点 → 点「开始」算路 → 点「播放」看搜索动画。

> **核心算法零第三方依赖**，所以跑测试不需要装任何东西。
> `path_planning` 在 `src/` 下，测试与脚本已通过
> [`tests/_bootstrap.py`](tests/_bootstrap.py) 自动处理，不必手工设 `PYTHONPATH`。
> 但**必须在仓库根目录执行**——这是唯一的要求。

### 方式二：安装成包（想在任意目录运行 / 用 IDE 更好补全）

```powershell
# 1) 建虚拟环境（可选但推荐）
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2) 安装核心包（零依赖）
python -m pip install -e .

# 3) 需要 HTTP 服务或跑测试时，装上对应依赖
python -m pip install -e ".[api,test]"

# 4) 需要教学脚本（osmnx/folium，较重）时
python -m pip install -e ".[demo]"
```

装好之后，**在任何目录**都能 `import path_planning`（IDE 补全、脚本复用都方便）：

```powershell
python -c "import path_planning; print(path_planning.__file__)"
```

> 依赖声明见 [`pyproject.toml`](pyproject.toml)：
> `dependencies = []` 是**刻意留空的**——核心算法只用标准库，
> fastapi/uvicorn 属于 `api` 可选组，osmnx 属于 `demo` 可选组。
>
> ⚠️ **但启动服务仍然必须在仓库根目录**，安装并不能改变这一点。
> 原因有两个，都实测确认过：
>
> 1. `api/` **不在安装的包范围内**（它是仓库里的脚本目录，不是库），
>    从别处执行 `python -m uvicorn api.main:app` 会报
>    `ModuleNotFoundError: No module named 'api'`
> 2. 服务按**相对仓库根**的路径读 `data/campus_552.graphml` 与 `web/index.html`
>
> 也就是说：**安装解决的是"导入 path_planning"，不是"换目录运行服务"。**

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
