#pragma once

#include "graph_types.hpp"

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace route_benchmark {

struct QueryPair {
    int query_id = 0;
    std::string distance_level;
    int source = -1;
    int target = -1;
    double straight_distance_m = 0.0;
};

std::vector<QueryPair> load_queries(const std::filesystem::path& path);
void save_queries(const std::filesystem::path& path,
                  const std::vector<QueryPair>& queries);
std::vector<QueryPair> generate_queries(
    const route_cpp17::RoadGraph& graph,
    int count,
    std::uint32_t seed);

} // namespace route_benchmark
