#include "bidirectional_astar_variants.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <random>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

extern "C" {
void* dijkstra_graph_create(int64_t n_nodes, int64_t n_edges,
                            const int64_t* indptr, const int64_t* indices,
                            const double* weights, const int64_t* edge_ids,
                            int32_t* error_code);
void dijkstra_graph_destroy(void* handle);
int32_t dijkstra_run(void* handle, int32_t algorithm, int64_t start,
                     int64_t goal, int64_t* node_buffer,
                     int64_t node_capacity, int64_t* edge_buffer,
                     int64_t edge_capacity, int64_t* node_count,
                     int64_t* edge_count, double* total_distance,
                     uint64_t* settled_count, uint64_t* elapsed_ns,
                     int64_t* trace_buffer, int64_t trace_capacity,
                     int64_t* trace_count);

void* astar_graph_create(int64_t n_nodes, int64_t n_edges,
                         const int64_t* indptr, const int64_t* indices,
                         const double* weights, const int64_t* edge_ids,
                         const double* lon, const double* lat,
                         int32_t* error_code);
void astar_graph_destroy(void* handle);
int32_t astar_prepare_geometry(void* handle, double* haversine_scale,
                               double* plane_scale, uint64_t* elapsed_ns);
int32_t astar_prepare_reverse(void* handle, uint64_t* elapsed_ns);
int32_t astar_prepare_alt(void* handle, int32_t landmark_count,
                          const int64_t* landmark_ids, uint64_t* elapsed_ns);
int32_t astar_run(void* handle, int32_t version, int32_t heuristic,
                  int32_t landmark_count, int64_t start, int64_t goal,
                  int64_t* node_buffer, int64_t node_capacity,
                  int64_t* edge_buffer, int64_t edge_capacity,
                  int64_t* node_count, int64_t* edge_count,
                  double* total_distance, uint64_t* expanded_count,
                  uint64_t* pushed_count, uint64_t* scanned_edges,
                  uint64_t* heuristic_evaluations, uint64_t* elapsed_ns,
                  int64_t* trace_buffer, int64_t trace_capacity,
                  int64_t* trace_count);

void* ch_graph_create(int64_t n_nodes, int64_t n_edges, const int64_t* indptr,
                      const int64_t* indices, const double* weights,
                      const int64_t* edge_ids, int32_t* error_code,
                      uint64_t* preprocess_ns, int64_t* hierarchy_arc_count,
                      int64_t* shortcut_count);
void* ch_graph_create_cached(
    int64_t n_nodes, int64_t n_edges, const int64_t* indptr,
    const int64_t* indices, const double* weights, const int64_t* edge_ids,
    const char* cache_path, const char* cache_key, int32_t* error_code,
    uint64_t* preprocess_ns, uint64_t* cache_load_ns, int32_t* cache_hit,
    int64_t* hierarchy_arc_count, int64_t* shortcut_count);
void ch_graph_destroy(void* handle);
int32_t ch_run(void* handle, int64_t start, int64_t goal,
               int64_t* node_buffer, int64_t node_capacity,
               int64_t* edge_buffer, int64_t edge_capacity,
               int64_t* node_count, int64_t* edge_count,
               double* total_distance, uint64_t* expanded_count,
               uint64_t* queue_pushes, uint64_t* elapsed_ns,
               int64_t* trace_buffer, int64_t trace_capacity,
               int64_t* trace_count);
}

using namespace route_cpp17;

