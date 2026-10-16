# A1-5 最终综合验收报告

**最终结论：PASS**

- 路网节点：41679
- 有向边：99543
- 原始 OSM Way：30711
- 路径对照：80 次

| 测试项 | 结果 |
|---|---|
| T1_node_count | PASS |
| T1_edge_count | PASS |
| T1_nodes_unchanged | PASS |
| T1_original_edges_and_attributes_unchanged | PASS |
| T1_new_field_definitions | PASS |
| T2_selected_way_count | PASS |
| T3_all_edge_source_fields_match_PBF | PASS |
| T3_speed_source_counts | PASS |
| T3_all_graph_ways_exist_in_PBF | PASS |
| T4_A1_1_closed_way_restored | PASS |
| T4_A1_2_permission_way_restored | PASS |
| T4_A1_2_permission_unit_cases | PASS |
| T5_all_edge_endpoints_valid | PASS |
| T5_no_isolated_nodes | PASS |
| T5_scc_analysis_completed | PASS |
| T6_40_OD_pairs_2_modes | PASS |

## 说明

PBF 字段与 GraphML 属性核验覆盖全部输出边；
路径测试为 40 组 OD、两种代价模式的抽样对照，
使用独立 Python 算法，不代表项目正式路由接口已验收。

详细统计与失败示例见同名 JSON 报告。