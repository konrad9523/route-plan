// A2-compatible A* variants for the Wuhan road-network experiment.
// Build as a DLL for ctypes; define ASTAR_SELF_TEST to run the embedded checks.
#include <algorithm>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <optional>
#include <queue>
#include <set>
#include <stdexcept>
#include <unordered_map>
#include <utility>
#include <vector>

#ifdef _WIN32
#define ASTAR_API extern "C" __declspec(dllexport)
#else
#define ASTAR_API extern "C"
#endif

namespace {

constexpr double kEarthRadiusM = 6371000.0;
constexpr double kPotentialSafety = 1.0 - 1e-12;
constexpr double kInfinity = std::numeric_limits<double>::infinity();

enum Status : int32_t {
    OK = 0,
    INVALID_ARGUMENT = 1,
    INVALID_GRAPH = 2,
    INVALID_QUERY = 3,
    BUFFER_TOO_SMALL = 4,
    PREPARATION_REQUIRED = 5,
    INTERNAL_ERROR = 6
};

enum Version : int32_t {
    L0 = 0,
    L0_CACHED_SCALE = 1,
    L1 = 2,
    L2 = 3,
    L3 = 4,
    L4 = 5,
    L5 = 6,
    B1 = 7
};

enum Heuristic : int32_t {
    H0 = 0,
    HPLANE = 1,
    HALT = 2,
    HMAX = 3,
    HMAX_PLANE = 4
};

struct Edge {
    int64_t to;
    double weight;
    int64_t id;
};

struct Graph {
    int64_t n = 0;
    int64_t m = 0;
    std::vector<int64_t> indptr, indices, edge_ids;
    std::vector<double> weights, lon, lat, x, y;
    std::vector<std::vector<Edge>> forward, reverse;
    std::vector<int64_t> landmarks;
    std::vector<double> from_landmark, to_landmark;
    double haversine_scale = 0.0;
    double plane_scale = 0.0;
    bool geometry_ready = false;
    bool reverse_ready = false;
    bool alt_ready = false;
};

struct QueueItem {
    double priority;
    double distance;
    uint64_t order;
    int64_t node;
};

struct Later {
    bool operator()(const QueueItem& a, const QueueItem& b) const {
        if (a.priority != b.priority) return a.priority > b.priority;
        return a.order > b.order;
    }
};

using Queue = std::priority_queue<QueueItem, std::vector<QueueItem>, Later>;

struct DistanceItem {
    double distance;
    int64_t node;
};

struct DistanceLater {
    bool operator()(const DistanceItem& a, const DistanceItem& b) const {
        if (a.distance != b.distance) return a.distance > b.distance;
        return a.node > b.node;
    }
};

struct Result {
    std::vector<int64_t> nodes, edges;
    double distance = kInfinity;
    uint64_t expanded = 0;
    uint64_t pushed = 0;
    uint64_t scanned = 0;
    uint64_t heuristic_evaluations = 0;
};

double haversine(double lon1, double lat1, double lon2, double lat2) {
    constexpr double pi = 3.141592653589793238462643383279502884;
    const double phi1 = lat1 * pi / 180.0;
    const double phi2 = lat2 * pi / 180.0;
    const double dphi = (lat2 - lat1) * pi / 180.0;
    const double dlambda = (lon2 - lon1) * pi / 180.0;
    double a = std::sin(dphi / 2.0) * std::sin(dphi / 2.0) +
               std::cos(phi1) * std::cos(phi2) *
                   std::sin(dlambda / 2.0) * std::sin(dlambda / 2.0);
    a = std::clamp(a, 0.0, 1.0);
    return kEarthRadiusM * 2.0 * std::atan2(std::sqrt(a), std::sqrt(1.0 - a));
}

double estimate_haversine_scale(const Graph& g) {
    double scale = kInfinity;
    for (int64_t u = 0; u < g.n; ++u) {
        const size_t begin = static_cast<size_t>(g.indptr[static_cast<size_t>(u)]);
        const size_t end = static_cast<size_t>(g.indptr[static_cast<size_t>(u + 1)]);
        for (size_t i = begin; i < end; ++i) {
            const int64_t v = g.indices[i];
            const double weight = g.weights[i];
            if (v < 0 || v >= g.n || !std::isfinite(weight) || weight < 0.0 ||
                !std::isfinite(g.lon[static_cast<size_t>(u)]) ||
                !std::isfinite(g.lat[static_cast<size_t>(u)]) ||
                !std::isfinite(g.lon[static_cast<size_t>(v)]) ||
                !std::isfinite(g.lat[static_cast<size_t>(v)]))
                throw std::logic_error("invalid edge encountered during scale estimation");
            const double length = haversine(
                g.lon[static_cast<size_t>(u)], g.lat[static_cast<size_t>(u)],
                g.lon[static_cast<size_t>(v)], g.lat[static_cast<size_t>(v)]);
            if (length > 0.0) scale = std::min(scale, weight / length);
        }
    }
    return std::isfinite(scale) ? std::max(0.0, scale * (1.0 - 1e-12)) : 0.0;
}

std::vector<double> dijkstra_distances(const std::vector<std::vector<Edge>>& adj,
                                       int64_t source) {
    std::vector<double> distance(adj.size(), kInfinity);
    std::priority_queue<DistanceItem, std::vector<DistanceItem>, DistanceLater> queue;
    distance[static_cast<size_t>(source)] = 0.0;
    queue.push({0.0, source});
    while (!queue.empty()) {
        const DistanceItem item = queue.top();
        queue.pop();
        if (item.distance != distance[static_cast<size_t>(item.node)]) continue;
        for (const Edge& edge : adj[static_cast<size_t>(item.node)]) {
            const double candidate = item.distance + edge.weight;
            double& old = distance[static_cast<size_t>(edge.to)];
            if (candidate < old) {
                old = candidate;
                queue.push({candidate, edge.to});
            }
        }
    }
    return distance;
}

double alt_heuristic(const Graph& g, int64_t node, int64_t goal, int32_t k) {
    if (!g.alt_ready || k < 1 || static_cast<size_t>(k) > g.landmarks.size())
        throw std::logic_error("ALT tables are not prepared for this landmark count");
    double best = 0.0;
    const size_t n = static_cast<size_t>(g.n);
    for (int32_t i = 0; i < k; ++i) {
        const size_t base = static_cast<size_t>(i) * n;
        const double l_goal = g.from_landmark[base + static_cast<size_t>(goal)];
        const double l_node = g.from_landmark[base + static_cast<size_t>(node)];
        if (std::isfinite(l_goal) && std::isfinite(l_node))
            best = std::max(best, l_goal - l_node);
        const double node_l = g.to_landmark[base + static_cast<size_t>(node)];
        const double goal_l = g.to_landmark[base + static_cast<size_t>(goal)];
        if (std::isfinite(node_l) && std::isfinite(goal_l))
            best = std::max(best, node_l - goal_l);
    }
    return best;
}

double heuristic_value(const Graph& g, int64_t node, int64_t goal,
                       int32_t kind, int32_t k, double scale) {
    const size_t u = static_cast<size_t>(node);
    const size_t t = static_cast<size_t>(goal);
    double geo = 0.0;
    if (kind == H0 || kind == HMAX) {
        geo = scale * haversine(g.lon[u], g.lat[u], g.lon[t], g.lat[t]);
        if (kind == H0) return geo;
    } else if (kind == HPLANE || kind == HMAX_PLANE) {
        geo = g.plane_scale * std::hypot(g.x[u] - g.x[t], g.y[u] - g.y[t]);
        if (kind == HPLANE) return geo;
    }
    const double alt = alt_heuristic(g, node, goal, k);
    return kind == HALT ? alt : std::max(geo, alt);
}

std::pair<std::vector<int64_t>, std::vector<int64_t>> restore_map(
    const std::unordered_map<int64_t, int64_t>& parent,
    const std::unordered_map<int64_t, int64_t>& parent_edge,
    int64_t start, int64_t goal, int64_t limit) {
    std::vector<int64_t> nodes{goal}, edges;
    for (int64_t node = goal; node != start;) {
        const auto p = parent.find(node);
        const auto e = parent_edge.find(node);
        if (p == parent.end() || e == parent_edge.end() ||
            static_cast<int64_t>(nodes.size()) > limit)
            throw std::logic_error("broken predecessor chain");
        edges.push_back(e->second);
        node = p->second;
        nodes.push_back(node);
    }
    std::reverse(nodes.begin(), nodes.end());
    std::reverse(edges.begin(), edges.end());
    return {std::move(nodes), std::move(edges)};
}

std::pair<std::vector<int64_t>, std::vector<int64_t>> restore_arrays(
    const std::vector<int64_t>& parent,
    const std::vector<int64_t>& parent_edge,
    int64_t start, int64_t goal, int64_t limit) {
    std::vector<int64_t> nodes{goal}, edges;
    for (int64_t node = goal; node != start;) {
        if (node < 0 || node >= limit || parent[static_cast<size_t>(node)] < 0 ||
            static_cast<int64_t>(nodes.size()) > limit)
            throw std::logic_error("broken predecessor array");
        edges.push_back(parent_edge[static_cast<size_t>(node)]);
        node = parent[static_cast<size_t>(node)];
        nodes.push_back(node);
    }
    std::reverse(nodes.begin(), nodes.end());
    std::reverse(edges.begin(), edges.end());
    return {std::move(nodes), std::move(edges)};
}

template <bool CheckEachEdge, typename HFn>
Result run_map(const Graph& g, int64_t start, int64_t goal, HFn&& h) {
    Result out;
    if (start == goal) {
        out.nodes = {start};
        out.distance = 0.0;
        out.expanded = 1;
        return out;
    }
    std::unordered_map<int64_t, double> best{{start, 0.0}}, explored;
    std::unordered_map<int64_t, int64_t> parent{{start, -1}}, parent_edge;
    Queue queue;
    uint64_t order = 0;
    auto eval_h = [&](int64_t node) {
        ++out.heuristic_evaluations;
        return h(node);
    };
    queue.push({eval_h(start), 0.0, order++, start});
    out.pushed = 1;

    while (!queue.empty()) {
        const QueueItem item = queue.top();
        queue.pop();
        const auto current = best.find(item.node);
        if (current == best.end() || item.distance != current->second) continue;
        const auto previous = explored.find(item.node);
        if (previous != explored.end() && item.distance >= previous->second) continue;
        explored[item.node] = item.distance;
        if (item.node == goal) {
            auto path = restore_map(parent, parent_edge, start, goal, g.n);
            out.nodes = std::move(path.first);
            out.edges = std::move(path.second);
            out.distance = item.distance;
            out.expanded = explored.size();
            return out;
        }
        for (const Edge& edge : g.forward[static_cast<size_t>(item.node)]) {
            ++out.scanned;
            if constexpr (CheckEachEdge) {
                if (edge.to < 0 || edge.to >= g.n || !std::isfinite(edge.weight) ||
                    edge.weight < 0.0 || !std::isfinite(g.lon[static_cast<size_t>(edge.to)]) ||
                    !std::isfinite(g.lat[static_cast<size_t>(edge.to)]))
                    throw std::logic_error("invalid edge encountered in search");
            }
            const double candidate = item.distance + edge.weight;
            auto old = best.find(edge.to);
            if (old == best.end() || candidate < old->second) {
                best[edge.to] = candidate;
                parent[edge.to] = item.node;
                parent_edge[edge.to] = edge.id;
                queue.push({candidate + eval_h(edge.to), candidate, order++, edge.to});
                ++out.pushed;
            }
        }
    }
    out.expanded = explored.size();
    return out;
}

template <bool DenseParent, bool UseCsr, bool CacheHeuristic, typename HFn>
Result run_dense(const Graph& g, int64_t start, int64_t goal, HFn&& raw_h) {
    Result out;
    if (start == goal) {
        out.nodes = {start};
        out.distance = 0.0;
        out.expanded = 1;
        return out;
    }
    const size_t n = static_cast<size_t>(g.n);
    std::vector<double> best(n, kInfinity), explored(n, kInfinity);
    std::vector<uint8_t> ever_expanded(n, 0);
    std::vector<int64_t> parent, parent_edge;
    std::unordered_map<int64_t, int64_t> map_parent{{start, -1}}, map_parent_edge;
    if constexpr (DenseParent) {
        parent.assign(n, -1);
        parent_edge.assign(n, -1);
    }
    std::unordered_map<int64_t, double> h_cache;
    auto h = [&](int64_t node) {
        if constexpr (CacheHeuristic) {
            const auto cached = h_cache.find(node);
            if (cached != h_cache.end()) return cached->second;
        }
        const double value = raw_h(node);
        ++out.heuristic_evaluations;
        if constexpr (CacheHeuristic) h_cache.emplace(node, value);
        return value;
    };

    Queue queue;
    uint64_t order = 0;
    best[static_cast<size_t>(start)] = 0.0;
    queue.push({h(start), 0.0, order++, start});
    out.pushed = 1;
    while (!queue.empty()) {
        const QueueItem item = queue.top();
        queue.pop();
        const size_t u = static_cast<size_t>(item.node);
        if (item.distance != best[u] || item.distance >= explored[u]) continue;
        if (!ever_expanded[u]) {
            ever_expanded[u] = 1;
            ++out.expanded;
        }
        explored[u] = item.distance;
        if (item.node == goal) {
            auto path = [&]() {
                if constexpr (DenseParent)
                    return restore_arrays(parent, parent_edge, start, goal, g.n);
                else
                    return restore_map(map_parent, map_parent_edge, start, goal, g.n);
            }();
            out.nodes = std::move(path.first);
            out.edges = std::move(path.second);
            out.distance = item.distance;
            return out;
        }
        auto relax = [&](int64_t v, double weight, int64_t edge_id) {
            ++out.scanned;
            const size_t vi = static_cast<size_t>(v);
            const double candidate = item.distance + weight;
            if (candidate < best[vi]) {
                best[vi] = candidate;
                if constexpr (DenseParent) {
                    parent[vi] = item.node;
                    parent_edge[vi] = edge_id;
                } else {
                    map_parent[v] = item.node;
                    map_parent_edge[v] = edge_id;
                }
                queue.push({candidate + h(v), candidate, order++, v});
                ++out.pushed;
            }
        };
        if constexpr (UseCsr) {
            for (int64_t i = g.indptr[u]; i < g.indptr[u + 1]; ++i) {
                const size_t k = static_cast<size_t>(i);
                relax(g.indices[k], g.weights[k], g.edge_ids[k]);
            }
        } else {
            for (const Edge& edge : g.forward[u]) relax(edge.to, edge.weight, edge.id);
        }
    }
    return out;
}

double valid_top(Queue& queue,
                 const std::unordered_map<int64_t, double>& distance,
                 const std::unordered_map<int64_t, double>& settled) {
    while (!queue.empty()) {
        const QueueItem& item = queue.top();
        const auto d = distance.find(item.node);
        if (settled.find(item.node) != settled.end() || d == distance.end() ||
            item.distance != d->second) {
            queue.pop();
        } else {
            return item.distance;
        }
    }
    return kInfinity;
}

struct Join {
    int64_t left;
    int64_t right;
    bool has_bridge;
    int64_t bridge_id;
    double bridge_weight;
};

template <typename HFn>
Result run_bidirectional(const Graph& g, int64_t start, int64_t goal, HFn&& raw_h) {
    Result out;
    if (start == goal) {
        out.nodes = {start};
        out.distance = 0.0;
        out.expanded = 1;
        return out;
    }
    const auto began = std::chrono::steady_clock::now();
    std::unordered_map<int64_t, double> h_cache;
    auto potential = [&](int64_t node) {
        const auto it = h_cache.find(node);
        if (it != h_cache.end()) return it->second;
        const double value = kPotentialSafety * raw_h(node);
        h_cache.emplace(node, value);
        ++out.heuristic_evaluations;
        return value;
    };
    auto reduced = [&](double weight, int64_t u, int64_t v) {
        const double value = weight + potential(u) - potential(v);
        if (value < -1e-9)
            throw std::logic_error("inconsistent heuristic produced a negative reduced edge");
        return std::max(0.0, value);
    };

    std::unordered_map<int64_t, double> df{{start, 0.0}}, db{{goal, 0.0}}, sf, sb;
    std::unordered_map<int64_t, int64_t> pf{{start, -1}}, ef, nb{{goal, -1}}, eb;
    Queue qf, qb;
    uint64_t of = 0, ob = 0;
    qf.push({0.0, 0.0, of++, start});
    qb.push({0.0, 0.0, ob++, goal});
    out.pushed = 2;
    double best = kInfinity;
    std::optional<Join> join;
    auto consider = [&](int64_t left, int64_t right, bool has_bridge,
                        int64_t bridge_id, double bridge_weight, double value) {
        if (value < best) {
            best = value;
            join = Join{left, right, has_bridge, bridge_id, bridge_weight};
        }
    };

    while (true) {
        const double mf = valid_top(qf, df, sf);
        const double mb = valid_top(qb, db, sb);
        if (best < kInfinity && mf + mb >= best) break;
        if (!std::isfinite(mf) || !std::isfinite(mb)) break;
        if (mf <= mb) {
            const QueueItem item = qf.top();
            qf.pop();
            sf.emplace(item.node, item.distance);
            const auto other = db.find(item.node);
            if (other != db.end())
                consider(item.node, item.node, false, -1, 0.0, item.distance + other->second);
            for (const Edge& edge : g.forward[static_cast<size_t>(item.node)]) {
                ++out.scanned;
                const double weight = reduced(edge.weight, item.node, edge.to);
                const double candidate = item.distance + weight;
                const auto old = df.find(edge.to);
                if (old == df.end() || candidate < old->second) {
                    df[edge.to] = candidate;
                    pf[edge.to] = item.node;
                    ef[edge.to] = edge.id;
                    qf.push({candidate, candidate, of++, edge.to});
                    ++out.pushed;
                }
                const auto back = db.find(edge.to);
                if (back != db.end())
                    consider(item.node, edge.to, true, edge.id, edge.weight,
                             item.distance + weight + back->second);
            }
        } else {
            const QueueItem item = qb.top();
            qb.pop();
            sb.emplace(item.node, item.distance);
            const auto other = df.find(item.node);
            if (other != df.end())
                consider(item.node, item.node, false, -1, 0.0, other->second + item.distance);
            for (const Edge& edge : g.reverse[static_cast<size_t>(item.node)]) {
                ++out.scanned;
                const double weight = reduced(edge.weight, edge.to, item.node);
                const double candidate = item.distance + weight;
                const auto old = db.find(edge.to);
                if (old == db.end() || candidate < old->second) {
                    db[edge.to] = candidate;
                    nb[edge.to] = item.node;
                    eb[edge.to] = edge.id;
                    qb.push({candidate, candidate, ob++, edge.to});
                    ++out.pushed;
                }
                const auto forward = df.find(edge.to);
                if (forward != df.end())
                    consider(edge.to, item.node, true, edge.id, edge.weight,
                             forward->second + weight + item.distance);
            }
        }
    }

    out.expanded = static_cast<uint64_t>(sf.size() + sb.size());
    if (!join) return out;
    auto left = restore_map(pf, ef, start, join->left, g.n);
    std::vector<int64_t> right_nodes{join->right}, right_edges;
    for (int64_t node = join->right; node != goal;) {
        const auto next = nb.find(node);
        const auto edge = eb.find(node);
        if (next == nb.end() || edge == eb.end() ||
            static_cast<int64_t>(right_nodes.size()) > g.n)
            throw std::logic_error("broken backward predecessor chain");
        right_edges.push_back(edge->second);
        node = next->second;
        right_nodes.push_back(node);
    }
    if (join->has_bridge) {
        left.first.push_back(join->right);
        left.second.push_back(join->bridge_id);
    }
    left.first.insert(left.first.end(), right_nodes.begin() + 1, right_nodes.end());
    left.second.insert(left.second.end(), right_edges.begin(), right_edges.end());
    out.nodes = std::move(left.first);
    out.edges = std::move(left.second);

    long double path_weight = 0.0L;
    for (size_t j = 0; j < out.edges.size(); ++j) {
        const int64_t u = out.nodes[j], v = out.nodes[j + 1], edge_id = out.edges[j];
        bool found = false;
        for (const Edge& edge : g.forward[static_cast<size_t>(u)]) {
            if (edge.to == v && edge.id == edge_id) {
                path_weight += static_cast<long double>(edge.weight);
                found = true;
                break;
            }
        }
        if (!found) throw std::logic_error("reconstructed edge is absent from original graph");
    }
    out.distance = static_cast<double>(path_weight);
    return out;
}

bool valid_version(int32_t value) { return value >= L0 && value <= B1; }
bool valid_heuristic(int32_t value) { return value >= H0 && value <= HMAX_PLANE; }

}  // namespace

