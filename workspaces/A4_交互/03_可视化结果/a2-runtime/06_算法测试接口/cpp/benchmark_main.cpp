#include "algorithms.hpp"
#include "cache_io.hpp"
#include "query_io.hpp"
#include "rgraph_io.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace fs = std::filesystem;
using route_cpp17::PathResult;
using Clock = std::chrono::steady_clock;

namespace {

    struct Options {
        fs::path graph;
        fs::path queries;
        fs::path output;
        fs::path cache_dir;
        std::string dataset;
        std::vector<std::string> algorithms;
        int generate_queries = 0;
        int repeat = 3;
        std::uint32_t seed = 20261102U;
        int ch_event_stride = 100;
        bool prepare_only = false;
        bool force_rebuild = false;
    };

    struct PreprocessRow {
        std::string algorithm;
        double preprocess_ms = 0.0;
        std::size_t original_edges = 0;
        std::size_t reverse_edges = 0;
        std::size_t shortcut_edges = 0;
        std::size_t index_edges = 0;
        double estimated_index_mb = 0.0;
        double visualization_overhead_ms = 0.0;
        bool cache_hit = false;
    };

    struct QueryRow {
        std::string dataset;
        std::string algorithm;
        route_benchmark::QueryPair query;
        double cost = route_cpp17::ROUTE_INF;
        double query_ms = 0.0;
        std::size_t expanded = 0;
        std::size_t queue_pushes = 0;
        std::size_t path_edges = 0;
        bool valid = false;
    };

    struct AlgorithmStats {
        double mean_ms = 0.0;
        double p50_ms = 0.0;
        double p95_ms = 0.0;
        double mean_expanded = 0.0;
        double mean_queue_pushes = 0.0;
        std::size_t valid_queries = 0;
    };

    std::vector<std::string> split(
        const std::string& value,
        char separator
    ) {
        std::vector<std::string> result;
        std::stringstream stream(value);
        std::string item;

        while (std::getline(stream, item, separator)) {
            if (!item.empty()) {
                result.push_back(item);
            }
        }

        return result;
    }

    Options parse_options(
        int argc,
        char** argv
    ) {
        Options options;

        for (int i = 1; i < argc; ++i) {
            const std::string key = argv[i];

            auto value = [&]() -> std::string {
                if (i + 1 >= argc) {
                    throw std::invalid_argument(
                        "missing value after " + key
                    );
                }

                return argv[++i];
                };

            if (key == "--graph") {
                options.graph = fs::u8path(value());
            }
            else if (key == "--queries") {
                options.queries = fs::u8path(value());
            }
            else if (key == "--output") {
                options.output = fs::u8path(value());
            }
            else if (key == "--cache-dir") {
                options.cache_dir = fs::u8path(value());
            }
            else if (key == "--dataset") {
                options.dataset = value();
            }
            else if (key == "--algorithms") {
                options.algorithms = split(value(), ',');
            }
            else if (key == "--generate-queries") {
                options.generate_queries = std::stoi(value());
            }
            else if (key == "--repeat") {
                options.repeat = std::stoi(value());
            }
            else if (key == "--seed") {
                options.seed = static_cast<std::uint32_t>(
                    std::stoul(value())
                    );
            }
            else if (key == "--ch-event-stride") {
                options.ch_event_stride = std::stoi(value());
            }
            else if (key == "--prepare-only") {
                options.prepare_only = true;
            }
            else if (key == "--force-rebuild") {
                options.force_rebuild = true;
            }
            else if (key == "--help") {
                std::cout
                    << "route_benchmark "
                    << "--graph file.rgraph "
                    << "--cache-dir cache "
                    << "--output results "
                    << "[--prepare-only] "
                    << "[--queries queries.csv] "
                    << "--algorithms "
                    << "dijkstra,astar,"
                    << "bidirectional_astar,ch\n";

                std::exit(0);
            }
            else {
                throw std::invalid_argument(
                    "unknown argument: " + key
                );
            }
        }

        if (
            options.graph.empty()
            || options.output.empty()
            || options.cache_dir.empty()
            ) {
            throw std::invalid_argument(
                "--graph, --cache-dir and --output "
                "are required"
            );
        }

        if (
            !options.prepare_only
            && options.queries.empty()
            ) {
            throw std::invalid_argument(
                "--queries is required unless "
                "--prepare-only is used"
            );
        }

        if (options.dataset.empty()) {
            options.dataset =
                options.graph.stem().string();
        }

        if (options.algorithms.empty()) {
            options.algorithms = {
                "dijkstra",
                "astar",
                "bidirectional_astar",
                "ch",
            };
        }

        const std::set<std::string> allowed{
            "dijkstra",
            "astar",
            "bidirectional_astar",
            "ch",
        };

        for (const auto& name : options.algorithms) {
            if (!allowed.count(name)) {
                throw std::invalid_argument(
                    "unknown algorithm: " + name
                );
            }
        }

        if (options.repeat < 1) {
            throw std::invalid_argument(
                "repeat must be at least 1"
            );
        }

        return options;
    }

#ifdef _WIN32

