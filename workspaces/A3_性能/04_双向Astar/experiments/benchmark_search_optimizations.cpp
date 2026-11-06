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
#include <sstream>
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

struct Query { int source; int target; };

struct Config {
    std::string name;
    BidirectionalAStarLayer layer;
    BidirectionalAStarHeuristic heuristic;
    std::size_t landmarks;
    BidirectionalAStarQueue queue;
    BidirectionalAStarDirectionPolicy direction =
        BidirectionalAStarDirectionPolicy::NATIVE;
    BidirectionalAStarMeetingPolicy meeting =
        BidirectionalAStarMeetingPolicy::NATIVE;
    bool strict_lower_bound = false;
};

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

std::vector<int> largest_strong_component(const RoadGraph& graph) {
    const int n = static_cast<int>(graph.size());
    std::vector<std::vector<int>> incoming(static_cast<std::size_t>(n));
    for (int source = 0; source < n; ++source) {
        for (const Edge& edge : graph.outgoing[static_cast<std::size_t>(source)]) {
            incoming[static_cast<std::size_t>(edge.to)].push_back(source);
        }
    }

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

    std::fill(visited.begin(), visited.end(), false);
    std::vector<int> stack;
    std::vector<int> largest;
    for (auto it = finish_order.rbegin(); it != finish_order.rend(); ++it) {
        if (visited[static_cast<std::size_t>(*it)]) continue;
        std::vector<int> members;
        visited[static_cast<std::size_t>(*it)] = true;
        stack.push_back(*it);
        while (!stack.empty()) {
            const int node = stack.back();
            stack.pop_back();
            members.push_back(node);
            for (const int predecessor : incoming[static_cast<std::size_t>(node)]) {
                if (!visited[static_cast<std::size_t>(predecessor)]) {
                    visited[static_cast<std::size_t>(predecessor)] = true;
                    stack.push_back(predecessor);
                }
            }
        }
        if (members.size() > largest.size()) largest.swap(members);
    }
    return largest;
}

std::vector<int> select_landmarks(const RoadGraph& graph,
                                 const std::vector<int>& component,
                                 std::size_t count) {
    if (component.size() < count) throw std::runtime_error("SCC is too small for ALT");
    double mean_lat = 0.0;
    for (const int node : component) {
        mean_lat += graph.coordinates[static_cast<std::size_t>(node)].lat;
    }
    mean_lat /= static_cast<double>(component.size());
    constexpr double degrees_to_radians = 3.14159265358979323846 / 180.0;
    const double lon_scale = std::cos(mean_lat * degrees_to_radians);
    auto point = [&](int node) {
        const Coordinate& coordinate = graph.coordinates[static_cast<std::size_t>(node)];
        return std::pair<double, double>{coordinate.lon * lon_scale, coordinate.lat};
    };

    int first = component.front();
    for (const int node : component) {
        const Coordinate& candidate = graph.coordinates[static_cast<std::size_t>(node)];
        const Coordinate& current = graph.coordinates[static_cast<std::size_t>(first)];
        if (candidate.lon < current.lon ||
            (candidate.lon == current.lon && candidate.lat < current.lat) ||
            (candidate.lon == current.lon && candidate.lat == current.lat && node < first)) {
            first = node;
        }
    }

    std::vector<int> selected;
    selected.reserve(count);
    std::vector<char> chosen(graph.size(), false);
    std::vector<double> nearest_squared(graph.size(),
                                        std::numeric_limits<double>::infinity());
    int current = first;
    for (std::size_t rank = 0; rank < count; ++rank) {
        selected.push_back(current);
        chosen[static_cast<std::size_t>(current)] = true;
        const auto [x, y] = point(current);
        for (const int node : component) {
            const auto [candidate_x, candidate_y] = point(node);
            const double dx = candidate_x - x;
            const double dy = candidate_y - y;
            double& nearest = nearest_squared[static_cast<std::size_t>(node)];
            nearest = std::min(nearest, dx * dx + dy * dy);
        }
        if (rank + 1 == count) break;
        double farthest = -1.0;
        int next = -1;
        for (const int node : component) {
            if (chosen[static_cast<std::size_t>(node)]) continue;
            const double distance = nearest_squared[static_cast<std::size_t>(node)];
            if (distance > farthest || (distance == farthest && (next < 0 || node < next))) {
                farthest = distance;
                next = node;
            }
        }
        current = next;
    }
    return selected;
}

