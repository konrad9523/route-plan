#include "bidirectional_astar_variants.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <limits>
#include <memory>
#include <queue>
#include <stdexcept>
#include <tuple>
#include <utility>
#include <vector>

using route_cpp17::BidirectionalAStarHeuristic;
using route_cpp17::BidirectionalAStarLayer;
using route_cpp17::BidirectionalAStarMeetingPolicy;
using route_cpp17::BidirectionalAStarQueue;
using route_cpp17::BidirectionalAStarStats;
using route_cpp17::BidirectionalAStarVariantIndex;
using route_cpp17::BidirectionalAStarDirectionPolicy;
using route_cpp17::Coordinate;
using route_cpp17::Edge;
using route_cpp17::PathResult;
using route_cpp17::RoadGraph;

namespace {

constexpr std::size_t LANDMARK_COUNT = 8;
constexpr int32_t OK = 0;
constexpr int32_t INVALID_ARGUMENT = 1;
constexpr int32_t PREPARATION_ERROR = 2;
constexpr int32_t INTERNAL_ERROR = 3;

struct Handle {
    RoadGraph graph;
    BidirectionalAStarVariantIndex index;
};

std::vector<int> largest_strongly_connected_component(const RoadGraph& graph) {
    const std::size_t node_count = graph.size();
    std::vector<std::vector<int>> reverse(node_count);
    for (std::size_t source = 0; source < node_count; ++source) {
        for (const Edge& edge : graph.outgoing[source]) {
            reverse[static_cast<std::size_t>(edge.to)].push_back(static_cast<int>(source));
        }
    }

    std::vector<unsigned char> visited(node_count, 0);
    std::vector<int> finish_order;
    finish_order.reserve(node_count);
    std::vector<std::pair<int, std::size_t>> dfs;
    for (std::size_t start = 0; start < node_count; ++start) {
        if (visited[start]) continue;
        visited[start] = 1;
        dfs.emplace_back(static_cast<int>(start), 0);
        while (!dfs.empty()) {
            const int node = dfs.back().first;
            std::size_t& next_edge = dfs.back().second;
            const auto& outgoing = graph.outgoing[static_cast<std::size_t>(node)];
            if (next_edge < outgoing.size()) {
                const int next = outgoing[next_edge++].to;
                if (!visited[static_cast<std::size_t>(next)]) {
                    visited[static_cast<std::size_t>(next)] = 1;
                    dfs.emplace_back(next, 0);
                }
            } else {
                finish_order.push_back(node);
                dfs.pop_back();
            }
        }
    }

    std::fill(visited.begin(), visited.end(), static_cast<unsigned char>(0));
    std::vector<int> largest;
    std::vector<int> stack;
    for (auto it = finish_order.rbegin(); it != finish_order.rend(); ++it) {
        const int start = *it;
        if (visited[static_cast<std::size_t>(start)]) continue;
        std::vector<int> component;
        visited[static_cast<std::size_t>(start)] = 1;
        stack.push_back(start);
        while (!stack.empty()) {
            const int node = stack.back();
            stack.pop_back();
            component.push_back(node);
            for (const int next : reverse[static_cast<std::size_t>(node)]) {
                if (!visited[static_cast<std::size_t>(next)]) {
                    visited[static_cast<std::size_t>(next)] = 1;
                    stack.push_back(next);
                }
            }
        }
        if (component.size() > largest.size()) largest = std::move(component);
    }
    std::sort(largest.begin(), largest.end());
    return largest;
}

std::vector<int> select_landmarks(const RoadGraph& graph,
                                  const std::vector<int>& candidates) {
    if (candidates.size() < LANDMARK_COUNT) {
        throw std::runtime_error("largest strongly connected component has fewer than 8 nodes");
    }
    double mean_lon = 0.0;
    double mean_lat = 0.0;
    for (const Coordinate& coordinate : graph.coordinates) {
        mean_lon += coordinate.lon;
        mean_lat += coordinate.lat;
    }
    mean_lon /= static_cast<double>(graph.coordinates.size());
    mean_lat /= static_cast<double>(graph.coordinates.size());
    constexpr double earth_radius_m = 6'371'000.0;
    constexpr double radians_per_degree = 3.14159265358979323846 / 180.0;
    const double lat_scale = earth_radius_m * radians_per_degree *
                             std::cos(mean_lat * radians_per_degree);
    const double lat_meters = earth_radius_m * radians_per_degree;

    std::vector<std::pair<double, double>> projected;
    projected.reserve(candidates.size());
    for (const int node : candidates) {
        const Coordinate& coordinate = graph.coordinates[static_cast<std::size_t>(node)];
        projected.emplace_back((coordinate.lon - mean_lon) * lat_scale,
                               (coordinate.lat - mean_lat) * lat_meters);
    }
    std::size_t first = 0;
    for (std::size_t i = 1; i < candidates.size(); ++i) {
        if (std::tie(projected[i].first, projected[i].second, candidates[i]) <
            std::tie(projected[first].first, projected[first].second, candidates[first])) {
            first = i;
        }
    }

    std::vector<double> nearest_sq(candidates.size(), std::numeric_limits<double>::infinity());
    std::vector<std::size_t> selected;
    selected.reserve(LANDMARK_COUNT);
    selected.push_back(first);
    auto update_distances = [&](std::size_t landmark) {
        const auto [x0, y0] = projected[landmark];
        for (std::size_t i = 0; i < projected.size(); ++i) {
            const double dx = projected[i].first - x0;
            const double dy = projected[i].second - y0;
            nearest_sq[i] = std::min(nearest_sq[i], dx * dx + dy * dy);
        }
    };
    update_distances(first);
    while (selected.size() < LANDMARK_COUNT) {
        std::size_t next = candidates.size();
        for (std::size_t i = 0; i < candidates.size(); ++i) {
            if (std::find(selected.begin(), selected.end(), i) != selected.end()) continue;
            if (next == candidates.size() || nearest_sq[i] > nearest_sq[next] ||
                (nearest_sq[i] == nearest_sq[next] && candidates[i] < candidates[next])) {
                next = i;
            }
        }
        selected.push_back(next);
        update_distances(next);
    }

    std::vector<int> landmarks;
    landmarks.reserve(LANDMARK_COUNT);
    for (const std::size_t index : selected) landmarks.push_back(candidates[index]);
    return landmarks;
}

}  // namespace

