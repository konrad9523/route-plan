"""A2-compatible A* baseline and controlled Wuhan-road-network variants.

Graph rows use (neighbor, weight, edge_id). L2-L5 expect dense integer node IDs
in [0, n); call prevalidate_graph once before benchmarking those layers.
"""

from array import array
from heapq import heappop, heappush
from itertools import count
from math import atan2, cos, fsum, inf, isfinite, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000.0
LANDMARK_SAFETY = 1.0 - 1e-12


def haversine_distance(positions, a, b):
    lon1, lat1 = positions[a]
    lon2, lat2 = positions[b]
    lon1, lat1, lon2, lat2 = map(radians, (lon1, lat1, lon2, lat2))
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    value = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    value = min(1.0, max(0.0, value))
    return EARTH_RADIUS_M * 2.0 * atan2(sqrt(value), sqrt(1.0 - value))


def prevalidate_graph(graph, positions):
    """One-time boundary check; also verifies the dense IDs required by L2-L5."""
    n = len(graph)
    if n == 0:
        raise ValueError("路网不能为空")
    if set(graph) != set(range(n)):
        raise ValueError("优化层要求节点编号连续且为 0..n-1 的整数")
    if len(positions) != n or any(node not in positions for node in graph):
        raise ValueError("每个图节点都必须有经纬度坐标")
    for node, (lon, lat) in positions.items():
        if node not in graph or not isfinite(lon) or not isfinite(lat):
            raise ValueError(f"节点 {node!r} 的坐标无效")
        if not -180.0 <= lon <= 180.0 or not -90.0 <= lat <= 90.0:
            raise ValueError(f"节点 {node!r} 的经纬度超出范围")
    for u, outgoing in graph.items():
        for edge in outgoing:
            if len(edge) != 3:
                raise ValueError("邻接边必须为 (neighbor, weight, edge_id)")
            v, weight, _edge_id = edge
            if v not in graph or not isfinite(weight) or weight < 0:
                raise ValueError(f"边 {u!r}->{v!r} 的端点或权重无效")
    return n


def estimate_heuristic_scale(graph, positions):
    """A2's conservative Haversine-to-edge-weight scale, computed over the graph."""
    scale = inf
    for u, outgoing in graph.items():
        if u not in positions:
            raise ValueError(f"节点 {u!r} 缺少坐标")
        for v, weight, _edge_id in outgoing:
            if v not in graph or v not in positions:
                raise ValueError(f"边 {u!r}->{v!r} 的邻接点或坐标缺失")
            if not isfinite(weight) or weight < 0:
                raise ValueError("A* 边权必须为有限非负数")
            length = haversine_distance(positions, u, v)
            if length > 0.0:
                scale = min(scale, weight / length)
    return 0.0 if scale == inf else max(0.0, scale * (1.0 - 1e-12))


def project_coordinates(positions):
    """Local equirectangular projection in meters; its heuristic is scaled separately."""
    n = len(positions)
    if n == 0:
        raise ValueError("坐标集合不能为空")
    if isinstance(positions, dict):
        lat0 = sum(lat for _lon, lat in positions.values()) / n
        lon0 = sum(lon for lon, _lat in positions.values()) / n
        xy = [None] * n
        for node, (lon, lat) in positions.items():
            xy[node] = (
                EARTH_RADIUS_M * radians(lon - lon0) * cos(radians(lat0)),
                EARTH_RADIUS_M * radians(lat - lat0),
            )
        return xy
    lat0 = sum(lat for _lon, lat in positions) / n
    lon0 = sum(lon for lon, _lat in positions) / n
    return [
        (
            EARTH_RADIUS_M * radians(lon - lon0) * cos(radians(lat0)),
            EARTH_RADIUS_M * radians(lat - lat0),
        )
        for lon, lat in positions
    ]


def estimate_plane_scale(graph, projected):
    """Largest global factor certified by every edge for projected Euclidean distance."""
    scale = inf
    for u, outgoing in graph.items():
        ux, uy = projected[u]
        for v, weight, _edge_id in outgoing:
            vx, vy = projected[v]
            length = sqrt((ux - vx) ** 2 + (uy - vy) ** 2)
            if length > 0.0:
                scale = min(scale, weight / length)
    return 0.0 if scale == inf else max(0.0, scale * (1.0 - 1e-12))


