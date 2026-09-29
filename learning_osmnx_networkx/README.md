# OSMnx + NetworkX 路网与路径规划练习

这是项目的第一个动手练习，用于理解：

~~~text
OpenStreetMap 数据
    → OSMnx 道路网络
    → NetworkX 图搜索
    → 距离最短 / 时间最短路线
    → HTML 地图展示
~~~

## 1. 安装依赖

在项目根目录执行：

~~~powershell
python -m pip install -r learning_osmnx_networkx/requirements.txt
~~~

## 2. 运行

默认以中国地质大学（武汉）为中心，请求半径 1800 米的校园及周边道路：

~~~powershell
python learning_osmnx_networkx/route_demo.py
~~~

也可以指定区域：

~~~powershell
python learning_osmnx_networkx/route_demo.py --place "China University of Geosciences, Wuhan, China"
~~~

也可以调整抓取半径：

~~~powershell
python learning_osmnx_networkx/route_demo.py --dist 2500
~~~

指定出行方式：

~~~powershell
python learning_osmnx_networkx/route_demo.py --network-type bike
~~~

程序会在当前目录生成：

- learning_osmnx_networkx/output/route_demo.html：路线地图；
- learning_osmnx_networkx/output/graph.graphml：保存的道路图；
- learning_osmnx_networkx/output/route_summary.json：路线统计。

## 3. 这个练习要观察什么

先分别运行：

~~~powershell
python learning_osmnx_networkx/route_demo.py --weight length
python learning_osmnx_networkx/route_demo.py --weight travel_time
~~~

然后比较：

- 两条路线是否相同；
- 距离和预计时间是否不同；
- 图中有多少节点和边；
- 程序使用了哪些道路属性；
- 单行道是否被遵守；
- walk、bike、drive 得到的路网是否不同。

## 4. 下一步练习

1. 增加 origin 和 destination 参数；
2. 增加不走高速的道路过滤；
3. 增加红绿灯惩罚；
4. 返回三条候选路线；
5. 把路线结果交给 FastAPI；
6. 用我们的 path_planning 代码和 NetworkX 对照；
7. 给道路叠加 DEM 坡度；
8. 增加消防车 emergency profile。

## 5. 重要提醒

这个练习第一次运行需要访问 OpenStreetMap 的数据服务，区域不要设置得太大。项目学习阶段使用小区域即可。数据下载和查询应遵守 OpenStreetMap 的使用政策，并在展示中保留数据来源说明。
