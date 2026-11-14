#include "bidirectional_astar_variants.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <functional>
#include <limits>
#include <queue>
#include <stdexcept>
#include <utility>

namespace route_cpp17 {

namespace {

constexpr double EARTH_RADIUS_M = 6371000.0;
constexpr double PI = 3.141592653589793238462643383279502884;
constexpr double REDUCED_WEIGHT_TOLERANCE = 1e-7;

void validate_coordinates(const RoadGraph& graph) {
    for (const Coordinate& coordinate : graph.coordinates) {
        if (!std::isfinite(coordinate.lon) || !std::isfinite(coordinate.lat) ||
            coordinate.lat < -90.0 || coordinate.lat > 90.0) {
            throw std::invalid_argument("graph contains an invalid coordinate");
        }
    }
}

std::vector<int> strongly_connected_components(
    const RoadGraph& graph,
    const std::vector<std::vector<Edge>>& incoming) {

    const int n = static_cast<int>(graph.size());
    std::vector<char> visited(static_cast<std::size_t>(n), false);
    std::vector<int> finish_order;
    finish_order.reserve(static_cast<std::size_t>(n));
    std::vector<std::pair<int, std::size_t>> stack;

    for (int root = 0; root < n; ++root) {
        if (visited[static_cast<std::size_t>(root)]) continue;
        visited[static_cast<std::size_t>(root)] = true;
        stack.emplace_back(root, 0);
        while (!stack.empty()) {
            int node = stack.back().first;
            std::size_t& next_edge = stack.back().second;
            const auto& outgoing = graph.outgoing[static_cast<std::size_t>(node)];
            if (next_edge < outgoing.size()) {
                const int next = outgoing[next_edge++].to;
                if (!visited[static_cast<std::size_t>(next)]) {
                    visited[static_cast<std::size_t>(next)] = true;
                    stack.emplace_back(next, 0);
                }
            } else {
                finish_order.push_back(node);
                stack.pop_back();
            }
        }
    }

    std::vector<int> component(static_cast<std::size_t>(n), -1);
    int component_id = 0;
    std::vector<int> nodes;
    for (auto it = finish_order.rbegin(); it != finish_order.rend(); ++it) {
        if (component[static_cast<std::size_t>(*it)] >= 0) continue;
        component[static_cast<std::size_t>(*it)] = component_id;
        nodes.push_back(*it);
        while (!nodes.empty()) {
            const int node = nodes.back();
            nodes.pop_back();
            for (const Edge& edge : incoming[static_cast<std::size_t>(node)]) {
                const int predecessor = edge.to;
                if (component[static_cast<std::size_t>(predecessor)] < 0) {
                    component[static_cast<std::size_t>(predecessor)] = component_id;
                    nodes.push_back(predecessor);
                }
            }
        }
        ++component_id;
    }
    return component;
}

std::vector<double> dijkstra_distances(
    const std::vector<std::vector<Edge>>& adjacency,
    int source) {

    std::vector<double> distances(adjacency.size(), ROUTE_INF);
    using Item = std::pair<double, int>;
    std::priority_queue<Item, std::vector<Item>, std::greater<Item>> queue;
    distances[static_cast<std::size_t>(source)] = 0.0;
    queue.emplace(0.0, source);

    while (!queue.empty()) {
        const auto [distance, node] = queue.top();
        queue.pop();
        if (distance != distances[static_cast<std::size_t>(node)]) continue;
        for (const Edge& edge : adjacency[static_cast<std::size_t>(node)]) {
            const double candidate = distance + edge.weight;
            double& old = distances[static_cast<std::size_t>(edge.to)];
            if (candidate < old) {
                old = candidate;
                queue.emplace(candidate, edge.to);
            }
        }
    }
    return distances;
}

double chord_distance(const BidirectionalAStarIndex::SpherePoint& first,
                      const BidirectionalAStarIndex::SpherePoint& second) {
    const double dx = first.x - second.x;
    const double dy = first.y - second.y;
    const double dz = first.z - second.z;
    return EARTH_RADIUS_M * std::sqrt(dx * dx + dy * dy + dz * dz);
}

double alt_to_goal(const BidirectionalAStarVariantIndex& index,
                   int node, int goal, std::size_t landmark_count) {
    const std::size_t n = index.base.sphere_points.size();
    double lower_bound = 0.0;
    for (std::size_t i = 0; i < landmark_count; ++i) {
        const std::size_t row = i * n;
        const double landmark_to_goal = index.from_landmark[row + static_cast<std::size_t>(goal)];
        const double landmark_to_node = index.from_landmark[row + static_cast<std::size_t>(node)];
        if (std::isfinite(landmark_to_goal) && std::isfinite(landmark_to_node)) {
            lower_bound = std::max(lower_bound, landmark_to_goal - landmark_to_node);
        }

        const double node_to_landmark = index.to_landmark[row + static_cast<std::size_t>(node)];
        const double goal_to_landmark = index.to_landmark[row + static_cast<std::size_t>(goal)];
        if (std::isfinite(node_to_landmark) && std::isfinite(goal_to_landmark)) {
            lower_bound = std::max(lower_bound, node_to_landmark - goal_to_landmark);
        }
    }
    return std::max(0.0, lower_bound);
}

double alt_from_start(const BidirectionalAStarVariantIndex& index,
                      int start, int node, std::size_t landmark_count) {
    const std::size_t n = index.base.sphere_points.size();
    double lower_bound = 0.0;
    for (std::size_t i = 0; i < landmark_count; ++i) {
        const std::size_t row = i * n;
        const double landmark_to_node = index.from_landmark[row + static_cast<std::size_t>(node)];
        const double landmark_to_start = index.from_landmark[row + static_cast<std::size_t>(start)];
        if (std::isfinite(landmark_to_node) && std::isfinite(landmark_to_start)) {
            lower_bound = std::max(lower_bound, landmark_to_node - landmark_to_start);
        }

        const double start_to_landmark = index.to_landmark[row + static_cast<std::size_t>(start)];
        const double node_to_landmark = index.to_landmark[row + static_cast<std::size_t>(node)];
        if (std::isfinite(start_to_landmark) && std::isfinite(node_to_landmark)) {
            lower_bound = std::max(lower_bound, start_to_landmark - node_to_landmark);
        }
    }
    return std::max(0.0, lower_bound);
}

struct ResearchItem {
    double key = 0.0;
    double g = 0.0;
    std::size_t serial = 0;
    int node = -1;
    bool operator>(const ResearchItem& other) const noexcept {
        if (key != other.key) return key > other.key;
        return serial > other.serial;
    }
};

using ResearchQueue = std::priority_queue<
    ResearchItem, std::vector<ResearchItem>, std::greater<ResearchItem>>;

class SearchOpenQueue {
public:
    SearchOpenQueue(BidirectionalAStarQueue kind,
                    detail::EpochArray<int>* positions)
        : kind_(kind), positions_(positions) {}