def build_csr(graph):
    """Return CSR buffers as Python lists; graph must already be validated."""
    n = len(graph)
    indptr = [0]
    indices, weights, edge_ids = [], [], []
    for u in range(n):
        for v, weight, edge_id in graph[u]:
            indices.append(v)
            weights.append(float(weight))
            edge_ids.append(edge_id)
        indptr.append(len(indices))
    return indptr, indices, weights, edge_ids


def build_reverse_graph(graph):
    reverse = {u: [] for u in graph}
    for u, outgoing in graph.items():
        for v, weight, edge_id in outgoing:
            reverse[v].append((u, weight, edge_id))
    return reverse


def select_landmarks(positions, candidates, count_requested=16):
    """Deterministic geographic farthest-point set; use prefixes for k=4/8/16."""
    candidates = sorted(set(candidates))
    if not candidates or not 1 <= count_requested <= len(candidates):
        raise ValueError("地标数必须介于 1 和候选节点数之间")
    projected = project_coordinates(positions)
    first = min(candidates, key=lambda node: (projected[node][0], projected[node][1], node))
    selected = [first]
    nearest_sq = {}
    x0, y0 = projected[first]
    for node in candidates:
        x, y = projected[node]
        nearest_sq[node] = (x - x0) ** 2 + (y - y0) ** 2
    while len(selected) < count_requested:
        nxt = max(candidates, key=lambda node: (nearest_sq[node], -node))
        selected.append(nxt)
        x0, y0 = projected[nxt]
        for node in candidates:
            x, y = projected[node]
            nearest_sq[node] = min(nearest_sq[node], (x - x0) ** 2 + (y - y0) ** 2)
    return selected


def _dijkstra_distances(adjacency, source):
    n = len(adjacency)
    distance = array("d", [inf]) * n
    distance[source] = 0.0
    heap = [(0.0, source)]
    while heap:
        du, u = heappop(heap)
        if du != distance[u]:
            continue
        for v, weight, _edge_id in adjacency[u]:
            candidate = du + weight
            if candidate < distance[v]:
                distance[v] = candidate
                heappush(heap, (candidate, v))
    return distance


class LandmarkTables:
    """Two directed distance tables per landmark: d(L,v) and d(v,L)."""

    __slots__ = ("landmarks", "from_landmark", "to_landmark", "n_nodes")

    def __init__(self, graph, landmarks):
        self.n_nodes = len(graph)
        self.landmarks = tuple(landmarks)
        reverse = build_reverse_graph(graph)
        self.from_landmark = []
        self.to_landmark = []
        for landmark in self.landmarks:
            self.from_landmark.append(_dijkstra_distances(graph, landmark))
            self.to_landmark.append(_dijkstra_distances(reverse, landmark))

    def heuristic(self, node, goal, landmark_count=None):
        k = len(self.landmarks) if landmark_count is None else landmark_count
        if not 1 <= k <= len(self.landmarks):
            raise ValueError("请求的地标数不在已预处理范围内")
        best = 0.0
        for i in range(k):
            from_l = self.from_landmark[i]
            to_l = self.to_landmark[i]
            a0, a1 = from_l[goal], from_l[node]
            if isfinite(a0) and isfinite(a1):
                best = max(best, a0 - a1)
            b0, b1 = to_l[node], to_l[goal]
            if isfinite(b0) and isfinite(b1):
                best = max(best, b0 - b1)
        return best


def prepare_landmarks(graph, landmarks):
    if not landmarks:
        raise ValueError("ALT 至少需要一个地标")
    if len(set(landmarks)) != len(landmarks):
        raise ValueError("地标编号不能重复")
    if any(node not in graph for node in landmarks):
        raise ValueError("地标必须属于图节点")
    return LandmarkTables(graph, landmarks)