    std::string wide_to_utf8(
        const std::wstring& value
    ) {
        if (value.empty()) {
            return {};
        }

        const int size = WideCharToMultiByte(
            CP_UTF8,
            WC_ERR_INVALID_CHARS,
            value.data(),
            static_cast<int>(value.size()),
            nullptr,
            0,
            nullptr,
            nullptr
        );

        if (size <= 0) {
            throw std::runtime_error(
                "cannot convert Windows argument to UTF-8"
            );
        }

        std::string result(
            static_cast<std::size_t>(size),
            '\0'
        );

        if (
            WideCharToMultiByte(
                CP_UTF8,
                WC_ERR_INVALID_CHARS,
                value.data(),
                static_cast<int>(value.size()),
                result.data(),
                size,
                nullptr,
                nullptr
            ) <= 0
            ) {
            throw std::runtime_error(
                "cannot convert Windows argument to UTF-8"
            );
        }

        return result;
    }

    Options parse_options(
        int argc,
        wchar_t** argv
    ) {
        Options options;

        for (int i = 1; i < argc; ++i) {
            const std::wstring key = argv[i];

            auto value = [&]() -> std::wstring {
                if (i + 1 >= argc) {
                    throw std::invalid_argument(
                        "missing value after "
                        + wide_to_utf8(key)
                    );
                }

                return argv[++i];
                };

            if (key == L"--graph") {
                options.graph = fs::path(value());
            }
            else if (key == L"--queries") {
                options.queries = fs::path(value());
            }
            else if (key == L"--output") {
                options.output = fs::path(value());
            }
            else if (key == L"--cache-dir") {
                options.cache_dir = fs::path(value());
            }
            else if (key == L"--dataset") {
                options.dataset =
                    wide_to_utf8(value());
            }
            else if (key == L"--algorithms") {
                options.algorithms = split(
                    wide_to_utf8(value()),
                    ','
                );
            }
            else if (key == L"--generate-queries") {
                options.generate_queries =
                    std::stoi(value());
            }
            else if (key == L"--repeat") {
                options.repeat = std::stoi(value());
            }
            else if (key == L"--seed") {
                options.seed =
                    static_cast<std::uint32_t>(
                        std::stoul(value())
                        );
            }
            else if (key == L"--ch-event-stride") {
                options.ch_event_stride =
                    std::stoi(value());
            }
            else if (key == L"--prepare-only") {
                options.prepare_only = true;
            }
            else if (key == L"--force-rebuild") {
                options.force_rebuild = true;
            }
            else if (key == L"--help") {
                std::cout
                    << "route_benchmark "
                    << "--graph file.rgraph "
                    << "--cache-dir cache "
                    << "--output results "
                    << "[--prepare-only] "
                    << "[--queries queries.csv] "
                    << "--algorithms "
                    << "dijkstra,astar,"
                    << "bidirectional_astar,ch\n";

                std::exit(0);
            }
            else {
                throw std::invalid_argument(
                    "unknown argument: "
                    + wide_to_utf8(key)
                );
            }
        }

        if (
            options.graph.empty()
            || options.output.empty()
            || options.cache_dir.empty()
            ) {
            throw std::invalid_argument(
                "--graph, --cache-dir and --output "
                "are required"
            );
        }

        if (
            !options.prepare_only
            && options.queries.empty()
            ) {
            throw std::invalid_argument(
                "--queries is required unless "
                "--prepare-only is used"
            );
        }

        if (options.dataset.empty()) {
            options.dataset =
                options.graph.stem().u8string();
        }

        if (options.algorithms.empty()) {
            options.algorithms = {
                "dijkstra",
                "astar",
                "bidirectional_astar",
                "ch",
            };
        }

        const std::set<std::string> allowed{
            "dijkstra",
            "astar",
            "bidirectional_astar",
            "ch",
        };

        for (const auto& name : options.algorithms) {
            if (!allowed.count(name)) {
                throw std::invalid_argument(
                    "unknown algorithm: " + name
                );
            }
        }

        if (options.repeat < 1) {
            throw std::invalid_argument(
                "repeat must be at least 1"
            );
        }

        return options;
    }

#endif

