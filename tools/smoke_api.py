"""端到端 HTTP 冒烟测试：验证前端依赖的每个接口与字段真的可用。

用法（在仓库根目录执行）：

    python tools/smoke_api.py

在进程内启动 uvicorn（不用 Start-Process，避免留下孤儿进程），
覆盖前端 index.html 实际会调用的：/api/meta、/api/nodes、POST /api/route、/。
全部通过时退出码 0，有失败项时退出码 1，便于以后接 CI。

为什么要有这个脚本：
`tests/` 里的 56 个测试用的是 FastAPI TestClient，走进程内调用，
不经过真实的 HTTP 与 uvicorn；而作业 1 有 35% 的分压在"界面能跑"上。
这个脚本用真实 socket 请求把那条路径也覆盖一遍。

已知且已接受的行为（不是失败项）：
- avoid_tolls 在当前 552 节点校园路网上与 fastest 结果完全相同，
  因为路网里 toll=True 的边为 0 条。详见
  `workspaces/A1_数据/03_数据质量/` 下的偏好行为记录。
"""

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# 支持 `python tools/smoke_api.py`：此时 sys.path[0] 是 tools/，导不到 api 包。
# path_planning 与 api 都不是已安装的包：
#   - path_planning 在 src/ 下
#   - api 在仓库根目录下
# 两者都要显式加进 sys.path。
ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "src", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import uvicorn  # noqa: E402

from api.main import app  # noqa: E402

PORT = 8083
threading.Thread(
    target=lambda: uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error"),
    daemon=True,
).start()

BASE = f"http://127.0.0.1:{PORT}"
for _ in range(60):
    try:
        urllib.request.urlopen(BASE + "/api/meta", timeout=1).read()
        break
    except Exception:
        time.sleep(0.25)
else:
    raise SystemExit("服务启动失败")

fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        fails.append(name)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return r.status, r.read()


def post_json(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read())


print("=" * 62)
print("1. GET /api/meta")
print("=" * 62)
status, body = get("/api/meta")
meta = json.loads(body)
check("200", status == 200)
check("node_count = 552", meta.get("node_count") == 552, str(meta.get("node_count")))
check("edge_count = 1400", meta.get("edge_count") == 1400, str(meta.get("edge_count")))
check("含 bbox（前端据此定地图范围）", isinstance(meta.get("bbox"), dict))
check("算法列表", meta.get("algorithms") == ["dijkstra", "astar"], str(meta.get("algorithms")))
check("偏好列表非空", len(meta.get("preferences") or []) == 4, str(meta.get("preferences")))

print()
print("=" * 62)
print("2. GET /api/nodes（列式结构）")
print("=" * 62)
status, body = get("/api/nodes")
nodes = json.loads(body)
ids = nodes.get("ids") or []
check("200", status == 200)
check("ids/lons/lats 三者等长且为 552",
      len(ids) == len(nodes.get("lons") or []) == len(nodes.get("lats") or []) == 552,
      f"{len(ids)}/{len(nodes.get('lons') or [])}/{len(nodes.get('lats') or [])}")
check("经纬度在校园 bbox 范围内",
      all(114.3 < lo < 114.5 for lo in nodes["lons"]) and all(30.4 < la < 30.6 for la in nodes["lats"]))

print()
print("=" * 62)
print("3. GET / 首页")
print("=" * 62)
status, body = get("/")
html = body.decode("utf-8", "replace")
check("200", status == 200, f"{len(html)} 字符")
check("引入 Leaflet", "leaflet" in html.lower())
check("Canvas 渲染（552 点用 SVG 会卡）", "preferCanvas" in html)
check("调用 /api/meta", "/api/meta" in html)
check("调用 /api/nodes", "/api/nodes" in html)
check("调用 /api/route", "/api/route" in html)
check("有播放/暂停控制", "pause" in html.lower() or "暂停" in html)

