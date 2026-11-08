# 路网数据

完整桌面运行时使用 `data/server/` 下的三套 SQLite 路网索引：

- `guangdong-roads.sqlite`：广东省，A4 导航默认使用；
- `shenzhen-roads.sqlite`：深圳市，A2/A3 性能测试；
- `nanshan-roads.sqlite`：南山区，A2/A3 性能测试。

SQLite 由本地 `server.py` 读取，浏览器不下载或绘制完整路网。A4 请求由服务端计算后只返回搜索轨迹和最终路径。

本源码目录不提交这些大体量 SQLite 文件，避免超过普通 Git 单文件限制。需要直接运行时，请下载仓库 Releases 中的完整桌面包。

武汉 JSON 和旧的 OSM/Overpass 构建脚本如果仍存在，只作为历史资料，不参与当前服务运行。新的路网数据应按项目的 GraphML 转换工具生成对应 SQLite，并保留来源、时间、范围和 ODbL 许可信息。