    bool empty() const noexcept {
        return kind_ == BidirectionalAStarQueue::LAZY_DUPLICATES
            ? lazy_.empty() : heap_.empty();
    }
    std::size_t size() const noexcept {
        return kind_ == BidirectionalAStarQueue::LAZY_DUPLICATES
            ? lazy_.size() : heap_.size();
    }
    const QueueItem& top() const {
        return kind_ == BidirectionalAStarQueue::LAZY_DUPLICATES
            ? lazy_.top() : heap_.front();
    }

    // Returns true when an existing indexed entry was decreased.
    bool push(const QueueItem& item) {
        if (kind_ == BidirectionalAStarQueue::LAZY_DUPLICATES) {
            lazy_.push(item);
            return false;
        }

        const int old_position = positions_->get(static_cast<std::size_t>(item.node));
        if (old_position >= 0) {
            const std::size_t position = static_cast<std::size_t>(old_position);
            if (!(item.key < heap_[position].key)) return true;
            heap_[position] = item;
            sift_up(position);
            return true;
        }

        const std::size_t position = heap_.size();
        heap_.push_back(item);
        positions_->set(static_cast<std::size_t>(item.node),
                        static_cast<int>(position));
        sift_up(position);
        return false;
    }

    void pop() {
        if (kind_ == BidirectionalAStarQueue::LAZY_DUPLICATES) {
            lazy_.pop();
            return;
        }

        const int removed_node = heap_.front().node;
        positions_->set(static_cast<std::size_t>(removed_node), -1);
        if (heap_.size() == 1) {
            heap_.pop_back();
            return;
        }

        heap_.front() = heap_.back();
        heap_.pop_back();
        positions_->set(static_cast<std::size_t>(heap_.front().node), 0);
        sift_down(0);
    }

private:
    void swap_entries(std::size_t first, std::size_t second) {
        std::swap(heap_[first], heap_[second]);
        positions_->set(static_cast<std::size_t>(heap_[first].node),
                        static_cast<int>(first));
        positions_->set(static_cast<std::size_t>(heap_[second].node),
                        static_cast<int>(second));
    }

    void sift_up(std::size_t position) {
        while (position > 0) {
            const std::size_t parent = (position - 1) / 2;
            if (!(heap_[parent] > heap_[position])) break;
            swap_entries(position, parent);
            position = parent;
        }
    }

    void sift_down(std::size_t position) {
        for (;;) {
            const std::size_t left = position * 2 + 1;
            if (left >= heap_.size()) return;
            const std::size_t right = left + 1;
            std::size_t best = left;
            if (right < heap_.size() && heap_[left] > heap_[right]) best = right;
            if (!(heap_[position] > heap_[best])) return;
            swap_entries(position, best);
            position = best;
        }
    }

