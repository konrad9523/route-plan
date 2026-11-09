#include "algorithms.hpp"

#include <algorithm>
#include <queue>

namespace route_cpp17 {

PathResult dijkstra(
    const RoadGraph& graph,
    int start,
    int goal,
    bool validate_input) {

    if (validate_input) validate_graph(graph, false);
    const int n = static_cast<int>(graph.size());
    if (start < 0 || start >= n || goal < 0 || goal >= n) {
        throw std::invalid_argument("start or goal index is invalid");
    }
    if (start == goal) return {{start}, {}, 0.0, 1, 1};

    std::vector<double> distance(n, ROUTE_INF);
    std::vector<int> parent(n, -1);
    std::vector<std::int64_t> parent_edge(n, -1);
    std::vector<char> settled(n, false);

    std::priority_queue<
        QueueItem,
        std::vector<QueueItem>,
        std::greater<QueueItem>> queue;

    std::size_t serial = 0;
    std::size_t expanded = 0;
    std::size_t queue_pushes = 1;
    distance[start] = 0.0;
    queue.push({0.0, serial++, start});

    while (!queue.empty()) {
        const QueueItem item = queue.top();
        queue.pop();
        const int u = item.node;

        // Lazy deletion: an older, worse queue record is ignored.
        if (settled[u] || item.key != distance[u]) continue;
        settled[u] = true;
        ++expanded;
        if (u == goal) break;

        for (const auto& edge : graph.outgoing[u]) {
            const double candidate = distance[u] + edge.weight;
            if (candidate >= distance[edge.to]) continue;
            distance[edge.to] = candidate;
            parent[edge.to] = u;
            parent_edge[edge.to] = edge.edge_id;
            queue.push({candidate, serial++, edge.to});
            ++queue_pushes;
        }
    }

    if (!std::isfinite(distance[goal])) {
        return {{}, {}, ROUTE_INF, expanded, queue_pushes};
    }

    PathResult result;
    result.cost = distance[goal];
    result.expanded = expanded;
    result.queue_pushes = queue_pushes;

    for (int node = goal; node != -1; node = parent[node]) {
        result.nodes.push_back(node);
        if (node != start) result.edges.push_back(parent_edge[node]);
    }
    std::reverse(result.nodes.begin(), result.nodes.end());
    std::reverse(result.edges.begin(), result.edges.end());

    if (result.nodes.empty() || result.nodes.front() != start ||
        result.nodes.back() != goal ||
        result.edges.size() + 1 != result.nodes.size()) {
        throw std::runtime_error("Dijkstra path reconstruction failed");
    }
    return result;
}

} // namespace route_cpp17
