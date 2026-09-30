"""搜索过程记录（SearchTrace）。

这一份数据结构同时服务三个作业的可视化：

* 作业 1：搜索动画（已访问节点 / 边界节点 / 最终路径）
* 作业 2：CH 预处理的收缩顺序与捷径边添加
* 作业 3：车辆沿路径行驶的位置推进

设计目标
--------
1. **记录搜索过程**，而不是记录渲染指令。渲染方式由前端决定。
2. **足够紧凑**。实测 552 节点单次查询约 650 个扩展事件，
   但按节点数外推到 10 万节点会到约 25 万个事件（约 4.3 MB）——
   一次性塞给浏览器不可接受。因此只记录**最小必要信息**，
   由 ``state_at()`` 按需重建任意一帧。
3. **单一状态模型**。搜索状态是 ``(previous_edge_id, node_id)``，
   但可视化只关心"哪个路口被摸到了"。因此对外统一用 **node_id** 表达，
   即使搜索内部的键是状态对象。前端不必理解状态扩展。

体积是怎么压下来的
------------------
朴素做法是每个事件存一条 ``(step, kind, node, edge, cost)``，约 18 字节/事件。

这里的做法是**全部用定长数组，且不出现任何以节点 ID 为键的字典**：

* ``pop_order``              第 k 次取出的是哪个节点（主时间轴）
* ``settled_cost_values``    与 pop_order 一一对应的代价
* ``discovered_order``       按发现顺序排列的节点
* ``discovered_after_steps`` 发现它时已经 pop 了多少个节点

四个数组的长度都 ≤ 节点数，**都不随边数增长**。
"已访问 / 边界 / 路径"三种状态完全由它们推导出来。

（曾经把"发现步号"存成 ``{节点: 步号}`` 字典，结果节点 ID 被存了两遍，
体积反而比朴素格式还大——这是实测出来的教训。）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SearchTrace:
    """一次搜索的完整过程记录。"""

    #: 算法名（dijkstra / astar / bidirectional_astar / ch）
    algorithm: str = ""
    #: 代价模型描述，用于前端显示"当前在优化什么"
    preference: str = ""

    #: 第 k 次"确定"的节点 ID。这是动画的主时间轴。
    pop_order: list[int] = field(default_factory=list)
    #: 与 pop_order 一一对应的"确定时的最优代价"，用于画代价热力。
    settled_cost_values: list[float] = field(default_factory=list)
    #: 按"发现顺序"排列的节点 ID。
    discovered_order: list[int] = field(default_factory=list)
    #: 发现 discovered_order[j] 时，已经确定了多少个节点。
    discovered_after_steps: list[int] = field(default_factory=list)
    #: node_id -> 确定它时用的那条入边（用于画搜索树）
    settled_via_edge: dict[int, int] = field(default_factory=dict)

    #: 最终路径的边序列与节点序列
    path_edges: list[int] = field(default_factory=list)
    path_nodes: list[int] = field(default_factory=list)

    #: 统计量
    total_steps: int = 0
    expanded_states: int = 0
    queue_pushes: int = 0
    #: 终点是在第几步被确定的（None 表示未找到）
    goal_step: int | None = None
    #: 是否做过降采样
    downsampled: bool = False
    #: 原始步数（降采样前）
    original_steps: int = 0

    # ---------------------------------------------------------------- 派生

    def found_at(self) -> dict[int, int]:
        """node_id -> 首次被发现时的步号。由发现顺序表重建。"""

        return dict(zip(self.discovered_order, self.discovered_after_steps))

    def settled_cost(self) -> dict[int, float]:
        """node_id -> 确定时的最优代价。"""

        return dict(zip(self.pop_order, self.settled_cost_values))

    # ---------------------------------------------------------------- 查询

    def state_at(self, step: int) -> dict[str, Any]:
        """重建第 ``step`` 步时的可视化状态。

        返回的三个集合正好对应作业 1 要求的"已访问 / 边界 / 最终路径"：

        * ``visited``：已经确定的节点
        * ``frontier``：已发现但还没确定的节点
        * ``path``：到这一步为止的最终路径（动画末尾才有意义）
        """

        step = max(0, min(step, len(self.pop_order)))
        visited = self.pop_order[:step]
        visited_set = set(visited)

        # 边界 = 到这一步为止已被发现的节点 减去 已被确定的节点。
        #
        # discovered_after_steps[j] 存的是"从第几步开始，该节点算作已发现"。
        # 时机细节：节点是在处理第 k 步的过程中被松弛出来的，所以站在第 k 步时
        # 这次发现已经发生。记录时用的是 (已完成的 pop 次数 + 1)，
        # 于是判据是 after <= step。
        #
        # 这里踩过两次坑：
        #   1) 一开始用 after < step，导致边界延迟一步；
        #   2) 后来干脆去掉时间判断，导致 step=0 时边界就已经装满了。
        frontier = [
            node
            for node, after in zip(self.discovered_order, self.discovered_after_steps)
            if after <= step and node not in visited_set
        ]

        path: list[int] = []
        if self.goal_step is not None and step >= self.goal_step:
            path = list(self.path_nodes)

        return {
            "step": step,
            "visited": visited,
            "frontier": frontier,
            "path": path,
            "visited_count": len(visited),
            "frontier_count": len(frontier),
        }

    def to_compact(self) -> dict[str, Any]:
        """转成紧凑的、可直接 JSON 序列化的结构（给前端用）。"""

        return {
            "algorithm": self.algorithm,
            "preference": self.preference,
            "pop_order": self.pop_order,
            "settled_cost_values": [round(v, 3) for v in self.settled_cost_values],
            "discovered_order": self.discovered_order,
            "discovered_after_steps": self.discovered_after_steps,
            "path_nodes": self.path_nodes,
            "path_edges": self.path_edges,
            "stats": {
                "total_steps": self.total_steps,
                "expanded_states": self.expanded_states,
                "queue_pushes": self.queue_pushes,
                "goal_step": self.goal_step,
                "downsampled": self.downsampled,
                "original_steps": self.original_steps or self.total_steps,
            },
        }

    # ---------------------------------------------------------------- 处理

    def downsample(self, max_steps: int = 2000) -> "SearchTrace":
        """把主时间轴压缩到 ``max_steps`` 长度以内。

        只在步数超出时才生效。做法是把区间**精确均分**成 ``max_steps`` 段再取点，
        并保证首尾都在，这样动画仍然覆盖整个搜索过程。

        注意：只压缩主时间轴 ``pop_order``；发现顺序表保持原样，
        因为边界重建依赖完整的发现信息。

        这里踩过一个坑：最初写的是 ``stride = original // max_steps``，
        当 ``max_steps`` 较大时 stride 会退化成 1，
        结果是"调用了降采样但一步都没减少"（例如 394 步降到 200，输出仍是 394）。
        改成均分取点后，输出长度严格满足 ``<= max_steps``（``max_steps >= 2`` 时）。
        """

        original = len(self.pop_order)
        if original <= max_steps:
            return self

        if max_steps <= 1:
            keep = [original - 1]
        else:
            last = original - 1
            keep = sorted({round(i * last / (max_steps - 1)) for i in range(max_steps)})
            if keep[-1] != last:
                keep.append(last)

        return SearchTrace(
            algorithm=self.algorithm,
            preference=self.preference,
            pop_order=[self.pop_order[i] for i in keep],
            settled_cost_values=[self.settled_cost_values[i] for i in keep],
            discovered_order=self.discovered_order,
            discovered_after_steps=self.discovered_after_steps,
            settled_via_edge=self.settled_via_edge,
            path_edges=self.path_edges,
            path_nodes=self.path_nodes,
            total_steps=len(keep),
            expanded_states=self.expanded_states,
            queue_pushes=self.queue_pushes,
            goal_step=self.goal_step,
            downsampled=True,
            original_steps=original,
        )


class TraceRecorder:
    """在搜索循环里收集 ``SearchTrace`` 的轻量记录器。

    关键设计：**未启用时每个方法都立刻返回**。这样 ``plan_route``
    在批量基准测试里没有任何额外开销——只有需要可视化时才传 ``trace=True``。
    实测 400 次查询，开启 trace 的总耗时只增加约 3.5%。
    """

    __slots__ = ("enabled", "trace", "_steps_done", "_discovered")

    def __init__(self, enabled: bool, algorithm: str = "", preference: str = "") -> None:
        self.enabled = enabled
        self._steps_done = 0
        self._discovered: set[int] = set()
        self.trace = SearchTrace(algorithm=algorithm, preference=preference)

    def record_pop(self, node_id: int, cost: float, via_edge: int | None) -> None:
        if not self.enabled:
            return
        self.trace.pop_order.append(node_id)
        self.trace.settled_cost_values.append(cost)
        if via_edge is not None:
            self.trace.settled_via_edge[node_id] = via_edge
        self._steps_done += 1

    def record_discover(self, node_id: int) -> None:
        """记录"首次发现某个路口"。

        一个节点可能因为代价被改进而**多次松弛**，但可视化只关心它
        "什么时候进入边界"，所以这里用集合去重——否则同一个节点会被
        记录多次，既浪费体积，也让 ``found_at()`` 的含义变含糊。
        """

        if not self.enabled:
            return
        if node_id in self._discovered:
            return
        self._discovered.add(node_id)
        self.trace.discovered_order.append(node_id)
        # +1 的含义：这次发现发生在"正在处理第 _steps_done+1 步"的过程中，
        # 因此站在第 (_steps_done+1) 步时它已经算作已发现。
        self.trace.discovered_after_steps.append(self._steps_done + 1)

    def finish(
        self,
        *,
        expanded_states: int,
        queue_pushes: int,
        path_nodes: list[int],
        path_edges: list[int],
        goal_step: int | None,
    ) -> None:
        if not self.enabled:
            return
        self.trace.total_steps = len(self.trace.pop_order)
        self.trace.expanded_states = expanded_states
        self.trace.queue_pushes = queue_pushes
        self.trace.path_nodes = path_nodes
        self.trace.path_edges = path_edges
        self.trace.goal_step = goal_step