def _heuristic(node, goal, kind, positions, heuristic_scale, projected,
               plane_scale, alt, landmark_count):
    if kind == "H0":
        return haversine_distance(positions, node, goal) * heuristic_scale
    if kind == "PLANE":
        x1, y1 = projected[node]
        x2, y2 = projected[goal]
        return plane_scale * sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)
    if kind == "ALT":
        return alt.heuristic(node, goal, landmark_count)
    if kind == "MAX":
        geo = haversine_distance(positions, node, goal) * heuristic_scale
        return max(geo, alt.heuristic(node, goal, landmark_count))
    if kind == "MAX_PLANE":
        x1, y1 = projected[node]
        x2, y2 = projected[goal]
        geo = plane_scale * sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)
        return max(geo, alt.heuristic(node, goal, landmark_count))
    raise ValueError(f"未知启发式：{kind!r}")


def _check_endpoints(graph, start, goal):
    if start not in graph:
        raise ValueError(f"起点 {start!r} 不存在")
    if goal not in graph:
        raise ValueError(f"终点 {goal!r} 不存在")


def _restore_dict(prev, prev_edge, start, goal):
    nodes, edges = [goal], []
    node = goal
    while node != start:
        if node not in prev or node not in prev_edge:
            raise RuntimeError("前驱记录不完整，无法恢复路径")
        edges.append(prev_edge[node])
        node = prev[node]
        nodes.append(node)
    nodes.reverse()
    edges.reverse()
    return nodes, edges


def _restore_arrays(prev, prev_edge, start, goal):
    nodes, edges = [goal], []
    node = goal
    while node != start:
        parent = prev[node]
        if parent < 0:
            raise RuntimeError("前驱数组不完整，无法恢复路径")
        edges.append(prev_edge[node])
        node = parent
        nodes.append(node)
        if len(nodes) > len(prev):
            raise RuntimeError("前驱数组存在环")
    nodes.reverse()
    edges.reverse()
    return nodes, edges


