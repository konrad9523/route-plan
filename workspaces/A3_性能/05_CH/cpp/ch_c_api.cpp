#include "algorithms.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <limits>
#include <memory>
#include <string>
#include <vector>

#if defined(_WIN32)
#define CH_API extern "C" __declspec(dllexport)
#else
#define CH_API extern "C" __attribute__((visibility("default")))
#endif

namespace {

enum Status : int32_t {
    OK = 0,
    INVALID_ARGUMENT = 1,
    INVALID_GRAPH = 2,
    INVALID_QUERY = 3,
    BUFFER_TOO_SMALL = 4,
    INTERNAL_ERROR = 5,
};

struct CHHandle {
    route_cpp17::ContractionHierarchy hierarchy;
    std::size_t shortcut_count = 0;
};

constexpr std::array<char, 8> kCacheMagic = {'A', '3', 'C', 'H', 'I', 'D', 'X', '1'};
constexpr std::uint32_t kCacheVersion = 1;

template <typename T>
bool write_scalar(std::ostream& stream, const T& value) {
    stream.write(reinterpret_cast<const char*>(&value), sizeof(T));
    return static_cast<bool>(stream);
}

template <typename T>
bool read_scalar(std::istream& stream, T& value) {
    stream.read(reinterpret_cast<char*>(&value), sizeof(T));
    return static_cast<bool>(stream);
}

bool save_cache(const std::filesystem::path& path, const std::string& key,
                const CHHandle& handle, std::size_t original_edge_count) {
    if (key.size() != 64) return false;
    const auto& hierarchy = handle.hierarchy;
    const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto temporary = path.string() + "." + std::to_string(nonce) + ".tmp";
    std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
    if (!output) return false;

    output.write(kCacheMagic.data(), static_cast<std::streamsize>(kCacheMagic.size()));
    const auto write_size = [&](std::size_t value) {
        return write_scalar(output, static_cast<std::uint64_t>(value));
    };
    if (!write_scalar(output, kCacheVersion) ||
        !write_size(hierarchy.rank.size()) ||
        !write_size(original_edge_count) ||
        !write_size(hierarchy.arcs.size()) ||
        !write_size(hierarchy.upward_out_offsets.size()) ||
        !write_size(hierarchy.upward_out_arcs.size()) ||
        !write_size(hierarchy.upward_in_offsets.size()) ||
        !write_size(hierarchy.upward_in_arcs.size()) ||
        !write_size(handle.shortcut_count)) {
        output.close();
        std::filesystem::remove(temporary);
        return false;
    }
    output.write(key.data(), static_cast<std::streamsize>(key.size()));
    for (const int rank : hierarchy.rank) {
        if (!write_scalar(output, static_cast<std::int32_t>(rank))) break;
    }
    for (const auto& arc : hierarchy.arcs) {
        if (!write_scalar(output, static_cast<std::int32_t>(arc.source)) ||
            !write_scalar(output, static_cast<std::int32_t>(arc.target)) ||
            !write_scalar(output, arc.weight) ||
            !write_scalar(output, static_cast<std::int64_t>(arc.original_edge_id)) ||
            !write_scalar(output, static_cast<std::int32_t>(arc.left)) ||
            !write_scalar(output, static_cast<std::int32_t>(arc.right))) break;
    }
    for (const std::size_t offset : hierarchy.upward_out_offsets) {
        if (!write_size(offset)) break;
    }
    for (const int arc_id : hierarchy.upward_out_arcs) {
        if (!write_scalar(output, static_cast<std::int32_t>(arc_id))) break;
    }
    for (const std::size_t offset : hierarchy.upward_in_offsets) {
        if (!write_size(offset)) break;
    }
    for (const int arc_id : hierarchy.upward_in_arcs) {
        if (!write_scalar(output, static_cast<std::int32_t>(arc_id))) break;
    }
    output.flush();
    const bool saved = static_cast<bool>(output);
    output.close();
    if (!saved) {
        std::filesystem::remove(temporary);
        return false;
    }

    std::error_code error;
    std::filesystem::rename(temporary, path, error);
    if (error) {
        std::filesystem::remove(path, error);
        error.clear();
        std::filesystem::rename(temporary, path, error);
    }
    if (error) {
        std::filesystem::remove(temporary);
        return false;
    }
    return true;
}

bool load_cache(const std::filesystem::path& path, const std::string& key,
                std::size_t expected_nodes, std::size_t expected_edges,
                CHHandle& handle) {
    if (key.size() != 64 || !std::filesystem::is_regular_file(path)) return false;
    std::ifstream input(path, std::ios::binary);
    if (!input) return false;
    std::array<char, 8> magic{};
    input.read(magic.data(), static_cast<std::streamsize>(magic.size()));
    std::uint32_t version = 0;
    std::uint64_t rank_count = 0, edge_count = 0, arc_count = 0;
    std::uint64_t out_offset_count = 0, out_arc_count = 0;
    std::uint64_t in_offset_count = 0, in_arc_count = 0, shortcut_count = 0;
    if (!input || magic != kCacheMagic || !read_scalar(input, version) ||
        !read_scalar(input, rank_count) || !read_scalar(input, edge_count) ||
        !read_scalar(input, arc_count) || !read_scalar(input, out_offset_count) ||
        !read_scalar(input, out_arc_count) || !read_scalar(input, in_offset_count) ||
        !read_scalar(input, in_arc_count) || !read_scalar(input, shortcut_count) ||
        version != kCacheVersion || rank_count != expected_nodes ||
        edge_count != expected_edges || out_offset_count != expected_nodes + 1 ||
        in_offset_count != expected_nodes + 1 || arc_count > std::numeric_limits<int>::max() ||
        out_arc_count > arc_count || in_arc_count > arc_count || shortcut_count > arc_count ||
        arc_count > std::numeric_limits<std::size_t>::max() ||
        out_arc_count > std::numeric_limits<std::size_t>::max() ||
        in_arc_count > std::numeric_limits<std::size_t>::max()) {
        return false;
    }
    std::error_code size_error;
    const std::uintmax_t file_size = std::filesystem::file_size(path, size_error);
    if (size_error) return false;
    std::uint64_t expected_size = 8 + 4 + 8 * 8 + 64;
    const auto add_bytes = [&expected_size](std::uint64_t count, std::uint64_t width) {
        if (count > (std::numeric_limits<std::uint64_t>::max() - expected_size) / width) return false;
        expected_size += count * width;
        return true;
    };
    if (!add_bytes(rank_count, 4) || !add_bytes(arc_count, 32) ||
        !add_bytes(out_offset_count, 8) || !add_bytes(out_arc_count, 4) ||
        !add_bytes(in_offset_count, 8) || !add_bytes(in_arc_count, 4) ||
        file_size != expected_size) return false;
    std::string stored_key(64, '\0');
    input.read(stored_key.data(), static_cast<std::streamsize>(stored_key.size()));
    if (!input || stored_key != key) return false;

    auto& hierarchy = handle.hierarchy;
    hierarchy.rank.resize(static_cast<std::size_t>(rank_count));
    for (int& rank : hierarchy.rank) {
        std::int32_t value = -1;
        if (!read_scalar(input, value)) return false;
        rank = value;
    }
    hierarchy.arcs.resize(static_cast<std::size_t>(arc_count));
    for (auto& arc : hierarchy.arcs) {
        std::int32_t source = -1, target = -1, left = -1, right = -1;
        std::int64_t original_edge_id = -1;
        if (!read_scalar(input, source) || !read_scalar(input, target) ||
            !read_scalar(input, arc.weight) || !read_scalar(input, original_edge_id) ||
            !read_scalar(input, left) || !read_scalar(input, right)) return false;
        arc.source = source;
        arc.target = target;
        arc.original_edge_id = original_edge_id;
        arc.left = left;
        arc.right = right;
    }
    auto read_offsets = [&](std::vector<std::size_t>& offsets, std::uint64_t count) {
        offsets.resize(static_cast<std::size_t>(count));
        for (std::size_t& offset : offsets) {
            std::uint64_t value = 0;
            if (!read_scalar(input, value) || value > std::numeric_limits<std::size_t>::max()) return false;
            offset = static_cast<std::size_t>(value);
        }
        return true;
    };
    auto read_arc_ids = [&](std::vector<int>& arc_ids, std::uint64_t count) {
        arc_ids.resize(static_cast<std::size_t>(count));
        for (int& arc_id : arc_ids) {
            std::int32_t value = -1;
            if (!read_scalar(input, value)) return false;
            arc_id = value;
        }
        return true;
    };
    if (!read_offsets(hierarchy.upward_out_offsets, out_offset_count) ||
        !read_arc_ids(hierarchy.upward_out_arcs, out_arc_count) ||
        !read_offsets(hierarchy.upward_in_offsets, in_offset_count) ||
        !read_arc_ids(hierarchy.upward_in_arcs, in_arc_count) ||
        input.peek() != std::char_traits<char>::eof()) return false;

    std::vector<char> seen(expected_nodes, false);
    for (const int rank : hierarchy.rank) {
        if (rank < 0 || static_cast<std::size_t>(rank) >= expected_nodes || seen[rank]) return false;
        seen[rank] = true;
    }
    for (std::size_t i = 0; i < hierarchy.arcs.size(); ++i) {
        const auto& arc = hierarchy.arcs[i];
        const bool is_shortcut = arc.left >= 0;
        if (arc.source < 0 || arc.target < 0 ||
            static_cast<std::size_t>(arc.source) >= expected_nodes ||
            static_cast<std::size_t>(arc.target) >= expected_nodes ||
            !std::isfinite(arc.weight) || arc.weight < 0.0 ||
            ((arc.left < 0) != (arc.right < 0)) ||
            (is_shortcut && (arc.left >= static_cast<int>(i) || arc.right >= static_cast<int>(i) ||
                             arc.original_edge_id != -1)) ||
            (!is_shortcut && (arc.left != -1 || arc.right != -1 || arc.original_edge_id < 0 ||
                              arc.original_edge_id >= static_cast<std::int64_t>(expected_edges)))) return false;
    }
    auto offsets_valid = [](const std::vector<std::size_t>& offsets,
                            const std::vector<int>& arc_ids,
                            std::size_t node_count, std::size_t arc_count) {
        if (offsets.size() != node_count + 1 || offsets.front() != 0 || offsets.back() != arc_ids.size()) return false;
        for (std::size_t i = 1; i < offsets.size(); ++i) {
            if (offsets[i] < offsets[i - 1]) return false;
        }
        return std::all_of(arc_ids.begin(), arc_ids.end(), [arc_count](int id) {
            return id >= 0 && static_cast<std::size_t>(id) < arc_count;
        });
    };
    if (!offsets_valid(hierarchy.upward_out_offsets, hierarchy.upward_out_arcs,
                       expected_nodes, hierarchy.arcs.size()) ||
        !offsets_valid(hierarchy.upward_in_offsets, hierarchy.upward_in_arcs,
                       expected_nodes, hierarchy.arcs.size())) return false;
    for (std::size_t node = 0; node < expected_nodes; ++node) {
        for (std::size_t pos = hierarchy.upward_out_offsets[node];
             pos < hierarchy.upward_out_offsets[node + 1]; ++pos) {
            const auto& arc = hierarchy.arcs[hierarchy.upward_out_arcs[pos]];
            if (arc.source != static_cast<int>(node) || hierarchy.rank[arc.source] >= hierarchy.rank[arc.target]) return false;
        }
        for (std::size_t pos = hierarchy.upward_in_offsets[node];
             pos < hierarchy.upward_in_offsets[node + 1]; ++pos) {
            const auto& arc = hierarchy.arcs[hierarchy.upward_in_arcs[pos]];
            if (arc.target != static_cast<int>(node) || hierarchy.rank[arc.source] <= hierarchy.rank[arc.target]) return false;
        }
    }
    handle.shortcut_count = static_cast<std::size_t>(shortcut_count);
    const auto actual_shortcuts = static_cast<std::size_t>(std::count_if(
        hierarchy.arcs.begin(), hierarchy.arcs.end(),
        [](const route_cpp17::CHArc& arc) { return arc.left >= 0; }));
    return handle.shortcut_count == actual_shortcuts;
}

}  // namespace

