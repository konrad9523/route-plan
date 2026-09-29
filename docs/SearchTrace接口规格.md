# SearchTrace 接口规格（给 A4 交互线）

> **用途**：这是"搜索动画"的数据契约。作业 1 的搜索动画、作业 2 的 CH 预处理动画、作业 3 的路径动画**都基于它**。
> **接口一旦改动，三处可视化都要返工**，所以先看这份文档再动手。
> **实测数据**：全部数字来自 552 节点真实校园路网的实测，不是估算。

---

## 0. 一句话说明

算法跑完之后，把"搜索过程中发生了什么"打包成一份紧凑的数据给前端。
前端按**步号**推进，每一步都能重建出"已访问 / 边界 / 最终路径"三个集合。

```text
plan_route(..., trace=True)  →  RouteResult.trace  →  trace.state_at(k)  →  渲染第 k 帧
```

---

## 1. 怎么拿到它

```python
from path_planning import load_graphml, plan_route, CostModel, Preference

graph = load_graphml("learning_osmnx_networkx/output/graph.graphml")
result = plan_route(
    graph, source, target,
    algorithm="astar",
    cost_model=CostModel(preference=Preference.SHORTEST),
    trace=True,                      # ← 只有这一个开关
)

trace = result.trace                 # SearchTrace | None
```

**注意**：

* `trace` 默认 `False`。**批量基准测试不要开启**（见第 5 节的实测开销）。
* 未开启时 `result.trace is None`。
* 未找到路径时 `plan_route` 抛 `NoRouteError`，不会返回 trace。

---

## 2. 数据结构

`SearchTrace` 的字段分两类：**给前端序列化的** 和 **后端内部用的**。

### 2.1 主时间轴（前端必须用）

| 字段 | 类型 | 含义 |
|---|---|---|
| `pop_order` | `list[int]` | **第 k 个元素 = 第 k 步"确定"了哪个节点**。这是动画的时间轴 |
| `settled_cost_values` | `list[float]` | 与 `pop_order` 一一对应的代价，用于画代价热力 |

**`pop_order` 的长度 = `result.expanded_states`**（已有测试保证）。

### 2.2 发现顺序（重建边界用）

| 字段 | 类型 | 含义 |
|---|---|---|
| `discovered_order` | `list[int]` | 按"被发现顺序"排列的节点 |
| `discovered_after_steps` | `list[int]` | 从**第几步开始**该节点算作已发现 |

**时序约定（重要，容易搞错）**：
节点是在**处理第 k 步的过程中**被松弛出来的。所以"站在第 k 步"时，这次发现**已经发生**。
因此判据是 `discovered_after_steps[j] <= step`。

实测例子（4 节点链）：

```text
pop_order             = [1, 2, 3, 4]
discovered_order      = [1, 2, 4, 3]
discovered_after_steps= [1, 2, 2, 3]

step=0  已访问=[]        边界=[]      ← 还没开始
step=1  已访问=[1]       边界=[]      ← 刚取出起点，还没处理它的出边
step=2  已访问=[1,2]     边界=[4]     ← 起点处理完了，4 进入边界
step=3  已访问=[1,2,3]   边界=[4]
step=4  已访问=[1,2,3,4] 边界=[]      ← 全部取出，边界清空
```

**注意 step=1 时边界是空的**——这是真实时序，不是 bug。

### 2.3 结果与统计

| 字段 | 含义 |
|---|---|
| `path_nodes` / `path_edges` | 最终路径的节点/边序列 |
| `goal_step` | 终点在第几步被确定（`None` 表示未到达） |
| `total_steps` | 主时间轴长度 |
| `expanded_states` / `queue_pushes` | 与 `RouteResult` 一致 |
| `downsampled` / `original_steps` | 是否降采样过、原始步数 |

### 2.4 后端内部字段（前端**不要**序列化）

| 字段 | 为什么前端不用 |
|---|---|
| `settled_via_edge` | `{node: edge}` 字典，是"以节点 ID 为键"，体积大。只在后端画搜索树时才需要 |

---

## 3. 前端怎么用

### 3.1 重建某一帧