def run_astar(version, graph, positions, start, goal, *, heuristic="H0",
              heuristic_scale=None, projected=None, plane_scale=None,
              csr=None, alt=None, landmark_count=0, stats=None):
    """Run L0-L5; return (nodes, edge_ids, distance, distinct_expanded_nodes).

    `stats`, when supplied, is filled with counters for a separate diagnostic pass.
    L1-L5 assume `prevalidate_graph` has already succeeded. L4-L5 need `csr`.
    """
    names = {"L0-CACHEDSCALE": "L0C", "L0-CACHED-SCALE": "L0C"}
    layer = names.get(version.upper().replace("_", "-"), version.upper())
    if layer not in {"L0", "L0C", "L1", "L2", "L3", "L4", "L5"}:
        raise ValueError(f"未知 A* 版本：{version!r}")
    if heuristic not in {"H0", "PLANE", "ALT", "MAX", "MAX_PLANE"}:
        raise ValueError(f"未知启发式：{heuristic!r}")
    if layer in {"L0", "L0C"} and heuristic != "H0":
        raise ValueError("A2 基线组只允许使用 H0")
    _check_endpoints(graph, start, goal)
    if layer in {"L2", "L3", "L4", "L5"}:
        n = len(graph)
        if type(start) is not int or type(goal) is not int or not (0 <= start < n and 0 <= goal < n):
            raise ValueError("L2-L5 要求连续整数节点编号")
    if layer in {"L4", "L5"}:
        if csr is None:
            raise ValueError("L4-L5 必须传入预先构造的 CSR")
        indptr, indices, weights, edge_ids = csr
        n = len(indptr) - 1
        if n != len(graph):
            raise ValueError("CSR 与邻接表节点数不一致")
    else:
        indptr = indices = weights = edge_ids = None
        n = len(graph)

    if layer == "L0" and heuristic_scale is None:
        heuristic_scale = estimate_heuristic_scale(graph, positions)
    elif heuristic in {"H0", "MAX"} and heuristic_scale is None:
        raise ValueError("请在查询计时外预先计算并传入 heuristic_scale")
    if layer == "L0C" and heuristic_scale is None:
        raise ValueError("L0-CachedScale 要求调用方传入预计算比例")
    if heuristic_scale is not None and (not isfinite(heuristic_scale) or heuristic_scale < 0):
        raise ValueError("heuristic_scale 必须为有限非负数")
    if heuristic in {"PLANE", "MAX_PLANE"} and (projected is None or plane_scale is None):
        raise ValueError("平面启发式需要预计算坐标投影和安全比例")
    if plane_scale is not None and (not isfinite(plane_scale) or plane_scale < 0):
        raise ValueError("plane_scale 必须为有限非负数")
    if heuristic in {"ALT", "MAX", "MAX_PLANE"} and alt is None:
        raise ValueError("ALT 启发式需要预处理的 LandmarkTables")
    if heuristic in {"ALT", "MAX", "MAX_PLANE"} and landmark_count < 1:
        raise ValueError("ALT 启发式需要 landmark_count >= 1")
    if heuristic in {"ALT", "MAX", "MAX_PLANE"} and landmark_count > len(alt.landmarks):
        raise ValueError("请求的地标数超过已预处理表的数量")

    if layer == "L0" and start == goal:
        return [start], [], 0.0, 1
    if start == goal:
        return [start], [], 0.0, 1

    dense_state = layer in {"L2", "L3", "L4", "L5"}
    dense_parent = layer in {"L3", "L4", "L5"}
    use_csr = layer in {"L4", "L5"}
    cache_h = layer == "L5"
    check_edges = layer in {"L0", "L0C"}
    best_g = [inf] * n if dense_state else {start: 0.0}
    explored_g = [inf] * n if dense_state else {}
    prev = [-1] * n if dense_parent else {start: None}
    prev_edge = [None] * n if dense_parent else {}
    if dense_state:
        best_g[start] = 0.0
    queue_order = count()
    h_cache = {} if cache_h else None
    counters = {"pushed_count": 1, "scanned_edges": 0, "heuristic_evaluations": 0}
    collect_stats = stats is not None

    def h_value(node):
        if cache_h and node in h_cache:
            return h_cache[node]
        value = _heuristic(node, goal, heuristic, positions, heuristic_scale,
                           projected, plane_scale, alt, landmark_count)
        if cache_h:
            h_cache[node] = value
        if collect_stats:
            counters["heuristic_evaluations"] += 1
        return value

    queue = [(h_value(start), next(queue_order), start, 0.0)]
    expanded_count = 0

    while queue:
        _f, _order, u, distance = heappop(queue)
        current_best = best_g[u] if dense_state else best_g.get(u, inf)
        if distance != current_best:
            continue
        previous_expansion = explored_g[u] if dense_state else explored_g.get(u, inf)
        if distance >= previous_expansion:
            continue
        if previous_expansion == inf:
            expanded_count += 1
        if dense_state:
            explored_g[u] = distance
        else:
            explored_g[u] = distance

        if u == goal:
            if dense_parent:
                nodes, path_edges = _restore_arrays(prev, prev_edge, start, goal)
            else:
                nodes, path_edges = _restore_dict(prev, prev_edge, start, goal)
            if collect_stats:
                stats.update(counters, expanded_nodes=expanded_count)
            return nodes, path_edges, distance, expanded_count

        if use_csr:
            neighbors = ((indices[i], weights[i], edge_ids[i])
                         for i in range(indptr[u], indptr[u + 1]))
        else:
            neighbors = graph[u]
        for v, weight, edge_id in neighbors:
            if collect_stats:
                counters["scanned_edges"] += 1
            if check_edges and (v not in graph or not isfinite(weight) or weight < 0 or v not in positions):
                raise ValueError("A* 搜索遇到无效邻接边、权重或坐标")
            candidate = distance + weight
            old = best_g[v] if dense_state else best_g.get(v, inf)
            if candidate < old:
                if dense_state:
                    best_g[v] = candidate
                else:
                    best_g[v] = candidate
                if dense_parent:
                    prev[v], prev_edge[v] = u, edge_id
                else:
                    prev[v], prev_edge[v] = u, edge_id
                heappush(queue, (candidate + h_value(v), next(queue_order), v, candidate))
                if collect_stats:
                    counters["pushed_count"] += 1

    if collect_stats:
        stats.update(counters, expanded_nodes=expanded_count)
    return [], [], inf, expanded_count