extern "C" {

__declspec(dllexport) void* bidirectional_astar_graph_create(
    int64_t node_count, int64_t edge_count, const int64_t* indptr,
    const int64_t* indices, const double* weights, const int64_t* edge_ids,
    const double* lon, const double* lat, int32_t* error_code,
    uint64_t* preprocess_ns, int64_t* landmark_count) {
    if (error_code) *error_code = OK;
    if (preprocess_ns) *preprocess_ns = 0;
    if (landmark_count) *landmark_count = 0;
    if (!error_code || !indptr || !indices || !weights || !edge_ids || !lon || !lat ||
        node_count <= 0 || edge_count < 0 || node_count > std::numeric_limits<int>::max() ||
        indptr[0] != 0 || indptr[node_count] != edge_count) {
        if (error_code) *error_code = INVALID_ARGUMENT;
        return nullptr;
    }

    try {
        auto handle = std::make_unique<Handle>();
        handle->graph.outgoing.resize(static_cast<std::size_t>(node_count));
        handle->graph.coordinates.resize(static_cast<std::size_t>(node_count));
        for (int64_t node = 0; node < node_count; ++node) {
            const double node_lon = lon[node];
            const double node_lat = lat[node];
            if (!std::isfinite(node_lon) || !std::isfinite(node_lat) ||
                node_lon < -180.0 || node_lon > 180.0 ||
                node_lat < -90.0 || node_lat > 90.0) {
                *error_code = INVALID_ARGUMENT;
                return nullptr;
            }
            handle->graph.coordinates[static_cast<std::size_t>(node)] = {node_lon, node_lat};
            const int64_t begin = indptr[node];
            const int64_t end = indptr[node + 1];
            if (begin < 0 || end < begin || end > edge_count) {
                *error_code = INVALID_ARGUMENT;
                return nullptr;
            }
            auto& outgoing = handle->graph.outgoing[static_cast<std::size_t>(node)];
            outgoing.reserve(static_cast<std::size_t>(end - begin));
            for (int64_t edge = begin; edge < end; ++edge) {
                if (indices[edge] < 0 || indices[edge] >= node_count ||
                    !std::isfinite(weights[edge]) || weights[edge] < 0.0) {
                    *error_code = INVALID_ARGUMENT;
                    return nullptr;
                }
                outgoing.push_back({static_cast<int>(indices[edge]), weights[edge], edge_ids[edge]});
            }
        }

        const auto prepare_begin = std::chrono::steady_clock::now();
        const std::vector<int> candidates = largest_strongly_connected_component(handle->graph);
        const std::vector<int> landmarks = select_landmarks(handle->graph, candidates);
        handle->index = route_cpp17::prepare_bidirectional_astar_variants(
            handle->graph, landmarks);
        const auto prepare_end = std::chrono::steady_clock::now();
        if (preprocess_ns) {
            *preprocess_ns = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
                prepare_end - prepare_begin).count());
        }
        if (landmark_count) *landmark_count = static_cast<int64_t>(landmarks.size());
        return handle.release();
    } catch (...) {
        *error_code = PREPARATION_ERROR;
        return nullptr;
    }
}

