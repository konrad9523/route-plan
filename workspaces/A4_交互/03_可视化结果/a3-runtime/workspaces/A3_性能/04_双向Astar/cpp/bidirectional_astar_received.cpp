#include "algorithms.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <queue>

namespace route_cpp17 {

namespace {

constexpr double BIDIRECTIONAL_EARTH_RADIUS_M = 6371000.0;
constexpr double BIDIRECTIONAL_PI = 3.14159265358979323846;

BidirectionalAStarIndex::SpherePoint to_sphere_point(
    const Coordinate& coordinate) {

    const double lon = coordinate.lon * BIDIRECTIONAL_PI / 180.0;
    const double lat = coordinate.lat * BIDIRECTIONAL_PI / 180.0;
    const double cos_lat = std::cos(lat);
    return {cos_lat * std::cos(lon),
            cos_lat * std::sin(lon),
            std::sin(lat)};
}

double sphere_chord_distance(
    const BidirectionalAStarIndex::SpherePoint& first,
    const BidirectionalAStarIndex::SpherePoint& second) {

    const double dx = first.x - second.x;
    const double dy = first.y - second.y;
    const double dz = first.z - second.z;
    return BIDIRECTIONAL_EARTH_RADIUS_M *
           std::sqrt(dx * dx + dy * dy + dz * dz);
}

} // namespace

// Build reverse adjacency and the safe Haversine scale once per graph.
// Reuse the returned index for every route query in performance tests and
// server applications.
BidirectionalAStarIndex prepare_bidirectional_astar(
    const RoadGraph& graph,
    double heuristic_scale) {

    validate_graph(graph, true);
    if (heuristic_scale < 0.0) heuristic_scale = estimate_astar_haversine_scale(graph);
    if (!std::isfinite(heuristic_scale) || heuristic_scale < 0.0) {
        throw std::invalid_argument(
            "heuristic_scale must be finite and non-negative");
    }

    BidirectionalAStarIndex index;
    index.heuristic_scale = heuristic_scale;
    index.incoming.resize(graph.size());
    index.sphere_points.reserve(graph.size());
    for (const auto& coordinate : graph.coordinates) {
        index.sphere_points.push_back(to_sphere_point(coordinate));
    }
    for (int u = 0; u < static_cast<int>(graph.size()); ++u) {
        for (const auto& edge : graph.outgoing[u]) {
            index.incoming[edge.to].push_back(
                {u, edge.weight, edge.edge_id});
        }
    }
    return index;
}

PathResult bidirectional_astar(
    const RoadGraph& graph,
    const BidirectionalAStarIndex& index,
    int start,
    int goal) {

    const int n = static_cast<int>(graph.size());
    if (graph.coordinates.size() != graph.outgoing.size() ||
        index.incoming.size() != graph.outgoing.size() ||
        index.sphere_points.size() != graph.outgoing.size()) {
        throw std::invalid_argument(
            "bidirectional A* index does not match graph size");
    }
    if (start < 0 || start >= n || goal < 0 || goal >= n) {
        throw std::invalid_argument("start or goal index is invalid");
    }
    if (start == goal) return {{start}, {}, 0.0, 1, 1};
    const double heuristic_scale = index.heuristic_scale;

    struct Workspace {
        detail::EpochArray<double> potential_cache;
        detail::EpochArray<double> forward_distance;
        detail::EpochArray<double> backward_distance;
        detail::EpochArray<int> forward_parent;
        detail::EpochArray<int> backward_next;
        detail::EpochArray<std::int64_t> forward_edge;
        detail::EpochArray<std::int64_t> backward_edge;
        detail::EpochArray<char> forward_settled;
        detail::EpochArray<char> backward_settled;
    };
    thread_local Workspace workspace;
    workspace.potential_cache.begin(
        n, std::numeric_limits<double>::quiet_NaN());
    workspace.forward_distance.begin(n, ROUTE_INF);
    workspace.backward_distance.begin(n, ROUTE_INF);
    workspace.forward_parent.begin(n, -1);
    workspace.backward_next.begin(n, -1);
    workspace.forward_edge.begin(n, -1);
    workspace.backward_edge.begin(n, -1);
    workspace.forward_settled.begin(n, false);
    workspace.backward_settled.begin(n, false);

    auto potential = [&](int node) {
        double& value = workspace.potential_cache.ref(node);
        if (std::isnan(value)) {
            // The 3-D chord is always no longer than the great-circle arc and
            // is itself a metric. With the safe Haversine scale it remains an
            // admissible, consistent lower bound while avoiding trigonometry
            // in the query loop.
            const double to_goal = sphere_chord_distance(
                index.sphere_points[node], index.sphere_points[goal]);
            const double from_start = sphere_chord_distance(
                index.sphere_points[start], index.sphere_points[node]);
            value = (to_goal - from_start) * heuristic_scale / 2.0;
        }
        return value;
    };
    auto nonnegative_reduced_weight = [](double value) {
        if (value < -1e-7) {
            throw std::invalid_argument(
                "heuristic is inconsistent; use a smaller heuristic_scale");
        }
        return std::max(0.0, value);
    };

    std::priority_queue<QueueItem, std::vector<QueueItem>, std::greater<QueueItem>>
        forward_queue, backward_queue;

    std::size_t serial = 0;
    workspace.forward_distance.set(start, 0.0);
    workspace.backward_distance.set(goal, 0.0);
    forward_queue.push({0.0, serial++, start});
    backward_queue.push({0.0, serial++, goal});

    double best = ROUTE_INF;
    int meeting = -1;
    std::size_t expanded = 0;
    std::size_t queue_pushes = 2;

    auto clean_forward_queue = [&]() {
        while (!forward_queue.empty() &&
               (workspace.forward_settled.get(forward_queue.top().node) ||
                forward_queue.top().key !=
                    workspace.forward_distance.get(forward_queue.top().node))) {
            forward_queue.pop();
        }
    };
    auto clean_backward_queue = [&]() {
        while (!backward_queue.empty() &&
               (workspace.backward_settled.get(backward_queue.top().node) ||
                backward_queue.top().key !=
                    workspace.backward_distance.get(backward_queue.top().node))) {
            backward_queue.pop();
        }
    };
    auto update_meeting = [&](int node, double candidate) {
        if (candidate < best) {
            best = candidate;
            meeting = node;
        }
    };

    while (!forward_queue.empty() || !backward_queue.empty()) {
        clean_forward_queue();
        clean_backward_queue();
        if (forward_queue.empty() && backward_queue.empty()) break;

        const double min_forward =
            forward_queue.empty() ? ROUTE_INF : forward_queue.top().key;
        const double min_backward =
            backward_queue.empty() ? ROUTE_INF : backward_queue.top().key;
        if (std::isfinite(best) && !forward_queue.empty() &&
            !backward_queue.empty() && min_forward + min_backward >= best) {
            break;
        }

        if (min_forward <= min_backward) {
            const QueueItem item = forward_queue.top();
            forward_queue.pop();
            const int u = item.node;
            if (workspace.forward_settled.get(u) ||
                item.key != workspace.forward_distance.get(u)) continue;
            workspace.forward_settled.set(u, true);
            ++expanded;
            const double potential_u = potential(u);

            for (const auto& edge : graph.outgoing[u]) {
                const double reduced = nonnegative_reduced_weight(
                    edge.weight + potential(edge.to) - potential_u);
                const double candidate =
                    workspace.forward_distance.get(u) + reduced;
                if (candidate < workspace.forward_distance.get(edge.to)) {
                    workspace.forward_distance.set(edge.to, candidate);
                    workspace.forward_parent.set(edge.to, u);
                    workspace.forward_edge.set(edge.to, edge.edge_id);
                    forward_queue.push({candidate, serial++, edge.to});
                    ++queue_pushes;
                    if (workspace.backward_distance.get(edge.to) < ROUTE_INF) {
                        update_meeting(
                            edge.to, candidate +
                                workspace.backward_distance.get(edge.to));
                    }
                }
            }
        } else {
            const QueueItem item = backward_queue.top();
            backward_queue.pop();
            const int v = item.node;
            if (workspace.backward_settled.get(v) ||
                item.key != workspace.backward_distance.get(v)) continue;
            workspace.backward_settled.set(v, true);
            ++expanded;
            const double potential_v = potential(v);

            for (const auto& edge : index.incoming[v]) {
                const int u = edge.to;
                const double reduced = nonnegative_reduced_weight(
                    edge.weight + potential_v - potential(u));
                const double candidate =
                    workspace.backward_distance.get(v) + reduced;
                if (candidate < workspace.backward_distance.get(u)) {
                    workspace.backward_distance.set(u, candidate);
                    workspace.backward_next.set(u, v);
                    workspace.backward_edge.set(u, edge.edge_id);
                    backward_queue.push({candidate, serial++, u});
                    ++queue_pushes;
                    if (workspace.forward_distance.get(u) < ROUTE_INF) {
                        update_meeting(
                            u, workspace.forward_distance.get(u) + candidate);
                    }
                }
            }
        }
    }

    if (meeting < 0) return {{}, {}, ROUTE_INF, expanded, queue_pushes};

    PathResult result;
    result.cost = 0.0;
    result.expanded = expanded;
    result.queue_pushes = queue_pushes;

    std::vector<int> left_nodes{meeting};
    std::vector<std::int64_t> left_edges;
    for (int node = meeting; node != start;
         node = workspace.forward_parent.get(node)) {
        if (workspace.forward_parent.get(node) < 0) {
            throw std::runtime_error("incomplete forward predecessor data");
        }
        left_edges.push_back(workspace.forward_edge.get(node));
        left_nodes.push_back(workspace.forward_parent.get(node));
    }
    std::reverse(left_nodes.begin(), left_nodes.end());
    std::reverse(left_edges.begin(), left_edges.end());
    result.nodes = std::move(left_nodes);
    result.edges = std::move(left_edges);

    for (int node = meeting; node != goal;
         node = workspace.backward_next.get(node)) {
        if (workspace.backward_next.get(node) < 0) {
            throw std::runtime_error("incomplete backward successor data");
        }
        result.edges.push_back(workspace.backward_edge.get(node));
        result.nodes.push_back(workspace.backward_next.get(node));
    }

    for (std::size_t i = 0; i + 1 < result.nodes.size(); ++i) {
        const int u = result.nodes[i];
        const int v = result.nodes[i + 1];
        const std::int64_t edge_id = result.edges[i];
        auto it = std::find_if(
            graph.outgoing[u].begin(), graph.outgoing[u].end(),
            [&](const Edge& edge) {
                return edge.to == v && edge.edge_id == edge_id;
            });
        if (it == graph.outgoing[u].end()) {
            throw std::runtime_error("failed to reconstruct an original edge");
        }
        result.cost += it->weight;
    }
    return result;
}

// Convenience overload for one-off queries. Repeated-query code should call
// prepare_bidirectional_astar() once and use the indexed overload above.
PathResult bidirectional_astar(
    const RoadGraph& graph,
    int start,
    int goal,
    double heuristic_scale) {

    const auto index = prepare_bidirectional_astar(graph, heuristic_scale);
    return bidirectional_astar(graph, index, start, goal);
}

} // namespace route_cpp17