// All buffers passed to create are copied. Node IDs must be dense [0,n_nodes).
ASTAR_API void* astar_graph_create(
    int64_t n_nodes, int64_t n_edges, const int64_t* indptr,
    const int64_t* indices, const double* weights, const int64_t* edge_ids,
    const double* lon, const double* lat, int32_t* error_code) {
    if (!error_code) return nullptr;
    *error_code = OK;
    if (n_nodes <= 0 || n_edges < 0 || !indptr || !lon || !lat ||
        (n_edges > 0 && (!indices || !weights || !edge_ids))) {
        *error_code = INVALID_ARGUMENT;
        return nullptr;
    }
    try {
        if (indptr[0] != 0 || indptr[n_nodes] != n_edges) {
            *error_code = INVALID_GRAPH;
            return nullptr;
        }
        auto graph = std::make_unique<Graph>();
        graph->n = n_nodes;
        graph->m = n_edges;
        graph->indptr.assign(indptr, indptr + n_nodes + 1);
        graph->lon.assign(lon, lon + n_nodes);
        graph->lat.assign(lat, lat + n_nodes);
        graph->indices.reserve(static_cast<size_t>(n_edges));
        graph->weights.reserve(static_cast<size_t>(n_edges));
        graph->edge_ids.reserve(static_cast<size_t>(n_edges));
        graph->forward.resize(static_cast<size_t>(n_nodes));
        for (int64_t u = 0; u < n_nodes; ++u) {
            const int64_t lo = graph->indptr[static_cast<size_t>(u)];
            const int64_t hi = graph->indptr[static_cast<size_t>(u + 1)];
            if (lo < 0 || hi < lo || hi > n_edges ||
                !std::isfinite(graph->lon[static_cast<size_t>(u)]) ||
                !std::isfinite(graph->lat[static_cast<size_t>(u)]) ||
                graph->lon[static_cast<size_t>(u)] < -180.0 ||
                graph->lon[static_cast<size_t>(u)] > 180.0 ||
                graph->lat[static_cast<size_t>(u)] < -90.0 ||
                graph->lat[static_cast<size_t>(u)] > 90.0) {
                *error_code = INVALID_GRAPH;
                return nullptr;
            }
            for (int64_t i = lo; i < hi; ++i) {
                const size_t k = static_cast<size_t>(i);
                const int64_t v = indices[k];
                if (v < 0 || v >= n_nodes || !std::isfinite(weights[k]) || weights[k] < 0.0) {
                    *error_code = INVALID_GRAPH;
                    return nullptr;
                }
                graph->indices.push_back(v);
                graph->weights.push_back(weights[k]);
                graph->edge_ids.push_back(edge_ids[k]);
                graph->forward[static_cast<size_t>(u)].push_back({v, weights[k], edge_ids[k]});
            }
        }
        return graph.release();
    } catch (...) {
        *error_code = INTERNAL_ERROR;
        return nullptr;
    }
}

