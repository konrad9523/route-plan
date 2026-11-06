#include "../cpp/bidirectional_astar_variants.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using namespace route_cpp17;

namespace {

struct EdgeRecord {
    std::int32_t source;
    std::int32_t target;
    double weight;
};
static_assert(sizeof(EdgeRecord) == 16, "benchmark edge record layout changed");

struct Query {
    int source;
    int target;
};

std::vector<int> largest_strong_component(const RoadGraph& graph,
                                          const BidirectionalAStarIndex& index) {
    const int n = static_cast<int>(graph.size());
    std::vector<char> visited(static_cast<std::size_t>(n), false);
    std::vector<int> finish_order;
    finish_order.reserve(static_cast<std::size_t>(n));
    std::vector<std::pair<int, std::size_t>> dfs;

    for (int root = 0; root < n; ++root) {
        if (visited[static_cast<std::size_t>(root)]) continue;
        visited[static_cast<std::size_t>(root)] = true;
        dfs.emplace_back(root, 0);
        while (!dfs.empty()) {
            int node = dfs.back().first;
            std::size_t& next = dfs.back().second;
            const auto& outgoing = graph.outgoing[static_cast<std::size_t>(node)];
            if (next < outgoing.size()) {
                const int neighbor = outgoing[next++].to;
                if (!visited[static_cast<std::size_t>(neighbor)]) {
                    visited[static_cast<std::size_t>(neighbor)] = true;
                    dfs.emplace_back(neighbor, 0);
                }
            } else {
                finish_order.push_back(node);
                dfs.pop_back();
            }
        }
    }

    std::vector<int> component(static_cast<std::size_t>(n), -1);
    std::vector<int> stack;
    std::vector<int> largest;
    int component_id = 0;
    for (auto it = finish_order.rbegin(); it != finish_order.rend(); ++it) {
        if (component[static_cast<std::size_t>(*it)] >= 0) continue;
        std::vector<int> members;
        component[static_cast<std::size_t>(*it)] = component_id;
        stack.push_back(*it);
        while (!stack.empty()) {
            const int node = stack.back();
            stack.pop_back();
            members.push_back(node);
            for (const Edge& edge : index.incoming[static_cast<std::size_t>(node)]) {
                const int predecessor = edge.to;
                if (component[static_cast<std::size_t>(predecessor)] < 0) {
                    component[static_cast<std::size_t>(predecessor)] = component_id;
                    stack.push_back(predecessor);
                }
            }
        }
        if (members.size() > largest.size()) largest.swap(members);
        ++component_id;
    }
    return largest;
}

RoadGraph load_graph(const std::string& path,
                     std::vector<int>& edge_sources,
                     std::vector<int>& edge_targets,
                     std::vector<double>& edge_weights) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("cannot open benchmark graph binary");
    std::uint64_t node_count = 0, edge_count = 0;
    input.read(reinterpret_cast<char*>(&node_count), sizeof(node_count));
    input.read(reinterpret_cast<char*>(&edge_count), sizeof(edge_count));
    if (!input || node_count == 0 || node_count > static_cast<std::uint64_t>(INT32_MAX)) {
        throw std::runtime_error("invalid graph binary header");
    }

    RoadGraph graph;
    graph.outgoing.resize(static_cast<std::size_t>(node_count));
    graph.coordinates.resize(static_cast<std::size_t>(node_count));
    for (Coordinate& coordinate : graph.coordinates) {
        input.read(reinterpret_cast<char*>(&coordinate.lon), sizeof(double));
        input.read(reinterpret_cast<char*>(&coordinate.lat), sizeof(double));
    }
    edge_sources.reserve(static_cast<std::size_t>(edge_count));
    edge_targets.reserve(static_cast<std::size_t>(edge_count));
    edge_weights.reserve(static_cast<std::size_t>(edge_count));
    for (std::uint64_t id = 0; id < edge_count; ++id) {
        EdgeRecord record{};
        input.read(reinterpret_cast<char*>(&record), sizeof(record));
        if (!input || record.source < 0 || record.target < 0 ||
            record.source >= static_cast<std::int32_t>(node_count) ||
            record.target >= static_cast<std::int32_t>(node_count) ||
            !std::isfinite(record.weight) || record.weight < 0.0) {
            throw std::runtime_error("invalid edge record in graph binary");
        }
        graph.outgoing[static_cast<std::size_t>(record.source)].push_back(
            {record.target, record.weight, static_cast<std::int64_t>(id)});
        edge_sources.push_back(record.source);
        edge_targets.push_back(record.target);
        edge_weights.push_back(record.weight);
    }
    if (input.peek() != std::char_traits<char>::eof()) {
        throw std::runtime_error("trailing bytes in graph binary");
    }
    return graph;
}

