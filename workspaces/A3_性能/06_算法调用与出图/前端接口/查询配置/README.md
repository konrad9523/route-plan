# 固定查询配置

每张路网各保留 100 对已验证连通的起终点和 16 个 ALT 地标 ID。性能 runner 从这里无放回抽取查询；这些是运行输入，不是逐轮实验输出。

查询集源自三规模路网的固定实验批次 `search_optimization_L4_rerun_2026-11-04`。GraphML SHA-256 和规模见仓库根目录 `data/a3_network_manifest.json`。更换路网版本时，应重新生成查询和地标配置。