print()
print("=" * 62)
print("4. POST /api/route（两种算法 × 四种偏好，共 8 组）")
print("=" * 62)
a, b = ids[0], ids[len(ids) // 2]
print(f"  起终点: {a} -> {b}")
results = {}
for algo in ("dijkstra", "astar"):
    for pref in ("fastest", "shortest", "avoid_tolls", "no_highway"):
        try:
            status, res = post_json("/api/route", {
                "source": a, "target": b, "algorithm": algo, "preference": pref,
            })
            ok = (status == 200 and res.get("status") == "ok"
                  and res.get("node_ids") and res.get("cost") is not None)
            check(f"{algo}/{pref}", ok,
                  f"cost={res.get('cost')} 节点={len(res.get('node_ids') or [])} "
                  f"扩展={res.get('stats', {}).get('expanded_states')}")
            results[(algo, pref)] = res
        except Exception as e:
            check(f"{algo}/{pref}", False, f"异常 {e}")

print()
print("=" * 62)
print("5. 正确性：A* 与 Dijkstra 代价必须一致")
print("=" * 62)
for pref in ("fastest", "shortest", "avoid_tolls", "no_highway"):
    d = results.get(("dijkstra", pref))
    x = results.get(("astar", pref))
    if d and x:
        gap = abs(d["cost"] - x["cost"])
        check(f"{pref}: 代价一致", gap < 1e-6,
              f"dijkstra={d['cost']} astar={x['cost']} 差={gap:.6f}")
        check(f"{pref}: A* 扩展更少",
              x["stats"]["expanded_states"] <= d["stats"]["expanded_states"],
              f"A*={x['stats']['expanded_states']} Dijkstra={d['stats']['expanded_states']}")

print()
print("=" * 62)
print("6. SearchTrace（前端动画的数据来源）")
print("=" * 62)
status, res = post_json("/api/route", {
    "source": a, "target": b, "algorithm": "astar",
    "preference": "fastest", "trace": True, "max_steps": 0,
})
trace = res.get("trace") or {}
print(f"  完整 trace 键: {sorted(trace)}")
for key in ("pop_order", "settled_cost_values", "discovered_order",
            "discovered_after_steps", "path_nodes", "path_edges", "stats"):
    check(f"含 {key}", key in trace)
stats = trace.get("stats") or {}
check("stats 含 total_steps", "total_steps" in stats, str(stats.get("total_steps")))
check("stats 含 goal_step", "goal_step" in stats, str(stats.get("goal_step")))

po = trace.get("pop_order") or []
das = trace.get("discovered_after_steps") or []
do = trace.get("discovered_order") or []
check("discovered_* 三者等长", len(das) == len(do) != 0, f"{len(das)} vs {len(do)}")
check("settled_cost_values 与 pop_order 等长",
      len(trace.get("settled_cost_values") or []) == len(po))
check("discovered_after_steps 单调不减",
      all(das[i] <= das[i + 1] for i in range(len(das) - 1)))
check("discovered_after_steps 均 ≤ total_steps",
      max(das, default=0) <= stats.get("total_steps", 0),
      f"max={max(das, default=0)} total={stats.get('total_steps')}")
check("path_nodes 首尾等于起终点",
      (trace.get("path_nodes") or [None])[0] == a and (trace.get("path_nodes") or [None])[-1] == b)

print()
print("=" * 62)
print("7. 降采样：max_steps 必须真的生效")
print("=" * 62)
full_len = len(po)
status, res2 = post_json("/api/route", {
    "source": a, "target": b, "algorithm": "astar",
    "preference": "fastest", "trace": True, "max_steps": 200,
})
t2 = res2.get("trace") or {}
po2 = t2.get("pop_order") or []
s2 = t2.get("stats") or {}
check(f"原始 {full_len} 步 → 降采样后 ≤ 200", len(po2) <= 200, f"实际 {len(po2)}")
check("降采样标记 downsampled=True", s2.get("downsampled") is True, str(s2.get("downsampled")))
check("保留原始步数 original_steps", s2.get("original_steps") == full_len,
      f"original={s2.get('original_steps')} 期望={full_len}")
check("降采样后仍保留终点",
      (t2.get("path_nodes") or [None])[-1] == b)

print()
print("=" * 62)
print("8. 错误处理")
print("=" * 62)
try:
    post_json("/api/route", {"source": a, "target": b, "algorithm": "nonexistent"})
    check("非法算法返回 4xx", False, "竟然成功了")
except urllib.error.HTTPError as e:
    check("非法算法返回 4xx", 400 <= e.code < 500, f"HTTP {e.code}")
try:
    post_json("/api/route", {"source": 999999999, "target": b, "algorithm": "astar"})
    check("非法节点返回 4xx/404", False, "竟然成功了")
except urllib.error.HTTPError as e:
    check("非法节点返回 4xx/404", 400 <= e.code < 500, f"HTTP {e.code}")

print()
print("=" * 62)
print("结果：" + ("全部通过 ✅" if not fails else f"失败 {len(fails)} 项 ❌: " + ", ".join(fails)))
print("=" * 62)
sys.exit(1 if fails else 0)