CH_API void* ch_graph_create(
    int64_t n_nodes, int64_t n_edges, const int64_t* indptr,
    const int64_t* indices, const double* weights, const int64_t* edge_ids,
    int32_t* error_code, uint64_t* preprocess_ns,
    int64_t* hierarchy_arc_count, int64_t* shortcut_count) {
    if (error_code) *error_code = OK;
    if (preprocess_ns) *preprocess_ns = 0;
    if (hierarchy_arc_count) *hierarchy_arc_count = 0;
    if (shortcut_count) *shortcut_count = 0;
    if (!error_code || !preprocess_ns || !hierarchy_arc_count || !shortcut_count ||
        n_nodes <= 0 || n_nodes > std::numeric_limits<int>::max() ||
        n_edges < 0 || n_edges > std::numeric_limits<int>::max() || !indptr ||
        (n_edges > 0 && (!indices || !weights || !edge_ids))) {
        if (error_code) *error_code = INVALID_ARGUMENT;
        return nullptr;
    }

    try {
        if (indptr[0] != 0 || indptr[n_nodes] != n_edges) {
            *error_code = INVALID_GRAPH;
            return nullptr;
        }

        const auto begin = std::chrono::steady_clock::now();
        route_cpp17::RoadGraph graph;
        graph.outgoing.resize(static_cast<std::size_t>(n_nodes));
        for (int64_t u = 0; u < n_nodes; ++u) {
            const int64_t edge_begin = indptr[u];
            const int64_t edge_end = indptr[u + 1];
            if (edge_begin < 0 || edge_end < edge_begin || edge_end > n_edges) {
                *error_code = INVALID_GRAPH;
                return nullptr;
            }
            auto& outgoing = graph.outgoing[static_cast<std::size_t>(u)];
            outgoing.reserve(static_cast<std::size_t>(edge_end - edge_begin));
            for (int64_t i = edge_begin; i < edge_end; ++i) {
                const int64_t v = indices[i];
                if (v < 0 || v >= n_nodes || !std::isfinite(weights[i]) || weights[i] < 0.0) {
                    *error_code = INVALID_GRAPH;
                    return nullptr;
                }
                outgoing.push_back({static_cast<int>(v), weights[i], edge_ids[i]});
            }
        }

        auto handle = std::make_unique<CHHandle>();
        handle->hierarchy = route_cpp17::preprocess_ch(graph);
        handle->shortcut_count = static_cast<std::size_t>(std::count_if(
            handle->hierarchy.arcs.begin(), handle->hierarchy.arcs.end(),
            [](const route_cpp17::CHArc& arc) { return arc.left >= 0; }));
        if (handle->hierarchy.arcs.size() >
                static_cast<std::size_t>(std::numeric_limits<int64_t>::max()) ||
            handle->shortcut_count >
                static_cast<std::size_t>(std::numeric_limits<int64_t>::max())) {
            *error_code = INTERNAL_ERROR;
            return nullptr;
        }
        const auto end = std::chrono::steady_clock::now();
        *preprocess_ns = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count());
        *hierarchy_arc_count = static_cast<int64_t>(handle->hierarchy.arcs.size());
        *shortcut_count = static_cast<int64_t>(handle->shortcut_count);
        return handle.release();
    } catch (const std::invalid_argument&) {
        *error_code = INVALID_GRAPH;
        return nullptr;
    } catch (...) {
        *error_code = INTERNAL_ERROR;
        return nullptr;
    }
}

