# 武汉服务器路网缓存

`wuhan-main-roads.json` 是从 OSM PBF 中提取的武汉范围主要道路数据。它由
`tools/build_wuhan_network.py` 生成，服务器启动后读取整份文件，但浏览器只通过
`/api/network?bbox=south,west,north,east` 获取当前区域。

数据范围包含 `motorway`、`trunk`、`primary`、`secondary`、`tertiary` 及其连接道路，
不包含 POI。数据来源为 OpenStreetMap，遵守 ODbL 1.0，并保留来源和下载时间元信息。

如果服务器数据文件不存在，`server.py` 会暂时回退到上一级 `data/wuhan-main-roads.json`
的小缓存；这只用于保证页面仍能打开，不代表全武汉数据已经准备完成。
