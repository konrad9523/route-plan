#include "../cpp/bidirectional_astar_variants.hpp"

#include <cassert>
#include <cmath>
#include <iostream>
#include <random>
#include <queue>
#include <stdexcept>
#include <vector>

using route_cpp17::BidirectionalAStarHeuristic;
using route_cpp17::BidirectionalAStarDirectionPolicy;
using route_cpp17::BidirectionalAStarLayer;
using route_cpp17::BidirectionalAStarMeetingPolicy;
using route_cpp17::BidirectionalAStarQueue;
using route_cpp17::BidirectionalAStarStats;
using route_cpp17::RoadGraph;

namespace {

void add_edge(RoadGraph& graph, int source, int target, double weight,
              std::int64_t edge_id) {
    graph.outgoing[static_cast<std::size_t>(source)].push_back(
        {target, weight, edge_id});
}

void assert_expected_path(const route_cpp17::PathResult& result) {
    assert(result.reachable());
    assert((result.nodes == std::vector<int>{0, 1, 2, 3}));
    assert((result.edges == std::vector<std::int64_t>{11, 12, 13}));
    assert(std::abs(result.cost - 2.7) < 1e-10);
}

double reference_dijkstra_cost(const RoadGraph& graph, int start, int goal) {
    std::vector<double> distance(graph.size(), route_cpp17::ROUTE_INF);
    using Item = std::pair<double, int>;
    std::priority_queue<Item, std::vector<Item>, std::greater<Item>> queue;
    distance[static_cast<std::size_t>(start)] = 0.0;
    queue.emplace(0.0, start);
    while (!queue.empty()) {
        const auto [cost, node] = queue.top();
        queue.pop();
        if (cost != distance[static_cast<std::size_t>(node)]) continue;
        if (node == goal) return cost;
        for (const auto& edge : graph.outgoing[static_cast<std::size_t>(node)]) {
            const double candidate = cost + edge.weight;
            double& old = distance[static_cast<std::size_t>(edge.to)];
            if (candidate < old) {
                old = candidate;
                queue.emplace(candidate, edge.to);
            }
        }
    }
    return route_cpp17::ROUTE_INF;
}

RoadGraph make_strongly_connected_graph() {
    RoadGraph graph;
    graph.outgoing.resize(4);
    graph.coordinates = {{0.000, 0.000}, {0.001, 0.000},
                         {0.002, 0.000}, {0.003, 0.000}};
    add_edge(graph, 0, 1, 1.0, 10);
    add_edge(graph, 0, 1, 0.7, 11); // parallel edge; this one is optimal
    add_edge(graph, 1, 2, 1.0, 12);
    add_edge(graph, 2, 3, 1.0, 13);
    add_edge(graph, 0, 3, 10.0, 14);
    add_edge(graph, 3, 2, 2.0, 15);
    add_edge(graph, 2, 1, 2.0, 16);
    add_edge(graph, 1, 0, 2.0, 17);
    add_edge(graph, 3, 0, 2.0, 18);
    return graph;
}

void test_layers_and_heuristics() {
    const RoadGraph graph = make_strongly_connected_graph();
    const auto index = route_cpp17::prepare_bidirectional_astar_variants(
        graph, {0, 2});

    const auto l0 = route_cpp17::bidirectional_astar_variant(
        graph, index, 0, 3, BidirectionalAStarLayer::L0_RECEIVED);
    assert_expected_path(l0);

    BidirectionalAStarStats stats;
    const auto l1 = route_cpp17::bidirectional_astar_variant(
        graph, index, 0, 3, BidirectionalAStarLayer::L1_EARLY_EXIT,
        BidirectionalAStarHeuristic::H0, 0, &stats);
    assert_expected_path(l1);
    assert(stats.expanded_states == l1.expanded);
    assert(stats.forward_expanded + stats.backward_expanded == l1.expanded);
    assert(stats.queue_pushes == l1.queue_pushes);

    const auto alt = route_cpp17::bidirectional_astar_variant(
        graph, index, 0, 3, BidirectionalAStarLayer::L1_EARLY_EXIT,
        BidirectionalAStarHeuristic::ALT, 2);
    assert_expected_path(alt);

    const auto combined = route_cpp17::bidirectional_astar_variant(
        graph, index, 0, 3, BidirectionalAStarLayer::L1_EARLY_EXIT,
        BidirectionalAStarHeuristic::MAX, 2);
    assert_expected_path(combined);

    const auto indexed = route_cpp17::bidirectional_astar_variant(
        graph, index, 0, 3, BidirectionalAStarLayer::L1_EARLY_EXIT,
        BidirectionalAStarHeuristic::H0, 0, nullptr,
        BidirectionalAStarQueue::INDEXED_BINARY_HEAP);
    assert_expected_path(indexed);

    const auto alternating = route_cpp17::bidirectional_astar_variant(
        graph, index, 0, 3, BidirectionalAStarLayer::L1_EARLY_EXIT,
        BidirectionalAStarHeuristic::H0, 0, nullptr,
        BidirectionalAStarQueue::LAZY_DUPLICATES,
        BidirectionalAStarDirectionPolicy::ALTERNATE,
        BidirectionalAStarMeetingPolicy::UPDATE_ON_RELAX_AND_POP);
    assert_expected_path(alternating);

    const auto bae_min_key = route_cpp17::bidirectional_astar_variant(
        graph, index, 0, 3, BidirectionalAStarLayer::L4_BAE_STAR,
        BidirectionalAStarHeuristic::H0, 0, nullptr,
        BidirectionalAStarQueue::LAZY_DUPLICATES,
        BidirectionalAStarDirectionPolicy::MIN_REDUCED_KEY,
        BidirectionalAStarMeetingPolicy::UPDATE_ON_RELAX_AND_POP, true);
    assert_expected_path(bae_min_key);

    const auto same_node = route_cpp17::bidirectional_astar_variant(
        graph, index, 2, 2, BidirectionalAStarLayer::L1_EARLY_EXIT);
    assert(same_node.reachable());
    assert(same_node.cost == 0.0);
    assert((same_node.nodes == std::vector<int>{2}));

    for (const auto layer : {BidirectionalAStarLayer::L2_MM,
                             BidirectionalAStarLayer::L3_MM_EPSILON,
                             BidirectionalAStarLayer::L4_BAE_STAR,
                             BidirectionalAStarLayer::L5_BAE_F_BOUND}) {
        for (const auto heuristic : {BidirectionalAStarHeuristic::H0,
                                     BidirectionalAStarHeuristic::ALT,
                                     BidirectionalAStarHeuristic::MAX}) {
            const std::size_t landmarks =
                heuristic == BidirectionalAStarHeuristic::H0 ? 0 : 2;
            const auto result = route_cpp17::bidirectional_astar_variant(
                graph, index, 0, 3, layer, heuristic, landmarks);
            assert_expected_path(result);
        }
    }
}

void test_unreachable_and_alt_component_guard() {
    RoadGraph graph;
    graph.outgoing.resize(3);
    graph.coordinates = {{0.0, 0.0}, {0.001, 0.0}, {0.010, 0.0}};
    add_edge(graph, 0, 1, 1.0, 1);
    add_edge(graph, 1, 0, 1.0, 2);

    const auto geometry_index = route_cpp17::prepare_bidirectional_astar_variants(graph);
    const auto unreachable = route_cpp17::bidirectional_astar_variant(
        graph, geometry_index, 0, 2, BidirectionalAStarLayer::L1_EARLY_EXIT);
    assert(!unreachable.reachable());
    assert(unreachable.nodes.empty());

    for (const auto layer : {BidirectionalAStarLayer::L2_MM,
                             BidirectionalAStarLayer::L3_MM_EPSILON,
                             BidirectionalAStarLayer::L4_BAE_STAR,
                             BidirectionalAStarLayer::L5_BAE_F_BOUND}) {
        const auto result = route_cpp17::bidirectional_astar_variant(
            graph, geometry_index, 0, 2, layer);
        assert(!result.reachable());
        assert(result.nodes.empty());
    }

    const auto alt_index = route_cpp17::prepare_bidirectional_astar_variants(
        graph, {0});
    bool rejected_cross_component_query = false;
    try {
        (void)route_cpp17::bidirectional_astar_variant(
            graph, alt_index, 0, 2, BidirectionalAStarLayer::L1_EARLY_EXIT,
            BidirectionalAStarHeuristic::ALT, 1);
    } catch (const std::invalid_argument&) {
        rejected_cross_component_query = true;
    }
    assert(rejected_cross_component_query);
}

void test_early_exit_after_frontier_exhaustion() {
    RoadGraph graph;
    graph.outgoing.resize(6);
    graph.coordinates = {{0.0, 0.0},   {0.001, 0.0}, {0.002, 0.0},
                         {0.003, 0.0}, {0.004, 0.0}, {0.005, 0.0}};
    add_edge(graph, 0, 2, 1.0, 20);
    add_edge(graph, 2, 3, 1.0, 21);
    add_edge(graph, 3, 4, 1.0, 22);
    add_edge(graph, 4, 5, 1.0, 23);
    const auto index = route_cpp17::prepare_bidirectional_astar_variants(
        graph, {}, 0.0);

    const auto l0 = route_cpp17::bidirectional_astar_variant(
        graph, index, 0, 1, BidirectionalAStarLayer::L0_RECEIVED);
    const auto l1 = route_cpp17::bidirectional_astar_variant(
        graph, index, 0, 1, BidirectionalAStarLayer::L1_EARLY_EXIT);
    assert(!l0.reachable() && !l1.reachable());
    assert(l1.expanded < l0.expanded);
}

void test_research_layers_against_dijkstra() {
    std::mt19937 generator(20261103);
    std::uniform_real_distribution<double> weight(0.25, 20.0);
    std::bernoulli_distribution include_edge(0.28);
    const std::vector<BidirectionalAStarLayer> layers = {
        BidirectionalAStarLayer::L0_RECEIVED,
        BidirectionalAStarLayer::L1_EARLY_EXIT,
        BidirectionalAStarLayer::L2_MM,
        BidirectionalAStarLayer::L3_MM_EPSILON,
        BidirectionalAStarLayer::L4_BAE_STAR,
        BidirectionalAStarLayer::L5_BAE_F_BOUND,
    };

    for (int graph_id = 0; graph_id < 20; ++graph_id) {
        RoadGraph graph;
        constexpr int node_count = 9;
        graph.outgoing.resize(node_count);
        for (int node = 0; node < node_count; ++node) {
            graph.coordinates.push_back({0.001 * node, 0.0003 * (node % 3)});
        }
        std::int64_t edge_id = 0;
        for (int source = 0; source < node_count; ++source) {
            for (int target = 0; target < node_count; ++target) {
                if (source != target && include_edge(generator)) {
                    add_edge(graph, source, target, weight(generator), edge_id++);
                }
            }
        }
        const auto index = route_cpp17::prepare_bidirectional_astar_variants(graph);
        for (int start = 0; start < node_count; ++start) {
            for (int goal = 0; goal < node_count; ++goal) {
                const double reference = reference_dijkstra_cost(graph, start, goal);
                for (const auto layer : layers) {
                    const auto result = route_cpp17::bidirectional_astar_variant(
                        graph, index, start, goal, layer);
                    assert(result.reachable() == std::isfinite(reference));
                    if (std::isfinite(reference)) {
                        if (std::abs(result.cost - reference) >
                            1e-8 * std::max(1.0, reference)) {
                            std::cerr << "cost mismatch graph=" << graph_id
                                      << " start=" << start << " goal=" << goal
                                      << " layer=" << static_cast<int>(layer)
                                      << " got=" << result.cost
                                      << " expected=" << reference << '\n';
                            assert(false);
                        }
                    }
                }
                const auto indexed = route_cpp17::bidirectional_astar_variant(
                    graph, index, start, goal,
                    BidirectionalAStarLayer::L1_EARLY_EXIT,
                    BidirectionalAStarHeuristic::H0, 0, nullptr,
                    BidirectionalAStarQueue::INDEXED_BINARY_HEAP);
                assert(indexed.reachable() == std::isfinite(reference));
                if (std::isfinite(reference)) {
                    assert(std::abs(indexed.cost - reference) <=
                           1e-8 * std::max(1.0, reference));
                }
            }
        }
    }
}

} // namespace

int main() {
    test_layers_and_heuristics();
    test_unreachable_and_alt_component_guard();
    test_early_exit_after_frontier_exhaustion();
    test_research_layers_against_dijkstra();
}
