#include <algorithm>
#ifdef DIJKSTRA_SELF_TEST
#include <cassert>
#endif
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <queue>
#include <stdexcept>
#include <unordered_map>
#include <utility>
#include <vector>

#ifdef _WIN32
#define DIJKSTRA_API extern "C" __declspec(dllexport)
#else
#define DIJKSTRA_API extern "C"
#endif

namespace {

enum Status : int32_t {
    OK = 0,
    INVALID_ARGUMENT = 1,
    INVALID_GRAPH = 2,
    INVALID_QUERY = 3,
    BUFFER_TOO_SMALL = 4,
    INTERNAL_ERROR = 5
};

enum Algorithm : int32_t { L0 = 0, L1 = 1, L2 = 2, L3 = 3, L4 = 4, B1 = 5 };

struct Edge {
    int64_t to;
    double weight;
    int64_t id;
};

struct Graph {
    int64_t n = 0;
    std::vector<int64_t> indptr, indices, edge_ids;
    std::vector<double> weights;
    std::vector<std::vector<Edge>> forward, reverse;
};

struct QueueItem {
    double distance;
    uint64_t order;
    int64_t node;
};

struct Later {
    bool operator()(const QueueItem& a, const QueueItem& b) const {
        return a.distance != b.distance ? a.distance > b.distance : a.order > b.order;
    }
};

struct Result {
    std::vector<int64_t> nodes, edges;
    double distance = std::numeric_limits<double>::infinity();
    uint64_t settled = 0;
};

using Queue = std::priority_queue<QueueItem, std::vector<QueueItem>, Later>;

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
            throw std::logic_error("broken predecessor chain");
        edges.push_back(parent_edge[static_cast<size_t>(node)]);
        node = parent[static_cast<size_t>(node)];
        nodes.push_back(node);
    }
    std::reverse(nodes.begin(), nodes.end());
    std::reverse(edges.begin(), edges.end());
    return {std::move(nodes), std::move(edges)};
}

template <bool CheckEachEdge>
Result run_map(const Graph& g, int64_t start, int64_t goal) {
    Result out;
    if (start == goal) {
        out.nodes = {start};
        out.distance = 0.0;
        out.settled = 1;
        return out;
    }
    std::unordered_map<int64_t, double> seen{{start, 0.0}}, settled;
    std::unordered_map<int64_t, int64_t> parent{{start, -1}}, parent_edge;
    Queue queue;
    uint64_t order = 0;
    queue.push({0.0, order++, start});

    while (!queue.empty()) {
        const QueueItem item = queue.top();
        queue.pop();
        if (settled.find(item.node) != settled.end()) continue;
        settled.emplace(item.node, item.distance);
        if (item.node == goal) {
            auto path = restore_map(parent, parent_edge, start, goal, g.n);
            out.nodes = std::move(path.first);
            out.edges = std::move(path.second);
            out.distance = item.distance;
            out.settled = settled.size();
            return out;
        }
        for (const Edge& edge : g.forward[static_cast<size_t>(item.node)]) {
            if constexpr (CheckEachEdge) {
                if (edge.to < 0 || edge.to >= g.n || edge.weight < 0.0)
                    throw std::logic_error("invalid edge encountered");
            }
            const double candidate = item.distance + edge.weight;
            const auto old = seen.find(edge.to);
            if (old == seen.end() || candidate < old->second) {
                seen[edge.to] = candidate;
                parent[edge.to] = item.node;
                parent_edge[edge.to] = edge.id;
                queue.push({candidate, order++, edge.to});
            }
        }
    }
    out.settled = settled.size();
    return out;
}