```python
state = trace.state_at(k)

state["visited"]        # list[int]  已确定的节点（帧 k 之前 pop 的）
state["frontier"]       # list[int]  已发现但未确定的节点 ← 就是"边界"
state["path"]           # list[int]  最终路径（k >= goal_step 后才有值）
state["visited_count"]  # int
state["frontier_count"] # int
```

### 3.2 播放动画

```python
total = len(trace.pop_order)
for k in range(total + 1):
    state = trace.state_at(k)
    # 三层渲染：已访问（冷色） / 边界（暖色） / 路径（高亮）
    render(state)
```

**性能提示**：`state_at` 每次都重建集合，**不要每帧都调用它去算总数**。
播放时只要推进 `k`，用返回的计数即可。

### 3.3 降采样（大图必用）

```python
trace = result.trace.downsample(max_steps=500)
```

**行为**：
* 步数 ≤ `max_steps` 时**原样返回**（`downsampled=False`）
* 超过时按间隔抽取，**保留首尾**
* 只压缩主时间轴，`discovered_order` 保持完整（边界重建需要）

**实测效果**（最长的一次查询，1381 步）：

| 限制 | 步数 | JSON 体积 | 末帧已访问数 |
|---|---|---|---|
| 不限制 | 1381 | 39.3 KB | 1381 |
| 500 | 691 | 24.6 KB | 691 |
| 200 | 231 | 14.8 KB | 231 |
| 50 | 53 | 11.0 KB | 53 |

> 注意：降到 50 步后体积仍有 11 KB，因为 `discovered_order` 没有压缩。
> 当前规模无所谓；如果将来上 10 万节点图，需要给发现事件也加降采样。

### 3.4 传给前端的格式

```python
payload = trace.to_compact()      # 全是数组，可直接 json.dumps
```

**设计约束**：`to_compact()` 的返回值里**不允许出现以节点 ID 为键的字典**。
已有测试 `test_compact_contains_no_dict_keyed_by_node` 守着这条。

原因：把 `{节点: 步号}` 存成字典会让**节点 ID 被存两遍**（键一次、值一次），
实测这样做的体积**比朴素格式还大**（压缩比 0.79x）。
改成"顺序表 + 平行数组"后压缩比变成 **1.53x**。

---

## 4. 实测体积数据

**552 节点真实校园路网**：

| 场景 | 事件数 | 紧凑 JSON |
|---|---|---|
| 单次查询（shortest） | pop 98 + 发现 73 | **3.8 KB** |
| 朴素格式对照 | 同 | 5.8 KB |
| **压缩比** | | **1.53x** |
| 最长查询（1381 步） | pop 1381 + 发现 543 | **39.3 KB** |

**外推到 10 万节点**（按节点数线性外推，**这是推算不是实测**）：

| 方案 | 体积 |
|---|---|
| 不降采样 | ≈ **7.0 MB** ❌ 不可接受 |
| 降到 2000 步 | ≈ **39.3 KB** ✅ |

**所以：大图必须降采样。** 作业 2 的 10 万节点演示要默认开启降采样。

---

## 5. 实测性能开销

**测量方式**：600 组查询、交错跑 7 轮取中位数（消除顺序影响和系统噪声）。

| 偏好 | trace 关闭 | trace 开启 | 绝对增加 | 相对 |
|---|---|---|---|---|
| fastest | 4.387 ms | 5.064 ms | **+0.677 ms** | +15.4% |
| shortest | 1.496 ms | 2.170 ms | **+0.674 ms** | +45.1% |

**关键读法**：两次的**绝对增量几乎相同**（0.677 / 0.674 ms），
说明开销是**按事件数线性**的，与偏好无关。
相对百分比差异大，只是因为分母不同（fastest 本身跑得久）。

**关闭 trace 时的成本**：
`record_*` 空调用每次 0.0281 微秒，每查询约 438 次 → **0.0123 毫秒**，
占单次查询 1.352 ms 的 **0.91%**。可以忽略。

**结论**：
* **基准测试用 `trace=False`**，开销 0（那 0.91% 是可接受的下限）
* **演示/可视化用 `trace=True`**，代价约 +0.7 ms/查询，对交互没有影响
* **不要在批量性能测试里开 trace**，否则数字会虚高 15–45%

---

## 6. 作业 2 / 作业 3 怎么复用

### 6.1 作业 2：CH 预处理动画