    BidirectionalAStarQueue kind_;
    detail::EpochArray<int>* positions_;
    std::priority_queue<QueueItem, std::vector<QueueItem>,
                        std::greater<QueueItem>> lazy_;
    std::vector<QueueItem> heap_;
};

struct ResearchSideQueues {
    ResearchQueue priority;
    ResearchQueue by_f;
    ResearchQueue by_g;
};

struct ResearchWorkspace {
    detail::EpochArray<double> forward_g;
    detail::EpochArray<double> backward_g;
    detail::EpochArray<double> forward_h;
    detail::EpochArray<double> backward_h;
    detail::EpochArray<double> forward_parent_weight;
    detail::EpochArray<double> backward_next_weight;
    detail::EpochArray<int> forward_parent;
    detail::EpochArray<int> backward_next;
    detail::EpochArray<std::int64_t> forward_edge;
    detail::EpochArray<std::int64_t> backward_edge;
    detail::EpochArray<char> forward_settled;
    detail::EpochArray<char> backward_settled;
};

double research_heuristic(
    const BidirectionalAStarVariantIndex& index,
    BidirectionalAStarHeuristic heuristic,
    int node,
    int endpoint,
    bool estimate_to_goal,
    std::size_t landmark_count) {

    const double geometric = index.base.heuristic_scale * chord_distance(
        index.base.sphere_points[static_cast<std::size_t>(node)],
        index.base.sphere_points[static_cast<std::size_t>(endpoint)]);
    if (heuristic == BidirectionalAStarHeuristic::H0) return geometric;

    const double alt = estimate_to_goal
        ? alt_to_goal(index, node, endpoint, landmark_count)
        : alt_from_start(index, endpoint, node, landmark_count);
    return heuristic == BidirectionalAStarHeuristic::ALT
        ? alt
        : std::max(geometric, alt);
}

PathResult run_research_bidirectional(
    const RoadGraph& graph,
    const BidirectionalAStarVariantIndex& index,
    int start,
    int goal,
    BidirectionalAStarLayer layer,
    BidirectionalAStarHeuristic heuristic,
    std::size_t landmark_count,
    BidirectionalAStarStats* stats,
    BidirectionalAStarDirectionPolicy direction_policy,
    BidirectionalAStarMeetingPolicy meeting_policy,
    bool strict_lower_bound,
    bool capture_trace) {

    const bool use_alt = heuristic != BidirectionalAStarHeuristic::H0;
    const std::size_t n = graph.size();
    if (use_alt) {
        if (landmark_count == 0 || landmark_count > index.landmarks.size() ||
            index.component_of_node.size() != n) {
            throw std::invalid_argument("ALT tables are not prepared for this landmark count");
        }
        if (index.component_of_node[static_cast<std::size_t>(start)] != index.landmark_component ||
            index.component_of_node[static_cast<std::size_t>(goal)] != index.landmark_component) {
            throw std::invalid_argument("ALT query endpoints must be in the landmark component");
        }
    } else if (landmark_count != 0) {
        throw std::invalid_argument("landmark_count must be zero when using H0");
    }

    if (start == goal) {
        if (stats) {
            stats->expanded_states = 1;
            stats->forward_expanded = 1;
            stats->queue_pushes = 1;
        }
        PathResult result{{start}, {}, 0.0, 1, 1};
        if (capture_trace) result.expanded_order = {start};
        return result;
    }

    thread_local ResearchWorkspace workspace;
    workspace.forward_g.begin(n, ROUTE_INF);
    workspace.backward_g.begin(n, ROUTE_INF);
    workspace.forward_h.begin(n, std::numeric_limits<double>::quiet_NaN());
    workspace.backward_h.begin(n, std::numeric_limits<double>::quiet_NaN());
    workspace.forward_parent.begin(n, -1);
    workspace.backward_next.begin(n, -1);
    workspace.forward_edge.begin(n, -1);
    workspace.backward_edge.begin(n, -1);
    workspace.forward_parent_weight.begin(n, 0.0);
    workspace.backward_next_weight.begin(n, 0.0);
    workspace.forward_settled.begin(n, false);
    workspace.backward_settled.begin(n, false);

    auto h_forward = [&](int node) {
        double& value = workspace.forward_h.ref(static_cast<std::size_t>(node));
        if (std::isnan(value)) {
            value = research_heuristic(index, heuristic, node, goal, true, landmark_count);
            if (stats) ++stats->heuristic_evaluations;
        }
        return value;
    };
    auto h_backward = [&](int node) {
        double& value = workspace.backward_h.ref(static_cast<std::size_t>(node));
        if (std::isnan(value)) {
            value = research_heuristic(index, heuristic, node, start, false, landmark_count);
            if (stats) ++stats->heuristic_evaluations;
        }
        return value;
    };

    double start_potential = 0.0;
    double goal_potential = 0.0;
    if (layer == BidirectionalAStarLayer::L4_BAE_STAR &&
        direction_policy == BidirectionalAStarDirectionPolicy::MIN_REDUCED_KEY) {
        start_potential = (h_forward(start) - h_backward(start)) / 2.0;
        goal_potential = (h_forward(goal) - h_backward(goal)) / 2.0;
    }
    auto clean = [&](ResearchQueue& queue,
                     const detail::EpochArray<double>& distances,
                     const detail::EpochArray<char>& settled) {
        while (!queue.empty() &&
               (settled.get(static_cast<std::size_t>(queue.top().node)) ||
                queue.top().g != distances.get(static_cast<std::size_t>(queue.top().node)))) {
            queue.pop();
            if (stats) ++stats->stale_pops;
        }
    };
    ResearchSideQueues forward_queues, backward_queues;
    std::size_t serial = 0;
    std::size_t expanded = 0;
    std::size_t logical_pushes = 0;
    std::vector<int> expanded_order;
    if (capture_trace) expanded_order.reserve(1024);
    double best = ROUTE_INF;
    int meeting = -1;
    workspace.forward_g.set(static_cast<std::size_t>(start), 0.0);
    workspace.backward_g.set(static_cast<std::size_t>(goal), 0.0);

    auto make_key = [&](bool forward, int node, double g) {
        if (layer == BidirectionalAStarLayer::L2_MM) {
            return std::max(g + (forward ? h_forward(node) : h_backward(node)),
                            2.0 * g);
        }
        if (layer == BidirectionalAStarLayer::L3_MM_EPSILON) {
            const std::size_t i = static_cast<std::size_t>(node);
            const double epsilon = forward
                ? index.minimum_outgoing_weight[i]
                : index.minimum_incoming_weight[i];
            const double edge_lower_bound = std::isfinite(epsilon) ? epsilon : 0.0;
            return std::max(g + (forward ? h_forward(node) : h_backward(node)),
                            2.0 * g + edge_lower_bound);
        }
        if (layer == BidirectionalAStarLayer::L4_BAE_STAR ||
            layer == BidirectionalAStarLayer::L5_BAE_F_BOUND) {
            // BAE*: b_D = f_D + (g_D - h_opposite).
            const double hf = h_forward(node);
            const double hb = h_backward(node);
            return forward ? 2.0 * g + hf - hb
                           : 2.0 * g + hb - hf;
        }
        throw std::logic_error("unsupported research-layer priority rule");
    };

    auto push_node = [&](bool forward, int node, double g) {
        ResearchSideQueues& side = forward ? forward_queues : backward_queues;
        const double key = make_key(forward, node, g);
        side.priority.push({key, g, serial++, node});
        if (layer == BidirectionalAStarLayer::L2_MM ||
            layer == BidirectionalAStarLayer::L3_MM_EPSILON) {
            const double f = g + (forward ? h_forward(node) : h_backward(node));
            side.by_f.push({f, g, serial++, node});
            side.by_g.push({g, g, serial++, node});
            if (stats) stats->auxiliary_queue_pushes += 2;
        } else if (layer == BidirectionalAStarLayer::L5_BAE_F_BOUND) {
            const double f = g + (forward ? h_forward(node) : h_backward(node));
            side.by_f.push({f, g, serial++, node});
            if (stats) ++stats->auxiliary_queue_pushes;
        }
        if (stats) ++stats->queue_pushes;
        ++logical_pushes;
    };

    push_node(true, start, 0.0);
    push_node(false, goal, 0.0);

    auto update_meeting = [&](int node) {
        const std::size_t i = static_cast<std::size_t>(node);
        const double gf = workspace.forward_g.get(i);
        const double gb = workspace.backward_g.get(i);
        if (std::isfinite(gf) && std::isfinite(gb) && gf + gb < best) {
            best = gf + gb;
            meeting = node;
            if (stats) ++stats->best_updates;
        }
    };

    auto relax = [&](bool forward, int from, const Edge& edge, double candidate) {
        const int to = edge.to;
        const std::size_t i = static_cast<std::size_t>(to);
        auto& distance = forward ? workspace.forward_g : workspace.backward_g;
        auto& settled = forward ? workspace.forward_settled : workspace.backward_settled;
        if (!(candidate < distance.get(i))) return;

        // Reopen a state if a strictly better label is found.
        distance.set(i, candidate);
        settled.set(i, false);
        if (forward) {
            workspace.forward_parent.set(i, from);
            workspace.forward_edge.set(i, edge.edge_id);
            workspace.forward_parent_weight.set(i, edge.weight);
        } else {
            workspace.backward_next.set(i, from);
            workspace.backward_edge.set(i, edge.edge_id);
            workspace.backward_next_weight.set(i, edge.weight);
        }

        push_node(forward, to, candidate);
        if (stats) ++stats->successful_relaxations;
        update_meeting(to);
    };

    bool next_forward = true;
    while (true) {
        clean(forward_queues.priority, workspace.forward_g, workspace.forward_settled);
        clean(backward_queues.priority, workspace.backward_g, workspace.backward_settled);
        if (layer == BidirectionalAStarLayer::L2_MM ||
            layer == BidirectionalAStarLayer::L3_MM_EPSILON ||
            layer == BidirectionalAStarLayer::L5_BAE_F_BOUND) {
            clean(forward_queues.by_f, workspace.forward_g, workspace.forward_settled);
            clean(backward_queues.by_f, workspace.backward_g, workspace.backward_settled);
        }
        if (layer == BidirectionalAStarLayer::L2_MM ||
            layer == BidirectionalAStarLayer::L3_MM_EPSILON) {
            clean(forward_queues.by_g, workspace.forward_g, workspace.forward_settled);
            clean(backward_queues.by_g, workspace.backward_g, workspace.backward_settled);
        }
        const bool has_forward = !forward_queues.priority.empty();
        const bool has_backward = !backward_queues.priority.empty();
        if (!has_forward || !has_backward) break;

        const double min_forward = forward_queues.priority.top().key;
        const double min_backward = backward_queues.priority.top().key;
        bool forward = true;
        const bool bae_order = layer == BidirectionalAStarLayer::L4_BAE_STAR ||
                               layer == BidirectionalAStarLayer::L5_BAE_F_BOUND;
        const bool alternate = direction_policy ==
                                   BidirectionalAStarDirectionPolicy::ALTERNATE ||
                               (direction_policy ==
                                    BidirectionalAStarDirectionPolicy::NATIVE &&
                                bae_order);
        if (alternate) {
            forward = (next_forward && has_forward) || !has_backward;
            next_forward = !forward;
        } else if (layer == BidirectionalAStarLayer::L4_BAE_STAR) {
            const double reduced_forward = direction_policy ==
                    BidirectionalAStarDirectionPolicy::MIN_REDUCED_KEY
                ? min_forward / 2.0 - start_potential
                : min_forward;
            const double reduced_backward = direction_policy ==
                    BidirectionalAStarDirectionPolicy::MIN_REDUCED_KEY
                ? min_backward / 2.0 + goal_potential
                : min_backward;
            forward = reduced_forward <= reduced_backward;
        } else {
            forward = forward_queues.priority.top().key <= backward_queues.priority.top().key;
        }

        const ResearchItem item = forward
            ? forward_queues.priority.top() : backward_queues.priority.top();
        if (std::isfinite(best)) {
            if (layer == BidirectionalAStarLayer::L4_BAE_STAR) {
                const double lower_bound = (min_forward + min_backward) / 2.0;
                if (strict_lower_bound ? best <= lower_bound
                                       : best <= lower_bound +
                                             1e-12 * std::max(1.0, std::abs(best))) {
                    break;
                }
            } else if (layer == BidirectionalAStarLayer::L5_BAE_F_BOUND) {
                const double lower_bound = std::max({
                    (min_forward + min_backward) / 2.0,
                    forward_queues.by_f.top().key,
                    backward_queues.by_f.top().key});
                if (best <= lower_bound + 1e-12 * std::max(1.0, std::abs(best))) break;
            } else if (layer == BidirectionalAStarLayer::L2_MM ||
                       layer == BidirectionalAStarLayer::L3_MM_EPSILON) {
                const double min_p = std::min(min_forward, min_backward);
                const double min_f = std::min(forward_queues.by_f.top().key,
                                              backward_queues.by_f.top().key);
                const double min_g_sum = forward_queues.by_g.top().key +
                                         backward_queues.by_g.top().key +
                                         index.minimum_edge_weight;
                const double lower_bound = std::max({min_p, min_f, min_g_sum});
                if (best <= lower_bound + 1e-12 * std::max(1.0, std::abs(best))) break;
            }
        }

        ResearchQueue& queue = forward
            ? forward_queues.priority : backward_queues.priority;
        queue.pop();
        const std::size_t u = static_cast<std::size_t>(item.node);
        auto& settled = forward ? workspace.forward_settled : workspace.backward_settled;
        auto& distance = forward ? workspace.forward_g : workspace.backward_g;
        if (item.g != distance.get(u) || settled.get(u)) {
            if (stats) ++stats->stale_pops;
            continue;
        }
        settled.set(u, true);
        ++expanded;
        if (capture_trace) expanded_order.push_back(u);
        if (stats) {
            if (forward) ++stats->forward_expanded;
            else ++stats->backward_expanded;
        }
        if (layer != BidirectionalAStarLayer::L1_EARLY_EXIT ||
            meeting_policy ==
                BidirectionalAStarMeetingPolicy::UPDATE_ON_RELAX_AND_POP) {
            update_meeting(item.node);
        }

        const auto& adjacency = forward
            ? graph.outgoing[u] : index.base.incoming[u];
        for (const Edge& edge : adjacency) {
            if (use_alt && index.component_of_node[static_cast<std::size_t>(edge.to)] !=
                               index.landmark_component) {
                continue;
            }
            if (stats) ++stats->scanned_edges;
            relax(forward, item.node, edge, item.g + edge.weight);
        }
    }

    if (stats) {
        stats->expanded_states = expanded;
        stats->queue_pushes = logical_pushes;
    }
    if (meeting < 0) {
        PathResult result{{}, {}, ROUTE_INF, expanded, logical_pushes};
        result.expanded_order = std::move(expanded_order);
        return result;
    }

    PathResult result;
    result.cost = 0.0;
    result.expanded = expanded;
    result.queue_pushes = logical_pushes;
    result.expanded_order = std::move(expanded_order);
    std::vector<int> reverse_nodes{meeting};
    std::vector<std::int64_t> reverse_edges;
    int node = meeting;
    while (node != start) {
        const std::size_t i = static_cast<std::size_t>(node);
        const int parent = workspace.forward_parent.get(i);
        if (parent < 0 || reverse_nodes.size() > n) {
            throw std::runtime_error("incomplete or cyclic research-layer predecessor data");
        }
        result.cost += workspace.forward_parent_weight.get(i);
        reverse_edges.push_back(workspace.forward_edge.get(i));
        reverse_nodes.push_back(parent);
        node = parent;
    }
    std::reverse(reverse_nodes.begin(), reverse_nodes.end());
    std::reverse(reverse_edges.begin(), reverse_edges.end());
    result.nodes = std::move(reverse_nodes);
    result.edges = std::move(reverse_edges);
    node = meeting;
    while (node != goal) {
        const std::size_t i = static_cast<std::size_t>(node);
        const int next = workspace.backward_next.get(i);
        if (next < 0 || result.nodes.size() > n) {
            throw std::runtime_error("incomplete or cyclic research-layer successor data");
        }
        result.cost += workspace.backward_next_weight.get(i);
        result.edges.push_back(workspace.backward_edge.get(i));
        result.nodes.push_back(next);
        node = next;
    }
    return result;
}

} // namespace

double astar_haversine_distance(const Coordinate& first,
                               const Coordinate& second) {
    if (!std::isfinite(first.lon) || !std::isfinite(first.lat) ||
        !std::isfinite(second.lon) || !std::isfinite(second.lat) ||
        first.lat < -90.0 || first.lat > 90.0 ||
        second.lat < -90.0 || second.lat > 90.0) {
        throw std::invalid_argument("coordinate is invalid");
    }
    const double lat1 = first.lat * PI / 180.0;
    const double lat2 = second.lat * PI / 180.0;
    const double delta_lat = (second.lat - first.lat) * PI / 180.0;
    const double delta_lon = (second.lon - first.lon) * PI / 180.0;
    const double sin_lat = std::sin(delta_lat / 2.0);
    const double sin_lon = std::sin(delta_lon / 2.0);
    const double a = std::clamp(
        sin_lat * sin_lat + std::cos(lat1) * std::cos(lat2) * sin_lon * sin_lon,
        0.0, 1.0);
    return EARTH_RADIUS_M * 2.0 *
           std::atan2(std::sqrt(a), std::sqrt(1.0 - a));
}

double estimate_astar_haversine_scale(const RoadGraph& graph) {
    validate_graph(graph, true);
    validate_coordinates(graph);
    double scale = ROUTE_INF;
    for (int u = 0; u < static_cast<int>(graph.size()); ++u) {
        for (const Edge& edge : graph.outgoing[static_cast<std::size_t>(u)]) {
            const double length = astar_haversine_distance(
                graph.coordinates[static_cast<std::size_t>(u)],
                graph.coordinates[static_cast<std::size_t>(edge.to)]);
            if (length > 0.0) scale = std::min(scale, edge.weight / length);
        }
    }
    return std::isfinite(scale)
        ? std::max(0.0, scale * (1.0 - 1e-12))
        : 0.0;
}

BidirectionalAStarVariantIndex prepare_bidirectional_astar_variants(
    const RoadGraph& graph,
    const std::vector<int>& landmark_ids,
    double heuristic_scale) {

    validate_graph(graph, true);
    validate_coordinates(graph);

    BidirectionalAStarVariantIndex index;
    index.base = prepare_bidirectional_astar(graph, heuristic_scale);
    index.minimum_edge_weight = ROUTE_INF;
    index.minimum_outgoing_weight.assign(graph.size(), ROUTE_INF);
    index.minimum_incoming_weight.assign(graph.size(), ROUTE_INF);
    for (std::size_t source = 0; source < graph.outgoing.size(); ++source) {
        for (const Edge& edge : graph.outgoing[source]) {
            index.minimum_edge_weight = std::min(index.minimum_edge_weight, edge.weight);
            index.minimum_outgoing_weight[source] =
                std::min(index.minimum_outgoing_weight[source], edge.weight);
            index.minimum_incoming_weight[static_cast<std::size_t>(edge.to)] =
                std::min(index.minimum_incoming_weight[static_cast<std::size_t>(edge.to)],
                         edge.weight);
        }
    }
    if (!std::isfinite(index.minimum_edge_weight)) index.minimum_edge_weight = 0.0;
    if (landmark_ids.empty()) return index;

    const auto alt_begin = std::chrono::steady_clock::now();
    index.component_of_node = strongly_connected_components(
        graph, index.base.incoming);
    std::vector<char> seen_landmark(graph.size(), false);
    int landmark_component = -1;
    for (const int landmark : landmark_ids) {
        if (landmark < 0 || landmark >= static_cast<int>(graph.size())) {
            throw std::invalid_argument("landmark index is invalid");
        }
        if (seen_landmark[static_cast<std::size_t>(landmark)]) {
            throw std::invalid_argument("landmark IDs must be unique");
        }
        seen_landmark[static_cast<std::size_t>(landmark)] = true;
        const int component = index.component_of_node[static_cast<std::size_t>(landmark)];
        if (landmark_component < 0) landmark_component = component;
        if (component != landmark_component) {
            throw std::invalid_argument(
                "ALT landmarks must belong to the same strongly connected component");
        }
    }
    index.landmarks = landmark_ids;
    index.landmark_component = landmark_component;

    const std::size_t n = graph.size();
    if (landmark_ids.size() > index.from_landmark.max_size() / n) {
        throw std::length_error("ALT distance table is too large");
    }
    const std::size_t table_size = landmark_ids.size() * n;
    index.from_landmark.resize(table_size, ROUTE_INF);
    index.to_landmark.resize(table_size, ROUTE_INF);
    index.alt_preprocess_ns_by_landmark.reserve(landmark_ids.size());

    for (std::size_t i = 0; i < landmark_ids.size(); ++i) {
        const int landmark = landmark_ids[i];
        const std::vector<double> from = dijkstra_distances(graph.outgoing, landmark);
        const std::vector<double> to = dijkstra_distances(index.base.incoming, landmark);
        const std::size_t row = i * n;
        std::copy(from.begin(), from.end(), index.from_landmark.begin() + row);
        std::copy(to.begin(), to.end(), index.to_landmark.begin() + row);
        const auto landmark_end = std::chrono::steady_clock::now();
        index.alt_preprocess_ns_by_landmark.push_back(static_cast<std::uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(
                landmark_end - alt_begin).count()));
    }
    const auto alt_end = std::chrono::steady_clock::now();
    index.alt_preprocess_ns = static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(alt_end - alt_begin).count());
    return index;
}