std::vector<Query> read_queries(const std::string& path) {
    std::ifstream input(path);
    if (!input) throw std::runtime_error("cannot open fixed query CSV");
    std::string line;
    if (!std::getline(input, line)) throw std::runtime_error("query CSV is empty");
    std::vector<Query> queries;
    while (std::getline(input, line)) {
        if (line.empty()) continue;
        std::istringstream row(line);
        std::string query_id, source, target;
        if (!std::getline(row, query_id, ',') || !std::getline(row, source, ',') ||
            !std::getline(row, target, ',')) {
            throw std::runtime_error("malformed fixed query CSV row");
        }
        queries.push_back({std::stoi(source), std::stoi(target)});
    }
    if (queries.empty()) throw std::runtime_error("fixed query CSV has no queries");
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

PathResult run_config(const RoadGraph& graph,
                      const BidirectionalAStarVariantIndex& index,
                      const Config& config,
                      const Query& query,
                      BidirectionalAStarStats& stats) {
    return bidirectional_astar_variant(
        graph, index, query.source, query.target, config.layer, config.heuristic,
        config.landmarks, &stats, config.queue, config.direction, config.meeting,
        config.strict_lower_bound);
}

std::vector<Config> make_configs() {
    using L = BidirectionalAStarLayer;
    using H = BidirectionalAStarHeuristic;
    using Q = BidirectionalAStarQueue;
    std::vector<Config> configs = {
        {"L1_H0_LAZY", L::L1_EARLY_EXIT, H::H0, 0, Q::LAZY_DUPLICATES},
        {"L1_ALT4_LAZY", L::L1_EARLY_EXIT, H::ALT, 4, Q::LAZY_DUPLICATES},
        {"L1_ALT8_LAZY", L::L1_EARLY_EXIT, H::ALT, 8, Q::LAZY_DUPLICATES},
        {"L1_ALT16_LAZY", L::L1_EARLY_EXIT, H::ALT, 16, Q::LAZY_DUPLICATES},
        {"L1_MAX4_LAZY", L::L1_EARLY_EXIT, H::MAX, 4, Q::LAZY_DUPLICATES},
        {"L1_MAX8_LAZY", L::L1_EARLY_EXIT, H::MAX, 8, Q::LAZY_DUPLICATES},
        {"L1_MAX16_LAZY", L::L1_EARLY_EXIT, H::MAX, 16, Q::LAZY_DUPLICATES},
        {"L1_H0_INDEXED", L::L1_EARLY_EXIT, H::H0, 0, Q::INDEXED_BINARY_HEAP},
        {"L1_ALT16_INDEXED", L::L1_EARLY_EXIT, H::ALT, 16, Q::INDEXED_BINARY_HEAP},
        {"L1_MAX16_INDEXED", L::L1_EARLY_EXIT, H::MAX, 16, Q::INDEXED_BINARY_HEAP},
        {"L4_H0_LAZY", L::L4_BAE_STAR, H::H0, 0, Q::LAZY_DUPLICATES},
        {"L4_ALT4_LAZY", L::L4_BAE_STAR, H::ALT, 4, Q::LAZY_DUPLICATES},
        {"L4_ALT8_LAZY", L::L4_BAE_STAR, H::ALT, 8, Q::LAZY_DUPLICATES},
        {"L4_ALT16_LAZY", L::L4_BAE_STAR, H::ALT, 16, Q::LAZY_DUPLICATES},
        {"L4_MAX4_LAZY", L::L4_BAE_STAR, H::MAX, 4, Q::LAZY_DUPLICATES},
        {"L4_MAX8_LAZY", L::L4_BAE_STAR, H::MAX, 8, Q::LAZY_DUPLICATES},
        {"L4_MAX16_LAZY", L::L4_BAE_STAR, H::MAX, 16, Q::LAZY_DUPLICATES},
        {"L5_H0_LAZY", L::L5_BAE_F_BOUND, H::H0, 0, Q::LAZY_DUPLICATES},
        {"L5_ALT16_LAZY", L::L5_BAE_F_BOUND, H::ALT, 16, Q::LAZY_DUPLICATES},
        {"L5_MAX16_LAZY", L::L5_BAE_F_BOUND, H::MAX, 16, Q::LAZY_DUPLICATES},
    };
    return configs;
}

std::vector<Config> make_best_heuristic_layer_configs() {
    using L = BidirectionalAStarLayer;
    using H = BidirectionalAStarHeuristic;
    using Q = BidirectionalAStarQueue;
    return {
        {"L0_H0_RECEIVED", L::L0_RECEIVED, H::H0, 0, Q::LAZY_DUPLICATES},
        {"L1_MAX8", L::L1_EARLY_EXIT, H::MAX, 8, Q::LAZY_DUPLICATES},
        {"L2_MAX8", L::L2_MM, H::MAX, 8, Q::LAZY_DUPLICATES},
        {"L3_MAX8", L::L3_MM_EPSILON, H::MAX, 8, Q::LAZY_DUPLICATES},
        {"L4_MAX8", L::L4_BAE_STAR, H::MAX, 8, Q::LAZY_DUPLICATES},
        {"L5_MAX8", L::L5_BAE_F_BOUND, H::MAX, 8, Q::LAZY_DUPLICATES},
    };
}

std::vector<Config> make_control_configs() {
    using D = BidirectionalAStarDirectionPolicy;
    using H = BidirectionalAStarHeuristic;
    using L = BidirectionalAStarLayer;
    using M = BidirectionalAStarMeetingPolicy;
    using Q = BidirectionalAStarQueue;
    return {
        {"L0_RECEIVED", L::L0_RECEIVED, H::H0, 0, Q::LAZY_DUPLICATES},
        {"L1_MIN_RELAX", L::L1_EARLY_EXIT, H::H0, 0, Q::LAZY_DUPLICATES,
         D::MIN_REDUCED_KEY, M::NATIVE},
        {"L1_MIN_RELAX_POP", L::L1_EARLY_EXIT, H::H0, 0, Q::LAZY_DUPLICATES,
         D::MIN_REDUCED_KEY, M::UPDATE_ON_RELAX_AND_POP},
        {"L1_ALT_RELAX_POP", L::L1_EARLY_EXIT, H::H0, 0, Q::LAZY_DUPLICATES,
         D::ALTERNATE, M::UPDATE_ON_RELAX_AND_POP},
        {"L4_ALT_NATIVE", L::L4_BAE_STAR, H::H0, 0, Q::LAZY_DUPLICATES},
        {"L4_ALT_STRICT", L::L4_BAE_STAR, H::H0, 0, Q::LAZY_DUPLICATES,
         D::ALTERNATE, M::UPDATE_ON_RELAX_AND_POP, true},
        {"L4_MIN_STRICT", L::L4_BAE_STAR, H::H0, 0, Q::LAZY_DUPLICATES,
         D::MIN_REDUCED_KEY, M::UPDATE_ON_RELAX_AND_POP, true},
    };
}

} // namespace