namespace {

constexpr std::size_t kLandmarkCount = 8;
constexpr int32_t kDijkstraL4 = 4;
constexpr int32_t kDijkstraB1 = 5;
constexpr int32_t kAstarL4 = 5;
constexpr int32_t kAstarMax = 3;

struct EdgeRecord {
    std::int32_t source;
    std::int32_t target;
    double weight;
};
static_assert(sizeof(EdgeRecord) == 16, "graph binary edge layout changed");

struct Query {
    std::size_t query_index = 0;
    int source = -1;
    int target = -1;
};

struct GraphData {
    RoadGraph graph;
    std::vector<int> edge_sources;
    std::vector<int> edge_targets;
    std::vector<double> edge_weights;
    std::vector<int64_t> indptr;
    std::vector<int64_t> indices;
    std::vector<int64_t> edge_ids;
    std::vector<double> weights;
    std::vector<double> lon;
    std::vector<double> lat;
};

struct RunResult {
    std::string algorithm;
    PathResult path;
    uint64_t elapsed_ns = 0;
    uint64_t kernel_ns = 0;
    uint64_t expanded = 0;
    uint64_t queue_pushes = 0;
    uint64_t scanned_edges = 0;
    uint64_t heuristic_evaluations = 0;
};

GraphData load_graph(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("cannot open graph binary");
    uint64_t node_count = 0, edge_count = 0;
    input.read(reinterpret_cast<char*>(&node_count), sizeof(node_count));
    input.read(reinterpret_cast<char*>(&edge_count), sizeof(edge_count));
    if (!input || node_count == 0 || node_count > static_cast<uint64_t>(INT32_MAX) ||
        edge_count > static_cast<uint64_t>(INT32_MAX)) {
        throw std::runtime_error("invalid graph binary header");
    }

    GraphData data;
    data.graph.outgoing.resize(static_cast<std::size_t>(node_count));
    data.graph.coordinates.resize(static_cast<std::size_t>(node_count));
    data.lon.resize(static_cast<std::size_t>(node_count));
    data.lat.resize(static_cast<std::size_t>(node_count));
    for (std::size_t node = 0; node < static_cast<std::size_t>(node_count); ++node) {
        Coordinate& coordinate = data.graph.coordinates[node];
        input.read(reinterpret_cast<char*>(&coordinate.lon), sizeof(double));
        input.read(reinterpret_cast<char*>(&coordinate.lat), sizeof(double));
        if (!input || !std::isfinite(coordinate.lon) || !std::isfinite(coordinate.lat)) {
            throw std::runtime_error("invalid coordinates in graph binary");
        }
        data.lon[node] = coordinate.lon;
        data.lat[node] = coordinate.lat;
    }

    data.edge_sources.reserve(static_cast<std::size_t>(edge_count));
    data.edge_targets.reserve(static_cast<std::size_t>(edge_count));
    data.edge_weights.reserve(static_cast<std::size_t>(edge_count));
    for (uint64_t edge_id = 0; edge_id < edge_count; ++edge_id) {
        EdgeRecord record{};
        input.read(reinterpret_cast<char*>(&record), sizeof(record));
        if (!input || record.source < 0 || record.target < 0 ||
            record.source >= static_cast<int32_t>(node_count) ||
            record.target >= static_cast<int32_t>(node_count) ||
            !std::isfinite(record.weight) || record.weight < 0.0) {
            throw std::runtime_error("invalid edge record in graph binary");
        }
        data.graph.outgoing[static_cast<std::size_t>(record.source)].push_back(
            {record.target, record.weight, static_cast<int64_t>(edge_id)});
        data.edge_sources.push_back(record.source);
        data.edge_targets.push_back(record.target);
        data.edge_weights.push_back(record.weight);
    }
    if (input.peek() != std::char_traits<char>::eof()) {
        throw std::runtime_error("unexpected trailing bytes in graph binary");
    }

    data.indptr.resize(static_cast<std::size_t>(node_count) + 1, 0);
    data.indices.reserve(static_cast<std::size_t>(edge_count));
    data.edge_ids.reserve(static_cast<std::size_t>(edge_count));
    data.weights.reserve(static_cast<std::size_t>(edge_count));
    for (std::size_t node = 0; node < static_cast<std::size_t>(node_count); ++node) {
        for (const Edge& edge : data.graph.outgoing[node]) {
            data.indices.push_back(edge.to);
            data.edge_ids.push_back(edge.edge_id);
            data.weights.push_back(edge.weight);
        }
        data.indptr[node + 1] = static_cast<int64_t>(data.indices.size());
    }
    return data;
}

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
            int node = dfs.back().first;
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
    std::vector<int> stack;
    std::vector<int> largest;
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

std::vector<Query> generate_queries(const std::vector<int>& candidates,
                                   std::size_t query_count,
                                   std::mt19937_64& rng) {
    if (candidates.size() < 2) {
        throw std::runtime_error("largest strongly connected component has fewer than two nodes");
    }
    if (query_count > candidates.size() * (candidates.size() - 1)) {
        throw std::invalid_argument("query_count exceeds the number of unique ordered pairs in the largest SCC");
    }
    std::uniform_int_distribution<std::size_t> choose(0, candidates.size() - 1);
    std::set<std::pair<int, int>> selected;
    while (selected.size() < query_count) {
        const int source = candidates[choose(rng)];
        const int target = candidates[choose(rng)];
        if (source != target) selected.emplace(source, target);
    }
    std::vector<Query> queries;
    queries.reserve(query_count);
    for (const auto& pair : selected) {
        queries.push_back({queries.size(), pair.first, pair.second});
    }
    return queries;
}

std::vector<int64_t> select_landmarks(const GraphData& data,
                                      const std::vector<int>& candidates) {
    if (candidates.size() < kLandmarkCount) {
        throw std::runtime_error("largest strongly connected component has fewer than 8 nodes");
    }
    double mean_lon = 0.0, mean_lat = 0.0;
    for (std::size_t node = 0; node < data.lon.size(); ++node) {
        mean_lon += data.lon[node];
        mean_lat += data.lat[node];
    }
    mean_lon /= static_cast<double>(data.lon.size());
    mean_lat /= static_cast<double>(data.lat.size());
    constexpr double earth_radius_m = 6'371'000.0;
    constexpr double radians_per_degree = 3.14159265358979323846 / 180.0;
    const double lat_scale = std::cos(mean_lat * radians_per_degree);
    const double lon_scale = earth_radius_m * radians_per_degree * lat_scale;
    const double lat_meters = earth_radius_m * radians_per_degree;

    std::vector<std::pair<double, double>> projected;
    projected.reserve(candidates.size());
    for (const int node : candidates) {
        projected.emplace_back((data.lon[static_cast<std::size_t>(node)] - mean_lon) * lon_scale,
                               (data.lat[static_cast<std::size_t>(node)] - mean_lat) * lat_meters);
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
    selected.reserve(kLandmarkCount);
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
    while (selected.size() < kLandmarkCount) {
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

    std::vector<int64_t> landmarks;
    landmarks.reserve(kLandmarkCount);
    for (const std::size_t index : selected) landmarks.push_back(candidates[index]);
    return landmarks;
}

std::vector<int> parse_algorithms(const std::string& text) {
    std::vector<int> algorithms;
    std::istringstream input(text);
    std::string item;
    while (std::getline(input, item, ',')) {
        int algorithm = -1;
        if (item == "dijkstra") algorithm = 0;
        else if (item == "astar") algorithm = 1;
        else if (item == "bidirectional_astar") algorithm = 2;
        else if (item == "bidirectional_dijkstra") algorithm = 3;
        else if (item == "ch") algorithm = 4;
        else throw std::invalid_argument("unknown algorithm: " + item);
        if (std::find(algorithms.begin(), algorithms.end(), algorithm) != algorithms.end())
            throw std::invalid_argument("duplicate algorithm selection: " + item);
        algorithms.push_back(algorithm);
    }
    if (algorithms.empty()) throw std::invalid_argument("select at least one algorithm");
    return algorithms;
}

void validate_route(const PathResult& route, const Query& query,
                    const GraphData& graph) {
    if (!route.reachable() || route.nodes.empty() ||
        route.nodes.front() != query.source || route.nodes.back() != query.target ||
        route.edges.size() + 1 != route.nodes.size()) {
        throw std::runtime_error("algorithm returned an invalid path shape");
    }
    double sum = 0.0;
    for (std::size_t i = 0; i < route.edges.size(); ++i) {
        const int64_t edge_id = route.edges[i];
        if (edge_id < 0 || static_cast<std::size_t>(edge_id) >= graph.edge_weights.size()) {
            throw std::runtime_error("path has an invalid edge ID");
        }
        const std::size_t id = static_cast<std::size_t>(edge_id);
        if (graph.edge_sources[id] != route.nodes[i] ||
            graph.edge_targets[id] != route.nodes[i + 1]) {
            throw std::runtime_error("path edge sequence is not directed and contiguous");
        }
        sum += graph.edge_weights[id];
    }
    if (std::abs(sum - route.cost) > 1e-8 * std::max(1.0, std::abs(route.cost))) {
        throw std::runtime_error("path edge-weight sum differs from reported distance");
    }
}

PathResult cpp_path(const std::vector<int64_t>& nodes,
                    const std::vector<int64_t>& edges,
                    int64_t node_count, int64_t edge_count,
                    double distance, uint64_t expanded, uint64_t pushes) {
    if (node_count < 0 || edge_count < 0 ||
        static_cast<uint64_t>(node_count) > nodes.size() ||
        static_cast<uint64_t>(edge_count) > edges.size()) {
        throw std::runtime_error("C++ algorithm returned invalid path lengths");
    }
    PathResult result;
    result.nodes.reserve(static_cast<std::size_t>(node_count));
    result.edges.assign(edges.begin(), edges.begin() + edge_count);
    for (int64_t i = 0; i < node_count; ++i) {
        if (nodes[static_cast<std::size_t>(i)] < 0 ||
            nodes[static_cast<std::size_t>(i)] > INT32_MAX) {
            throw std::runtime_error("C++ algorithm returned an invalid node ID");
        }
        result.nodes.push_back(static_cast<int>(nodes[static_cast<std::size_t>(i)]));
    }
    result.cost = distance;
    result.expanded = static_cast<std::size_t>(expanded);
    result.queue_pushes = static_cast<std::size_t>(pushes);
    return result;
}

RunResult run_dijkstra(void* handle, const Query& query,
                       std::vector<int64_t>& nodes,
                       std::vector<int64_t>& edges) {
    int64_t node_count = 0, edge_count = 0;
    double distance = ROUTE_INF;
    uint64_t settled = 0, kernel_ns = 0;
    int64_t trace_count = 0;
    const auto begin = std::chrono::steady_clock::now();
    const int32_t status = dijkstra_run(
        handle, kDijkstraL4, query.source, query.target, nodes.data(),
        static_cast<int64_t>(nodes.size()), edges.data(),
        static_cast<int64_t>(edges.size()), &node_count, &edge_count,
        &distance, &settled, &kernel_ns, nullptr, 0, &trace_count);
    const auto end = std::chrono::steady_clock::now();
    if (status != 0) throw std::runtime_error("Dijkstra L4 query failed: " + std::to_string(status));
    RunResult result;
    result.algorithm = "Dijkstra L4";
    result.elapsed_ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count());
    result.kernel_ns = kernel_ns;
    result.expanded = settled;
    result.path = cpp_path(nodes, edges, node_count, edge_count, distance, settled, 0);
    return result;
}

RunResult run_bidirectional_dijkstra(void* handle, const Query& query,
                                     std::vector<int64_t>& nodes,
                                     std::vector<int64_t>& edges) {
    int64_t node_count = 0, edge_count = 0;
    double distance = ROUTE_INF;
    uint64_t settled = 0, kernel_ns = 0;
    int64_t trace_count = 0;
    const auto begin = std::chrono::steady_clock::now();
    const int32_t status = dijkstra_run(
        handle, kDijkstraB1, query.source, query.target, nodes.data(),
        static_cast<int64_t>(nodes.size()), edges.data(),
        static_cast<int64_t>(edges.size()), &node_count, &edge_count,
        &distance, &settled, &kernel_ns, nullptr, 0, &trace_count);
    const auto end = std::chrono::steady_clock::now();
    if (status != 0)
        throw std::runtime_error("bidirectional Dijkstra B1 query failed: " + std::to_string(status));
    RunResult result;
    result.algorithm = "双向 Dijkstra B1";
    result.elapsed_ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count());
    result.kernel_ns = kernel_ns;
    result.expanded = settled;
    result.path = cpp_path(nodes, edges, node_count, edge_count, distance, settled, 0);
    return result;
}

RunResult run_astar(void* handle, const Query& query,
                    std::vector<int64_t>& nodes,
                    std::vector<int64_t>& edges) {
    int64_t node_count = 0, edge_count = 0;
    double distance = ROUTE_INF;
    uint64_t expanded = 0, pushes = 0, scanned = 0, evaluations = 0, kernel_ns = 0;
    int64_t trace_count = 0;
    const auto begin = std::chrono::steady_clock::now();
    const int32_t status = astar_run(
        handle, kAstarL4, kAstarMax, static_cast<int32_t>(kLandmarkCount),
        query.source, query.target, nodes.data(), static_cast<int64_t>(nodes.size()),
        edges.data(), static_cast<int64_t>(edges.size()), &node_count, &edge_count,
        &distance, &expanded, &pushes, &scanned, &evaluations, &kernel_ns,
        nullptr, 0, &trace_count);
    const auto end = std::chrono::steady_clock::now();
    if (status != 0) throw std::runtime_error("A* L4 MAX-8 query failed: " + std::to_string(status));
    RunResult result;
    result.algorithm = "A* L4 MAX-8";
    result.elapsed_ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count());
    result.kernel_ns = kernel_ns;
    result.expanded = expanded;
    result.queue_pushes = pushes;
    result.scanned_edges = scanned;
    result.heuristic_evaluations = evaluations;
    result.path = cpp_path(nodes, edges, node_count, edge_count, distance, expanded, pushes);
    return result;
}