__declspec(dllexport) void bidirectional_astar_graph_destroy(void* opaque_handle) {
    delete static_cast<Handle*>(opaque_handle);
}

__declspec(dllexport) int32_t bidirectional_astar_run(
    void* opaque_handle, int64_t start, int64_t goal,
    int64_t* node_buffer, int64_t node_capacity,
    int64_t* edge_buffer, int64_t edge_capacity,
    int64_t* node_count, int64_t* edge_count, double* total_distance,
    uint64_t* expanded_count, uint64_t* queue_pushes,
    uint64_t* scanned_edges, uint64_t* heuristic_evaluations,
    uint64_t* elapsed_ns, int64_t* trace_buffer,
    int64_t trace_capacity, int64_t* trace_count) {
    if (node_count) *node_count = 0;
    if (edge_count) *edge_count = 0;
    if (total_distance) *total_distance = route_cpp17::ROUTE_INF;
    if (expanded_count) *expanded_count = 0;
    if (queue_pushes) *queue_pushes = 0;
    if (scanned_edges) *scanned_edges = 0;
    if (heuristic_evaluations) *heuristic_evaluations = 0;
    if (elapsed_ns) *elapsed_ns = 0;
    if (trace_count) *trace_count = 0;
    if (!opaque_handle || !node_count || !edge_count || !total_distance ||
        !expanded_count || !queue_pushes || !scanned_edges || !heuristic_evaluations ||
        !elapsed_ns || !trace_count || node_capacity < 0 || edge_capacity < 0 ||
        trace_capacity < 0 || (node_capacity > 0 && !node_buffer) ||
        (edge_capacity > 0 && !edge_buffer)) {
        return INVALID_ARGUMENT;
    }

    try {
        auto& handle = *static_cast<Handle*>(opaque_handle);
        if (start < 0 || goal < 0 ||
            start >= static_cast<int64_t>(handle.graph.size()) ||
            goal >= static_cast<int64_t>(handle.graph.size())) {
            return INVALID_ARGUMENT;
        }
        const bool capture_trace = trace_buffer && trace_capacity > 0;
        const bool endpoints_support_alt =
            handle.index.component_of_node.size() == handle.graph.size() &&
            handle.index.landmark_component >= 0 &&
            handle.index.component_of_node[static_cast<std::size_t>(start)] ==
                handle.index.landmark_component &&
            handle.index.component_of_node[static_cast<std::size_t>(goal)] ==
                handle.index.landmark_component;
        const auto heuristic = endpoints_support_alt
            ? BidirectionalAStarHeuristic::MAX
            : BidirectionalAStarHeuristic::H0;
        const std::size_t landmark_count = endpoints_support_alt ? LANDMARK_COUNT : 0;
        BidirectionalAStarStats stats;
        const auto begin = std::chrono::steady_clock::now();
        const PathResult result = route_cpp17::bidirectional_astar_variant(
            handle.graph, handle.index, static_cast<int>(start), static_cast<int>(goal),
            BidirectionalAStarLayer::L4_BAE_STAR, heuristic, landmark_count, &stats,
            BidirectionalAStarQueue::LAZY_DUPLICATES,
            BidirectionalAStarDirectionPolicy::NATIVE,
            BidirectionalAStarMeetingPolicy::NATIVE, false, capture_trace);
        const auto end = std::chrono::steady_clock::now();
        *elapsed_ns = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
            end - begin).count());
        *node_count = static_cast<int64_t>(result.nodes.size());
        *edge_count = static_cast<int64_t>(result.edges.size());
        *total_distance = result.cost;
        *expanded_count = static_cast<uint64_t>(stats.expanded_states);
        *queue_pushes = static_cast<uint64_t>(stats.queue_pushes);
        *scanned_edges = static_cast<uint64_t>(stats.scanned_edges);
        *heuristic_evaluations = static_cast<uint64_t>(stats.heuristic_evaluations);
        *trace_count = capture_trace ? static_cast<int64_t>(result.expanded_order.size()) : 0;
        if (result.nodes.size() > static_cast<std::size_t>(node_capacity) ||
            result.edges.size() > static_cast<std::size_t>(edge_capacity) ||
            (capture_trace && result.expanded_order.size() > static_cast<std::size_t>(trace_capacity))) {
            return INVALID_ARGUMENT;
        }
        std::copy(result.nodes.begin(), result.nodes.end(), node_buffer);
        std::copy(result.edges.begin(), result.edges.end(), edge_buffer);
        if (capture_trace) {
            std::copy(result.expanded_order.begin(), result.expanded_order.end(), trace_buffer);
        }
        return OK;
    } catch (...) {
        return INTERNAL_ERROR;
    }
}

}  // extern "C"