int main(int argc, char** argv) {
    try {
        if (argc != 7 && argc != 8) {
            std::cerr << "usage: benchmark_search GRAPH.bin NETWORK RAW.csv QUERIES.csv PREPROCESS.csv LANDMARKS.csv [controls|layers]\n";
            return 2;
        }
        const std::string mode = argc == 8 ? argv[7] : "heuristics";
        const bool controls = mode == "controls";
        const bool layer_sweep = mode == "layers";
        if (mode != "heuristics" && !controls && !layer_sweep) {
            throw std::invalid_argument("supported modes are heuristics, controls, and layers");
        }
        const std::string binary_path = argv[1];
        const std::string network = argv[2];
        const std::string raw_path = argv[3];
        const std::string queries_path = argv[4];
        const std::string preprocess_path = argv[5];
        const std::string landmarks_path = argv[6];
        constexpr int rounds = 5;
        constexpr std::uint32_t order_seed = 20261103;
        constexpr std::size_t max_landmarks = 16;

        std::vector<int> edge_sources, edge_targets;
        std::vector<double> edge_weights;
        const auto load_begin = std::chrono::steady_clock::now();
        RoadGraph graph = load_graph(binary_path, edge_sources, edge_targets, edge_weights);
        const auto load_end = std::chrono::steady_clock::now();
        std::vector<int> component = largest_strong_component(graph);
        const std::vector<int> landmarks = controls
            ? std::vector<int>{}
            : select_landmarks(graph, component, max_landmarks);
        std::vector<char> in_component(graph.size(), false);
        for (const int node : component) in_component[static_cast<std::size_t>(node)] = true;
        const std::vector<Query> queries = read_queries(queries_path);
        for (const Query& query : queries) {
            if (query.source < 0 || query.target < 0 ||
                static_cast<std::size_t>(query.source) >= graph.size() ||
                static_cast<std::size_t>(query.target) >= graph.size() ||
                !in_component[static_cast<std::size_t>(query.source)] ||
                !in_component[static_cast<std::size_t>(query.target)]) {
                throw std::runtime_error("fixed query endpoint is outside the largest SCC");
            }
        }

        const auto prepare_begin = std::chrono::steady_clock::now();
        const BidirectionalAStarVariantIndex index =
            prepare_bidirectional_astar_variants(graph, landmarks, -1.0);
        const auto prepare_end = std::chrono::steady_clock::now();

        std::ofstream landmark_output(landmarks_path, std::ios::trunc);
        if (!landmark_output) throw std::runtime_error("cannot create landmarks CSV");
        landmark_output << "network,rank,node_index,longitude,latitude\n" << std::setprecision(12);
        for (std::size_t i = 0; i < landmarks.size(); ++i) {
            const Coordinate& coordinate = graph.coordinates[static_cast<std::size_t>(landmarks[i])];
            landmark_output << network << ',' << (i + 1) << ',' << landmarks[i] << ','
                            << coordinate.lon << ',' << coordinate.lat << '\n';
        }

        std::ofstream preprocess(preprocess_path, std::ios::trunc);
        if (!preprocess) throw std::runtime_error("cannot create preprocessing CSV");
        const double total_prepare_ms = std::chrono::duration<double, std::milli>(
            prepare_end - prepare_begin).count();
        if (controls) {
            preprocess << "network,nodes,directed_edges,largest_scc,queries,index_prep_ms\n"
                       << network << ',' << graph.size() << ',' << edge_weights.size() << ','
                       << component.size() << ',' << queries.size() << ','
                       << std::fixed << std::setprecision(3) << total_prepare_ms << '\n';
        } else {
            preprocess << "network,nodes,directed_edges,largest_scc,queries,total_index_and_ALT_prep_ms,"
                          "ALT_prefix_landmarks,ALT_prefix_prep_ms,ALT_table_bytes\n";
            for (const std::size_t count : {std::size_t{4}, std::size_t{8}, std::size_t{16}}) {
                preprocess << network << ',' << graph.size() << ',' << edge_weights.size() << ','
                           << component.size() << ',' << queries.size() << ','
                           << std::fixed << std::setprecision(3) << total_prepare_ms << ','
                           << count << ','
                           << static_cast<double>(index.alt_preprocess_ns_by_landmark[count - 1]) /
                                  1'000'000.0 << ','
                           << (2ULL * count * graph.size() * sizeof(double)) << '\n';
            }
        }

        std::vector<double> oracle_cost(queries.size(), ROUTE_INF);
        for (std::size_t qi = 0; qi < queries.size(); ++qi) {
            const PathResult reference = bidirectional_astar(
                graph, index.base, queries[qi].source, queries[qi].target);
            validate_route(reference, queries[qi].source, queries[qi].target,
                           edge_sources, edge_targets, edge_weights);
            oracle_cost[qi] = reference.cost;
        }

        const std::vector<Config> configs = controls
            ? make_control_configs()
            : (layer_sweep ? make_best_heuristic_layer_configs() : make_configs());
        for (const Config& config : configs) {
            for (std::size_t qi = 0; qi < std::min<std::size_t>(5, queries.size()); ++qi) {
                BidirectionalAStarStats stats;
                const PathResult route = run_config(graph, index, config, queries[qi], stats);
                if (std::abs(route.cost - oracle_cost[qi]) >
                    1e-8 * std::max(1.0, std::abs(oracle_cost[qi]))) {
                    throw std::runtime_error("warm-up path cost differs from H0 reference");
                }
            }
        }

        std::ofstream raw(raw_path, std::ios::trunc);
        if (!raw) throw std::runtime_error("cannot create raw results CSV");
        raw << "network,query,round,config,elapsed_ns,cost_m,expanded,queue_pushes,best_updates,"
               "queue_decreases,peak_open_entries,forward_expanded,backward_expanded,"
               "scanned_edges,successful_relaxations,stale_pops,heuristic_evaluations,"
               "auxiliary_queue_pushes\n";
        std::mt19937 order_generator(order_seed);
        for (int round = 0; round < rounds; ++round) {
            std::vector<std::size_t> query_order(queries.size());
            for (std::size_t i = 0; i < queries.size(); ++i) query_order[i] = i;
            std::shuffle(query_order.begin(), query_order.end(), order_generator);
            for (const std::size_t qi : query_order) {
                std::vector<std::size_t> config_order(configs.size());
                for (std::size_t i = 0; i < configs.size(); ++i) config_order[i] = i;
                std::shuffle(config_order.begin(), config_order.end(), order_generator);
                for (const std::size_t ci : config_order) {
                    const Config& config = configs[ci];
                    BidirectionalAStarStats stats;
                    const auto begin = std::chrono::steady_clock::now();
                    const PathResult route = run_config(graph, index, config, queries[qi], stats);
                    const auto end = std::chrono::steady_clock::now();
                    const auto elapsed_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
                        end - begin).count();
                    if (std::abs(route.cost - oracle_cost[qi]) >
                        1e-8 * std::max(1.0, std::abs(oracle_cost[qi]))) {
                        throw std::runtime_error("timed path cost differs from H0 reference");
                    }
                    validate_route(route, queries[qi].source, queries[qi].target,
                                   edge_sources, edge_targets, edge_weights);
                    raw << network << ',' << qi << ',' << round << ',' << config.name << ','
                        << elapsed_ns << ',' << std::setprecision(17) << route.cost << ','
                        << stats.expanded_states << ',' << stats.queue_pushes << ','
                        << stats.best_updates << ','
                        << stats.queue_decreases << ',' << stats.peak_open_entries << ','
                        << stats.forward_expanded << ',' << stats.backward_expanded << ','
                        << stats.scanned_edges << ',' << stats.successful_relaxations << ','
                        << stats.stale_pops << ',' << stats.heuristic_evaluations << ','
                        << stats.auxiliary_queue_pushes << '\n';
                }
            }
        }

        const double load_ms = std::chrono::duration<double, std::milli>(load_end - load_begin).count();
        const double prepare_ms = std::chrono::duration<double, std::milli>(prepare_end - prepare_begin).count();
        std::cout << network << ": " << graph.size() << " nodes, " << edge_weights.size()
                  << " directed edges; largest SCC=" << component.size()
                  << "; queries=" << queries.size() << "; rounds=" << rounds
                  << "; load=" << std::fixed << std::setprecision(1) << load_ms
                  << " ms; graph+ALT prep=" << prepare_ms << " ms; ALT(16)="
                  << static_cast<double>(index.alt_preprocess_ns) / 1'000'000.0 << " ms\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "search optimization benchmark failed: " << error.what() << '\n';
        return 1;
    }
}
