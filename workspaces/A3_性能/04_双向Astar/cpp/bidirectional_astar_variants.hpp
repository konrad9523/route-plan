#pragma once

#include "algorithms.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace route_cpp17 {

enum class BidirectionalAStarLayer : int {
    L0_RECEIVED = 0,
    L1_EARLY_EXIT = 1,
    L2_MM = 2,
    L3_MM_EPSILON = 3,
    L4_BAE_STAR = 4,
    // BAE* expansion order with a compound admissible termination bound.
    L5_BAE_F_BOUND = 5,
};

enum class BidirectionalAStarHeuristic : int {
    H0 = 0,
    ALT = 1,
    MAX = 2,
};

enum class BidirectionalAStarQueue : int {
    LAZY_DUPLICATES = 0,
    INDEXED_BINARY_HEAP = 1,
};

enum class BidirectionalAStarDirectionPolicy : int {
    NATIVE = 0,
    ALTERNATE = 1,
    MIN_REDUCED_KEY = 2,
};

enum class BidirectionalAStarMeetingPolicy : int {
    NATIVE = 0,
    UPDATE_ON_RELAX_AND_POP = 1,
};

struct BidirectionalAStarVariantIndex {
    BidirectionalAStarIndex base;
    std::vector<int> component_of_node;
    std::vector<int> landmarks;
    // Row-major [landmark][node]. from_landmark stores d(L,node);
    // to_landmark stores d(node,L) on the original directed graph.
    std::vector<double> from_landmark;
    std::vector<double> to_landmark;
    int landmark_component = -1;
    std::uint64_t alt_preprocess_ns = 0;
    // Cumulative ALT preprocessing time after each landmark prefix.
    std::vector<std::uint64_t> alt_preprocess_ns_by_landmark;
    double minimum_edge_weight = 0.0;
    // Cheapest edge available from a node in each search direction.
    std::vector<double> minimum_outgoing_weight;
    std::vector<double> minimum_incoming_weight;
};

struct BidirectionalAStarStats {
    std::size_t expanded_states = 0;
    std::size_t forward_expanded = 0;
    std::size_t backward_expanded = 0;
    std::size_t scanned_edges = 0;
    std::size_t successful_relaxations = 0;
    std::size_t queue_pushes = 0;
    std::size_t stale_pops = 0;
    std::size_t heuristic_evaluations = 0;
    std::size_t best_updates = 0;
    // MM maintains min-f/min-g heaps; L5 maintains min-f heaps for termination.
    std::size_t auxiliary_queue_pushes = 0;
    std::size_t queue_decreases = 0;
    std::size_t peak_open_entries = 0;
};

BidirectionalAStarVariantIndex prepare_bidirectional_astar_variants(
    const RoadGraph& graph,
    const std::vector<int>& landmark_ids = {},
    double heuristic_scale = -1.0);

// Pass the same, unchanged graph used to build index.
PathResult bidirectional_astar_variant(
    const RoadGraph& graph,
    const BidirectionalAStarVariantIndex& index,
    int start,
    int goal,
    BidirectionalAStarLayer layer = BidirectionalAStarLayer::L1_EARLY_EXIT,
    BidirectionalAStarHeuristic heuristic = BidirectionalAStarHeuristic::H0,
    std::size_t landmark_count = 0,
    BidirectionalAStarStats* stats = nullptr,
    BidirectionalAStarQueue queue = BidirectionalAStarQueue::LAZY_DUPLICATES,
    BidirectionalAStarDirectionPolicy direction_policy =
        BidirectionalAStarDirectionPolicy::NATIVE,
    BidirectionalAStarMeetingPolicy meeting_policy =
        BidirectionalAStarMeetingPolicy::NATIVE,
    bool strict_lower_bound = false);

} // namespace route_cpp17
