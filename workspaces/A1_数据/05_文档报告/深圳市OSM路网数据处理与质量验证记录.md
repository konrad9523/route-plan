# 深圳市 OSM 路网数据处理与质量验证记录

## 一、目标与数据来源

本次处理的目标是从广东省 OpenStreetMap（OSM）数据中提取深圳市道路网络，构建可供项目 `path_planning` 图加载器、Dijkstra 和 A* 算法使用的有向 GraphML 路网，保持与此前华盛顿特区路网处理基本一致的技术口径。

| 输入资料 | 文件 | 作用 |
|---|---|---|
| 广东省 OSM 提取数据 | `data/raw/guangdong-latest.pbf` | 路网及其 OSM 标签原始来源（Geofabrik） |
| 深圳市行政边界 | `data/raw/shenzhen_boundary.geojson` | 裁剪区域边界，1 个 MultiPolygon 要素 |
| 裁剪后的深圳 OSM | `data/raw/shenzhen.osm.pbf` | 后续检查与路网转换的输入 |

**环境：** Windows、VS Code、项目 Python `.venv`；使用 Anaconda Navigator 管理的 `osm_extract` 环境运行 Osmium Tool 1.19.1。两个环境作用不同：命令行 `osmium` 用于区域提取；项目 Python `osmium`（pyosmium）用于 OSM 数据解析和图构建。

## 二、处理流程与实际步骤

### 1. 核对行政边界与裁剪

深圳行政边界由 QGIS 处理后保存为 `shenzhen_boundary.geojson`。在 `osm_extract` 环境、项目根目录下检查 GeoJSON，输出为 `FeatureCollection`、1 个要素、几何类型 `MultiPolygon`。

随后执行：

```powershell
osmium extract --polygon "data/raw/shenzhen_boundary.geojson" --strategy complete_ways --output "data/raw/shenzhen.osm.pbf" "data/raw/guangdong-latest.pbf"
```

最初曾误用输入名 `guangdong-latest.osm.pbf` 而报文件不存在；核对实际文件名为 `guangdong-latest.pbf` 后重试成功，裁剪进度达到 100%。

通过 `osmium fileinfo data/raw/shenzhen.osm.pbf` 确认输出为 PBF，文件大小 16,629,708 字节（约 16.6 MB）。`complete_ways` 可能保留延伸到深圳边界外的完整道路 Way，因此后续仍应检查边界附近的覆盖情况。

### 2. 检查裁剪后的 OSM 数据

在项目 `.venv` 中执行：

```powershell
python tools/inspect_osm.py data/raw/shenzhen.osm.pbf --output data/processed/shenzhen_osm_inspection.json
```

主要统计结果：

| 指标 | 数量 |
|---|---:|
| OSM Node | 1,980,792 |
| OSM Way | 232,546 |
| OSM Relation | 5,266 |
| 带 `highway` 标签的 Way | 102,907 |
| 转向限制 Relation | 970 |
| `oneway=yes` | 30,424 |
| `oneway=-1` | 50 |
| `maxspeed` 存在 | 2,743 |
| `maxspeed` 缺失 | 100,164 |

以上 `maxspeed` 统计以**全部带 `highway` 标签的 Way** 为分母，不能等同于机动车道路的速度缺失率。原始道路类型中还包括 footway、steps、cycleway、path 等非机动车道路，需要在转换时排除。

### 3. 构建优化后的有向路网

为保留华盛顿已验证代码，复制 `tools/convert_dc_osm_optimized.py` 为 `tools/convert_shenzhen_osm.py`。本次基线转换**沿用原程序的道路筛选与默认速度规则**，没有基于深圳实测限速重新标定参数。

在项目 `.venv` 中执行：

```powershell
python tools/convert_shenzhen_osm.py data/raw/shenzhen.osm.pbf data/processed/shenzhen_driving_optimized.graphml
```

处理环节包括：按 `highway` 类型挑选可能通行的机动车道路；排除程序所识别的禁行标签；处理单向、反向单行及部分隐含单向；解析 `maxspeed` 或使用道路类型默认速度；在道路连接节点切分 Way；计算道路距离并写入有向 GraphML；保留中间形状点在边的 `geometry` 中，避免把不参与路由的形状点作为额外图节点。

实际输出：

| 指标 | 结果 |
|---|---:|
| 筛选机动车道路 Way | 57,822 |
| 路由图节点 | 85,287 |
| 有向边 | 176,241 |
| 物理道路段 | 117,641 |
| 仅保留于边几何中的形状点 | 312,468 |
| 因节点坐标缺失跳过的道路段 | 0 |
| 使用默认速度的 Way | 55,231（约 95.52%） |
| 排除可变单向道路 Way | 1 |

输出文件：

- `data/processed/shenzhen_driving_optimized.graphml`：供路径规划系统读取的最终有向路网。
- `data/processed/shenzhen_driving_optimized.summary.json`：转换统计与提示信息。

### 4. 路网质量和算法一致性验证

执行：

```powershell
python tools/validate_dc_network.py --input data/processed/shenzhen_driving_optimized.graphml --output data/processed/shenzhen_validation.json --max-checks 2
```

终端实际结果：