    std::size_t edge_count(
        const route_cpp17::RoadGraph& graph
    ) {
        std::size_t count = 0;

        for (const auto& edges : graph.outgoing) {
            count += edges.size();
        }

        return count;
    }

    double elapsed_ms(
        const Clock::time_point& start
    ) {
        return std::chrono::duration<
            double,
            std::milli
        >(
            Clock::now() - start
        ).count();
    }

    double percentile(
        std::vector<double> values,
        double p
    ) {
        if (values.empty()) {
            return 0.0;
        }

        std::sort(
            values.begin(),
            values.end()
        );

        const double position =
            p * static_cast<double>(
                values.size() - 1
                );

        const std::size_t lower =
            static_cast<std::size_t>(
                std::floor(position)
                );

        const std::size_t upper =
            static_cast<std::size_t>(
                std::ceil(position)
                );

        const double fraction =
            position - lower;

        return (
            values[lower] * (1.0 - fraction)
            + values[upper] * fraction
            );
    }

    double median(
        std::vector<double> values
    ) {
        return percentile(
            std::move(values),
            0.5
        );
    }

    bool same_cost(
        double first,
        double second
    ) {
        if (
            !std::isfinite(first)
            || !std::isfinite(second)
            ) {
            return (
                !std::isfinite(first)
                && !std::isfinite(second)
                );
        }

        const double tolerance =
            1e-6
            * std::max(
                {
                    1.0,
                    std::abs(first),
                    std::abs(second),
                }
                );

        return (
            std::abs(first - second)
            <= tolerance
            );
    }

    std::string json_escape(
        const std::string& value
    ) {
        std::string output;

        for (char ch : value) {
            if (
                ch == '"'
                || ch == '\\'
                ) {
                output.push_back('\\');
            }

            output.push_back(ch);
        }

        return output;
    }

    AlgorithmStats compute_stats(
        const std::vector<QueryRow>& rows,
        const std::string& algorithm
    ) {
        AlgorithmStats result;
        std::vector<double> times;
        double expanded = 0.0;
        double pushes = 0.0;

        for (const auto& row : rows) {
            if (
                row.algorithm != algorithm
                || !row.valid
                ) {
                continue;
            }

            times.push_back(row.query_ms);

            expanded += static_cast<double>(
                row.expanded
                );

            pushes += static_cast<double>(
                row.queue_pushes
                );
        }

        result.valid_queries = times.size();

        if (times.empty()) {
            return result;
        }

        for (double value : times) {
            result.mean_ms += value;
        }

        result.mean_ms /=
            static_cast<double>(times.size());

        result.p50_ms = percentile(
            times,
            0.5
        );

        result.p95_ms = percentile(
            times,
            0.95
        );

        result.mean_expanded =
            expanded
            / static_cast<double>(times.size());

        result.mean_queue_pushes =
            pushes
            / static_cast<double>(times.size());

        return result;
    }

    void write_query_rows(
        const fs::path& path,
        const std::vector<QueryRow>& rows
    ) {
        std::ofstream output(path);

        if (!output) {
            throw std::runtime_error(
                "cannot write " + path.string()
            );
        }

        output
            << "dataset,algorithm,query_id,"
            << "distance_level,source,target,"
            << "straight_distance_m,cost,query_ms,"
            << "expanded_nodes,queue_pushes,"
            << "path_edges,valid\n";

        output << std::setprecision(15);

        for (const auto& row : rows) {
            output
                << row.dataset << ','
                << row.algorithm << ','
                << row.query.query_id << ','
                << row.query.distance_level << ','
                << row.query.source << ','
                << row.query.target << ','
                << row.query.straight_distance_m << ','
                << row.cost << ','
                << row.query_ms << ','
                << row.expanded << ','
                << row.queue_pushes << ','
                << row.path_edges << ','
                << (row.valid ? "true" : "false")
                << '\n';
        }
    }

