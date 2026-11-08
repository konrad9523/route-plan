#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

namespace route_cpp17 {

inline constexpr double ROUTE_INF = std::numeric_limits<double>::infinity();

struct Edge {
    int to = -1;
    double weight = 0.0;
    std::int64_t edge_id = -1;
};

struct Coordinate {
    double lon = 0.0;
    double lat = 0.0;
};

struct RoadGraph {
    std::vector<std::vector<Edge>> outgoing;
    std::vector<Coordinate> coordinates;
    std::size_t size() const noexcept { return outgoing.size(); }
};

struct PathResult {
    std::vector<int> nodes;
    std::vector<std::int64_t> edges;
    double cost = ROUTE_INF;
    std::size_t expanded = 0;
    std::size_t queue_pushes = 0;

    bool reachable() const noexcept { return std::isfinite(cost); }
};

struct QueueItem {
    double key = 0.0;
    std::size_t serial = 0;
    int node = -1;
    bool operator>(const QueueItem& other) const noexcept {
        if (key != other.key) return key > other.key;
        return serial > other.serial;
    }
};

inline void validate_graph(const RoadGraph& graph, bool require_coordinates) {
    const int n = static_cast<int>(graph.outgoing.size());
    if (require_coordinates && graph.coordinates.size() != graph.outgoing.size()) {
        throw std::invalid_argument("coordinates size must equal graph size");
    }
    for (int u = 0; u < n; ++u) {
        for (const auto& edge : graph.outgoing[u]) {
            if (edge.to < 0 || edge.to >= n) {
                throw std::invalid_argument("edge target index is invalid");
            }
            if (!std::isfinite(edge.weight) || edge.weight < 0.0) {
                throw std::invalid_argument("edge weight must be finite and non-negative");
            }
        }
    }
}

namespace detail {

// 用查询代数代替每次 O(V) 清空。四种算法的新版实现共用该工作区容器。
template <typename T>
class EpochArray {
public:
    void begin(std::size_t size, const T& default_value) {
        default_value_ = default_value;
        if (values_.size() != size) {
            values_.assign(size, default_value_);
            stamps_.assign(size, 0);
            epoch_ = 1;
            return;
        }
        ++epoch_;
        if (epoch_ == 0) {
            std::fill(stamps_.begin(), stamps_.end(), 0);
            epoch_ = 1;
        }
    }

    T get(std::size_t index) const {
        return stamps_[index] == epoch_ ? values_[index] : default_value_;
    }

    T& ref(std::size_t index) {
        touch(index);
        return values_[index];
    }

    void set(std::size_t index, const T& value) {
        touch(index);
        values_[index] = value;
    }

private:
    void touch(std::size_t index) {
        if (stamps_[index] != epoch_) {
            stamps_[index] = epoch_;
            values_[index] = default_value_;
        }
    }

    std::vector<T> values_;
    std::vector<std::uint32_t> stamps_;
    std::uint32_t epoch_ = 0;
    T default_value_{};
};

} // namespace detail

} // namespace route_cpp17