template <bool DenseParent, bool UseCsr>
Result run_dense(const Graph& g, int64_t start, int64_t goal) {
    Result out;
    if (start == goal) {
        out.nodes = {start};
        out.distance = 0.0;
        out.settled = 1;
        return out;
    }
    const size_t n = static_cast<size_t>(g.n);
    std::vector<double> distance(n, std::numeric_limits<double>::infinity());
    std::vector<uint8_t> settled(n, 0);
    std::vector<int64_t> parent, parent_edge;
    std::unordered_map<int64_t, int64_t> map_parent, map_parent_edge;
    if constexpr (DenseParent) {
        parent.assign(n, -1);
        parent_edge.assign(n, -1);
    } else {
        map_parent.emplace(start, -1);
    }
    Queue queue;
    uint64_t order = 0;
    uint64_t settled_count = 0;
    distance[static_cast<size_t>(start)] = 0.0;
    queue.push({0.0, order++, start});

    while (!queue.empty()) {
        const QueueItem item = queue.top();
        queue.pop();
        const size_t u = static_cast<size_t>(item.node);
        if (settled[u] || item.distance != distance[u]) continue;
        settled[u] = 1;
        ++settled_count;
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
            out.settled = settled_count;
            return out;
        }
        auto relax = [&](int64_t v, double weight, int64_t edge_id) {
            const double candidate = item.distance + weight;
            const size_t vi = static_cast<size_t>(v);
            if (candidate < distance[vi]) {
                distance[vi] = candidate;
                if constexpr (DenseParent) {
                    parent[vi] = item.node;
                    parent_edge[vi] = edge_id;
                } else {
                    map_parent[v] = item.node;
                    map_parent_edge[v] = edge_id;
                }
                queue.push({candidate, order++, v});
            }
        };
        if constexpr (UseCsr) {
            for (int64_t i = g.indptr[u]; i < g.indptr[u + 1]; ++i) {
                const size_t k = static_cast<size_t>(i);
                relax(g.indices[k], g.weights[k], g.edge_ids[k]);
            }
        } else {
            for (const Edge& edge : g.forward[u])
                relax(edge.to, edge.weight, edge.id);
        }
    }
    out.settled = settled_count;
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
    return std::numeric_limits<double>::infinity();
}

Result run_bidirectional(const Graph& g, int64_t start, int64_t goal) {
    Result out;
    if (start == goal) {
        out.nodes = {start};
        out.distance = 0.0;
        out.settled = 1;
        return out;
    }
    const double infinity = std::numeric_limits<double>::infinity();
    std::unordered_map<int64_t, double> df{{start, 0.0}}, db{{goal, 0.0}}, sf, sb;
    std::unordered_map<int64_t, int64_t> pf{{start, -1}}, ef, nb{{goal, -1}}, eb;
    Queue qf, qb;
    uint64_t of = 0, ob = 0;
    qf.push({0.0, of++, start});
    qb.push({0.0, ob++, goal});
    double best = infinity;
    int64_t meeting = -1;

    while (true) {
        const double mf = valid_top(qf, df, sf);
        const double mb = valid_top(qb, db, sb);
        if (best < infinity && mf + mb >= best) break;
        if (!std::isfinite(mf) || !std::isfinite(mb)) break;

        if (mf <= mb) {
            const QueueItem item = qf.top();
            qf.pop();
            sf.emplace(item.node, item.distance);
            const auto other = db.find(item.node);
            if (other != db.end() && item.distance + other->second < best) {
                best = item.distance + other->second;
                meeting = item.node;
            }
            for (const Edge& edge : g.forward[static_cast<size_t>(item.node)]) {
                const double candidate = item.distance + edge.weight;
                const auto old = df.find(edge.to);
                if (old == df.end() || candidate < old->second) {
                    df[edge.to] = candidate;
                    pf[edge.to] = item.node;
                    ef[edge.to] = edge.id;
                    qf.push({candidate, of++, edge.to});
                    const auto back = db.find(edge.to);
                    if (back != db.end() && candidate + back->second < best) {
                        best = candidate + back->second;
                        meeting = edge.to;
                    }
                }
            }
        } else {
            const QueueItem item = qb.top();
            qb.pop();
            sb.emplace(item.node, item.distance);
            const auto other = df.find(item.node);
            if (other != df.end() && other->second + item.distance < best) {
                best = other->second + item.distance;
                meeting = item.node;
            }
            for (const Edge& edge : g.reverse[static_cast<size_t>(item.node)]) {
                const double candidate = item.distance + edge.weight;
                const auto old = db.find(edge.to);
                if (old == db.end() || candidate < old->second) {
                    db[edge.to] = candidate;
                    nb[edge.to] = item.node;
                    eb[edge.to] = edge.id;
                    qb.push({candidate, ob++, edge.to});
                    const auto forward = df.find(edge.to);
                    if (forward != df.end() && forward->second + candidate < best) {
                        best = forward->second + candidate;
                        meeting = edge.to;
                    }
                }
            }
        }
    }
    out.settled = static_cast<uint64_t>(sf.size() + sb.size());
    if (meeting < 0) return out;

    auto left = restore_map(pf, ef, start, meeting, g.n);
    std::vector<int64_t> right_nodes{meeting}, right_edges;
    for (int64_t node = meeting; node != goal;) {
        const auto next = nb.find(node);
        const auto edge = eb.find(node);
        if (next == nb.end() || edge == eb.end() ||
            static_cast<int64_t>(right_nodes.size()) > g.n)
            throw std::logic_error("broken reverse predecessor chain");
        right_edges.push_back(edge->second);
        node = next->second;
        right_nodes.push_back(node);
    }
    left.first.insert(left.first.end(), right_nodes.begin() + 1, right_nodes.end());
    left.second.insert(left.second.end(), right_edges.begin(), right_edges.end());
    out.nodes = std::move(left.first);
    out.edges = std::move(left.second);
    out.distance = best;
    return out;
}

}  // namespace