CH_API void* ch_graph_create_cached(
    int64_t n_nodes, int64_t n_edges, const int64_t* indptr,
    const int64_t* indices, const double* weights, const int64_t* edge_ids,
    const char* cache_path, const char* cache_key, int32_t* error_code,
    uint64_t* preprocess_ns, uint64_t* cache_load_ns, int32_t* cache_hit,
    int64_t* hierarchy_arc_count, int64_t* shortcut_count) {
    if (error_code) *error_code = OK;
    if (preprocess_ns) *preprocess_ns = 0;
    if (cache_load_ns) *cache_load_ns = 0;
    if (cache_hit) *cache_hit = 0;
    if (hierarchy_arc_count) *hierarchy_arc_count = 0;
    if (shortcut_count) *shortcut_count = 0;
    if (!error_code || !preprocess_ns || !cache_load_ns || !cache_hit ||
        !hierarchy_arc_count || !shortcut_count || !cache_path || !cache_key ||
        n_nodes <= 0 || n_nodes > std::numeric_limits<int>::max() ||
        n_edges < 0 || n_edges > std::numeric_limits<int>::max()) {
        if (error_code) *error_code = INVALID_ARGUMENT;
        return nullptr;
    }

    try {
        const auto load_begin = std::chrono::steady_clock::now();
        auto cached = std::make_unique<CHHandle>();
        if (load_cache(cache_path, cache_key, static_cast<std::size_t>(n_nodes),
                       static_cast<std::size_t>(n_edges), *cached)) {
            const auto load_end = std::chrono::steady_clock::now();
            *cache_load_ns = static_cast<std::uint64_t>(
                std::chrono::duration_cast<std::chrono::nanoseconds>(load_end - load_begin).count());
            *cache_hit = 1;
            *hierarchy_arc_count = static_cast<int64_t>(cached->hierarchy.arcs.size());
            *shortcut_count = static_cast<int64_t>(cached->shortcut_count);
            return cached.release();
        }
        const auto load_end = std::chrono::steady_clock::now();
        *cache_load_ns = static_cast<std::uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(load_end - load_begin).count());

        void* created = ch_graph_create(
            n_nodes, n_edges, indptr, indices, weights, edge_ids, error_code,
            preprocess_ns, hierarchy_arc_count, shortcut_count);
        if (!created) return nullptr;
        auto* handle = static_cast<CHHandle*>(created);
        try {
            const std::filesystem::path path(cache_path);
            if (!path.parent_path().empty()) std::filesystem::create_directories(path.parent_path());
            (void)save_cache(path, cache_key, *handle, static_cast<std::size_t>(n_edges));
        } catch (...) {
            // A cache write failure must not discard a valid in-memory hierarchy.
        }
        return created;
    } catch (...) {
        *error_code = INTERNAL_ERROR;
        return nullptr;
    }
}