std::vector<Query> make_queries(const std::vector<int>& component,
                                std::size_t count,
                                std::uint32_t seed) {
    if (component.size() < 2) throw std::runtime_error("largest SCC has fewer than two nodes");
    std::mt19937 generator(seed);
    std::uniform_int_distribution<std::size_t> pick(0, component.size() - 1);
    std::vector<Query> queries;
    queries.reserve(count);
    for (std::size_t i = 0; i < count; ++i) {
        const int source = component[pick(generator)];
        int target = component[pick(generator)];
        while (target == source) target = component[pick(generator)];
        queries.push_back({source, target});
    }
    return queries;
}

void validate_route(const PathResult& route,
                    int source,
                    int target,
                    const std::vector<int>& edge_sources,
                    const std::vector<int>& edge_targets,
                    const std::vector<double>& edge_weights) {
    if (!route.reachable() || route.nodes.empty() || route.nodes.front() != source ||
        route.nodes.back() != target || route.edges.size() + 1 != route.nodes.size()) {
        throw std::runtime_error("algorithm returned an invalid path shape");
    }
    double sum = 0.0;
    for (std::size_t i = 0; i < route.edges.size(); ++i) {
        const std::int64_t edge_id = route.edges[i];
        if (edge_id < 0 || static_cast<std::size_t>(edge_id) >= edge_weights.size()) {
            throw std::runtime_error("route contains an invalid internal edge ID");
        }
        const std::size_t id = static_cast<std::size_t>(edge_id);
        if (edge_sources[id] != route.nodes[i] || edge_targets[id] != route.nodes[i + 1]) {
            throw std::runtime_error("route edge sequence is not directed/contiguous");
        }
        sum += edge_weights[id];
    }
    if (std::abs(sum - route.cost) > 1e-8 * std::max(1.0, std::abs(route.cost))) {
        throw std::runtime_error("route edge-weight sum does not match reported cost");
    }
}

PathResult run_layer(const RoadGraph& graph,
                     const BidirectionalAStarVariantIndex& index,
                     int source,
                     int target,
                     int layer_id,
                     BidirectionalAStarStats& stats) {
    const auto layer = static_cast<BidirectionalAStarLayer>(layer_id);
    return bidirectional_astar_variant(graph, index, source, target, layer,
                                       BidirectionalAStarHeuristic::H0, 0, &stats);
}

} // namespace

