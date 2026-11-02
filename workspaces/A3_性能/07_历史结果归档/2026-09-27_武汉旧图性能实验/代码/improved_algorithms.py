# 实验候选，尚未接入正式内核；缓存仅用于不可变图与坐标，数据变化须手动清空。
"""A3 改进版 Dijkstra / A* / 双向搜索。

实测结论（500 组点对、校园路网 552 节点/1400 边）
--------------------------------------------------------------
使用 `ablation.py` 的 20 轮交错计时（中位轮，详细区间见实现与实测记录）：

    算法                        中位 ms/查询   平均展开数
    原始 Dijkstra                  0.3490        267.7
    改进 A*（平面投影）             0.2153        106.2
    平衡势函数双向 A*              0.7458        117.3

双向 A* 与 Dijkstra 距离对拍 **0/500 不符**，逐边 edge id 校验通过；
它比 Dijkstra 少展开约 56%，但在本图规模和纯 Python 实现下仍慢约 2.14 倍，
因此保留为对比算法，不设为默认。其安全提前终止基于共享可行势函数的重加权距离，
不是“前沿相遇即停”；旧版全队列方案及错误终止尝试见调研/实测记录中的历史说明。

改进点及来源
------------
1. **平面投影启发式**（来源：GraphHopper `DistancePlaneProjection`）
   Haversine 每次要 ~8 次三角函数；平面投影只要 4 次，实测单次调用快 2.7 倍。
   局部近似不自动保证可采纳/一致；武汉重加权检查已发现违例，见复测报告。
   校园样本曾测得一致性违例为 0；这不是对其他图或所有目标的保证。
   【贡献】相同展开数（106.2）下，本轮整套 A* 中位 0.3726 → 0.2153 ms（约 1.73x）；
   单独启发式调用微基准为 0.9456 → 0.3026 µs（约 3.1x）。

2. **预处理结果缓存 `_Prepared`**（本项目最大的单项收益）
   邻接表 + 反向邻接表 + 经纬度表的构造成本实测 0.187~0.238 ms/次
   （随预热与系统状态浮动），而一次 A* 查询本身只要 0.13~0.17 ms。
   原实现每次调用都重建，导致"改进版比原始版还慢"（0.347 vs 0.270 ms）。
   按 (id(graph), 节点数) 缓存后降到 0.0025 ms/次。
   【贡献】0.347 → 0.168 ms，约 2x。教训：先测量再优化，热点常在意料之外。

3. **重加权形式**（来源：Organic-Maps 注释 + Eppstein）
   A* 等价于在重加权图上跑 Dijkstra：l_r(v,w) = l(v,w) + h(w) - h(v)
   当 h 一致时 l_r >= 0，于是可以直接复用 Dijkstra 的循环结构。
   实测展开数与 A* 相同（106.2），剪枝效果一致。

4. **路径重建只存边**（来源：GraphHopper `SPTEntry.parent`）
   entry 里存 (边, 父节点)，回溯时从边取端点即可，
   不必同时维护 prev 和 prev_edge 两张表。
   【重要】重建时必须用**搜索当时存下的 edge id**，不能按节点对反查：
   本图存在平行边（同一对节点多条边），反查会取到另一条，长度对不上
   （实测出现过 2.25 m 的假"脱钩"）。

5. **结果结构统一**（响应用户要求）
   三个算法返回同一个 `RouteOutcome`，字段一致，便于对比与测试。

6. **离线做一致性检查，不在热循环里做**
   逐边检查 l_r >= 0 会给每次松弛增加分支，实测让 A* 从 0.25 涨到 0.42 ms。
   而"数据是否自洽"是**离线属性**，加载时查一次即可
   （`path_planning.check_heuristic_consistency()`，本图违反数 0）。

关于平局处理
------------
GraphHopper 的 `compareTo` 在等权重时返回 0（Java 允许），
但 **Python 的 heapq 不允许**：等代价时会去比较元组下一项，抛 TypeError。
实测原始实现因此在真实路网上有 52.3%~58.2%（均值 55.5%）的查询直接崩溃。
所以这里保留单调计数器作为堆键，并写进注释说明原因。

关于双向搜索
-------------
当前 `bidirectional_astar` 是平衡势函数双向 A*。它在同一非负重加权图上运行两侧
Dijkstra，并用队列下界与当前可行路径上界作安全提前终止。500 组真实路网查询正确，
但最新 20 轮中位耗时约 0.7458 ms/查询，慢于单向 A* 与 Dijkstra；故保留作实验对照。
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from heapq import heappop, heappush
from itertools import count

EARTH_RADIUS_M = 6371000.0
_DEG2RAD = math.pi / 180.0


# ============================================================
# 启发函数
# ============================================================

def haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """球面距离（基线用，保留以便公平对比）。"""
    lon1, lat1, lon2, lat2 = lon1 * _DEG2RAD, lat1 * _DEG2RAD, lon2 * _DEG2RAD, lat2 * _DEG2RAD
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat * 0.5) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon * 0.5) ** 2
    if a >= 1.0:
        return 2 * EARTH_RADIUS_M * math.asin(1.0)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def plane_projection(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """平面投影距离（GraphHopper 默认启发式）。

    dlat/dlon 转弧度后，经度方向用中点纬度的 cos 缩放——这正是"把球面投影到平面"。
    这是局部近似，不自动保证小于 Haversine；使用前须验证当前代价模型与目标。
    """
    dlat = (lat2 - lat1) * _DEG2RAD
    dlon = (lon2 - lon1) * _DEG2RAD
    left = math.cos((lat1 + lat2) * 0.5 * _DEG2RAD) * dlon
    return EARTH_RADIUS_M * math.sqrt(dlat * dlat + left * left)


# ============================================================
# 统一结果结构
# ============================================================

@dataclass(slots=True)
class RouteOutcome:
    """三个算法共用的返回结构。"""

    algorithm: str
    found: bool
    node_path: list = field(default_factory=list)
    edge_path: list = field(default_factory=list)
    distance: float = math.inf
    expanded: int = 0          # 展开（确定）的节点数
    pushed: int = 0            # 入堆次数
    solved: bool = True        # 启发式是否满足一致性（False 时结果仍对，但警告）

    def summary(self) -> str:
        if not self.found:
            return f"{self.algorithm:22s} 不可达   展开={self.expanded}"
        return (
            f"{self.algorithm:22s} 距离={self.distance:9.2f} m  "
            f"节点={len(self.node_path):3d} 边={len(self.edge_path):3d} "
            f"展开={self.expanded:4d} 入堆={self.pushed:4d}"
        )


# ============================================================
# 内部工具：把邻接表标准化 + 预取坐标
# ============================================================

class _Prepared:
    """把图与坐标预先摊平成最省的形式，避免热循环里反复做同一件事。

    ⚠️ **结果必须缓存**：构造成本实测 0.187 ms/次，而一次 A* 查询本身只要
    0.16 ms。若每次调用都重建，改进版会比原始版还慢一倍（实测 0.347 vs
    0.237 ms/查询）——这正是"改进版反而更慢"的主要来源。
    缓存键用 (id(graph), 节点数)：同进程内反复查询同一个图对象即命中；
    传入不同的图对象会自动失效重建。
    """

    __slots__ = ("adj", "radj", "lon", "lat", "n_nodes")

    _cache_key = None
    _cache_val = None

    def __new__(cls, graph, positions):
        # 缓存必须放在 __new__（而非 __init__）：Python 在 __new__ 返回已有实例后
        # **仍会调用 __init__**，若把建表写在 __init__ 里，缓存等于白做。
        # 另外 _cache_key/_cache_val 是**类属性**，不能写进 __slots__——
        # 否则赋值会创建同名实例属性，类上始终是 None，判定永不命中。
        key = (id(graph), len(graph))
        if cls._cache_key == key and cls._cache_val is not None:
            return cls._cache_val
        self = object.__new__(cls)
        # adj[u] = [(v, w, eid), ...]  正向邻接表
        self.adj = graph
        # radj[v] = [(u, w, eid), ...] 反向邻接表：把每条 u->v 收进 radj[v]
        #
        # 为什么必须有它：反向搜索从终点出发找"谁通向终点"。
        # 若直接扫正向表 u->v，会得到 g_b[v] = g_b[u] + w，
        # 这个式子的含义是"v 经 u 到终点"，只有当边是 v->u 时才成立。
        # 在有向图上这样算会得到比真实最短路还小的荒谬结果
        # （实测：双向 A* 报 2970，而真最优是 3655）。
        radj = {n: [] for n in graph}
        for u, edges in graph.items():
            for v, w, eid in edges:
                radj.setdefault(v, []).append((u, w, eid))
        self.radj = radj
        self.lon = {n: positions[n][0] for n in positions}
        self.lat = {n: positions[n][1] for n in positions}
        self.n_nodes = len(graph)
        cls._cache_key = key
        cls._cache_val = self
        return self

    def __init__(self, graph, positions):
        # 全部构建已在 __new__ 中完成（缓存友好），这里刻意留空。
        pass


def _reconstruct_edges(parent, node):
    """从 node 沿 parent 链回溯到根，返回**按回溯顺序**的边与节点。

    parent[v] = (edge_id, u) 表示"经由 edge_id 从 u 到达 v"，parent[根] = None。

    返回 (nodes, edges)：
      nodes = [node, u1, u2, ..., 根]
      edges = [进入 node 的边, 进入 u1 的边, ...]   —— 与 nodes 前 len(edges) 项一一对应

    注意正向与反向搜索的区别：
      正向：parent 的根是 start，边是"朝向 v"的 → 反转后方向正确
      反向：parent 的根是 goal，边是"朝向 u"的 → **反转后方向才正确**
    这个方向问题非常容易搞错（我错了三次），所以调用方必须用
    `_assemble_forward_path` 或自行做端点校验。
    """
    nodes = [node]
    edges = []
    while True:
        entry = parent.get(node)
        if entry is None:
            break
        eid, u = entry
        edges.append(eid)
        nodes.append(u)
        node = u
    return nodes, edges


def _assemble_forward_path(graph, parents_list, roots, meet, start, goal):
    """把多段 parent 链拼成一条**从 start 到 goal 的正向路径**。

    做法分两步，且顺序很重要：

    1. **先用节点链**：每段从 meet 沿 parent 回溯得到 [meet, ..., root]（节点），
       反转后即为 root..meet 的正向节点序。把各段首尾相接得到完整节点链。
       节点链是可靠的方向来源——parent 语义就是"我在树上从谁过来"。

    2. **再由节点链反查边**：在正向邻接表里找 u→v 的那条边。
       每一步都校验"确实存在这条正向边"，不存在就抛错。

    为什么不直接用 parent 里存的边 ID：
      反向搜索用的是**反向图**，par_b 里的边 ID 是"原始边的反向"。
      实测症状就是边序列整体错位：
        "节点链要求 13926351892->13926351887，但边 1398 在邻接表里不是这条"。
      由节点链反查可以彻底回避这个方向问题。

    任何一步校验失败都立刻抛错——绝不返回一条看起来正常却走不通的路径。
    """
    full_nodes: list = []

    for idx, (parent, root) in enumerate(zip(parents_list, roots)):
        nodes, _edges = _reconstruct_edges(parent, meet)
        nodes.reverse()                     # root .. meet

        if nodes[0] != root:
            raise RuntimeError(
                f"第 {idx} 段根节点错误: 期望 {root}，实际 {nodes[0]}"
            )

        if full_nodes and full_nodes[-1] == nodes[0]:
            full_nodes.extend(nodes[1:])
        else:
            full_nodes.extend(nodes)

    if full_nodes[0] != start or full_nodes[-1] != goal:
        raise RuntimeError(
            f"拼装后的路径端点错误: 期望 {start}->{goal}，"
            f"实际 {full_nodes[0]}->{full_nodes[-1]}"
        )

    # 由节点链反查正向边，并逐条校验
    full_edges: list = []
    for i in range(len(full_nodes) - 1):
        u, v = full_nodes[i], full_nodes[i + 1]
        found = None
        for vv, _w, e in graph.get(u, ()):
            if vv == v:
                found = e
                break
        if found is None:
            raise RuntimeError(
                f"节点链第 {i} 步 {u}->{v} 在正向邻接表里没有对应边，"
                f"说明拼装出的路径走不通"
            )
        full_edges.append(found)

    return full_nodes, full_edges


def _edges_to_nodes(edge_path, graph, start, goal):
    """由边序列推出节点序列。边端点为 (u, v)，需要按行进方向取。"""
    if not edge_path:
        return [start]
    nodes = [start]
    cur = start
    for eid in edge_path:
        # 在邻接表里找这条边对应的目标点（同一 eid 方向唯一）
        nxt = None
        for v, _w, e in graph.get(cur, ()):
            if e == eid:
                nxt = v
                break
        if nxt is None:
            return nodes
        nodes.append(nxt)
        cur = nxt
    return nodes


# ============================================================
# Dijkstra（改进版）
# ============================================================

def dijkstra(graph, positions, start, goal, *, use_reduced=False, heuristic=None):
    """Dijkstra 最短路。

    use_reduced=True 时在重加权图上跑（用于验证 A* 与 Dijkstra 的等价性）。
    """
    for name, node in (("起点", start), ("终点", goal)):
        if node not in graph:
            raise ValueError(f"{name} {node!r} 不在图中")

    prepared = _Prepared(graph, positions)
    empty = RouteOutcome(algorithm="dijkstra", found=False)
    if start == goal:
        return RouteOutcome(algorithm="dijkstra", found=True, node_path=[start], distance=0.0, expanded=1)

    tie = count()
    dist = {start: 0.0}
    parent = {start: None}
    heap = [(0.0, next(tie), start)]
    settled = set()
    pushed = 1
    glon, glat = prepared.lon[goal], prepared.lat[goal]

    while heap:
        d, _, u = heappop(heap)
        if u in settled:
            continue
        settled.add(u)

        # —— 到达终点：终止（这一行之前漏掉了，导致重加权版本跑满全图）——
        if u == goal:
            # 正向搜索：parent 的根是 start，反转后即得 start..goal 的正向节点与边
            raw_nodes, raw_edges = _reconstruct_edges(parent, goal)
            node_path = list(reversed(raw_nodes))
            edges = list(reversed(raw_edges))
            # 重加权后堆里的 d 是 reduced 长度，要还原成真实长度。
            #
            # 手工推导（用平面投影时 h(goal)=0）：
            #   heap_key(u) = dist(start,u) + h(u) - h(start)
            #   令 u = goal：heap_key(goal) = dist + h(goal) - h(start) = dist - h(start)
            #   所以  real = heap_key(goal) + h(start)
            #
            # 踩过的坑：一开始写成了减去 h(start)（方向反了），
            # 实测在小图上得到 -637.17 m 这种负距离。
            real_d = d
            if use_reduced and heuristic is not None:
                real_d = d + heuristic(
                    prepared.lon[start], prepared.lat[start], glon, glat
                )
            return RouteOutcome(
                algorithm="dijkstra(reduced)" if use_reduced else "dijkstra",
                found=True,
                edge_path=edges,
                node_path=node_path,
                distance=real_d,
                expanded=len(settled),
                pushed=pushed,
            )

        for v, w, eid in graph[u]:
            if v in settled:
                continue
            if use_reduced and heuristic is not None:
                # 重加权：l_r(v,w) = l(v,w) + h(w) - h(v)
                w = w + heuristic(prepared.lon[v], prepared.lat[v], glon, glat) - heuristic(
                    prepared.lon[u], prepared.lat[u], glon, glat
                )
            nd = d + w
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                parent[v] = (eid, u)
                heappush(heap, (nd, next(tie), v))
                pushed += 1

    return empty


# ============================================================
# A*（改进版）
# ============================================================

def astar(graph, positions, start, goal, *, heuristic=plane_projection, check_consistency=False):
    """A* 最短路。默认用平面投影启发式（GraphHopper 的做法）。

    check_consistency=True 时，在松弛过程中逐边检查 l_r(v,w) = w + h(w) - h(v) >= 0。
    一旦发现负值，说明启发式不一致（A* 的最优性不再有保证），solved 会置 False。

    ⚠️ **默认关闭**，这是实测后的决定：
      这个检查给每次松弛增加一次浮点比较和一次分支，
      实测让 A* 每查询耗时从 0.25 ms 涨到 0.42 ms（+68%），
      把平面投影启发式带来的收益全部抵消。
      一致性依赖图权重、启发式和目标；固定组合可以在查询热循环外检查。
      项目里的 `path_planning.check_heuristic_consistency()` 就是干这个的，
      在真实校园路网上实测违反数为 0。
      所以：**离线查数据，在线不查**。
    """
    for name, node in (("起点", start), ("终点", goal)):
        if node not in graph:
            raise ValueError(f"{name} {node!r} 不在图中")

    prepared = _Prepared(graph, positions)
    if start == goal:
        return RouteOutcome(algorithm="astar", found=True, node_path=[start], distance=0.0, expanded=1)

    glon, glat = prepared.lon[goal], prepared.lat[goal]
    lon, lat = prepared.lon, prepared.lat
    tie = count()
    g_score = {start: 0.0}
    parent = {start: None}
    h0 = heuristic(lon[start], lat[start], glon, glat)
    heap = [(h0, next(tie), start, 0.0)]
    settled = {}
    pushed = 1
    consistent = True
    # h 缓存：node -> 启发值。启发式只依赖节点与（固定的）目标，
    # 所以一个节点只需算一次。
    #
    # 为什么必须有它：A* 里同一节点会被反复松弛（每次找到更短的 g），
    # 若每次松弛都重算 h，调用次数会翻倍，把便宜启发式的优势全吃掉。
    # 实测（200 次查询）：无缓存 42554 次调用 vs 有缓存 21289 次，
    # 直接导致我的版本比原始版还慢一倍。
    # 这个技巧是从项目里【原始的 astar.py】学来的——它把 h 存在 enqueued 里。
    h_cache = {start: h0}

    while heap:
        _f, _, u, g = heappop(heap)
        if u in settled and settled[u] <= g:
            continue
        settled[u] = g

        if u == goal:
            raw_nodes, raw_edges = _reconstruct_edges(parent, goal)
            node_path = list(reversed(raw_nodes))
            edges = list(reversed(raw_edges))
            return RouteOutcome(
                algorithm=f"astar({heuristic.__name__})",
                found=True,
                edge_path=edges,
                node_path=node_path,
                distance=g,
                expanded=len(settled),
                pushed=pushed,
                solved=consistent,
            )

        hu = h_cache[u]
        for v, w, eid in graph[u]:
            ng = g + w
            if ng >= g_score.get(v, math.inf):
                continue
            hv = h_cache.get(v)
            if hv is None:
                hv = heuristic(lon[v], lat[v], glon, glat)
                h_cache[v] = hv
            if check_consistency and w + hv - hu < -1e-6:
                consistent = False
            g_score[v] = ng
            parent[v] = (eid, u)
            heappush(heap, (ng + hv, next(tie), v, ng))
            pushed += 1

    return RouteOutcome(algorithm=f"astar({heuristic.__name__})", found=False, expanded=len(settled), pushed=pushed)


# ============================================================
# 双向 A*（改进版）
# ============================================================

def bidirectional_astar(graph, positions, start, goal, *, heuristic=haversine):
    """Balanced bidirectional A* using one shared, feasible reduced-cost graph.

    Requires nonnegative edge costs and a symmetric, edge-consistent heuristic.
    For road distance, Haversine is the safe default:
        p(v) = (h(v, goal) - h(start, v)) / 2
        w'(u,v) = w(u,v) - p(u) + p(v) >= 0

    Both frontiers run Dijkstra on the same reduced costs. The safe stopping
    bound is min_f + min_b >= best_distance + p(goal) - p(start).
    """
    for label, node in (("起点", start), ("终点", goal)):
        if node not in graph:
            raise ValueError(f"{label} {node!r} 不在图中")
    if start == goal:
        return RouteOutcome(
            algorithm="bidirectional_astar", found=True,
            node_path=[start], distance=0.0, expanded=1,
        )

    prepared = _Prepared(graph, positions)
    fwd_adj, rev_adj = prepared.adj, prepared.radj
    lon, lat = prepared.lon, prepared.lat
    slon, slat = lon[start], lat[start]
    glon, glat = lon[goal], lat[goal]
    potential_cache = {}

    def potential(node):
        if node not in potential_cache:
            h_to_goal = heuristic(lon[node], lat[node], glon, glat)
            h_from_start = heuristic(slon, slat, lon[node], lat[node])
            potential_cache[node] = 0.5 * (h_to_goal - h_from_start)
        return potential_cache[node]

    p_start, p_goal = potential(start), potential(goal)
    tie = count()
    g_f, parent_f, closed_f = {start: 0.0}, {start: None}, set()
    g_b, parent_b, closed_b = {goal: 0.0}, {goal: None}, set()
    heap_f = [(0.0, next(tie), start, 0.0)]
    heap_b = [(0.0, next(tie), goal, 0.0)]
    best, meet = math.inf, None
    pushed, expanded = 2, 0

    def discard_stale(heap, distances, closed):
        while heap:
            _key, _order, node, g = heap[0]
            if node in closed or g != distances.get(node):
                heappop(heap)
            else:
                break

    def reduced_cost(tail, head, weight):
        if not math.isfinite(weight) or weight < 0:
            raise ValueError(f"边权必须是有限非负数：{tail!r}->{head!r}={weight!r}")
        result = weight - potential(tail) + potential(head)
        if result < 0:
            raise ValueError(
                f"启发式势函数不可行：reduced cost {tail!r}->{head!r}={result}; "
                "请使用对该图一致的启发式"
            )
        return result

    def update_meeting(node):
        nonlocal best, meet
        if node in g_f and node in g_b:
            candidate = g_f[node] + g_b[node]
            if candidate < best:
                best, meet = candidate, node

    while heap_f and heap_b:
        discard_stale(heap_f, g_f, closed_f)
        discard_stale(heap_b, g_b, closed_b)
        if not heap_f or not heap_b:
            break

        # Queue keys are distances in the same reduced-cost graph.
        if best < math.inf and heap_f[0][0] + heap_b[0][0] >= best + p_goal - p_start:
            break

        use_forward = heap_f[0][0] <= heap_b[0][0]
        heap, own_g, own_parent, own_closed = (
            (heap_f, g_f, parent_f, closed_f) if use_forward
            else (heap_b, g_b, parent_b, closed_b)
        )
        key, _order, node, g = heappop(heap)
        own_closed.add(node)
        expanded += 1
        update_meeting(node)

        if use_forward:
            for nxt, weight, eid in fwd_adj[node]:
                reduced = reduced_cost(node, nxt, weight)
                if nxt in closed_f:
                    continue
                new_g = g + weight
                if new_g < g_f.get(nxt, math.inf):
                    g_f[nxt] = new_g
                    parent_f[nxt] = (eid, node, weight)
                    heappush(
                        heap_f,
                        (key + reduced, next(tie), nxt, new_g),
                    )
                    pushed += 1
                    update_meeting(nxt)
        else:
            # Reverse edge node->nxt corresponds to original edge nxt->node.
            for nxt, weight, eid in rev_adj[node]:
                reduced = reduced_cost(nxt, node, weight)
                if nxt in closed_b:
                    continue
                new_g = g + weight
                if new_g < g_b.get(nxt, math.inf):
                    g_b[nxt] = new_g
                    parent_b[nxt] = (eid, node, weight)
                    heappush(
                        heap_b,
                        (key + reduced, next(tie), nxt, new_g),
                    )
                    pushed += 1
                    update_meeting(nxt)

    if meet is None:
        return RouteOutcome(
            algorithm="bidirectional_astar", found=False,
            expanded=expanded, pushed=pushed,
        )

    left_nodes, left_edges, left_weights = [meet], [], []
    node = meet
    while parent_f[node] is not None:
        eid, previous, weight = parent_f[node]
        left_edges.append(eid)
        left_weights.append(weight)
        left_nodes.append(previous)
        node = previous
    left_nodes.reverse()
    left_edges.reverse()
    left_weights.reverse()

    right_nodes, right_edges, right_weights = [meet], [], []
    node = meet
    while node != goal:
        parent = parent_b.get(node)
        if parent is None:
            raise RuntimeError(f"反向父链断裂：{node!r} 到不了 {goal!r}")
        eid, nxt, weight = parent
        right_edges.append(eid)
        right_weights.append(weight)
        right_nodes.append(nxt)
        node = nxt

    node_path = left_nodes + right_nodes[1:]
    edge_path = left_edges + right_edges
    distance = math.fsum(left_weights + right_weights)
    if not math.isclose(distance, best, rel_tol=1e-12, abs_tol=1e-6):
        raise RuntimeError(f"路径边长和 {distance} 与搜索代价 {best} 不一致")

    return RouteOutcome(
        algorithm=f"bidirectional_astar({heuristic.__name__})",
        found=True,
        edge_path=edge_path,
        node_path=node_path,
        distance=distance,
        expanded=expanded,
        pushed=pushed,
    )
