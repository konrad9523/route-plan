# G4 车辆导航可视化

基于 Leaflet 和 OpenStreetMap 数据的车辆路网导航实验页面，用于展示 Dijkstra 与 A* 的路径搜索过程。

## 运行

1. Windows 用户双击 `start-server.bat`，脚本会自动启动本地 HTTP 服务；不需要手动输入 Python 命令。
2. 浏览器访问 `http://localhost:5173/`。
3. 服务器启动时读取 `data/server/wuhan-main-roads.json`，前端按地图区域自动请求路网。
4. 直接在地图上依次点击起点和终点，再选择算法并开始规划。

请通过 `start-server.bat` 或本地 HTTP 服务打开页面。浏览器会限制 `file://` 页面读取同目录 JSON，而自动路网请求也需要 HTTP 页面环境。

## 上传 GitHub 后如何演示

### 方式一：克隆后本机完整运行（推荐协作使用）

请把项目文件夹中的内容直接放在仓库根目录，不要只上传压缩包。必须保留：

- `index.html`、`app.js`、`styles.css`
- `server.py`、`start-server.bat`
- `data/server/wuhan-main-roads.json`
- `assets/`、`tools/` 和说明文档

其他开发者克隆仓库后，在 Windows 下双击 `start-server.bat`，再访问
`http://localhost:5173/`。这种方式使用服务器按区域读取武汉路网，加载更快，功能与开发机一致。

### 方式二：GitHub Pages 在线演示

在 GitHub 仓库的 `Settings` → `Pages` 中选择 `Deploy from a branch`，选择 `main` 分支和 `/ (root)`，保存后使用 GitHub Pages 地址打开。

GitHub Pages 没有 Python `/api/network` 服务，页面会自动读取仓库内的
`data/server/wuhan-main-roads.json` 静态完整武汉路网。第一次加载可能需要等待一段时间，之后 Dijkstra、A*、起终点吸附、搜索动画和最终路径都在浏览器中运行。

GitHub Pages 和本地服务都需要联网加载 Leaflet、地图瓦片以及超出武汉缓存范围时的在线 OSM 数据。直接双击 `index.html` 的 `file://` 模式仍不支持自动路网加载。

完整路网 JSON 约 35 MB，低于 GitHub 单文件 100 MB 限制，但超过 GitHub 网页上传的 25 MB 限制。请使用 Git push 或 GitHub Desktop 上传，不要在网页上单独拖拽这个 JSON 文件。

## 功能

- OSM 主要道路路网加载
- 服务器保存武汉范围主要道路，前端按 bbox 请求当前区域，缺失时回退到本地小缓存或 Overpass API
- 起点、终点点击设置与拖动
- 端点自动吸附到最近的真实 OSM 道路节点
- Dijkstra 与 A* 路径搜索（A* 使用 Haversine 距离和安全启发式比例）
- 已访问折点、边界折点和最终路径动画
- 多种底图与页面皮肤

路网显示逻辑：完整 OSM 路网会保留在浏览器内存中供 Dijkstra/A* 计算，但普通路网不会绘制。用户点击地图设置起终点；搜索过程中只显示已遍历折点、边界折点和当前折点；搜索完成后只显示最终路线动画。

## 数据与服务说明

- `data/server/wuhan-main-roads.json` 是服务器端的武汉范围主要道路缓存，不包含 POI。服务器启动后会读入整份数据，但不会把整份数据发给浏览器。
- 浏览器只通过 `/api/network?bbox=south,west,north,east` 请求当前地图、起点或终点附近的道路，因此数据规模扩大后不会一次性拖慢页面。
- `data/wuhan-main-roads.json` 仍保留为历史小范围文件，但正常启动服务器不会使用它；服务器缺少完整文件时会直接提示，避免误用小范围路网。
- 地图不绘制完整路网。搜索动画只显示已遍历折点、候选边界折点和当前折点；搜索完成后只显示最终路线。
- 地图底图使用 OpenStreetMap、Esri 或百度实验图层。
- 使用 OpenStreetMap 数据时请遵守其版权与使用政策。
- 本地服务 API 是正常路径；静态部署没有 `/api/network` 时，页面会回退到项目内的完整武汉路网，超出武汉范围时再请求 Overpass API。

生成服务器数据：先准备湖北或武汉的 `.osm.pbf` 文件，再运行：

```text
py tools/build_wuhan_network.py --pbf E:\\G4-A4数据\\hubei-latest.osm.pbf
```

脚本只提取武汉范围的 OSM 主要道路，写入 `data/server/wuhan-main-roads.json`。
请保留 JSON 内的来源、范围、时间及 ODbL 署名信息。

## 项目结构

```text
index.html          页面结构
app.js              地图、路网、Dijkstra/A* 与交互逻辑
styles.css          页面样式
assets/             页面资源
data/               本地 OSM 数据与元信息
data/server/        服务器端武汉主要道路缓存
tools/              OSM 数据下载脚本
server.py           提供静态页面与按区域路网 API 的本地服务器
tools/astar_haversine.py
                    与网页 A* 对齐的 Python 参考实现
start-server.bat   本地启动脚本
使用说明.txt        简要使用说明
```
