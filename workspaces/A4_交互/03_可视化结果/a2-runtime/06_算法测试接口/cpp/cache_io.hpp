#pragma once

#include "algorithms.hpp"

#include <cstddef>
#include <filesystem>

namespace route_benchmark {

struct CachedAStar {
    double heuristic_scale = 0.0;
    double preprocess_ms = 0.0;
};

struct CachedBidirectionalAStar {
    route_cpp17::BidirectionalAStarIndex index;
    double preprocess_ms = 0.0;
};

struct CachedCH {
    route_cpp17::ContractionHierarchy index;
    double preprocess_ms = 0.0;
};

void save_astar_cache(const std::filesystem::path& path,
                      std::size_t node_count,
                      double heuristic_scale,
                      double preprocess_ms);
CachedAStar load_astar_cache(const std::filesystem::path& path,
                             std::size_t expected_node_count);

void save_bidirectional_cache(
    const std::filesystem::path& path,
    std::size_t node_count,
    const route_cpp17::BidirectionalAStarIndex& index,
    double preprocess_ms);
CachedBidirectionalAStar load_bidirectional_cache(
    const std::filesystem::path& path,
    std::size_t expected_node_count);

void save_ch_cache(const std::filesystem::path& path,
                   std::size_t node_count,
                   const route_cpp17::ContractionHierarchy& index,
                   double preprocess_ms);
CachedCH load_ch_cache(const std::filesystem::path& path,
                       std::size_t expected_node_count);

}  // namespace route_benchmark
