# A1 路网统一回归测试报告

- 结果：**PASS**
- 时间（UTC）：2026-10-16T10:18:39.752728+00:00
- 旧图：`C:\a1_osm_test\dc_a1_1_fixed.graphml`
- 新图：`C:\a1_osm_test\dc_a1_2_fixed.graphml`
- PBF：`C:\a1_osm_test\dc.osm.pbf`

## 测试统计

| 指标 | 数量 |
|---|---:|
| old_nodes | 41666 |
| new_nodes | 41679 |
| old_edges | 99497 |
| new_edges | 99543 |
| old_nodes_removed | 0 |
| old_node_coords_changed | 0 |
| unchanged_old_edges | 99493 |
| verified_subdivided_old_edges | 4 |
| changed_old_edges | 4 |

## 核验项目

| 项目 | 结果 |
|---|---|
| input_graphs_parse | PASS |
| old_nodes_preserved | PASS |
| old_edges_preserved_or_verified_exactly_split | PASS |
| new_graph_all_edges_valid | PASS |
| new_graph_no_isolated_nodes | PASS |
| all_permission_changes_are_restorations | PASS |
| all_restored_ways_present_with_correct_directions | PASS |
| way_50425284_restored | PASS |
| a1_1_way_6053502_preserved | PASS |
| verified_service_loops_preserved | PASS |
| sampled_route_costs_consistent | PASS |

## 全量权限变更扫描

- 候选道路 Way 数：33516
- 权限规则判定变化 Way 数：11
- 旧规则拒绝、新规则允许：11
- 旧规则允许、新规则拒绝：0

| Way ID | 名称 | 方向 | 几何覆盖 |
|---|---|---|---|
| 6052418 | First Street Northwest | 0 | PASS |
| 6061205 | 1st Street Northwest | 0 | PASS |
| 50425284 | 34th Street Northwest | 0 | PASS |
| 357122797 |  | 0 | PASS |
| 493044665 | First Street Northwest | 0 | PASS |
| 566302862 |  | 0 | PASS |
| 566334462 | Water Street Southeast | 0 | PASS |
| 628378841 |  | 0 | PASS |
| 848845368 |  | 0 | PASS |
| 944921560 |  | 0 | PASS |
| 1442272436 |  | 0 | PASS |

## 旧道路变化与精确拆分验证

- 完全一致的旧边：99493
- 变化的旧边：4
- 逐条拆分几何匹配：PASS

- `1819089471 -> 1354444673` Southeast Boulevard: PASS; 几何匹配 True; 长度差 0.0 m
- `1354444673 -> 1819089471` Southeast Boulevard: PASS; 几何匹配 True; 长度差 0.0 m
- `1934652434 -> 49764326` Rhode Island Avenue Northwest: PASS; 几何匹配 True; 长度差 -0.001 m
- `49764326 -> 1934652434` Rhode Island Avenue Northwest: PASS; 几何匹配 True; 长度差 -0.001 m

## 全量结构与路径抽样

- 旧版弱/强连通分量：349 / 895
- 新版弱/强连通分量：345 / 891
- 新版结构异常：`{}`
- OD：40 组，距离/时间两种代价，固定随机种子 6053502。**路径测试为抽样，而非全 OD 穷举。**
- 路径检查：PASS

## 范围说明

OSM 条件权限、复杂转向限制、真实交通管制等不在本验证器覆盖范围内。该脚本独立检验生成 GraphML 的普通节点最短路径，并非直接调用项目边状态路由器。