def bidirectional_astar(graph, reverse_graph, positions, start, goal, *,
                        heuristic="H0", heuristic_scale=None, projected=None,
                        plane_scale=None, alt=None, landmark_count=0, stats=None):
    """Exact bidirectional A* via one consistent target potential and reweighted edges.

    Both Dijkstra queues operate on the same nonnegative reduced costs. The stopping
    bound is min_forward + min_backward >= best_complete_route, not first meeting.
    """
    _check_endpoints(graph, start, goal)
    if heuristic not in {"H0", "PLANE", "ALT", "MAX", "MAX_PLANE"}:
        raise ValueError(f"未知启发式：{heuristic!r}")
    if start not in reverse_graph or goal not in reverse_graph:
        raise ValueError("反向图缺少起点或终点")
    if heuristic in {"H0", "MAX"} and heuristic_scale is None:
        raise ValueError("请预先传入 Haversine 安全比例")
    if heuristic in {"PLANE", "MAX_PLANE"} and (projected is None or plane_scale is None):
        raise ValueError("平面启发式需要投影坐标与安全比例")
    if heuristic in {"ALT", "MAX", "MAX_PLANE"} and (alt is None or landmark_count < 1):
        raise ValueError("ALT 启发式需要有效的地标表与地标数")
    if heuristic in {"ALT", "MAX", "MAX_PLANE"} and landmark_count > len(alt.landmarks):
        raise ValueError("请求的地标数超过已预处理表的数量")
    if heuristic_scale is not None and (not isfinite(heuristic_scale) or heuristic_scale < 0):
        raise ValueError("heuristic_scale 必须为有限非负数")
    if plane_scale is not None and (not isfinite(plane_scale) or plane_scale < 0):
        raise ValueError("plane_scale 必须为有限非负数")
    if start == goal:
        if stats is not None:
            stats.update(pushed_count=1, scanned_edges=0, heuristic_evaluations=0, expanded_nodes=1)
        return [start], [], 0.0, 1

    h_cache = {}
    h_calls = 0

    def potential(node):
        nonlocal h_calls
        if node not in h_cache:
            h_cache[node] = LANDMARK_SAFETY * _heuristic(
                node, goal, heuristic, positions, heuristic_scale,
                projected, plane_scale, alt, landmark_count,
            )
            h_calls += 1
        return h_cache[node]

    def reduced(weight, u, v):
        value = weight + potential(u) - potential(v)
        if value < -1e-9:
            raise ValueError("双向 A* 启发函数不一致，重标权边出现负值")
        return max(0.0, value)

    order_f, order_b = count(), count()
    dist_f, dist_b = {start: 0.0}, {goal: 0.0}
    settled_f, settled_b = {}, {}
    parent_f, edge_f = {start: None}, {}
    next_b, edge_b = {goal: None}, {}
    qf = [(0.0, next(order_f), start)]
    qb = [(0.0, next(order_b), goal)]
    best = inf
    join = None
    scanned = pushed = 0

    def consider(left, right, bridge, value):
        nonlocal best, join
        if value < best:
            best, join = value, (left, right, bridge)

    def top_valid(queue, distances, settled):
        while queue:
            distance, _order, node = queue[0]
            if node in settled or distance != distances.get(node, inf):
                heappop(queue)
            else:
                return distance
        return inf

    while True:
        min_f = top_valid(qf, dist_f, settled_f)
        min_b = top_valid(qb, dist_b, settled_b)
        if best < inf and min_f + min_b >= best:
            break
        if min_f == inf or min_b == inf:
            break
        if min_f <= min_b:
            distance, _order, u = heappop(qf)
            settled_f[u] = distance
            if u in dist_b:
                consider(u, u, None, distance + dist_b[u])
            for v, weight, edge_id in graph[u]:
                scanned += 1
                reduced_weight = reduced(weight, u, v)
                candidate = distance + reduced_weight
                if candidate < dist_f.get(v, inf):
                    dist_f[v] = candidate
                    parent_f[v], edge_f[v] = u, edge_id
                    heappush(qf, (candidate, next(order_f), v))
                    pushed += 1
                if v in dist_b:
                    consider(u, v, (edge_id, weight), distance + reduced_weight + dist_b[v])
        else:
            distance, _order, v = heappop(qb)
            settled_b[v] = distance
            if v in dist_f:
                consider(v, v, None, dist_f[v] + distance)
            for u, weight, edge_id in reverse_graph[v]:
                scanned += 1
                reduced_weight = reduced(weight, u, v)
                candidate = distance + reduced_weight
                if candidate < dist_b.get(u, inf):
                    dist_b[u] = candidate
                    next_b[u], edge_b[u] = v, edge_id
                    heappush(qb, (candidate, next(order_b), u))
                    pushed += 1
                if u in dist_f:
                    consider(u, v, (edge_id, weight), dist_f[u] + reduced_weight + distance)

    expanded = len(settled_f) + len(settled_b)
    if join is None:
        if stats is not None:
            stats.update(pushed_count=pushed + 2, scanned_edges=scanned,
                         heuristic_evaluations=h_calls, expanded_nodes=expanded)
        return [], [], inf, expanded

    left, right, bridge = join
    nodes, path_edges = _restore_dict(parent_f, edge_f, start, left)
    if bridge is not None:
        bridge_id, _bridge_weight = bridge
        nodes.append(right)
        path_edges.append(bridge_id)
    node = right
    while node != goal:
        if node not in next_b or node not in edge_b:
            raise RuntimeError("反向前驱记录不完整，无法恢复双向路径")
        path_edges.append(edge_b[node])
        node = next_b[node]
        nodes.append(node)
        if len(nodes) > len(graph):
            raise RuntimeError("双向前驱链存在环")
    route_weights = []
    for u, v, edge_id in zip(nodes, nodes[1:], path_edges):
        for nxt, weight, candidate_edge_id in graph[u]:
            if nxt == v and candidate_edge_id == edge_id:
                route_weights.append(weight)
                break
        else:
            raise RuntimeError("双向路径包含不属于原图的 edge_id")
    route_distance = fsum(route_weights)
    if stats is not None:
        stats.update(pushed_count=pushed + 2, scanned_edges=scanned,
                     heuristic_evaluations=h_calls, expanded_nodes=expanded)
    return nodes, path_edges, route_distance, expanded