int main(int argc, char** argv) {
    try {
        if (argc != 6) {
            std::cerr << "usage: benchmark GRAPH.bin NETWORK RAW.csv QUERIES.csv QUERY_COUNT\n";
            return 2;
        }
        const std::string binary_path = argv[1];
        const std::string network = argv[2];
        const std::string raw_path = argv[3];
        const std::string queries_path = argv[4];
        const std::size_t query_count = static_cast<std::size_t>(std::stoull(argv[5]));
        constexpr int rounds = 5;
        constexpr std::uint32_t query_seed = 20261103;
        constexpr std::array<int, 5> layers = {0, 1, 2, 3, 4};
        const std::array<const char*, 5> layer_names = {
            "L0_RECEIVED", "L1_EARLY_EXIT", "L2_MM", "L3_MM_EPSILON", "L4_BAE_STAR"};

        std::vector<int> edge_sources, edge_targets;
        std::vector<double> edge_weights;
        const auto load_begin = std::chrono::steady_clock::now();
        RoadGraph graph = load_graph(binary_path, edge_sources, edge_targets, edge_weights);
        const auto load_end = std::chrono::steady_clock::now();
        const auto prepare_begin = std::chrono::steady_clock::now();
        BidirectionalAStarVariantIndex index =
            prepare_bidirectional_astar_variants(graph, {}, -1.0);
        const auto prepare_end = std::chrono::steady_clock::now();
        std::vector<int> largest = largest_strong_component(graph, index.base);
        const std::vector<Query> queries = make_queries(largest, query_count, query_seed);

        std::ofstream query_output(queries_path, std::ios::trunc);
        if (!query_output) throw std::runtime_error("cannot create query CSV");
        query_output << "query,source_index,target_index\n";
        for (std::size_t i = 0; i < queries.size(); ++i) {
            query_output << i << ',' << queries[i].source << ',' << queries[i].target << '\n';
        }
        query_output.close();

        std::vector<double> oracle_cost(query_count, ROUTE_INF);
        for (std::size_t qi = 0; qi < query_count; ++qi) {
            BidirectionalAStarStats stats;
            const PathResult route = run_layer(graph, index, queries[qi].source,
                                               queries[qi].target, 0, stats);
            validate_route(route, queries[qi].source, queries[qi].target,
                           edge_sources, edge_targets, edge_weights);
            oracle_cost[qi] = route.cost;
        }

        // Warm every implementation on the same five queries before collecting timings.
        for (int layer : layers) {
            for (std::size_t qi = 0; qi < std::min<std::size_t>(5, query_count); ++qi) {
                BidirectionalAStarStats stats;
                const PathResult route = run_layer(graph, index, queries[qi].source,
                                                   queries[qi].target, layer, stats);
                if (std::abs(route.cost - oracle_cost[qi]) >
                    1e-8 * std::max(1.0, std::abs(oracle_cost[qi]))) {
                    throw std::runtime_error("warm-up result differs from received baseline");
                }
            }
        }

        std::ofstream raw(raw_path, std::ios::trunc);
        if (!raw) throw std::runtime_error("cannot create raw results CSV");
        raw << "network,query,round,layer,elapsed_ns,cost_m,expanded,queue_pushes,"
               "forward_expanded,backward_expanded,scanned_edges,successful_relaxations,"
               "stale_pops,heuristic_evaluations,auxiliary_queue_pushes\n";
        std::mt19937 order_generator(20261103);
        for (int round = 0; round < rounds; ++round) {
            std::vector<std::size_t> query_order(query_count);
            for (std::size_t i = 0; i < query_count; ++i) query_order[i] = i;
            std::shuffle(query_order.begin(), query_order.end(), order_generator);
            for (std::size_t qi : query_order) {
                std::array<int, layers.size()> run_order = layers;
                std::shuffle(run_order.begin(), run_order.end(), order_generator);
                for (int layer : run_order) {
                    BidirectionalAStarStats stats;
                    const auto begin = std::chrono::steady_clock::now();
                    const PathResult route = run_layer(graph, index, queries[qi].source,
                                                       queries[qi].target, layer, stats);
                    const auto end = std::chrono::steady_clock::now();
                    const auto elapsed_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
                        end - begin).count();
                    if (std::abs(route.cost - oracle_cost[qi]) >
                        1e-8 * std::max(1.0, std::abs(oracle_cost[qi]))) {
                        throw std::runtime_error("timed result differs from received baseline");
                    }
                    validate_route(route, queries[qi].source, queries[qi].target,
                                   edge_sources, edge_targets, edge_weights);
                    raw << network << ',' << qi << ',' << round << ',' << layer_names[layer]
                        << ',' << elapsed_ns << ',' << std::setprecision(17) << route.cost
                        << ',' << stats.expanded_states << ',' << stats.queue_pushes
                        << ',';
                    if (layer == 0) {
                        // The received implementation exposes only aggregate expansions
                        // and pushes; keep unavailable counters empty instead of reporting 0.
                        raw << ",,,,,,";
                    } else {
                        raw << stats.forward_expanded << ',' << stats.backward_expanded
                            << ',' << stats.scanned_edges << ',' << stats.successful_relaxations
                            << ',' << stats.stale_pops << ',' << stats.heuristic_evaluations
                            << ',' << stats.auxiliary_queue_pushes;
                    }
                    raw << '\n';
                }
            }
        }
        raw.close();

        const auto load_ms = std::chrono::duration<double, std::milli>(load_end - load_begin).count();
        const auto prepare_ms = std::chrono::duration<double, std::milli>(prepare_end - prepare_begin).count();
        std::cout << network << ": " << graph.size() << " nodes, " << edge_weights.size()
                  << " directed edges; largest SCC=" << largest.size()
                  << "; queries=" << queries.size() << "; rounds=" << rounds
                  << "; load=" << load_ms << " ms; shared index preparation="
                  << prepare_ms << " ms; H0 scale=" << std::setprecision(12)
                  << index.base.heuristic_scale << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "benchmark failed: " << error.what() << '\n';
        return 1;
    }
}