// CSR buffers must be contiguous int64/double arrays and remain valid only for this call;
// the graph copies them, preserving parallel edges and original edge IDs.
DIJKSTRA_API void* dijkstra_graph_create(
    int64_t n_nodes, int64_t n_edges, const int64_t* indptr,
    const int64_t* indices, const double* weights, const int64_t* edge_ids,
    int32_t* error_code) {
    if (error_code) *error_code = OK;
    if (!error_code || n_nodes < 0 || n_edges < 0 || !indptr ||
        (n_edges > 0 && (!indices || !weights || !edge_ids))) {
        if (error_code) *error_code = INVALID_ARGUMENT;
        return nullptr;
    }
    try {
        if (indptr[0] != 0 || indptr[n_nodes] != n_edges) {
            *error_code = INVALID_GRAPH;
            return nullptr;
        }
        auto graph = std::make_unique<Graph>();
        graph->n = n_nodes;
        graph->indptr.assign(indptr, indptr + n_nodes + 1);
        if (n_edges > 0) {
            graph->indices.assign(indices, indices + n_edges);
            graph->weights.assign(weights, weights + n_edges);
            graph->edge_ids.assign(edge_ids, edge_ids + n_edges);
        }
        graph->forward.resize(static_cast<size_t>(n_nodes));
        graph->reverse.resize(static_cast<size_t>(n_nodes));
        for (int64_t u = 0; u < n_nodes; ++u) {
            if (graph->indptr[static_cast<size_t>(u)] >
                graph->indptr[static_cast<size_t>(u + 1)]) {
                *error_code = INVALID_GRAPH;
                return nullptr;
            }
            for (int64_t i = graph->indptr[static_cast<size_t>(u)];
                 i < graph->indptr[static_cast<size_t>(u + 1)]; ++i) {
                const size_t k = static_cast<size_t>(i);
                const int64_t v = graph->indices[k];
                if (v < 0 || v >= n_nodes || !std::isfinite(graph->weights[k]) ||
                    graph->weights[k] < 0.0) {
                    *error_code = INVALID_GRAPH;
                    return nullptr;
                }
                graph->forward[static_cast<size_t>(u)].push_back(
                    {v, graph->weights[k], graph->edge_ids[k]});
                graph->reverse[static_cast<size_t>(v)].push_back(
                    {u, graph->weights[k], graph->edge_ids[k]});
            }
        }
        return graph.release();
    } catch (...) {
        *error_code = INTERNAL_ERROR;
        return nullptr;
    }
}

DIJKSTRA_API void dijkstra_graph_destroy(void* handle) {
    delete static_cast<Graph*>(handle);
}

