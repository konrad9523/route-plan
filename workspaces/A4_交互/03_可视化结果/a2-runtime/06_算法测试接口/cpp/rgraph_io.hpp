#pragma once

#include "graph_types.hpp"

#include <filesystem>

namespace route_benchmark {

route_cpp17::RoadGraph load_rgraph(const std::filesystem::path& path);

} // namespace route_benchmark