    void write_preprocess(
        const fs::path& path,
        const std::vector<PreprocessRow>& rows
    ) {
        std::ofstream output(path);

        output
            << "algorithm,preprocess_ms,"
            << "original_edges,reverse_edges,"
            << "shortcut_edges,index_edges,"
            << "estimated_index_mb,"
            << "visualization_overhead_ms,"
            << "cache_hit\n";

        output << std::setprecision(15);

        for (const auto& row : rows) {
            output
                << row.algorithm << ','
                << row.preprocess_ms << ','
                << row.original_edges << ','
                << row.reverse_edges << ','
                << row.shortcut_edges << ','
                << row.index_edges << ','
                << row.estimated_index_mb << ','
                << row.visualization_overhead_ms << ','
                << (row.cache_hit ? "true" : "false")
                << '\n';
        }
    }

    void write_total_cost(
        const fs::path& path,
        const std::vector<std::string>& algorithms,
        const std::map<
        std::string,
        AlgorithmStats
        >& stats,
        const std::map<
        std::string,
        double
        >& preprocess,
        int actual_query_count
    ) {
        std::vector<int> counts{
            1,
            10,
            100,
            300,
            1000,
            10000,
            actual_query_count,
        };

        std::sort(
            counts.begin(),
            counts.end()
        );

        counts.erase(
            std::unique(
                counts.begin(),
                counts.end()
            ),
            counts.end()
        );

        std::ofstream output(path);

        output
            << "algorithm,query_count,"
            << "preprocess_ms,"
            << "estimated_query_ms,total_ms\n";

        output << std::setprecision(15);

        for (const auto& algorithm : algorithms) {
            for (int count : counts) {
                const double query =
                    stats.at(algorithm).mean_ms
                    * count;

                output
                    << algorithm << ','
                    << count << ','
                    << preprocess.at(algorithm) << ','
                    << query << ','
                    << preprocess.at(algorithm) + query
                    << '\n';
            }
        }
    }

    void write_summary(
        const fs::path& path,
        const Options& options,
        std::size_t nodes,
        std::size_t edges,
        double graph_load_ms,
        const std::vector<std::string>& algorithms,
        const std::map<
        std::string,
        AlgorithmStats
        >& stats,
        const std::map<
        std::string,
        PreprocessRow
        >& prep
    ) {
        std::ofstream output(path);

        output << std::setprecision(15);

        output
            << "{\n  \"dataset\": {\"id\": \""
            << json_escape(options.dataset)
            << "\", \"nodes\": "
            << nodes
            << ", \"edges\": "
            << edges
            << ", \"graph_load_ms\": "
            << graph_load_ms
            << "},\n";

        output << "  \"algorithms\": {\n";

        for (
            std::size_t i = 0;
            i < algorithms.size();
            ++i
            ) {
            const auto& name = algorithms[i];
            const auto& value = stats.at(name);
            const auto& p = prep.at(name);

            output
                << "    \"" << name << "\": {"
                << "\"preprocess_ms\": "
                << p.preprocess_ms << ", "
                << "\"query_mean_ms\": "
                << value.mean_ms << ", "
                << "\"query_p50_ms\": "
                << value.p50_ms << ", "
                << "\"query_p95_ms\": "
                << value.p95_ms << ", "
                << "\"expanded_mean\": "
                << value.mean_expanded << ", "
                << "\"queue_pushes_mean\": "
                << value.mean_queue_pushes << ", "
                << "\"valid_queries\": "
                << value.valid_queries << ", "
                << "\"shortcut_edges\": "
                << p.shortcut_edges << ", "
                << "\"index_edges\": "
                << p.index_edges << ", "
                << "\"estimated_index_mb\": "
                << p.estimated_index_mb << ", "
                << "\"cache_hit\": "
                << (
                    p.cache_hit
                    ? "true"
                    : "false"
                    )
                << "}"
                << (
                    i + 1 == algorithms.size()
                    ? "\n"
                    : ",\n"
                    );
        }

        output << "  }\n}\n";
    }

} // namespace

