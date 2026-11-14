#include "rgraph_io.hpp"

#include <array>
#include <cstdint>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>

namespace route_benchmark {
namespace {

template <class T>
T read_value(std::ifstream& input, const char* field) {
    T value{};
    input.read(reinterpret_cast<char*>(&value), sizeof(T));
    if (!input) throw std::runtime_error(std::string("rgraph truncated at ") + field);
    return value;
}

} // namespace

route_cpp17::RoadGraph load_rgraph(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("cannot open rgraph: " + path.u8string());

    std::array<char, 8> magic{};
    input.read(magic.data(), static_cast<std::streamsize>(magic.size()));
    if (!input || std::string(magic.data(), 7) != "RGRAPH1") {
        throw std::runtime_error("invalid rgraph magic");
    }
    const auto node_count = read_value<std::uint64_t>(input, "node count");
    const auto edge_count = read_value<std::uint64_t>(input, "edge count");
    if (node_count > static_cast<std::uint64_t>(std::numeric_limits<int>::max())) {
        throw std::runtime_error("rgraph has too many nodes for int indices");
    }

    route_cpp17::RoadGraph graph;
    graph.outgoing.resize(static_cast<std::size_t>(node_count));
    graph.coordinates.resize(static_cast<std::size_t>(node_count));
    for (std::size_t i = 0; i < graph.size(); ++i) {
        graph.coordinates[i].lon = read_value<double>(input, "node longitude");
        graph.coordinates[i].lat = read_value<double>(input, "node latitude");
    }

    for (std::uint64_t i = 0; i < edge_count; ++i) {
        const auto source = read_value<std::int32_t>(input, "edge source");
        const auto target = read_value<std::int32_t>(input, "edge target");
        const auto weight = read_value<double>(input, "edge weight");
        const auto edge_id = read_value<std::int64_t>(input, "edge id");
        if (source < 0 || target < 0 ||
            source >= static_cast<std::int32_t>(node_count) ||
            target >= static_cast<std::int32_t>(node_count)) {
            throw std::runtime_error("rgraph edge endpoint is invalid");
        }
        graph.outgoing[static_cast<std::size_t>(source)].push_back(
            {target, weight, edge_id});
    }
    route_cpp17::validate_graph(graph, true);
    return graph;
}

} // namespace route_benchmark
