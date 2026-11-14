# 服务器路网数据

服务器端保存三套尺度的主要道路 SQLite 索引：

- `guangdong-roads.sqlite`：广东省，A4 导航默认使用；
- `shenzhen-roads.sqlite`：深圳市，供 A2/A3 性能测试选择；
- `nanshan-roads.sqlite`：南山区，供 A2/A3 性能测试选择。

服务器通过 `server.py` 读取这些文件。A4 不让用户手动选择底层文件，也不向浏览器发送完整路网；`POST /api/route` 负责吸附、搜索和返回结果。

三份数据库由 `tools/build_graphml_network_db.py` 从对应 GraphML 生成。大文件不要通过 GitHub 网页直接上传，应使用 Git LFS、Release 附件或团队约定的数据包。

数据来源为 OpenStreetMap。重新分发时保留来源、下载时间、范围及 ODbL 许可信息。