ASTAR_API void astar_graph_destroy(void* handle) {
    delete static_cast<Graph*>(handle);
}

ASTAR_API int32_t astar_prepare_geometry(void* handle, double* haversine_scale,
                                          double* plane_scale, uint64_t* elapsed_ns) {
    if (elapsed_ns) *elapsed_ns = 0;
    if (!handle || !haversine_scale || !plane_scale || !elapsed_ns) return INVALID_ARGUMENT;
    try {
        Graph& g = *static_cast<Graph*>(handle);
        const auto begin = std::chrono::steady_clock::now();
        constexpr double pi = 3.141592653589793238462643383279502884;
        double mean_lon = 0.0, mean_lat = 0.0;
        for (int64_t i = 0; i < g.n; ++i) {
            mean_lon += g.lon[static_cast<size_t>(i)];
            mean_lat += g.lat[static_cast<size_t>(i)];
        }
        mean_lon /= static_cast<double>(g.n);
        mean_lat /= static_cast<double>(g.n);
        const double cos_lat = std::cos(mean_lat * pi / 180.0);
        g.x.resize(static_cast<size_t>(g.n));
        g.y.resize(static_cast<size_t>(g.n));
        for (int64_t i = 0; i < g.n; ++i) {
            const size_t u = static_cast<size_t>(i);
            g.x[u] = kEarthRadiusM * (g.lon[u] - mean_lon) * pi / 180.0 * cos_lat;
            g.y[u] = kEarthRadiusM * (g.lat[u] - mean_lat) * pi / 180.0;
        }
        g.haversine_scale = estimate_haversine_scale(g);
        double scale = kInfinity;
        for (int64_t u = 0; u < g.n; ++u) {
            const size_t lo = static_cast<size_t>(g.indptr[static_cast<size_t>(u)]);
            const size_t hi = static_cast<size_t>(g.indptr[static_cast<size_t>(u + 1)]);
            for (size_t i = lo; i < hi; ++i) {
                const size_t v = static_cast<size_t>(g.indices[i]);
                const double length = std::hypot(g.x[u] - g.x[v], g.y[u] - g.y[v]);
                if (length > 0.0) scale = std::min(scale, g.weights[i] / length);
            }
        }
        g.plane_scale = std::isfinite(scale) ? std::max(0.0, scale * (1.0 - 1e-12)) : 0.0;
        g.geometry_ready = true;
        *haversine_scale = g.haversine_scale;
        *plane_scale = g.plane_scale;
        const auto end = std::chrono::steady_clock::now();
        *elapsed_ns = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count());
        return OK;
    } catch (...) {
        return INTERNAL_ERROR;
    }
}

