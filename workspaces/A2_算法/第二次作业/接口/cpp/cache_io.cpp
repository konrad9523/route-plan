#include "cache_io.hpp"

#include <array>
#include <cstdint>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

namespace fs = std::filesystem;

namespace route_benchmark {
namespace {

constexpr std::array<char, 8> MAGIC{{'A', '2', 'I', 'D', 'X', '0', '0', '1'}};
constexpr std::uint32_t VERSION = 1;
constexpr std::uint32_t KIND_ASTAR = 1;
constexpr std::uint32_t KIND_BIDIRECTIONAL = 2;
constexpr std::uint32_t KIND_CH = 3;
constexpr std::uint64_t MAX_ITEMS = 1ULL << 34;

template <typename T>
void write_pod(std::ostream& output, const T& value) {
    static_assert(std::is_trivially_copyable<T>::value, "POD required");
    output.write(reinterpret_cast<const char*>(&value), sizeof(T));
    if (!output) throw std::runtime_error("cannot write cache payload");
}

template <typename T>
T read_pod(std::istream& input) {
    static_assert(std::is_trivially_copyable<T>::value, "POD required");
    T value{};
    input.read(reinterpret_cast<char*>(&value), sizeof(T));
    if (!input) throw std::runtime_error("cache file is truncated");
    return value;
}

void write_size(std::ostream& output, std::size_t size) {
    write_pod(output, static_cast<std::uint64_t>(size));
}

std::size_t read_size(std::istream& input) {
    const auto value = read_pod<std::uint64_t>(input);
    if (value > MAX_ITEMS || value > std::numeric_limits<std::size_t>::max()) {
        throw std::runtime_error("cache item count is invalid");
    }
    return static_cast<std::size_t>(value);
}

void write_header(std::ostream& output, std::uint32_t kind,
                  std::size_t node_count, double preprocess_ms) {
    output.write(MAGIC.data(), static_cast<std::streamsize>(MAGIC.size()));
    write_pod(output, VERSION);
    write_pod(output, kind);
    write_size(output, node_count);
    write_pod(output, preprocess_ms);
}

double read_header(std::istream& input, std::uint32_t expected_kind,
                   std::size_t expected_nodes) {
    std::array<char, MAGIC.size()> magic{};
    input.read(magic.data(), static_cast<std::streamsize>(magic.size()));
    if (!input || magic != MAGIC) throw std::runtime_error("cache magic is invalid");
    if (read_pod<std::uint32_t>(input) != VERSION) {
        throw std::runtime_error("cache version is unsupported");
    }
    if (read_pod<std::uint32_t>(input) != expected_kind) {
        throw std::runtime_error("cache algorithm type is invalid");
    }
    if (read_size(input) != expected_nodes) {
        throw std::runtime_error("cache node count does not match graph");
    }
    return read_pod<double>(input);
}

template <typename Writer>
void atomic_write(const fs::path& path, Writer writer) {
    fs::create_directories(path.parent_path());
    fs::path temporary = path;
    temporary += ".tmp";
    {
        std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
        if (!output) throw std::runtime_error("cannot create cache: " + temporary.string());
        writer(output);
        output.flush();
        if (!output) throw std::runtime_error("cannot finish cache: " + temporary.string());
    }
    std::error_code ignored;
    fs::remove(path, ignored);
    fs::rename(temporary, path);
}

std::ifstream open_cache(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("cannot open cache: " + path.string());
    return input;
}

void write_edge(std::ostream& output, const route_cpp17::Edge& edge) {
    write_pod(output, static_cast<std::int32_t>(edge.to));
    write_pod(output, edge.weight);
    write_pod(output, edge.edge_id);
}

route_cpp17::Edge read_edge(std::istream& input) {
    route_cpp17::Edge edge;
    edge.to = read_pod<std::int32_t>(input);
    edge.weight = read_pod<double>(input);
    edge.edge_id = read_pod<std::int64_t>(input);
    return edge;
}

void write_int_lists(std::ostream& output,
                     const std::vector<std::vector<int>>& lists) {
    write_size(output, lists.size());
    for (const auto& list : lists) {
        write_size(output, list.size());
        for (int value : list) write_pod(output, static_cast<std::int32_t>(value));
    }
}

std::vector<std::vector<int>> read_int_lists(std::istream& input) {
    std::vector<std::vector<int>> result(read_size(input));
    for (auto& list : result) {
        list.resize(read_size(input));
        for (int& value : list) value = read_pod<std::int32_t>(input);
    }
    return result;
}

}  // namespace

void save_astar_cache(const fs::path& path, std::size_t node_count,
                      double heuristic_scale, double preprocess_ms) {
    atomic_write(path, [&](std::ostream& output) {
        write_header(output, KIND_ASTAR, node_count, preprocess_ms);
        write_pod(output, heuristic_scale);
    });
}

CachedAStar load_astar_cache(const fs::path& path,
                             std::size_t expected_node_count) {
    auto input = open_cache(path);
    CachedAStar result;
    result.preprocess_ms = read_header(input, KIND_ASTAR, expected_node_count);
    result.heuristic_scale = read_pod<double>(input);
    return result;
}

void save_bidirectional_cache(
    const fs::path& path, std::size_t node_count,
    const route_cpp17::BidirectionalAStarIndex& index, double preprocess_ms) {
    atomic_write(path, [&](std::ostream& output) {
        write_header(output, KIND_BIDIRECTIONAL, node_count, preprocess_ms);
        write_pod(output, index.heuristic_scale);
        write_size(output, index.incoming.size());
        for (const auto& edges : index.incoming) {
            write_size(output, edges.size());
            for (const auto& edge : edges) write_edge(output, edge);
        }
        write_size(output, index.sphere_points.size());
        for (const auto& point : index.sphere_points) {
            write_pod(output, point.x);
            write_pod(output, point.y);
            write_pod(output, point.z);
        }
    });
}

CachedBidirectionalAStar load_bidirectional_cache(
    const fs::path& path, std::size_t expected_node_count) {
    auto input = open_cache(path);
    CachedBidirectionalAStar result;
    result.preprocess_ms = read_header(input, KIND_BIDIRECTIONAL, expected_node_count);
    result.index.heuristic_scale = read_pod<double>(input);
    result.index.incoming.resize(read_size(input));
    for (auto& edges : result.index.incoming) {
        edges.resize(read_size(input));
        for (auto& edge : edges) edge = read_edge(input);
    }
    result.index.sphere_points.resize(read_size(input));
    for (auto& point : result.index.sphere_points) {
        point.x = read_pod<double>(input);
        point.y = read_pod<double>(input);
        point.z = read_pod<double>(input);
    }
    if (result.index.incoming.size() != expected_node_count ||
        result.index.sphere_points.size() != expected_node_count) {
        throw std::runtime_error("bidirectional cache size is invalid");
    }
    return result;
}

void save_ch_cache(const fs::path& path, std::size_t node_count,
                   const route_cpp17::ContractionHierarchy& index,
                   double preprocess_ms) {
    atomic_write(path, [&](std::ostream& output) {
        write_header(output, KIND_CH, node_count, preprocess_ms);
        write_size(output, index.rank.size());
        for (int value : index.rank) write_pod(output, static_cast<std::int32_t>(value));
        write_size(output, index.arcs.size());
        for (const auto& arc : index.arcs) {
            write_pod(output, static_cast<std::int32_t>(arc.source));
            write_pod(output, static_cast<std::int32_t>(arc.target));
            write_pod(output, arc.weight);
            write_pod(output, arc.original_edge_id);
            write_pod(output, static_cast<std::int32_t>(arc.left));
            write_pod(output, static_cast<std::int32_t>(arc.right));
        }
        write_int_lists(output, index.upward_out);
        write_int_lists(output, index.upward_in);
    });
}

CachedCH load_ch_cache(const fs::path& path,
                       std::size_t expected_node_count) {
    auto input = open_cache(path);
    CachedCH result;
    result.preprocess_ms = read_header(input, KIND_CH, expected_node_count);
    result.index.rank.resize(read_size(input));
    for (int& value : result.index.rank) value = read_pod<std::int32_t>(input);
    result.index.arcs.resize(read_size(input));
    for (auto& arc : result.index.arcs) {
        arc.source = read_pod<std::int32_t>(input);
        arc.target = read_pod<std::int32_t>(input);
        arc.weight = read_pod<double>(input);
        arc.original_edge_id = read_pod<std::int64_t>(input);
        arc.left = read_pod<std::int32_t>(input);
        arc.right = read_pod<std::int32_t>(input);
    }
    result.index.upward_out = read_int_lists(input);
    result.index.upward_in = read_int_lists(input);
    if (result.index.rank.size() != expected_node_count ||
        result.index.upward_out.size() != expected_node_count ||
        result.index.upward_in.size() != expected_node_count) {
        throw std::runtime_error("CH cache size is invalid");
    }
    return result;
}

}  // namespace route_benchmark