| 指标 | 结果 |
|---|---:|
| 节点 | 85,287 |
| 有向边 | 176,241 |
| 弱连通分量 | 249 个，最大分量 84,408 节点 |
| 强连通分量 | 1,281 个，最大分量 83,307 节点 |
| 孤立节点 | 0 |
| 可疑过短边 | 0 |
| 检测到的最大速度 | 120.0 km/h |
| Dijkstra 与 A* 对照 | 两组起终点、各测试最短及最快偏好，最优代价均一致 |
| 验证程序最终结果 | `RESULT: BASIC CHECKS PASSED` |

该检查验证了基础图结构与选定样例的一致性，**不表示所有道路都符合实际交通规则**。

### 5. 项目功能回归测试

在项目 `.venv` 中运行：

```powershell
python -m pytest -q
```

首次运行遇到虚拟环境缺失 `pip`、`pytest`，使用 `python -m ensurepip --upgrade` 恢复 pip 后安装 pytest。首次测试结果是 **55 passed、1 failed**：`test_route_trace_respects_max_steps` 测试要求 `max_steps=20` 时返回的 `trace.pop_order` 不超过 20 条，但 API 实际返回 394 条。

检查发现，先前为大路网网页动画保留完整轨迹的 API 逻辑未调用 `trace.downsample()`。在 `api/main.py` 中将行为调整为：`max_steps=0` 返回完整轨迹，`max_steps>0` 调用 `trace.downsample(max_steps)`。同时修复编辑期间首页接口 `index()` 的代码缩进问题。

**最终用户反馈：全部 56 项测试通过。** 这属于项目功能回归测试；测试主要使用项目已有测试数据，不能代替深圳路网的质量验证。

## 三、成果文件清单

| 文件 | 用途 |
|---|---|
| `data/raw/shenzhen.osm.pbf` | 深圳区域原始 OSM 数据，便于复现转换 |
| `data/processed/shenzhen_osm_inspection.json` | OSM 标签与道路属性统计 |
| `tools/convert_shenzhen_osm.py` | 深圳有向 GraphML 转换脚本 |
| `data/processed/shenzhen_driving_optimized.graphml` | **正式处理后的深圳市路网** |
| `data/processed/shenzhen_driving_optimized.summary.json` | 路网转换统计 |
| `data/processed/shenzhen_validation.json` | 路网拓扑及路由算法验证报告 |

向其他组员交付路径规划用数据时，至少发送 GraphML；推荐一并提供 summary.json、validation.json 和本记录。若需完整复现，还应提供原始 PBF、边界文件和转换程序。

## 四、数据局限与后续工作

1. **限速缺失较多。** 57,822 条已选 Way 中有 55,231 条使用程序默认速度，最快路径结果对这些假设较敏感，后续可开展速度参数敏感性检验。
2. **转向限制未完整实现。** 原始数据发现 970 条转向限制 Relation，但现有转换脚本没有把这些关系约束应用于路径规划。
3. **通行条件简化。** 条件性通行、车道级规则及部分复杂进出权限未完整建模。
4. **边界与拓扑仍应抽样复核。** `complete_ways` 可能扩展出行政边界；复杂立交等位置不能仅凭节点坐标一致认定现实中可转向。
5. **网页验证需单独留证。** 已完成后端基础检查与 56 项回归测试；本记录没有可核实的深圳网页端起终点路线和动画检查结果，不能把该项写成已完成。

## 五、结果说明

本次深圳路网沿用华盛顿方案，实现了从广东省 OSM PBF、深圳行政边界裁剪，到机动车道路筛选、优化 GraphML 构建和基础质量验证的完整流程。最终获得 **85,287 个路由节点、176,241 条有向边**，质量验证程序返回 `BASIC CHECKS PASSED`，项目回归测试经修复后全部 56 项通过。数据已具备进入进一步路径规划实验的基础，但不应被表述为已经达到商业导航级别的交通规则完整性。

## A1-3 修复后归档说明

本节记录本次可复现性修复后的文件存放位置。文中旧的 data/raw、tools 和 data/processed 路径属于历史项目目录，不应直接理解为当前 A1 工作区的相对路径。

当前仓库内已归档：

- 转换脚本：`workspaces/A1_数据/05_文档报告/scripts/convert_shenzhen_osm.py`
- 裁剪边界：`workspaces/A1_数据/01_路网清单/raw/shenzhen_boundary.geojson`
- 原始检查结果：`workspaces/A1_数据/03_数据质量/shenzhen_osm_inspection.json`
- 路网成果：`workspaces/A1_数据/01_路网清单/processed/shenzhen_driving_optimized.graphml`

原始处理文件目前保存在本机 `D:\DDDesk\G4\route-plan-main (2)\data\raw`，包括广东原始 PBF 和深圳裁剪 PBF。深圳裁剪 PBF 已归档至本仓库：`workspaces/A1_数据/01_路网清单/raw/shenzhen.osm.pbf`。可直接使用该文件和转换脚本复现深圳路网；广东原始 PBF 尚未纳入 Git，因此从广东原始数据重新裁剪的完整上游流程仍需外部数据。

A1-3 验证已使用恢复的 `shenzhen.osm.pbf` 和原始转换脚本重新生成路网。复现统计为：85,287 个节点、176,241 条有向边、57,822 条选中 Way、117,641 个物理路段，与历史记录一致。该验证属于转换成功及统计复现，不等同于 GraphML 逐字节一致性验证。

复现时运行转换脚本，输入深圳裁剪 PBF，输出至独立临时文件，不覆盖正式路网。