CH 预处理的事件**不是搜索过程**，而是**图结构变化**：

* 收缩了哪个节点（顺序）
* 新增了哪些捷径边
* 当前有多少节点已收缩

**建议**：`SearchTrace` 的"主时间轴 + 平行数组"模式可以直接套用：

```python
@dataclass
class ContractionTrace:
    contraction_order: list[int]        # 第 k 步收缩了哪个节点
    shortcut_added: list[tuple[int,int,int]]  # (from, to, mid_node)
    nodes_contracted_after_step: list[int]
```

**不要**硬塞进 `SearchTrace`——两者的语义不同（一个是"搜索到哪了"，一个是"图变成什么样了"）。
共享的是**设计模式**，不是同一个类。

### 6.2 作业 3：路径动画

路径动画不需要 `SearchTrace`，只需要：

* `result.geometry`（折线坐标）
* `result.edge_ids` / `node_ids`
* 每段边的长度和限速（用于算"还剩多远/多久"）

**建议**：作业 3 单独做一个 `animate_along(result, t)` 的推进器，与 `SearchTrace` 解耦。

### 6.3 统一的地方

三处可视化应该共用同一套**渲染约定**：

| 状态 | 颜色约定 | 数据来源 |
|---|---|---|
| 已访问 | 冷色（灰/蓝） | `state["visited"]` |
| 边界 | 暖色（橙/红） | `state["frontier"]` |
| 最终路径 | 高亮粗线 | `state["path"]` |

---

## 7. 现有测试覆盖

`tests/test_search_trace.py`，**18 个测试**（全部通过）。

| 测试 | 守什么 |
|---|---|
| `test_disabled_recorder_records_nothing` | 关闭时不记录 |
| `test_enabled_recorder_records_in_order` | 记录顺序与 `+1` 步号语义 |
| `test_duplicate_discovery_is_recorded_once` | 重复发现只记一次（体积关键） |
| `test_state_at_step_zero_is_empty` | 第 0 帧必须是空的 |
| `test_final_state_contains_path` | 末帧含完整路径 |
| `test_frontier_appears_after_the_step_that_discovered_it` | **边界时序语义**（慢一拍是正常的） |
| `test_frontier_empties_at_the_end` | 末帧边界清空 |
| `test_frontier_is_monotonic_in_discovery` | 边界节点不会凭空消失，只能被取出 |
| `test_visited_and_frontier_never_overlap` | 两个集合不重叠 |
| `test_pop_order_matches_expanded_states` | 时间轴与统计一致 |
| `test_compact_contains_no_dict_keyed_by_node` | **体积约束**（不许有以节点 ID 为键的字典） |
| `test_compact_is_json_serializable` | 可直接 JSON 序列化 |
| `test_downsample_caps_the_timeline` | 降采样生效 |
| `test_downsample_is_noop_when_already_short` | 步数够短时不改动 |
| `test_downsample_keeps_first_and_last_step` | 降采样保留首尾 |
| `test_no_trace_by_default` | 默认不收集 |
| `test_trace_on_real_network` | 真实 552 节点路网上的行为 |
| `test_found_at_reconstruction` | 发现索引重建正确 |

**全项目测试数：40**（router 7 + regressions 7 + osm_loader 8 + search_trace 18）。

---

## 8. 已知限制（诚实标注）

| 限制 | 影响 | 应对 |
|---|---|---|
| **大图体积** | 10 万节点不降采样约 7 MB（**推算**） | 必须降采样；将来可能需要给发现事件也加降采样 |
| **降采样后边界仍有 11 KB** | `discovered_order` 不压缩 | 当前规模无影响 |
| **`state_at` 每帧重建集合** | 大图上略慢 | 前端只需推进步号，不必每帧重算总数 |
| **`settled_via_edge` 是大字典** | 若序列化会显著增加体积 | 前端不要序列化它，或按需单独取 |
| **未做流式传输** | 一次性返回全部事件 | 若将来需要，可按步分块（接口已支持，`state_at` 天然可分块） |

---

## 9. 一句话总结

> **`trace=True` 拿到 `SearchTrace`，用 `state_at(k)` 按步重建"已访问/边界/路径"，
> 用 `to_compact()` 传前端，大图先 `downsample()`。**
> 基准测试用 `trace=False`（零开销）。