def self_test():
    graph = {
        0: [(1, 1.0, 100), (1, 1.2, 101), (2, 5.0, 102)],
        1: [(2, 1.0, 103), (3, 4.0, 104)],
        2: [(3, 1.0, 105)],
        3: [(4, 0.5, 106)],
        4: [(4, 0.0, 107)],
        5: [],
    }
    positions = {
        0: (114.0, 30.0), 1: (114.01, 30.0), 2: (114.02, 30.0),
        3: (114.03, 30.0), 4: (114.04, 30.0), 5: (115.0, 31.0),
    }
    prevalidate_graph(graph, positions)
    csr = build_csr(graph)
    h_scale = estimate_heuristic_scale(graph, positions)
    projected = project_coordinates(positions)
    p_scale = estimate_plane_scale(graph, projected)
    alt = prepare_landmarks(graph, [0, 4])
    expected = 3.5
    for version in ("L0", "L1", "L2", "L3", "L4", "L5"):
        for heuristic in ("H0", "PLANE", "ALT", "MAX"):
            kwargs = dict(heuristic=heuristic, heuristic_scale=h_scale,
                          projected=projected, plane_scale=p_scale, csr=csr,
                          alt=alt, landmark_count=2)
            if version == "L0":
                kwargs["heuristic"] = "H0"
            nodes, edges, distance, expanded = run_astar(
                version, graph, positions, 0, 4, **kwargs
            )
            assert abs(distance - expected) < 1e-12
            assert len(nodes) == len(edges) + 1 and expanded > 0
            for u, v, edge_id in zip(nodes, nodes[1:], edges):
                assert any(nxt == v and eid == edge_id for nxt, _w, eid in graph[u])
    reverse = build_reverse_graph(graph)
    nodes, edges, distance, _expanded = bidirectional_astar(
        graph, reverse, positions, 0, 4, heuristic="MAX",
        heuristic_scale=h_scale, alt=alt, landmark_count=2,
    )
    assert abs(distance - expected) < 1e-12 and len(nodes) == len(edges) + 1
    assert run_astar("L5", graph, positions, 0, 5, heuristic="ALT",
                     csr=csr, alt=alt, landmark_count=2)[2] == inf
    assert bidirectional_astar(graph, reverse, positions, 0, 5,
                               heuristic="ALT", alt=alt, landmark_count=2)[2] == inf
    assert run_astar("L0", graph, positions, 3, 3)[2] == 0.0
    assert run_astar("L0", graph, positions, 0, 4)[2] == expected


if __name__ == "__main__":
    self_test()
    print("A* Python self-test passed")