ASTAR_API int32_t astar_prepare_reverse(void* handle, uint64_t* elapsed_ns) {
    if (elapsed_ns) *elapsed_ns = 0;
    if (!handle || !elapsed_ns) return INVALID_ARGUMENT;
    try {
        Graph& g = *static_cast<Graph*>(handle);
        const auto begin = std::chrono::steady_clock::now();
        g.reverse.assign(static_cast<size_t>(g.n), {});
        for (int64_t u = 0; u < g.n; ++u) {
            for (const Edge& edge : g.forward[static_cast<size_t>(u)])
                g.reverse[static_cast<size_t>(edge.to)].push_back({u, edge.weight, edge.id});
        }
        g.reverse_ready = true;
        const auto end = std::chrono::steady_clock::now();
        *elapsed_ns = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count());
        return OK;
    } catch (...) {
        return INTERNAL_ERROR;
    }
}

ASTAR_API int32_t astar_prepare_alt(void* handle, int32_t landmark_count,
                                    const int64_t* landmark_ids, uint64_t* elapsed_ns) {
    if (elapsed_ns) *elapsed_ns = 0;
    if (!handle || !elapsed_ns || landmark_count <= 0 || !landmark_ids)
        return INVALID_ARGUMENT;
    try {
        Graph& g = *static_cast<Graph*>(handle);
        if (!g.reverse_ready) return PREPARATION_REQUIRED;
        std::set<int64_t> unique;
        for (int32_t i = 0; i < landmark_count; ++i) {
            if (landmark_ids[i] < 0 || landmark_ids[i] >= g.n ||
                !unique.insert(landmark_ids[i]).second)
                return INVALID_GRAPH;
        }
        const auto begin = std::chrono::steady_clock::now();
        const size_t n = static_cast<size_t>(g.n);
        std::vector<double> from(static_cast<size_t>(landmark_count) * n);
        std::vector<double> to(static_cast<size_t>(landmark_count) * n);
        for (int32_t i = 0; i < landmark_count; ++i) {
            auto forward = dijkstra_distances(g.forward, landmark_ids[i]);
            auto backward = dijkstra_distances(g.reverse, landmark_ids[i]);
            std::copy(forward.begin(), forward.end(), from.begin() + static_cast<size_t>(i) * n);
            std::copy(backward.begin(), backward.end(), to.begin() + static_cast<size_t>(i) * n);
        }
        g.landmarks.assign(landmark_ids, landmark_ids + landmark_count);
        g.from_landmark = std::move(from);
        g.to_landmark = std::move(to);
        g.alt_ready = true;
        const auto end = std::chrono::steady_clock::now();
        *elapsed_ns = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count());
        return OK;
    } catch (...) {
        return INTERNAL_ERROR;
    }
}