CH_API void ch_graph_destroy(void* opaque_handle) {
    delete static_cast<CHHandle*>(opaque_handle);
}

CH_API int32_t ch_run(
    void* opaque_handle, int64_t start, int64_t goal,
    int64_t* node_buffer, int64_t node_capacity,
    int64_t* edge_buffer, int64_t edge_capacity,
    int64_t* node_count, int64_t* edge_count, double* total_distance,
    uint64_t* expanded_count, uint64_t* queue_pushes, uint64_t* elapsed_ns) {
    if (node_count) *node_count = 0;
    if (edge_count) *edge_count = 0;
    if (total_distance) *total_distance = std::numeric_limits<double>::infinity();
    if (expanded_count) *expanded_count = 0;
    if (queue_pushes) *queue_pushes = 0;
    if (elapsed_ns) *elapsed_ns = 0;
    if (!opaque_handle || !node_count || !edge_count || !total_distance ||
        !expanded_count || !queue_pushes || !elapsed_ns || node_capacity < 0 ||
        edge_capacity < 0 || (node_capacity > 0 && !node_buffer) ||
        (edge_capacity > 0 && !edge_buffer)) {
        return INVALID_ARGUMENT;
    }

    auto& handle = *static_cast<CHHandle*>(opaque_handle);
    const auto& rank = handle.hierarchy.rank;
    if (start < 0 || goal < 0 || start >= static_cast<int64_t>(rank.size()) ||
        goal >= static_cast<int64_t>(rank.size())) {
        return INVALID_QUERY;
    }

    try {
        const auto begin = std::chrono::steady_clock::now();
        const route_cpp17::PathResult result = handle.hierarchy.query(
            static_cast<int>(start), static_cast<int>(goal));
        const auto end = std::chrono::steady_clock::now();
        *elapsed_ns = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count());
        *node_count = static_cast<int64_t>(result.nodes.size());
        *edge_count = static_cast<int64_t>(result.edges.size());
        *total_distance = result.cost;
        *expanded_count = static_cast<uint64_t>(result.expanded);
        *queue_pushes = static_cast<uint64_t>(result.queue_pushes);
        if (result.nodes.size() > static_cast<std::size_t>(node_capacity) ||
            result.edges.size() > static_cast<std::size_t>(edge_capacity)) {
            return BUFFER_TOO_SMALL;
        }
        if (!result.nodes.empty()) {
            std::transform(result.nodes.begin(), result.nodes.end(), node_buffer,
                           [](int node) { return static_cast<int64_t>(node); });
        }
        if (!result.edges.empty()) {
            std::copy(result.edges.begin(), result.edges.end(), edge_buffer);
        }
        return OK;
    } catch (...) {
        return INTERNAL_ERROR;
    }
}
