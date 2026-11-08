#pragma once

#include "graph_types.hpp"

#include <functional>
#include <vector>

namespace route_cpp17 {

PathResult dijkstra(const RoadGraph& graph, int start, int goal,
                    bool validate_input = true);

double astar_haversine_distance(const Coordinate& first,
                                 const Coordinate& second);
double estimate_astar_haversine_scale(const RoadGraph& graph);
PathResult astar(const RoadGraph& graph, int start, int goal,
                 double heuristic_scale = -1.0,
                 bool validate_input = true);

struct BidirectionalAStarIndex {
    struct SpherePoint {
        double x = 0.0;
        double y = 0.0;
        double z = 0.0;
    };

    std::vector<std::vector<Edge>> incoming;
    // Unit-sphere coordinates make the per-query geographic lower bound a
    // few arithmetic operations instead of two full Haversine evaluations.
    std::vector<SpherePoint> sphere_points;
    double heuristic_scale = 0.0;
};

BidirectionalAStarIndex prepare_bidirectional_astar(
    const RoadGraph& graph, double heuristic_scale = -1.0);
PathResult bidirectional_astar(const RoadGraph& graph,
                               const BidirectionalAStarIndex& index,
                               int start, int goal);
PathResult bidirectional_astar(const RoadGraph& graph, int start, int goal,
                               double heuristic_scale = -1.0);

struct CHArc {
    int source = -1;
    int target = -1;
    double weight = 0.0;
    std::int64_t original_edge_id = -1;
    int left = -1;
    int right = -1;
};

class ContractionHierarchy {
public:
    std::vector<int> rank;
    std::vector<CHArc> arcs;
    std::vector<std::vector<int>> upward_out;
    std::vector<std::vector<int>> upward_in;

    PathResult query(int start, int goal) const;
};

struct CHProgressEvent {
    int step = 0;
    int total = 0;
    int contracted_node = -1;
    std::size_t arc_count = 0;
    std::size_t shortcuts_added = 0;
};

using CHProgressCallback = std::function<void(const CHProgressEvent&)>;
ContractionHierarchy preprocess_ch(const RoadGraph& graph,
                                   const CHProgressCallback& progress = {});

} // namespace route_cpp17