RunResult run_bidirectional_astar(const RoadGraph& graph,
                                  const BidirectionalAStarVariantIndex& index,
                                  const Query& query) {
    BidirectionalAStarStats stats;
    const auto begin = std::chrono::steady_clock::now();
    PathResult path = bidirectional_astar_variant(
        graph, index, query.source, query.target,
        BidirectionalAStarLayer::L4_BAE_STAR,
        BidirectionalAStarHeuristic::MAX, kLandmarkCount, &stats);
    const auto end = std::chrono::steady_clock::now();
    RunResult result;
    result.algorithm = "双向 A* L4 MAX-8";
    result.elapsed_ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count());
    result.kernel_ns = result.elapsed_ns;
    result.expanded = stats.expanded_states;
    result.queue_pushes = stats.queue_pushes;
    result.scanned_edges = stats.scanned_edges;
    result.heuristic_evaluations = stats.heuristic_evaluations;
    result.path = std::move(path);
    return result;
}

RunResult run_ch(void* handle, const Query& query,
                 std::vector<int64_t>& nodes,
                 std::vector<int64_t>& edges) {
    int64_t node_count = 0, edge_count = 0;
    double distance = ROUTE_INF;
    uint64_t expanded = 0, pushes = 0, kernel_ns = 0;
    int64_t trace_count = 0;
    const auto begin = std::chrono::steady_clock::now();
    const int32_t status = ch_run(
        handle, query.source, query.target, nodes.data(),
        static_cast<int64_t>(nodes.size()), edges.data(),
        static_cast<int64_t>(edges.size()), &node_count, &edge_count,
        &distance, &expanded, &pushes, &kernel_ns, nullptr, 0, &trace_count);
    const auto end = std::chrono::steady_clock::now();
    if (status != 0) throw std::runtime_error("CH query failed: " + std::to_string(status));
    RunResult result;
    result.algorithm = "CH";
    result.elapsed_ns = static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count());
    result.kernel_ns = kernel_ns;
    result.expanded = expanded;
    result.queue_pushes = pushes;
    result.path = cpp_path(nodes, edges, node_count, edge_count, distance, expanded, pushes);
    return result;
}