// Algorithm IDs: L0=0, L1=1, L2=2, L3=3, L4=4, bidirectional B1=5.
// elapsed_ns measures the C++ query kernel, including per-query state allocation
// and path reconstruction, but excluding ABI validation and copying into output buffers.
DIJKSTRA_API int32_t dijkstra_run(
    void* handle, int32_t algorithm, int64_t start, int64_t goal,
    int64_t* node_buffer, int64_t node_capacity,
    int64_t* edge_buffer, int64_t edge_capacity,
    int64_t* node_count, int64_t* edge_count, double* total_distance,
    uint64_t* settled_count, uint64_t* elapsed_ns) {
    if (node_count) *node_count = 0;
    if (edge_count) *edge_count = 0;
    if (total_distance) *total_distance = std::numeric_limits<double>::infinity();
    if (settled_count) *settled_count = 0;
    if (elapsed_ns) *elapsed_ns = 0;
    if (!handle || !node_count || !edge_count || !total_distance ||
        !settled_count || !elapsed_ns || node_capacity < 0 || edge_capacity < 0 ||
        (node_capacity > 0 && !node_buffer) || (edge_capacity > 0 && !edge_buffer))
        return INVALID_ARGUMENT;

    const Graph& graph = *static_cast<const Graph*>(handle);
    if (start < 0 || start >= graph.n || goal < 0 || goal >= graph.n ||
        algorithm < L0 || algorithm > B1)
        return INVALID_QUERY;

    try {
        const auto begin = std::chrono::steady_clock::now();
        Result result;
        switch (algorithm) {
            case L0: result = run_map<true>(graph, start, goal); break;
            case L1: result = run_map<false>(graph, start, goal); break;
            case L2: result = run_dense<false, false>(graph, start, goal); break;
            case L3: result = run_dense<true, false>(graph, start, goal); break;
            case L4: result = run_dense<true, true>(graph, start, goal); break;
            case B1: result = run_bidirectional(graph, start, goal); break;
        }
        const auto end = std::chrono::steady_clock::now();
        *elapsed_ns = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count());
        *node_count = static_cast<int64_t>(result.nodes.size());
        *edge_count = static_cast<int64_t>(result.edges.size());
        *total_distance = result.distance;
        *settled_count = result.settled;
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

#ifdef DIJKSTRA_SELF_TEST
int main() {
    constexpr int64_t n = 7;
    const int64_t indptr[] = {0, 3, 4, 7, 8, 9, 9, 9};
    const int64_t indices[] = {1, 2, 2, 3, 1, 3, 4, 4, 5};
    const double weights[] = {8, 1, 3, 2, 1, 9, 10, 0, 1};
    const int64_t edge_ids[] = {80, 10, 11, 13, 21, 23, 24, 34, 45};
    int32_t error = OK;
    void* graph = dijkstra_graph_create(n, 9, indptr, indices, weights,
                                        edge_ids, &error);
    assert(graph && error == OK);
    for (int32_t algorithm = L0; algorithm <= B1; ++algorithm) {
        int64_t nodes[n]{}, edges[n]{}, node_count = 0, edge_count = 0;
        double distance = 0;
        uint64_t settled = 0, elapsed = 0;
        assert(dijkstra_run(graph, algorithm, 0, 5, nodes, n, edges, n,
                            &node_count, &edge_count, &distance, &settled,
                            &elapsed) == OK);
        assert(distance == 5.0 && node_count == edge_count + 1 && settled > 0);
        double route_distance = 0;
        for (int64_t j = 0; j < edge_count; ++j) {
            bool found = false;
            for (int64_t u = 0; u < n && !found; ++u) {
                for (int64_t i = indptr[u]; i < indptr[u + 1]; ++i) {
                    if (edge_ids[i] == edges[j]) {
                        assert(u == nodes[j] && indices[i] == nodes[j + 1]);
                        route_distance += weights[i];
                        found = true;
                        break;
                    }
                }
            }
            assert(found);
        }
        assert(route_distance == distance);
    }
    int64_t nodes[n]{}, edges[n]{}, node_count = 0, edge_count = 0;
    double distance = 0;
    uint64_t settled = 0, elapsed = 0;
    assert(dijkstra_run(graph, B1, 0, 6, nodes, n, edges, n, &node_count,
                        &edge_count, &distance, &settled, &elapsed) == OK);
    assert(node_count == 0 && edge_count == 0 && std::isinf(distance));
    assert(dijkstra_run(graph, L3, 4, 4, nodes, n, edges, n, &node_count,
                        &edge_count, &distance, &settled, &elapsed) == OK);
    assert(node_count == 1 && nodes[0] == 4 && edge_count == 0 && distance == 0);
    dijkstra_graph_destroy(graph);

    const int64_t empty_indptr[] = {0, 0};
    graph = dijkstra_graph_create(1, 0, empty_indptr, nullptr, nullptr, nullptr,
                                  &error);
    assert(graph && error == OK);
    dijkstra_graph_destroy(graph);
    return 0;
}
#endif
