#include "query_io.hpp"

#include "algorithms.hpp"

#include <algorithm>
#include <fstream>
#include <random>
#include <sstream>
#include <stdexcept>
#include <unordered_set>
#include <utility>

namespace route_benchmark {
namespace {

std::vector<int> largest_strong_component(const route_cpp17::RoadGraph& graph) {
    const int n = static_cast<int>(graph.size());
    std::vector<std::vector<int>> incoming(static_cast<std::size_t>(n));
    for (int u = 0; u < n; ++u) {
        for (const auto& edge : graph.outgoing[u]) incoming[edge.to].push_back(u);
    }

    std::vector<char> seen(static_cast<std::size_t>(n), false);
    std::vector<int> order;
    order.reserve(static_cast<std::size_t>(n));
    for (int start = 0; start < n; ++start) {
        if (seen[start]) continue;
        seen[start] = true;
        std::vector<std::pair<int, std::size_t>> stack{{start, 0}};
        while (!stack.empty()) {
            auto& [u, next] = stack.back();
            if (next < graph.outgoing[u].size()) {
                const int v = graph.outgoing[u][next++].to;
                if (!seen[v]) {
                    seen[v] = true;
                    stack.emplace_back(v, 0);
                }
            } else {
                order.push_back(u);
                stack.pop_back();
            }
        }
    }

    std::fill(seen.begin(), seen.end(), false);
    std::vector<int> largest;
    for (auto it = order.rbegin(); it != order.rend(); ++it) {
        const int start = *it;
        if (seen[start]) continue;
        std::vector<int> component;
        std::vector<int> stack{start};
        seen[start] = true;
        while (!stack.empty()) {
            const int u = stack.back();
            stack.pop_back();
            component.push_back(u);
            for (int v : incoming[u]) {
                if (!seen[v]) {
                    seen[v] = true;
                    stack.push_back(v);
                }
            }
        }
        if (component.size() > largest.size()) largest = std::move(component);
    }
    return largest;
}

std::vector<std::string> split_csv(const std::string& line) {
    std::vector<std::string> fields;
    std::stringstream stream(line);
    std::string field;
    while (std::getline(stream, field, ',')) fields.push_back(field);
    return fields;
}

} // namespace

std::vector<QueryPair> load_queries(const std::filesystem::path& path) {
    std::ifstream input(path);
    if (!input) throw std::runtime_error("cannot open query CSV: " + path.u8string());
    std::string line;
    std::getline(input, line);
    std::vector<QueryPair> result;
    while (std::getline(input, line)) {
        if (line.empty()) continue;
        const auto fields = split_csv(line);
        if (fields.size() < 5) throw std::runtime_error("invalid query CSV row");
        result.push_back({std::stoi(fields[0]), fields[1], std::stoi(fields[2]),
                          std::stoi(fields[3]), std::stod(fields[4])});
    }
    return result;
}

void save_queries(const std::filesystem::path& path,
                  const std::vector<QueryPair>& queries) {
    if (!path.parent_path().empty()) {
        std::filesystem::create_directories(path.parent_path());
    }
    std::ofstream output(path);
    if (!output) throw std::runtime_error("cannot write query CSV: " + path.u8string());
    output << "query_id,distance_level,source,target,straight_distance_m\n";
    for (const auto& q : queries) {
        output << q.query_id << ',' << q.distance_level << ',' << q.source << ','
               << q.target << ',' << q.straight_distance_m << '\n';
    }
}

std::vector<QueryPair> generate_queries(const route_cpp17::RoadGraph& graph,
                                        int count,
                                        std::uint32_t seed) {
    if (count < 3) throw std::invalid_argument("query count must be at least 3");
    const auto component = largest_strong_component(graph);
    if (component.size() < 2) {
        throw std::runtime_error("largest strongly connected component has fewer than 2 nodes");
    }

    std::mt19937 random(seed);
    std::uniform_int_distribution<std::size_t> pick(0, component.size() - 1);
    const std::size_t wanted = std::max<std::size_t>(
        static_cast<std::size_t>(count) * 12, static_cast<std::size_t>(count));
    const std::size_t max_pairs = component.size() * (component.size() - 1);
    const std::size_t target_candidates = std::min(wanted, max_pairs);
    std::unordered_set<std::uint64_t> used;
    std::vector<QueryPair> candidates;
    candidates.reserve(target_candidates);
    std::size_t attempts = 0;
    const std::size_t attempt_limit = target_candidates * 100 + 1000;
    while (candidates.size() < target_candidates && attempts++ < attempt_limit) {
        const int source = component[pick(random)];
        const int target = component[pick(random)];
        if (source == target) continue;
        const std::uint64_t key =
            (static_cast<std::uint64_t>(static_cast<std::uint32_t>(source)) << 32U) |
            static_cast<std::uint32_t>(target);
        if (!used.insert(key).second) continue;
        const double straight = route_cpp17::astar_haversine_distance(
            graph.coordinates[source], graph.coordinates[target]);
        candidates.push_back({0, "", source, target, straight});
    }
    if (candidates.size() < static_cast<std::size_t>(count)) {
        throw std::runtime_error("unable to generate enough unique query pairs");
    }

    std::sort(candidates.begin(), candidates.end(), [](const auto& a, const auto& b) {
        return a.straight_distance_m < b.straight_distance_m;
    });
    const int short_count = count / 3;
    const int medium_count = count / 3;
    const int long_count = count - short_count - medium_count;
    const std::size_t first_cut = candidates.size() / 3;
    const std::size_t second_cut = candidates.size() * 2 / 3;

    std::vector<QueryPair> result;
    result.reserve(static_cast<std::size_t>(count));
    auto append_range = [&](std::size_t begin, std::size_t end, int amount,
                            const std::string& level) {
        if (end <= begin || static_cast<std::size_t>(amount) > end - begin) {
            throw std::runtime_error("not enough candidates in distance group");
        }
        const double step = static_cast<double>(end - begin) / amount;
        for (int i = 0; i < amount; ++i) {
            const std::size_t index = begin + std::min<std::size_t>(
                static_cast<std::size_t>(i * step), end - begin - 1);
            auto query = candidates[index];
            query.query_id = static_cast<int>(result.size()) + 1;
            query.distance_level = level;
            result.push_back(std::move(query));
        }
    };
    append_range(0, first_cut, short_count, "short");
    append_range(first_cut, second_cut, medium_count, "medium");
    append_range(second_cut, candidates.size(), long_count, "long");
    return result;
}

} // namespace route_benchmark