#ifdef _WIN32
int wmain(
    int argc,
    wchar_t** argv
) {
#else
int main(
    int argc,
    char** argv
) {
#endif
    try {
        const Options options =
            parse_options(argc, argv);

        fs::create_directories(
            options.output
        );

        std::cout
            << "PROGRESS loading_graph 0\n";

        const auto load_started =
            Clock::now();

        const auto graph =
            route_benchmark::load_rgraph(
                options.graph
            );

        const double graph_load_ms =
            elapsed_ms(load_started);

        const std::size_t original_edges =
            edge_count(graph);

        std::cout
            << "PROGRESS loading_graph 100\n";

        fs::create_directories(
            options.cache_dir
        );

        std::optional<double> astar_scale;

        std::optional<
            route_cpp17::BidirectionalAStarIndex
        > bidirectional_index;

        std::optional<
            route_cpp17::ContractionHierarchy
        > ch_index;

        std::vector<PreprocessRow>
            preprocess_rows;

        std::map<
            std::string,
            PreprocessRow
        > preprocess_by_name;

        for (
            const auto& algorithm :
            options.algorithms
            ) {
            std::cout
                << "PROGRESS preprocessing_"
                << algorithm
                << " 0\n";

            PreprocessRow row;
            row.algorithm = algorithm;
            row.original_edges = original_edges;

            if (algorithm == "astar") {
                const fs::path cache =
                    options.cache_dir
                    / "astar.cache";

                row.cache_hit =
                    fs::exists(cache)
                    && !options.force_rebuild;

                if (row.cache_hit) {
                    const auto cached =
                        route_benchmark::
                        load_astar_cache(
                            cache,
                            graph.size()
                        );

                    astar_scale =
                        cached.heuristic_scale;

                    row.preprocess_ms =
                        cached.preprocess_ms;
                }
                else {
                    const auto started =
                        Clock::now();

                    astar_scale =
                        route_cpp17::
                        estimate_astar_haversine_scale(
                            graph
                        );

                    row.preprocess_ms =
                        elapsed_ms(started);

                    route_benchmark::
                        save_astar_cache(
                            cache,
                            graph.size(),
                            *astar_scale,
                            row.preprocess_ms
                        );
                }

                row.estimated_index_mb =
                    sizeof(double)
                    / (1024.0 * 1024.0);

            }
            else if (
                algorithm
                == "bidirectional_astar"
                ) {
                const fs::path cache =
                    options.cache_dir
                    / "bidirectional_astar.cache";

                row.cache_hit =
                    fs::exists(cache)
                    && !options.force_rebuild;

                if (row.cache_hit) {
                    auto cached =
                        route_benchmark::
                        load_bidirectional_cache(
                            cache,
                            graph.size()
                        );

                    row.preprocess_ms =
                        cached.preprocess_ms;

                    bidirectional_index =
                        std::move(cached.index);
                }
                else {
                    const auto started =
                        Clock::now();

                    bidirectional_index =
                        route_cpp17::
                        prepare_bidirectional_astar(
                            graph
                        );

                    row.preprocess_ms =
                        elapsed_ms(started);

                    route_benchmark::
                        save_bidirectional_cache(
                            cache,
                            graph.size(),
                            *bidirectional_index,
                            row.preprocess_ms
                        );
                }

                row.reverse_edges =
                    original_edges;

                row.index_edges =
                    original_edges;

                row.estimated_index_mb =
                    (
                        original_edges
                        * sizeof(route_cpp17::Edge)
                        + graph.size()
                        * sizeof(
                            std::vector<
                            route_cpp17::Edge
                            >
                            )
                        + graph.size()
                        * sizeof(
                            route_cpp17::
                            BidirectionalAStarIndex::
                            SpherePoint
                            )
                        )
                    / (1024.0 * 1024.0);

            }
            else if (algorithm == "ch") {
                const fs::path cache =
                    options.cache_dir
                    / "ch.cache";

                row.cache_hit =
                    fs::exists(cache)
                    && !options.force_rebuild;

                if (row.cache_hit) {
                    auto cached =
                        route_benchmark::
                        load_ch_cache(
                            cache,
                            graph.size()
                        );

                    row.preprocess_ms =
                        cached.preprocess_ms;

                    ch_index =
                        std::move(cached.index);
                }
                else {
                    std::ofstream events(
                        options.output
                        / "ch_events.csv"
                    );

                    events
                        << "step,total,"
                        << "contracted_node,"
                        << "lon,lat,arc_count,"
                        << "shortcuts_added\n";

                    const auto callback =
                        [&](
                            const route_cpp17::
                            CHProgressEvent& event
                            ) {
                                if (
                                    options.ch_event_stride
            > 0
                                    && (
                                        event.step
                                        == event.total
                                        || event.step
                                        % options
                                        .ch_event_stride
                                        == 0
                                        )
                                    ) {
                                    const auto event_started =
                                        Clock::now();

                                    const auto& coordinate =
                                        graph.coordinates[
                                            event.contracted_node
                                        ];

                                    events
                                        << event.step << ','
                                        << event.total << ','
                                        << event.contracted_node
                                        << ','
                                        << coordinate.lon << ','
                                        << coordinate.lat << ','
                                        << event.arc_count << ','
                                        << event.shortcuts_added
                                        << '\n';

                                    const int percent =
                                        static_cast<int>(
                                            100.0
                                            * event.step
                                            / std::max(
                                                1,
                                                event.total
                                            )
                                            );

                                    std::cout
                                        << "PROGRESS "
                                        << "preprocessing_ch "
                                        << percent
                                        << '\n';

                                    row.visualization_overhead_ms
                                        += elapsed_ms(
                                            event_started
                                        );
                                }
                        };

                    const auto started =
                        Clock::now();

                    ch_index =
                        route_cpp17::
                        preprocess_ch(
                            graph,
                            callback
                        );

                    row.preprocess_ms =
                        std::max(
                            0.0,
                            elapsed_ms(started)
                            - row
                            .visualization_overhead_ms
                        );

                    route_benchmark::
                        save_ch_cache(
                            cache,
                            graph.size(),
                            *ch_index,
                            row.preprocess_ms
                        );
                }

                row.index_edges =
                    ch_index->arcs.size();

                row.shortcut_edges =
                    row.index_edges
                    - original_edges;

                std::size_t index_ints = 0;

                for (
                    const auto& list :
                    ch_index->upward_out
                    ) {
                    index_ints += list.size();
                }

                for (
                    const auto& list :
                    ch_index->upward_in
                    ) {
                    index_ints += list.size();
                }

                row.estimated_index_mb =
                    (
                        row.index_edges
                        * sizeof(route_cpp17::CHArc)
                        + index_ints
                        * sizeof(int)
                        + graph.size()
                        * sizeof(int)
                        )
                    / (1024.0 * 1024.0);

            }
            else {
                row.cache_hit = true;
                row.preprocess_ms = 0.0;
            }

            preprocess_rows.push_back(row);
            preprocess_by_name[algorithm] = row;

            std::cout
                << "CACHE "
                << algorithm
                << ' '
                << (
                    row.cache_hit
                    ? "hit"
                    : "built"
                    )
                << '\n';

            std::cout
                << "PROGRESS preprocessing_"
                << algorithm
                << " 100\n";
        }

        write_preprocess(
            options.output
            / "preprocess_summary.csv",
            preprocess_rows
        );

        if (options.prepare_only) {
            std::cout
                << "PROGRESS completed 100\n";

            std::cout
                << "CACHE_READY "
                << options.cache_dir.u8string()
                << '\n';

            return 0;
        }

        std::vector<
            route_benchmark::QueryPair
        > queries;

        if (fs::exists(options.queries)) {
            queries =
                route_benchmark::load_queries(
                    options.queries
                );
        }
        else {
            if (options.generate_queries < 3) {
                throw std::runtime_error(
                    "query CSV is absent; "
                    "use --generate-queries >= 3"
                );
            }

            std::cout
                << "PROGRESS generating_queries 0\n";

            queries =
                route_benchmark::generate_queries(
                    graph,
                    options.generate_queries,
                    options.seed
                );

            route_benchmark::save_queries(
                options.queries,
                queries
            );

            std::cout
                << "PROGRESS generating_queries 100\n";
        }

        if (queries.empty()) {
            throw std::runtime_error(
                "query set is empty"
            );
        }

        auto run = [&](
            const std::string& algorithm,
            int source,
            int target
            ) {
                if (algorithm == "dijkstra") {
                    return route_cpp17::dijkstra(
                        graph,
                        source,
                        target,
                        false
                    );
                }

                if (algorithm == "astar") {
                    return route_cpp17::astar(
                        graph,
                        source,
                        target,
                        *astar_scale,
                        false
                    );
                }

                if (
                    algorithm
                    == "bidirectional_astar"
                    ) {
                    return route_cpp17::
                        bidirectional_astar(
                            graph,
                            *bidirectional_index,
                            source,
                            target
                        );
                }

                return ch_index->query(
                    source,
                    target
                );
            };

        for (
            const auto& algorithm :
            options.algorithms
            ) {
            const std::size_t warmups =
                std::min<std::size_t>(
                    10,
                    queries.size()
                );

            for (
                std::size_t i = 0;
                i < warmups;
                ++i
                ) {
                (void)run(
                    algorithm,
                    queries[i].source,
                    queries[i].target
                );
            }
        }

        std::vector<QueryRow> rows;

        std::vector<double> baseline(
            queries.size(),
            route_cpp17::ROUTE_INF
        );

        for (
            std::size_t index = 0;
            index < queries.size();
            ++index
            ) {
            baseline[index] =
                route_cpp17::dijkstra(
                    graph,
                    queries[index].source,
                    queries[index].target,
                    false
                ).cost;
        }

        const std::size_t total_runs =
            options.algorithms.size()
            * queries.size();

        std::size_t completed = 0;

        for (
            const auto& algorithm :
            options.algorithms
            ) {
            for (
                std::size_t index = 0;
                index < queries.size();
                ++index
                ) {
                std::vector<double> times;
                PathResult result;

                for (
                    int repetition = 0;
                    repetition < options.repeat;
                    ++repetition
                    ) {
                    const auto started =
                        Clock::now();

                    result = run(
                        algorithm,
                        queries[index].source,
                        queries[index].target
                    );

                    times.push_back(
                        elapsed_ms(started)
                    );
                }

                rows.push_back(
                    {
                        options.dataset,
                        algorithm,
                        queries[index],
                        result.cost,
                        median(std::move(times)),
                        result.expanded,
                        result.queue_pushes,
                        result.edges.size(),
                        same_cost(
                            result.cost,
                            baseline[index]
                        ),
                    }
                );

                ++completed;

                const int percent =
                    static_cast<int>(
                        100.0
                        * completed
                        / total_runs
                        );

                std::cout
                    << "PROGRESS running_queries "
                    << percent
                    << '\n';
            }
        }

        std::map<
            std::string,
            AlgorithmStats
        > stats;

        std::map<
            std::string,
            double
        > preprocess_time;

        for (
            const auto& algorithm :
            options.algorithms
            ) {
            stats[algorithm] =
                compute_stats(
                    rows,
                    algorithm
                );

            preprocess_time[algorithm] =
                preprocess_by_name
                .at(algorithm)
                .preprocess_ms;
        }

        write_query_rows(
            options.output / "query_raw.csv",
            rows
        );

        write_preprocess(
            options.output
            / "preprocess_summary.csv",
            preprocess_rows
        );

        write_total_cost(
            options.output / "total_cost.csv",
            options.algorithms,
            stats,
            preprocess_time,
            static_cast<int>(queries.size())
        );

        write_summary(
            options.output / "summary.json",
            options,
            graph.size(),
            original_edges,
            graph_load_ms,
            options.algorithms,
            stats,
            preprocess_by_name
        );

        std::cout
            << "PROGRESS completed 100\n";

        std::cout
            << "RESULT "
            << (
                options.output
                / "summary.json"
                ).u8string()
            << '\n';

        return 0;

    }
    catch (
        const std::exception& error
        ) {
        std::cerr
            << "ERROR "
            << error.what()
            << '\n';

        return 1;
    }
}