// Version IDs: L0=0, L0-CachedScale=1, L1..L5=2..6, B1=7.
// Heuristic IDs: H0=0, PLANE=1, ALT=2, MAX(H0,ALT)=3, MAX(PLANE,ALT)=4.
// elapsed_ns includes query state setup and path restoration; it excludes ABI buffer copies.
ASTAR_API int32_t astar_run(
    void* handle, int32_t version, int32_t heuristic, int32_t landmark_count,
    int64_t start, int64_t goal, int64_t* node_buffer, int64_t node_capacity,
    int64_t* edge_buffer, int64_t edge_capacity, int64_t* node_count,
    int64_t* edge_count, double* total_distance, uint64_t* expanded_count,
    uint64_t* pushed_count, uint64_t* scanned_edges,
    uint64_t* heuristic_evaluations, uint64_t* elapsed_ns) {
    if (node_count) *node_count = 0;
    if (edge_count) *edge_count = 0;
    if (total_distance) *total_distance = kInfinity;
    if (expanded_count) *expanded_count = 0;
    if (pushed_count) *pushed_count = 0;
    if (scanned_edges) *scanned_edges = 0;
    if (heuristic_evaluations) *heuristic_evaluations = 0;
    if (elapsed_ns) *elapsed_ns = 0;
    if (!handle || !node_count || !edge_count || !total_distance || !expanded_count ||
        !pushed_count || !scanned_edges || !heuristic_evaluations || !elapsed_ns ||
        node_capacity < 0 || edge_capacity < 0 ||
        (node_capacity > 0 && !node_buffer) || (edge_capacity > 0 && !edge_buffer))
        return INVALID_ARGUMENT;
    Graph& g = *static_cast<Graph*>(handle);
    if (!valid_version(version) || !valid_heuristic(heuristic) ||
        start < 0 || start >= g.n || goal < 0 || goal >= g.n || landmark_count < 0)
        return INVALID_QUERY;
    if ((version == L0 || version == L0_CACHED_SCALE) && heuristic != H0)
        return INVALID_QUERY;
    if ((version != L0) && (heuristic == H0 || heuristic == HMAX) &&
        !g.geometry_ready)
        return PREPARATION_REQUIRED;
    if ((heuristic == HPLANE || heuristic == HMAX_PLANE) && !g.geometry_ready)
        return PREPARATION_REQUIRED;
    if ((heuristic == HALT || heuristic == HMAX || heuristic == HMAX_PLANE) &&
        (!g.alt_ready || landmark_count <= 0 ||
         static_cast<size_t>(landmark_count) > g.landmarks.size()))
        return PREPARATION_REQUIRED;
    if (version == B1 && !g.reverse_ready) return PREPARATION_REQUIRED;

    try {
        const auto begin = std::chrono::steady_clock::now();
        double scale = g.haversine_scale;
        if (version == L0) scale = estimate_haversine_scale(g);
        auto h = [&](int64_t node) {
            return heuristic_value(g, node, goal, heuristic, landmark_count, scale);
        };
        Result result;
        switch (version) {
            case L0: result = run_map<true>(g, start, goal, h); break;
            case L0_CACHED_SCALE: result = run_map<true>(g, start, goal, h); break;
            case L1: result = run_map<false>(g, start, goal, h); break;
            case L2: result = run_dense<false, false, false>(g, start, goal, h); break;
            case L3: result = run_dense<true, false, false>(g, start, goal, h); break;
            case L4: result = run_dense<true, true, false>(g, start, goal, h); break;
            case L5: result = run_dense<true, true, true>(g, start, goal, h); break;
            case B1: result = run_bidirectional(g, start, goal, h); break;
        }
        const auto end = std::chrono::steady_clock::now();
        *elapsed_ns = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count());
        *node_count = static_cast<int64_t>(result.nodes.size());
        *edge_count = static_cast<int64_t>(result.edges.size());
        *total_distance = result.distance;
        *expanded_count = result.expanded;
        *pushed_count = result.pushed;
        *scanned_edges = result.scanned;
        *heuristic_evaluations = result.heuristic_evaluations;
        if (result.nodes.size() > static_cast<size_t>(node_capacity) ||
            result.edges.size() > static_cast<size_t>(edge_capacity))
            return BUFFER_TOO_SMALL;
        if (!result.nodes.empty())
            std::copy(result.nodes.begin(), result.nodes.end(), node_buffer);
        if (!result.edges.empty())
            std::copy(result.edges.begin(), result.edges.end(), edge_buffer);
        return OK;
    } catch (...) {
        return INTERNAL_ERROR;
    }
}

