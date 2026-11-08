#include "algorithms.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <queue>

namespace route_cpp17 {

constexpr double ASTAR_EARTH_RADIUS_M = 6371000.0;

double astar_haversine_distance(
    const Coordinate& first,
    const Coordinate& second) {

    constexpr double PI = 3.14159265358979323846;
    const double lon1 = first.lon * PI / 180.0;
    const double lat1 = first.lat * PI / 180.0;
    const double lon2 = second.lon * PI / 180.0;
    const double lat2 = second.lat * PI / 180.0;
    const double dlon = lon2 - lon1;
    const double dlat = lat2 - lat1;

    double value =
        std::sin(dlat / 2.0) * std::sin(dlat / 2.0) +
        std::cos(lat1) * std::cos(lat2) *
        std::sin(dlon / 2.0) * std::sin(dlon / 2.0);
    value = std::max(0.0, std::min(1.0, value));

    return ASTAR_EARTH_RADIUS_M * 2.0 *
           std::atan2(std::sqrt(value), std::sqrt(1.0 - value));
}

// Finds a safe conversion factor from Haversine metres to graph cost.
// For distance weights in metres this is normally close to, but not above, 1.
double estimate_astar_haversine_scale(const RoadGraph& graph) {
    validate_graph(graph, true);
    double scale = ROUTE_INF;

    for (int u = 0; u < static_cast<int>(graph.size()); ++u) {
        for (const auto& edge : graph.outgoing[u]) {
            const double straight = astar_haversine_distance(
                graph.coordinates[u], graph.coordinates[edge.to]);
            if (straight > 0.0) {
                scale = std::min(scale, edge.weight / straight);
            }
        }
    }

    if (std::isinf(scale)) return 0.0;
    return std::max(0.0, scale * (1.0 - 1e-12));
}

struct AStarQueueItem {
    double priority = 0.0;
    double cost = 0.0;
    std::size_t serial = 0;
    int node = -1;

    bool operator>(const AStarQueueItem& other) const {
        if (priority != other.priority) return priority > other.priority;
        if (cost != other.cost) return cost > other.cost;
        return serial > other.serial;
    }
};

PathResult astar(
    const RoadGraph& graph,
    int start,
    int goal,
    double heuristic_scale,
    bool validate_input) {

    if (validate_input) {
        validate_graph(graph, true);
    } else if (graph.coordinates.size() != graph.outgoing.size()) {
        throw std::invalid_argument("coordinates size must equal graph size");
    }
    const int n = static_cast<int>(graph.size());
    if (start < 0 || start >= n || goal < 0 || goal >= n) {
        throw std::invalid_argument("start or goal index is invalid");
    }
    if (start == goal) return {{start}, {}, 0.0, 1, 1};

    // The default computes a safe scale once. Performance tests should
    // precompute it outside the query loop and pass it here, avoiding an O(E)
    // scan for every route request.
    if (heuristic_scale < 0.0) {
        heuristic_scale = estimate_astar_haversine_scale(graph);
    }
    if (!std::isfinite(heuristic_scale) || heuristic_scale < 0.0) {
        throw std::invalid_argument(
            "heuristic_scale must be finite and non-negative");
    }
    struct Workspace {
        detail::EpochArray<double> heuristic;
        detail::EpochArray<double> distance;
        detail::EpochArray<int> parent;
        detail::EpochArray<std::int64_t> parent_edge;
        detail::EpochArray<char> settled;
    };
    thread_local Workspace workspace;
    workspace.heuristic.begin(
        n, std::numeric_limits<double>::quiet_NaN());
    workspace.distance.begin(n, ROUTE_INF);
    workspace.parent.begin(n, -1);
    workspace.parent_edge.begin(n, -1);
    workspace.settled.begin(n, false);

    auto h = [&](int node) {
        double& value = workspace.heuristic.ref(node);
        if (std::isnan(value)) {
            value = heuristic_scale * astar_haversine_distance(
                graph.coordinates[node], graph.coordinates[goal]);
        }
        return value;
    };

    std::priority_queue<
        AStarQueueItem,
        std::vector<AStarQueueItem>,
        std::greater<AStarQueueItem>> queue;

    std::size_t serial = 0;
    std::size_t expanded = 0;
    std::size_t queue_pushes = 1;
    workspace.distance.set(start, 0.0);
    queue.push({h(start), 0.0, serial++, start});

    while (!queue.empty()) {
        const AStarQueueItem item = queue.top();
        queue.pop();
        const int u = item.node;

        if (workspace.settled.get(u) ||
            item.cost != workspace.distance.get(u)) continue;
        workspace.settled.set(u, true);
        ++expanded;
        if (u == goal) break;

        for (const auto& edge : graph.outgoing[u]) {
            const double candidate = workspace.distance.get(u) + edge.weight;
            if (candidate >= workspace.distance.get(edge.to)) continue;
            workspace.distance.set(edge.to, candidate);
            workspace.parent.set(edge.to, u);
            workspace.parent_edge.set(edge.to, edge.edge_id);
            queue.push({candidate + h(edge.to), candidate,
                        serial++, edge.to});
            ++queue_pushes;
        }
    }

    if (!std::isfinite(workspace.distance.get(goal))) {
        return {{}, {}, ROUTE_INF, expanded, queue_pushes};
    }

    PathResult result;
    result.cost = workspace.distance.get(goal);
    result.expanded = expanded;
    result.queue_pushes = queue_pushes;

    for (int node = goal; node != -1; node = workspace.parent.get(node)) {
        result.nodes.push_back(node);
        if (node != start) {
            result.edges.push_back(workspace.parent_edge.get(node));
        }
    }
    std::reverse(result.nodes.begin(), result.nodes.end());
    std::reverse(result.edges.begin(), result.edges.end());

    if (result.nodes.empty() || result.nodes.front() != start ||
        result.nodes.back() != goal ||
        result.edges.size() + 1 != result.nodes.size()) {
        throw std::runtime_error("A* path reconstruction failed");
    }
    return result;
}

} // namespace route_cpp17