RunResult run_selected_algorithm(
    int algorithm, void* dijkstra, void* astar,
    const RoadGraph& graph, const BidirectionalAStarVariantIndex& bi_index,
    void* ch, const Query& query, std::vector<int64_t>& nodes,
    std::vector<int64_t>& edges) {
    switch (algorithm) {
        case 0: return run_dijkstra(dijkstra, query, nodes, edges);
        case 1: return run_astar(astar, query, nodes, edges);
        case 2: return run_bidirectional_astar(graph, bi_index, query);
        case 3: return run_bidirectional_dijkstra(dijkstra, query, nodes, edges);
        case 4: return run_ch(ch, query, nodes, edges);
        default: throw std::logic_error("invalid algorithm selection");
    }
}

std::string csv_field(const std::string& value) {
    if (value.find_first_of(",\"\r\n") == std::string::npos) return value;
    std::string escaped = "\"";
    for (char ch : value) {
        if (ch == '"') escaped += '"';
        escaped += ch;
    }
    return escaped + '"';
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 11) {
        std::cerr << "usage: performance_comparison <graph.bin> <network> "
                     "<query_count> <rounds> <seed> <algorithms_csv> "
                     "<raw.csv> <preprocess.csv> <ch_cache.bin> <ch_cache_key>\n";
        return 2;
    }
    try {
        const std::string graph_path = argv[1];
        const std::string network = argv[2];
        const std::size_t query_count = static_cast<std::size_t>(std::stoull(argv[3]));
        const int rounds = std::stoi(argv[4]);
        const uint64_t seed = std::stoull(argv[5]);
        const std::vector<int> algorithms = parse_algorithms(argv[6]);
        const std::string raw_path = argv[7];
        const std::string preprocess_path = argv[8];
        const std::string ch_cache_path = argv[9];
        const std::string ch_cache_key = argv[10];
        if (query_count == 0 || rounds <= 0) throw std::invalid_argument("count and rounds must be positive");
        const bool include_astar = std::find(algorithms.begin(), algorithms.end(), 1) != algorithms.end();
        const bool include_biastar = std::find(algorithms.begin(), algorithms.end(), 2) != algorithms.end();
        const bool include_ch = std::find(algorithms.begin(), algorithms.end(), 4) != algorithms.end();

        const auto load_begin = std::chrono::steady_clock::now();
        GraphData data = load_graph(graph_path);
        const auto load_end = std::chrono::steady_clock::now();
        const auto query_begin = std::chrono::steady_clock::now();
        const std::vector<int> query_component = largest_strongly_connected_component(data.graph);
        std::mt19937_64 query_rng(seed);
        const std::vector<Query> queries = generate_queries(query_component, query_count, query_rng);
        const auto query_end = std::chrono::steady_clock::now();
        const double query_generation_ms = std::chrono::duration<double, std::milli>(
            query_end - query_begin).count();

        const auto landmark_begin = std::chrono::steady_clock::now();
        const std::vector<int64_t> landmarks = include_astar || include_biastar
            ? select_landmarks(data, query_component)
            : std::vector<int64_t>{};
        const auto landmark_end = std::chrono::steady_clock::now();
        const double landmark_selection_ms = std::chrono::duration<double, std::milli>(
            landmark_end - landmark_begin).count();

        std::mt19937_64 rng(seed ^ 0x9e3779b97f4a7c15ULL);

        const std::array<std::string, 5> algorithm_names = {
            "dijkstra", "astar", "bidirectional_astar",
            "bidirectional_dijkstra", "ch"};
        void* dijkstra = nullptr;
        void* astar = nullptr;
        void* ch = nullptr;
        BidirectionalAStarVariantIndex bi_index;
        double h0_scale = 0.0, plane_scale = 0.0;
        uint64_t prep_ns = 0;
        double dijkstra_init_ms = 0.0, astar_init_ms = 0.0, biastar_init_ms = 0.0;
        double ch_init_ms = 0.0;
        uint64_t ch_preprocess_ns = 0;
        uint64_t ch_cache_load_ns = 0;
        int32_t ch_cache_hit = 0;
        int64_t ch_hierarchy_arcs = 0, ch_shortcut_count = 0;
        try {
            // Keep a Dijkstra L4 oracle even when the UI did not select Dijkstra.
            // It is used only for untimed correctness checks and its setup is
            // reported separately from query latency.
            const auto dijkstra_begin = std::chrono::steady_clock::now();
            int32_t dijkstra_error = 0;
            dijkstra = dijkstra_graph_create(
                static_cast<int64_t>(data.graph.size()), static_cast<int64_t>(data.edge_weights.size()),
                data.indptr.data(), data.indices.data(), data.weights.data(), data.edge_ids.data(), &dijkstra_error);
            const auto dijkstra_end = std::chrono::steady_clock::now();
            if (!dijkstra || dijkstra_error != 0)
                throw std::runtime_error("Dijkstra oracle graph init failed: " + std::to_string(dijkstra_error));
            dijkstra_init_ms = std::chrono::duration<double, std::milli>(
                dijkstra_end - dijkstra_begin).count();

            if (include_astar) {
                const auto begin = std::chrono::steady_clock::now();
                int32_t error = 0;
                astar = astar_graph_create(
                    static_cast<int64_t>(data.graph.size()), static_cast<int64_t>(data.edge_weights.size()),
                    data.indptr.data(), data.indices.data(), data.weights.data(), data.edge_ids.data(),
                    data.lon.data(), data.lat.data(), &error);
                if (!astar || error != 0)
                    throw std::runtime_error("A* graph init failed: " + std::to_string(error));
                if (astar_prepare_geometry(astar, &h0_scale, &plane_scale, &prep_ns) != 0 ||
                    astar_prepare_reverse(astar, &prep_ns) != 0 ||
                    astar_prepare_alt(astar, static_cast<int32_t>(landmarks.size()),
                                      landmarks.data(), &prep_ns) != 0)
                    throw std::runtime_error("A* L4 MAX-8 preparation failed");
                const auto end = std::chrono::steady_clock::now();
                astar_init_ms = std::chrono::duration<double, std::milli>(end - begin).count();
            }

            if (include_biastar) {
                std::vector<int> bi_landmarks;
                bi_landmarks.reserve(landmarks.size());
                for (const int64_t landmark : landmarks) {
                    if (landmark > std::numeric_limits<int>::max())
                        throw std::runtime_error("landmark ID exceeds the bidirectional API range");
                    bi_landmarks.push_back(static_cast<int>(landmark));
                }
                const auto begin = std::chrono::steady_clock::now();
                bi_index = prepare_bidirectional_astar_variants(data.graph, bi_landmarks);
                const auto end = std::chrono::steady_clock::now();
                biastar_init_ms = std::chrono::duration<double, std::milli>(end - begin).count();
            }

            if (include_ch) {
                const auto begin = std::chrono::steady_clock::now();
                int32_t error = 0;
                ch = ch_graph_create_cached(
                    static_cast<int64_t>(data.graph.size()),
                    static_cast<int64_t>(data.edge_weights.size()),
                    data.indptr.data(), data.indices.data(), data.weights.data(),
                    data.edge_ids.data(), ch_cache_path.c_str(), ch_cache_key.c_str(),
                    &error, &ch_preprocess_ns, &ch_cache_load_ns, &ch_cache_hit,
                    &ch_hierarchy_arcs, &ch_shortcut_count);
                const auto end = std::chrono::steady_clock::now();
                if (!ch || error != 0)
                    throw std::runtime_error("CH preprocessing failed: " + std::to_string(error));
                if (!ch_cache_hit && ch_preprocess_ns == 0)
                    throw std::runtime_error("CH preprocessing reported zero elapsed time");
                ch_init_ms = std::chrono::duration<double, std::milli>(end - begin).count();
            }

            std::vector<int64_t> node_buffer(data.graph.size());
            std::vector<int64_t> edge_buffer(data.graph.size());
            std::vector<double> oracle(queries.size(), ROUTE_INF);
            for (std::size_t qi = 0; qi < queries.size(); ++qi) {
                std::vector<RunResult> checked;
                for (const int algorithm : algorithms) {
                    RunResult result = run_selected_algorithm(
                        algorithm, dijkstra, astar, data.graph, bi_index, ch,
                        queries[qi], node_buffer, edge_buffer);
                    validate_route(result.path, queries[qi], data);
                    checked.push_back(std::move(result));
                }
                const auto dijkstra_it = std::find_if(checked.begin(), checked.end(),
                    [](const RunResult& result) { return result.algorithm == "Dijkstra L4"; });
                if (dijkstra_it != checked.end()) {
                    oracle[qi] = dijkstra_it->path.cost;
                } else {
                    const RunResult dijkstra_result = run_dijkstra(
                        dijkstra, queries[qi], node_buffer, edge_buffer);
                    validate_route(dijkstra_result.path, queries[qi], data);
                    oracle[qi] = dijkstra_result.path.cost;
                }
                for (const RunResult& candidate : checked) {
                    if (std::abs(candidate.path.cost - oracle[qi]) >
                        1e-8 * std::max(1.0, std::abs(oracle[qi])))
                        throw std::runtime_error("selected algorithms returned different distances");
                }
            }

            for (std::size_t qi = 0; qi < std::min<std::size_t>(5, queries.size()); ++qi) {
                for (const int algorithm : algorithms) {
                    (void)run_selected_algorithm(
                        algorithm, dijkstra, astar, data.graph, bi_index, ch,
                        queries[qi], node_buffer, edge_buffer);
                }
            }

            std::ofstream raw(raw_path, std::ios::trunc);
            if (!raw) throw std::runtime_error("cannot create raw result CSV");
            raw << "network,query,source_index,target_index,algorithm,round,elapsed_ns,kernel_ns,"
                   "distance_m,expanded_nodes,queue_pushes,scanned_edges,heuristic_evaluations\n";
            for (int round = 0; round < rounds; ++round) {
                std::vector<std::size_t> query_order(queries.size());
                std::iota(query_order.begin(), query_order.end(), 0);
                std::shuffle(query_order.begin(), query_order.end(), rng);
                for (const std::size_t qi : query_order) {
                    std::vector<int> algorithm_order = algorithms;
                    std::shuffle(algorithm_order.begin(), algorithm_order.end(), rng);
                    for (const int algorithm : algorithm_order) {
                        RunResult result = run_selected_algorithm(
                            algorithm, dijkstra, astar, data.graph, bi_index, ch,
                            queries[qi], node_buffer, edge_buffer);
                        validate_route(result.path, queries[qi], data);
                        if (std::abs(result.path.cost - oracle[qi]) >
                            1e-8 * std::max(1.0, std::abs(oracle[qi])))
                            throw std::runtime_error("timed route differs from Dijkstra L4 distance");
                        raw << network << ',' << qi << ','
                            << queries[qi].source << ',' << queries[qi].target << ','
                            << algorithm_names[algorithm] << ',' << round << ','
                            << result.elapsed_ns << ',' << result.kernel_ns << ','
                            << std::setprecision(17) << result.path.cost << ','
                            << result.expanded << ',' << result.queue_pushes << ','
                            << result.scanned_edges << ',' << result.heuristic_evaluations << '\n';
                    }
                }
            }
            raw.close();

            std::ofstream prep(preprocess_path, std::ios::trunc);
            if (!prep) throw std::runtime_error("cannot create preprocessing CSV");
            const auto load_ms = std::chrono::duration<double, std::milli>(load_end - load_begin).count();
            prep << "network,algorithms,nodes,directed_edges,query_component_nodes,queries,rounds,landmarks,"
                    "query_generation_ms,landmark_selection_ms,"
                    "binary_load_and_csr_ms,dijkstra_graph_init_ms,astar_graph_geometry_reverse_alt_ms,"
                    "bidirectional_index_alt_ms,ch_preprocess_ms,ch_cache_load_ms,ch_cache_hit,"
                    "ch_setup_ms,ch_hierarchy_arcs,ch_shortcut_count\n"
                 << network << ',';
            for (std::size_t i = 0; i < algorithms.size(); ++i) {
                if (i) prep << '+';
                prep << algorithm_names[algorithms[i]];
            }
            prep << ',' << data.graph.size() << ',' << data.edge_weights.size() << ','
                 << query_component.size() << ',' << queries.size() << ',' << rounds << ',' << landmarks.size() << ','
                 << std::fixed << std::setprecision(3) << query_generation_ms << ','
                 << landmark_selection_ms << ','
                 << std::fixed << std::setprecision(3) << load_ms << ',';
            if (dijkstra) prep << dijkstra_init_ms;
            prep << ',';
            if (astar) prep << astar_init_ms;
            prep << ',';
            if (include_biastar) prep << biastar_init_ms;
            prep << ',';
            if (include_ch) prep << static_cast<double>(ch_preprocess_ns) / 1'000'000.0;
            prep << ',';
            if (include_ch) prep << static_cast<double>(ch_cache_load_ns) / 1'000'000.0;
            prep << ',';
            if (include_ch) prep << ch_cache_hit;
            prep << ',';
            if (include_ch) prep << ch_init_ms;
            prep << ',';
            if (include_ch) prep << ch_hierarchy_arcs;
            prep << ',';
            if (include_ch) prep << ch_shortcut_count;
            prep << '\n';
            std::cout << network << ": " << data.graph.size() << " nodes, "
                      << data.edge_weights.size() << " directed edges, queries="
                      << queries.size() << ", rounds=" << rounds << "; prep ms: Dijkstra="
                      << dijkstra_init_ms << ", A*=" << astar_init_ms
                      << ", bidirectional A*=" << biastar_init_ms
                      << ", CH setup=" << ch_init_ms << " ms (preprocess="
                      << static_cast<double>(ch_preprocess_ns) / 1'000'000.0
                      << " ms, cache_hit=" << ch_cache_hit << ")\n";
        } catch (...) {
            if (ch) ch_graph_destroy(ch);
            if (astar) astar_graph_destroy(astar);
            dijkstra_graph_destroy(dijkstra);
            throw;
        }
        ch_graph_destroy(ch);
        astar_graph_destroy(astar);
        dijkstra_graph_destroy(dijkstra);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "performance comparison failed: " << error.what() << '\n';
        return 1;
    }
}