PathResult bidirectional_astar_variant(
    const RoadGraph& graph,
    const BidirectionalAStarVariantIndex& index,
    int start,
    int goal,
    BidirectionalAStarLayer layer,
    BidirectionalAStarHeuristic heuristic,
    std::size_t landmark_count,
    BidirectionalAStarStats* stats,
    BidirectionalAStarQueue queue_kind,
    BidirectionalAStarDirectionPolicy direction_policy,
    BidirectionalAStarMeetingPolicy meeting_policy,
    bool strict_lower_bound,
    bool capture_trace) {

    if (stats) *stats = {};
    if (layer == BidirectionalAStarLayer::L2_MM ||
        layer == BidirectionalAStarLayer::L3_MM_EPSILON ||
        layer == BidirectionalAStarLayer::L4_BAE_STAR ||
        layer == BidirectionalAStarLayer::L5_BAE_F_BOUND) {
        if (queue_kind != BidirectionalAStarQueue::LAZY_DUPLICATES) {
            throw std::invalid_argument("indexed heap is currently implemented for L1 only");
        }
        if (heuristic != BidirectionalAStarHeuristic::H0 &&
            heuristic != BidirectionalAStarHeuristic::ALT &&
            heuristic != BidirectionalAStarHeuristic::MAX) {
            throw std::invalid_argument("unsupported bidirectional A* heuristic");
        }
        const int n = static_cast<int>(graph.size());
        if (graph.coordinates.size() != graph.outgoing.size() ||
            index.base.incoming.size() != graph.outgoing.size() ||
            index.base.sphere_points.size() != graph.outgoing.size()) {
            throw std::invalid_argument("bidirectional A* index does not match graph size");
        }
        if (start < 0 || start >= n || goal < 0 || goal >= n) {
            throw std::invalid_argument("start or goal index is invalid");
        }
        const bool is_l4 = layer == BidirectionalAStarLayer::L4_BAE_STAR;
        if ((direction_policy != BidirectionalAStarDirectionPolicy::NATIVE ||
             meeting_policy != BidirectionalAStarMeetingPolicy::NATIVE ||
             strict_lower_bound) &&
            layer != BidirectionalAStarLayer::L1_EARLY_EXIT && !is_l4) {
            throw std::invalid_argument(
                "control policies are supported only for L1 and L4");
        }
        if (strict_lower_bound && !is_l4) {
            throw std::invalid_argument(
                "strict_lower_bound is supported only for L4");
        }
        return run_research_bidirectional(
            graph, index, start, goal, layer, heuristic, landmark_count, stats,
            direction_policy, meeting_policy, strict_lower_bound, capture_trace);
    }
    if (layer == BidirectionalAStarLayer::L0_RECEIVED) {
        if (queue_kind != BidirectionalAStarQueue::LAZY_DUPLICATES) {
            throw std::invalid_argument("L0 received implementation uses its original queue");
        }
        if (heuristic != BidirectionalAStarHeuristic::H0 || landmark_count != 0) {
            throw std::invalid_argument("L0_RECEIVED supports only H0");
        }
        if (direction_policy != BidirectionalAStarDirectionPolicy::NATIVE ||
            meeting_policy != BidirectionalAStarMeetingPolicy::NATIVE ||
            strict_lower_bound) {
            throw std::invalid_argument(
                "control policies are not available for L0_RECEIVED");
        }
        PathResult result = bidirectional_astar(graph, index.base, start, goal);
        if (stats) {
            stats->expanded_states = result.expanded;
            stats->queue_pushes = result.queue_pushes;
        }
        return result;
    }
    if (layer != BidirectionalAStarLayer::L1_EARLY_EXIT) {
        throw std::invalid_argument("unsupported bidirectional A* layer");
    }
    if (direction_policy != BidirectionalAStarDirectionPolicy::NATIVE &&
        direction_policy != BidirectionalAStarDirectionPolicy::ALTERNATE &&
        direction_policy != BidirectionalAStarDirectionPolicy::MIN_REDUCED_KEY) {
        throw std::invalid_argument("unsupported L1 direction policy");
    }
    if (meeting_policy != BidirectionalAStarMeetingPolicy::NATIVE &&
        meeting_policy !=
            BidirectionalAStarMeetingPolicy::UPDATE_ON_RELAX_AND_POP) {
        throw std::invalid_argument("unsupported L1 meeting policy");
    }
    if (strict_lower_bound) {
        throw std::invalid_argument(
            "strict_lower_bound is supported only for L4");
    }
    if (heuristic != BidirectionalAStarHeuristic::H0 &&
        heuristic != BidirectionalAStarHeuristic::ALT &&
        heuristic != BidirectionalAStarHeuristic::MAX) {
        throw std::invalid_argument("unsupported bidirectional A* heuristic");
    }
    if (queue_kind != BidirectionalAStarQueue::LAZY_DUPLICATES &&
        queue_kind != BidirectionalAStarQueue::INDEXED_BINARY_HEAP) {
        throw std::invalid_argument("unsupported bidirectional A* queue");
    }

    const int n = static_cast<int>(graph.size());
    if (graph.coordinates.size() != graph.outgoing.size() ||
        index.base.incoming.size() != graph.outgoing.size() ||
        index.base.sphere_points.size() != graph.outgoing.size()) {
        throw std::invalid_argument("bidirectional A* index does not match graph size");
    }
    if (start < 0 || start >= n || goal < 0 || goal >= n) {
        throw std::invalid_argument("start or goal index is invalid");
    }

    if (start == goal) {
        if (stats) {
            stats->expanded_states = 1;
            stats->forward_expanded = 1;
            stats->queue_pushes = 1;
        }
        return {{start}, {}, 0.0, 1, 1};
    }

    const bool use_alt = heuristic != BidirectionalAStarHeuristic::H0;
    if (use_alt) {
        if (landmark_count == 0 || landmark_count > index.landmarks.size() ||
            index.component_of_node.size() != graph.size()) {
            throw std::invalid_argument("ALT tables are not prepared for this landmark count");
        }
        if (index.component_of_node[static_cast<std::size_t>(start)] != index.landmark_component ||
            index.component_of_node[static_cast<std::size_t>(goal)] != index.landmark_component) {
            throw std::invalid_argument(
                "ALT query endpoints must be in the landmark component");
        }
    } else if (landmark_count != 0) {
        throw std::invalid_argument("landmark_count must be zero when using H0");
    }

    struct Workspace {
        detail::EpochArray<double> potential_cache;
        detail::EpochArray<double> forward_distance;
        detail::EpochArray<double> backward_distance;
        detail::EpochArray<int> forward_parent;
        detail::EpochArray<int> backward_next;
        detail::EpochArray<std::int64_t> forward_edge;
        detail::EpochArray<std::int64_t> backward_edge;
        detail::EpochArray<char> forward_settled;
        detail::EpochArray<char> backward_settled;
        detail::EpochArray<int> forward_heap_position;
        detail::EpochArray<int> backward_heap_position;
    };
    thread_local Workspace workspace;
    workspace.potential_cache.begin(n, std::numeric_limits<double>::quiet_NaN());
    workspace.forward_distance.begin(n, ROUTE_INF);
    workspace.backward_distance.begin(n, ROUTE_INF);
    workspace.forward_parent.begin(n, -1);
    workspace.backward_next.begin(n, -1);
    workspace.forward_edge.begin(n, -1);
    workspace.backward_edge.begin(n, -1);
    workspace.forward_settled.begin(n, false);
    workspace.backward_settled.begin(n, false);
    workspace.forward_heap_position.begin(n, -1);
    workspace.backward_heap_position.begin(n, -1);

    auto potential = [&](int node) {
        double& cached = workspace.potential_cache.ref(node);
        if (std::isnan(cached)) {
            const double geometric_to_goal = index.base.heuristic_scale * chord_distance(
                index.base.sphere_points[static_cast<std::size_t>(node)],
                index.base.sphere_points[static_cast<std::size_t>(goal)]);
            const double geometric_from_start = index.base.heuristic_scale * chord_distance(
                index.base.sphere_points[static_cast<std::size_t>(start)],
                index.base.sphere_points[static_cast<std::size_t>(node)]);
            double to_goal = geometric_to_goal;
            double from_start = geometric_from_start;
            if (use_alt) {
                const double alt_goal = alt_to_goal(index, node, goal, landmark_count);
                const double alt_start = alt_from_start(index, start, node, landmark_count);
                if (heuristic == BidirectionalAStarHeuristic::ALT) {
                    to_goal = alt_goal;
                    from_start = alt_start;
                } else {
                    to_goal = std::max(geometric_to_goal, alt_goal);
                    from_start = std::max(geometric_from_start, alt_start);
                }
            }
            cached = (to_goal - from_start) / 2.0;
            if (stats) ++stats->heuristic_evaluations;
        }
        return cached;
    };
    auto reduced_weight = [](double weight) {
        if (weight < -REDUCED_WEIGHT_TOLERANCE) {
            throw std::invalid_argument(
                "heuristic is inconsistent; reduced edge weight is negative");
        }
        return std::max(0.0, weight);
    };

    SearchOpenQueue forward_queue(queue_kind, &workspace.forward_heap_position);
    SearchOpenQueue backward_queue(queue_kind, &workspace.backward_heap_position);
    std::size_t serial = 0;
    workspace.forward_distance.set(start, 0.0);
    workspace.backward_distance.set(goal, 0.0);
    forward_queue.push({0.0, serial++, start});
    backward_queue.push({0.0, serial++, goal});

    double best = ROUTE_INF;
    int meeting = -1;
    std::size_t expanded = 0;
    std::size_t queue_pushes = 2;
    if (stats) stats->peak_open_entries = 2;
    auto clean_queue = [&](SearchOpenQueue& queue,
                           const detail::EpochArray<double>& distances,
                           const detail::EpochArray<char>& settled) {
        while (!queue.empty() &&
               (settled.get(queue.top().node) ||
                queue.top().key != distances.get(queue.top().node))) {
            queue.pop();
            if (stats) ++stats->stale_pops;
        }
    };
    auto update_meeting = [&](int node, double candidate) {
        if (candidate < best) {
            best = candidate;
            meeting = node;
            if (stats) ++stats->best_updates;
        }
    };

    bool next_forward = true;
    while (!forward_queue.empty() || !backward_queue.empty()) {
        clean_queue(forward_queue, workspace.forward_distance,
                    workspace.forward_settled);
        clean_queue(backward_queue, workspace.backward_distance,
                    workspace.backward_settled);
        // Once either Dijkstra frontier is exhausted, that direction has
        // finalized every reachable label; the opposite side cannot improve it.
        if (forward_queue.empty() || backward_queue.empty()) break;

        const double min_forward = forward_queue.top().key;
        const double min_backward = backward_queue.top().key;
        if (std::isfinite(best) && min_forward + min_backward >= best) break;

        const bool forward_turn = direction_policy ==
                BidirectionalAStarDirectionPolicy::ALTERNATE
            ? next_forward
            : min_forward <= min_backward;
        if (direction_policy == BidirectionalAStarDirectionPolicy::ALTERNATE) {
            next_forward = !next_forward;
        }

        if (forward_turn) {
            const QueueItem item = forward_queue.top();
            forward_queue.pop();
            const int u = item.node;
            if (workspace.forward_settled.get(u) ||
                item.key != workspace.forward_distance.get(u)) {
                if (stats) ++stats->stale_pops;
                continue;
            }
            workspace.forward_settled.set(u, true);
            ++expanded;
            if (stats) ++stats->forward_expanded;
            if (meeting_policy ==
                    BidirectionalAStarMeetingPolicy::UPDATE_ON_RELAX_AND_POP &&
                workspace.backward_distance.get(u) < ROUTE_INF) {
                update_meeting(
                    u, workspace.forward_distance.get(u) +
                           workspace.backward_distance.get(u));
            }
            const double potential_u = potential(u);

            for (const Edge& edge : graph.outgoing[static_cast<std::size_t>(u)]) {
                if (use_alt && index.component_of_node[static_cast<std::size_t>(edge.to)] !=
                                   index.landmark_component) {
                    continue;
                }
                if (stats) ++stats->scanned_edges;
                const double reduced = reduced_weight(
                    edge.weight + potential(edge.to) - potential_u);
                const double candidate =
                    workspace.forward_distance.get(u) + reduced;
                if (candidate < workspace.forward_distance.get(edge.to)) {
                    workspace.forward_distance.set(edge.to, candidate);
                    workspace.forward_parent.set(edge.to, u);
                    workspace.forward_edge.set(edge.to, edge.edge_id);
                    const bool decreased = forward_queue.push(
                        {candidate, serial++, edge.to});
                    ++queue_pushes;
                    if (stats) {
                        ++stats->successful_relaxations;
                        if (decreased) ++stats->queue_decreases;
                        stats->peak_open_entries = std::max(
                            stats->peak_open_entries,
                            forward_queue.size() + backward_queue.size());
                    }
                    if (workspace.backward_distance.get(edge.to) < ROUTE_INF) {
                        update_meeting(
                            edge.to, candidate +
                                         workspace.backward_distance.get(edge.to));
                    }
                }
            }
        } else {
            const QueueItem item = backward_queue.top();
            backward_queue.pop();
            const int v = item.node;
            if (workspace.backward_settled.get(v) ||
                item.key != workspace.backward_distance.get(v)) {
                if (stats) ++stats->stale_pops;
                continue;
            }
            workspace.backward_settled.set(v, true);
            ++expanded;
            if (stats) ++stats->backward_expanded;
            if (meeting_policy ==
                    BidirectionalAStarMeetingPolicy::UPDATE_ON_RELAX_AND_POP &&
                workspace.forward_distance.get(v) < ROUTE_INF) {
                update_meeting(
                    v, workspace.forward_distance.get(v) +
                           workspace.backward_distance.get(v));
            }
            const double potential_v = potential(v);

            for (const Edge& edge : index.base.incoming[static_cast<std::size_t>(v)]) {
                const int u = edge.to;
                if (use_alt && index.component_of_node[static_cast<std::size_t>(u)] !=
                                   index.landmark_component) {
                    continue;
                }
                if (stats) ++stats->scanned_edges;
                const double reduced = reduced_weight(
                    edge.weight + potential_v - potential(u));
                const double candidate =
                    workspace.backward_distance.get(v) + reduced;
                if (candidate < workspace.backward_distance.get(u)) {
                    workspace.backward_distance.set(u, candidate);
                    workspace.backward_next.set(u, v);
                    workspace.backward_edge.set(u, edge.edge_id);
                    const bool decreased = backward_queue.push(
                        {candidate, serial++, u});
                    ++queue_pushes;
                    if (stats) {
                        ++stats->successful_relaxations;
                        if (decreased) ++stats->queue_decreases;
                        stats->peak_open_entries = std::max(
                            stats->peak_open_entries,
                            forward_queue.size() + backward_queue.size());
                    }
                    if (workspace.forward_distance.get(u) < ROUTE_INF) {
                        update_meeting(
                            u, workspace.forward_distance.get(u) + candidate);
                    }
                }
            }
        }
    }

    if (stats) {
        stats->expanded_states = expanded;
        stats->queue_pushes = queue_pushes;
    }
    if (meeting < 0) return {{}, {}, ROUTE_INF, expanded, queue_pushes};

    PathResult result;
    result.cost = 0.0;
    result.expanded = expanded;
    result.queue_pushes = queue_pushes;

    std::vector<int> left_nodes{meeting};
    std::vector<std::int64_t> left_edges;
    int node = meeting;
    while (node != start) {
        const int parent = workspace.forward_parent.get(node);
        if (parent < 0 || left_nodes.size() > graph.size()) {
            throw std::runtime_error("incomplete or cyclic forward predecessor data");
        }
        left_edges.push_back(workspace.forward_edge.get(node));
        left_nodes.push_back(parent);
        node = parent;
    }
    std::reverse(left_nodes.begin(), left_nodes.end());
    std::reverse(left_edges.begin(), left_edges.end());
    result.nodes = std::move(left_nodes);
    result.edges = std::move(left_edges);

    node = meeting;
    while (node != goal) {
        const int next = workspace.backward_next.get(node);
        if (next < 0 || result.nodes.size() > graph.size()) {
            throw std::runtime_error("incomplete or cyclic backward successor data");
        }
        result.edges.push_back(workspace.backward_edge.get(node));
        result.nodes.push_back(next);
        node = next;
    }

    for (std::size_t i = 0; i + 1 < result.nodes.size(); ++i) {
        const int u = result.nodes[i];
        const int v = result.nodes[i + 1];
        const std::int64_t edge_id = result.edges[i];
        const auto& outgoing = graph.outgoing[static_cast<std::size_t>(u)];
        const auto it = std::find_if(
            outgoing.begin(), outgoing.end(), [&](const Edge& edge) {
                return edge.to == v && edge.edge_id == edge_id;
            });
        if (it == outgoing.end()) {
            throw std::runtime_error("failed to reconstruct an original edge");
        }
        result.cost += it->weight;
    }
    return result;
}

} // namespace route_cpp17