#ifdef ASTAR_SELF_TEST
int main() {
    constexpr int64_t n = 6, m = 8;
    const int64_t indptr[] = {0, 3, 5, 6, 7, 8, 8};
    const int64_t indices[] = {1, 1, 2, 2, 3, 3, 4, 4};
    const double weights[] = {1.0, 1.2, 5.0, 1.0, 4.0, 1.0, 0.5, 0.0};
    const int64_t edge_ids[] = {100, 101, 102, 103, 104, 105, 106, 107};
    const double lon[] = {114.0, 114.01, 114.02, 114.03, 114.04, 115.0};
    const double lat[] = {30.0, 30.0, 30.0, 30.0, 30.0, 31.0};
    int32_t error = OK;
    void* handle = astar_graph_create(n, m, indptr, indices, weights, edge_ids,
                                      lon, lat, &error);
    assert(handle && error == OK);
    double hscale = 0.0, pscale = 0.0;
    uint64_t prep_ns = 0;
    assert(astar_prepare_geometry(handle, &hscale, &pscale, &prep_ns) == OK);
    assert(astar_prepare_reverse(handle, &prep_ns) == OK);
    const int64_t landmarks[] = {0, 4};
    assert(astar_prepare_alt(handle, 2, landmarks, &prep_ns) == OK);

    for (int32_t version = L0; version <= L5; ++version) {
        const int32_t first_h = H0;
        const int32_t last_h = version == L0 || version == L0_CACHED_SCALE ? H0 : HMAX_PLANE;
        for (int32_t heuristic = first_h; heuristic <= last_h; ++heuristic) {
            int64_t nodes[n]{}, edges[n]{}, node_count = 0, edge_count = 0;
            double distance = 0.0;
            uint64_t expanded = 0, pushed = 0, scanned = 0, h_calls = 0, elapsed = 0;
            const int32_t k = (heuristic == HALT || heuristic == HMAX || heuristic == HMAX_PLANE) ? 2 : 0;
            const int32_t status = astar_run(handle, version, heuristic, k, 0, 4,
                nodes, n, edges, n, &node_count, &edge_count, &distance, &expanded,
                &pushed, &scanned, &h_calls, &elapsed);
            assert(status == OK && std::abs(distance - 3.5) < 1e-12);
            assert(node_count == edge_count + 1 && expanded > 0 && pushed > 0);
            double path_weight = 0.0;
            for (int64_t j = 0; j < edge_count; ++j) {
                bool found = false;
                for (int64_t i = indptr[nodes[j]]; i < indptr[nodes[j] + 1]; ++i) {
                    if (indices[i] == nodes[j + 1] && edge_ids[i] == edges[j]) {
                        path_weight += weights[i];
                        found = true;
                        break;
                    }
                }
                assert(found);
            }
            assert(std::abs(path_weight - distance) < 1e-12);
        }
    }
    for (int32_t heuristic = H0; heuristic <= HMAX_PLANE; ++heuristic) {
        int64_t nodes[n]{}, edges[n]{}, node_count = 0, edge_count = 0;
        double distance = 0.0;
        uint64_t expanded = 0, pushed = 0, scanned = 0, h_calls = 0, elapsed = 0;
        const int32_t k = heuristic >= HALT ? 2 : 0;
        assert(astar_run(handle, B1, heuristic, k, 0, 4, nodes, n, edges, n,
            &node_count, &edge_count, &distance, &expanded, &pushed, &scanned,
            &h_calls, &elapsed) == OK);
        assert(std::abs(distance - 3.5) < 1e-12 && node_count == edge_count + 1);
    }
    int64_t nodes[n]{}, edges[n]{}, node_count = 0, edge_count = 0;
    double distance = 0.0;
    uint64_t expanded = 0, pushed = 0, scanned = 0, h_calls = 0, elapsed = 0;
    assert(astar_run(handle, L5, HALT, 2, 0, 5, nodes, n, edges, n, &node_count,
        &edge_count, &distance, &expanded, &pushed, &scanned, &h_calls, &elapsed) == OK);
    assert(node_count == 0 && edge_count == 0 && std::isinf(distance));
    assert(astar_run(handle, L3, H0, 0, 3, 3, nodes, n, edges, n, &node_count,
        &edge_count, &distance, &expanded, &pushed, &scanned, &h_calls, &elapsed) == OK);
    assert(node_count == 1 && nodes[0] == 3 && edge_count == 0 && distance == 0.0);
    astar_graph_destroy(handle);
    return 0;
}
#endif
