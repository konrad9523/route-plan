#include "algorithms.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <queue>
#include <tuple>
#include <utility>

namespace route_cpp17 {

PathResult ContractionHierarchy::query(int start, int goal) const {
    if (start < 0 || goal < 0 || start >= static_cast<int>(rank.size()) || goal >= static_cast<int>(rank.size()))
        throw std::invalid_argument("CH 起点或终点索引无效");
    if (start == goal) return {{start}, {}, 0.0, 1, 1};
    const int n = static_cast<int>(rank.size());
    struct Workspace {
        detail::EpochArray<double> df;
        detail::EpochArray<double> db;
        detail::EpochArray<int> pf;
        detail::EpochArray<int> pfa;
        detail::EpochArray<int> nb;
        detail::EpochArray<int> nba;
        detail::EpochArray<char> sf;
        detail::EpochArray<char> sb;
    };
    thread_local Workspace workspace;
    workspace.df.begin(n, ROUTE_INF);
    workspace.db.begin(n, ROUTE_INF);
    workspace.pf.begin(n, -1);
    workspace.pfa.begin(n, -1);
    workspace.nb.begin(n, -1);
    workspace.nba.begin(n, -1);
    workspace.sf.begin(n, false);
    workspace.sb.begin(n, false);
    std::priority_queue<QueueItem, std::vector<QueueItem>, std::greater<QueueItem>> qf, qb;
    std::size_t serial = 0;
    workspace.df.set(start, 0.0);
    workspace.db.set(goal, 0.0);
    qf.push({0.0, serial++, start}); qb.push({0.0, serial++, goal});
    double best = ROUTE_INF; int meeting = -1; std::size_t expanded = 0;
    std::vector<int> expanded_order;
    std::size_t queue_pushes = 2;
    auto clean_forward = [&]() {
        while (!qf.empty() &&
               (workspace.sf.get(qf.top().node) ||
                qf.top().key != workspace.df.get(qf.top().node))) qf.pop();
    };
    auto clean_backward = [&]() {
        while (!qb.empty() &&
               (workspace.sb.get(qb.top().node) ||
                qb.top().key != workspace.db.get(qb.top().node))) qb.pop();
    };
    auto meet = [&](int node) {
        const double forward = workspace.df.get(node);
        const double backward = workspace.db.get(node);
        if (std::isfinite(forward) && std::isfinite(backward) &&
            forward + backward < best) {
            best = forward + backward;
            meeting = node;
        }
    };
    while (!qf.empty() || !qb.empty()) {
        clean_forward(); clean_backward();
        if (qf.empty() && qb.empty()) break;
        const double mf = qf.empty() ? ROUTE_INF : qf.top().key;
        const double mb = qb.empty() ? ROUTE_INF : qb.top().key;
        // 两侧使用的 CH 弧集合不同，min_f + min_b 不能作为可靠终止
        // 下界（尤其存在零权边时）。只有两侧剩余最小距离都不可能
        // 单独改进 best 时才终止。
        if (std::isfinite(best) && mf >= best && mb >= best) break;
        if (mf <= mb) {
            const auto item = qf.top(); qf.pop(); int u = item.node;
            if (workspace.sf.get(u) || item.key != workspace.df.get(u)) continue;
            workspace.sf.set(u, true); ++expanded; expanded_order.push_back(u); meet(u);
            bool stalled = false;
            for (std::size_t pos = upward_in_offsets[u];
                 pos < upward_in_offsets[u + 1]; ++pos) {
                const int aid = upward_in_arcs[pos];
                const auto& a = arcs[aid]; // Higher-rank source -> u.
                if (workspace.df.get(a.source) + a.weight < workspace.df.get(u)) {
                    stalled = true;
                    break;
                }
            }
            if (!stalled) {
                for (std::size_t pos = upward_out_offsets[u];
                     pos < upward_out_offsets[u + 1]; ++pos) {
                    const int aid = upward_out_arcs[pos];
                    const auto& a = arcs[aid];
                    const double cand = workspace.df.get(u) + a.weight;
                    if (cand < workspace.df.get(a.target)) {
                        workspace.df.set(a.target, cand);
                        workspace.pf.set(a.target, u);
                        workspace.pfa.set(a.target, aid);
                        qf.push({cand, serial++, a.target});
                        ++queue_pushes;
                    }
                    meet(a.target);
                }
            }
        } else {
            const auto item = qb.top(); qb.pop(); int v = item.node;
            if (workspace.sb.get(v) || item.key != workspace.db.get(v)) continue;
            workspace.sb.set(v, true); ++expanded; expanded_order.push_back(v); meet(v);
            bool stalled = false;
            for (std::size_t pos = upward_out_offsets[v];
                 pos < upward_out_offsets[v + 1]; ++pos) {
                const int aid = upward_out_arcs[pos];
                const auto& a = arcs[aid]; // v -> higher-rank target.
                if (workspace.db.get(a.target) + a.weight < workspace.db.get(v)) {
                    stalled = true;
                    break;
                }
            }
            if (!stalled) {
                for (std::size_t pos = upward_in_offsets[v];
                     pos < upward_in_offsets[v + 1]; ++pos) {
                    const int aid = upward_in_arcs[pos];
                    const auto& a = arcs[aid]; const int u = a.source;
                    const double cand = workspace.db.get(v) + a.weight;
                    if (cand < workspace.db.get(u)) {
                        workspace.db.set(u, cand);
                        workspace.nb.set(u, v);
                        workspace.nba.set(u, aid);
                        qb.push({cand, serial++, u});
                        ++queue_pushes;
                    }
                    meet(u);
                }
            }
        }
    }
    if (meeting < 0) return {{}, {}, ROUTE_INF, expanded, queue_pushes};
    std::vector<int> query_arcs;
    std::vector<int> left;
    for (int x = meeting; x != start; x = workspace.pf.get(x)) {
        if (workspace.pf.get(x) < 0) {
            throw std::runtime_error("CH 前向记录不完整");
        }
        left.push_back(workspace.pfa.get(x));
    }
    std::reverse(left.begin(), left.end());
    query_arcs.insert(query_arcs.end(), left.begin(), left.end());
    for (int x = meeting; x != goal; x = workspace.nb.get(x)) {
        if (workspace.nb.get(x) < 0) {
            throw std::runtime_error("CH 后向记录不完整");
        }
        query_arcs.push_back(workspace.nba.get(x));
    }
    std::vector<std::tuple<int, int, std::int64_t, double>> steps;
    // Iterative shortcut expansion avoids recursion depth depending on the
    // hierarchy shape. Push right before left to preserve path order.
    std::vector<int> unpack_stack;
    for (int aid : query_arcs) {
        unpack_stack.push_back(aid);
        while (!unpack_stack.empty()) {
            const int current_aid = unpack_stack.back();
            unpack_stack.pop_back();
            const auto& a = arcs[current_aid];
            if (a.left < 0) {
                steps.emplace_back(
                    a.source, a.target, a.original_edge_id, a.weight);
            } else {
                unpack_stack.push_back(a.right);
                unpack_stack.push_back(a.left);
            }
        }
    }
    PathResult result; result.expanded = expanded; result.queue_pushes = queue_pushes;
    result.expanded_order = std::move(expanded_order);
    result.cost = 0.0; result.nodes.push_back(start);
    int current = start;
    for (const auto& [u, v, eid, weight] : steps) {
        if (u != current) throw std::runtime_error("CH shortcut 展开后的边序列不连续");
        result.nodes.push_back(v); result.edges.push_back(eid); result.cost += weight; current = v;
    }
    if (current != goal) throw std::runtime_error("CH 路径未到达终点");
    return result;
}

ContractionHierarchy preprocess_ch(
    const RoadGraph& graph,
    const CHProgressCallback& progress) {
    validate_graph(graph, false);
    const int n = static_cast<int>(graph.outgoing.size());
    ContractionHierarchy ch;
    std::vector<std::vector<int>> out(n), in(n);
    ch.arcs.reserve(2 * graph.outgoing.size());
    for (int u = 0; u < n; ++u) for (const auto& e : graph.outgoing[u]) {
        const int aid = static_cast<int>(ch.arcs.size());
        ch.arcs.push_back({u, e.to, e.weight, e.edge_id, -1, -1});
        out[u].push_back(aid); in[e.to].push_back(aid);
    }
    std::vector<char> contracted(n, false);
    // 达到上限时直接认为没有找到 witness，加入 shortcut 是安全的，只会
    // 增加预处理结果的弧数，不会破坏最短路正确性。复用数组避免每次
    // witness search 都清空 8.5 万个节点。
    // shortcut: cap local witness searches at 5000 settled nodes; raise it if
    // measured shortcut growth outweighs the preprocessing savings.
    const std::size_t witness_limit = 5000;
    std::vector<double> witness_distance(n, ROUTE_INF);
    std::vector<int> witness_stamp(n, 0);
    int current_stamp = 0;
    auto witness = [&](int source, int excluded, double limit) {
        ++current_stamp;
        if (current_stamp == std::numeric_limits<int>::max()) {
            std::fill(witness_stamp.begin(), witness_stamp.end(), 0);
            current_stamp = 1;
        }
        auto get_distance = [&](int node) {
            return witness_stamp[node] == current_stamp ? witness_distance[node] : ROUTE_INF;
        };
        std::priority_queue<QueueItem, std::vector<QueueItem>, std::greater<QueueItem>> q;
        std::size_t serial = 0, visited = 0;
        witness_stamp[source] = current_stamp;
        witness_distance[source] = 0.0;
        q.push({0.0, serial++, source});
        while (!q.empty() && visited < witness_limit) {
            const auto item = q.top(); q.pop(); int u = item.node;
            if (item.key != get_distance(u) || item.key > limit) continue;
            ++visited;
            for (int aid : out[u]) {
                const auto& a = ch.arcs[aid];
                if (a.target == excluded || contracted[a.target] || contracted[a.source]) continue;
                const double cand = item.key + a.weight;
                if (cand <= limit && cand < get_distance(a.target)) {
                    witness_stamp[a.target] = current_stamp;
                    witness_distance[a.target] = cand;
                    q.push({cand, serial++, a.target});
                }
            }
        }
        return current_stamp;
    };
    // 动态收缩优先级：边差值越小，预计产生的 shortcut 越少；已经收缩
    // 邻居数作为次要惩罚，避免形成局部高密度核心。每次收缩后只更新
    // 受影响的相邻节点，避免静态顺序后期发生 shortcut 爆炸。
    std::vector<int> contracted_neighbors(n, 0), priority_version(n, 0);
    auto active_degrees = [&](int v) {
        std::size_t indegree = 0, outdegree = 0;
        for (int aid : in[v]) {
            const auto& a = ch.arcs[aid];
            if (!contracted[a.source] && a.source != v) ++indegree;
        }
        for (int aid : out[v]) {
            const auto& a = ch.arcs[aid];
            if (!contracted[a.target] && a.target != v) ++outdegree;
        }
        return std::pair<std::size_t, std::size_t>{indegree, outdegree};
    };
    auto priority = [&](int v) {
        const auto [indegree, outdegree] = active_degrees(v);
        const long long edge_difference =
            static_cast<long long>(indegree * outdegree) -
            static_cast<long long>(indegree + outdegree);
        return edge_difference * 10LL + contracted_neighbors[v];
    };
    using PriorityItem = std::tuple<long long, int, int>; // score, version, node
    std::priority_queue<PriorityItem, std::vector<PriorityItem>, std::greater<PriorityItem>> node_queue;
    for (int v = 0; v < n; ++v) node_queue.emplace(priority(v), priority_version[v], v);

    std::vector<int> order;
    order.reserve(n);
    int contracted_count = 0;
    while (!node_queue.empty()) {
        const auto [stored_priority, stored_version, v] = node_queue.top();
        node_queue.pop();
        if (contracted[v] || stored_version != priority_version[v]) continue;
        const long long current_priority = priority(v);
        if (current_priority != stored_priority) {
            ++priority_version[v];
            node_queue.emplace(current_priority, priority_version[v], v);
            continue;
        }

        std::vector<int> ins, outs;
        for (int aid : in[v]) if (!contracted[ch.arcs[aid].source] && ch.arcs[aid].source != v) ins.push_back(aid);
        for (int aid : out[v]) if (!contracted[ch.arcs[aid].target] && ch.arcs[aid].target != v) outs.push_back(aid);
        // For shortest-path distance without turn-state constraints, among
        // parallel active arcs only the lightest arc for each source/target can
        // participate in a shortest path through v. Deduplicating here avoids
        // repeated identical witness searches and redundant shortcuts.
        std::sort(ins.begin(), ins.end(), [&](int lhs, int rhs) {
            const auto& a = ch.arcs[lhs];
            const auto& b = ch.arcs[rhs];
            if (a.source != b.source) return a.source < b.source;
            if (a.weight != b.weight) return a.weight < b.weight;
            return lhs < rhs;
        });
        ins.erase(std::unique(ins.begin(), ins.end(), [&](int lhs, int rhs) {
            return ch.arcs[lhs].source == ch.arcs[rhs].source;
        }), ins.end());
        std::sort(outs.begin(), outs.end(), [&](int lhs, int rhs) {
            const auto& a = ch.arcs[lhs];
            const auto& b = ch.arcs[rhs];
            if (a.target != b.target) return a.target < b.target;
            if (a.weight != b.weight) return a.weight < b.weight;
            return lhs < rhs;
        });
        outs.erase(std::unique(outs.begin(), outs.end(), [&](int lhs, int rhs) {
            return ch.arcs[lhs].target == ch.arcs[rhs].target;
        }), outs.end());
        const std::size_t arcs_before_contraction = ch.arcs.size();
        for (int ia : ins) {
            // 后面 push_back shortcut 可能触发 arcs 重新分配，因此必须复制，
            // 不能持有指向 vector 元素的引用。
            const CHArc left = ch.arcs[ia];
            double max_limit = 0.0;
            bool has_candidate = false;
            for (int oa : outs) if (left.source != ch.arcs[oa].target) {
                has_candidate = true;
                max_limit = std::max(max_limit, left.weight + ch.arcs[oa].weight);
            }
            if (!has_candidate) continue;
            const int witness_id = witness(left.source, v, max_limit);
            for (int oa : outs) {
                const CHArc right = ch.arcs[oa];
                if (left.source == right.target) continue;
                const double candidate = left.weight + right.weight;
                const double witness_cost = witness_stamp[right.target] == witness_id
                    ? witness_distance[right.target] : ROUTE_INF;
                if (witness_cost <= candidate) continue;
                const int sid = static_cast<int>(ch.arcs.size());
                ch.arcs.push_back({left.source, right.target, candidate, -1, ia, oa});
                out[left.source].push_back(sid); in[right.target].push_back(sid);
            }
        }
        contracted[v] = true;
        order.push_back(v);
        ++contracted_count;

        std::vector<int> affected;
        affected.reserve(ins.size() + outs.size());
        for (int aid : ins) affected.push_back(ch.arcs[aid].source);
        for (int aid : outs) affected.push_back(ch.arcs[aid].target);
        std::sort(affected.begin(), affected.end());
        affected.erase(std::unique(affected.begin(), affected.end()), affected.end());
        for (int neighbor : affected) {
            if (contracted[neighbor]) continue;
            ++contracted_neighbors[neighbor];
            ++priority_version[neighbor];
            node_queue.emplace(priority(neighbor), priority_version[neighbor], neighbor);
        }
        if (progress) {
            progress({contracted_count, n, v, ch.arcs.size(),
                      ch.arcs.size() - arcs_before_contraction});
        }
    }
    ch.rank.assign(n, 0);
    for (int i = 0; i < n; ++i) ch.rank[order[i]] = i;
    ch.upward_out_offsets.assign(static_cast<std::size_t>(n) + 1, 0);
    ch.upward_in_offsets.assign(static_cast<std::size_t>(n) + 1, 0);
    for (int aid = 0; aid < static_cast<int>(ch.arcs.size()); ++aid) {
        const auto& a = ch.arcs[aid];
        if (ch.rank[a.source] < ch.rank[a.target]) {
            ++ch.upward_out_offsets[static_cast<std::size_t>(a.source) + 1];
        }
        if (ch.rank[a.source] > ch.rank[a.target]) {
            ++ch.upward_in_offsets[static_cast<std::size_t>(a.target) + 1];
        }
    }
    for (int v = 0; v < n; ++v) {
        ch.upward_out_offsets[v + 1] += ch.upward_out_offsets[v];
        ch.upward_in_offsets[v + 1] += ch.upward_in_offsets[v];
    }
    ch.upward_out_arcs.resize(ch.upward_out_offsets.back());
    ch.upward_in_arcs.resize(ch.upward_in_offsets.back());
    auto out_cursor = ch.upward_out_offsets;
    auto in_cursor = ch.upward_in_offsets;
    for (int aid = 0; aid < static_cast<int>(ch.arcs.size()); ++aid) {
        const auto& a = ch.arcs[aid];
        if (ch.rank[a.source] < ch.rank[a.target]) {
            ch.upward_out_arcs[out_cursor[a.source]++] = aid;
        }
        if (ch.rank[a.source] > ch.rank[a.target]) {
            ch.upward_in_arcs[in_cursor[a.target]++] = aid;
        }
    }
    return ch;
}



} // namespace route_cpp17
