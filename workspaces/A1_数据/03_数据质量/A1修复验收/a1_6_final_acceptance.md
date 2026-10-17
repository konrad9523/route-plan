# A1-6 收费属性加载修复综合验收报告

**最终结论：PASS**

- 节点数：41679
- 有向边数：99543
- 收费边数：25
- 非收费或未标记收费边数：99518

| 测试项目 | 结果 |
|---|---|
| T1_loader_patch | PASS |
| T2_toll_parsing | PASS |
| T3_graphml_to_edge_toll | PASS |
| T4_dijkstra_and_astar_toll_routing | PASS |
| T5_real_graph_node_count | PASS |
| T6_real_graph_edge_count | PASS |
| T7_all_real_toll_attributes_match | PASS |
| T8_project_pytest | PASS |
