"""检查文档结构：Markdown 代码围栏是否配对、角色 README 目录树是否与磁盘一致。

用法（在仓库根目录执行）：

    python tools/check_docs.py

退出码：**全部通过返回 0，发现任何问题返回 1**——便于以后接 CI。
（首版只打印结果、始终返回 0，那样接了 CI 也等于没检查。）

它检查什么、不检查什么（别过度信任它）：
  ✅ 代码围栏是否成对（漏写 ``` 会让后面整段渲染错乱）
  ✅ 各角色 README 里声明的子目录是否与磁盘实际一致（含顺序）
  ❌ 不检查职责描述、Git 命令、管理结论是否正确
  ❌ 不检查 .github/ 下的模板
  ❌ 不检查链接是否可达（网络内容不在范围内）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOTS = [Path("docs"), Path("workspaces"), Path("tests")]
FILES = [Path("README.md"), Path("CHANGELOG.md")]


def collect() -> list[Path]:
    out = list(FILES)
    for r in ROOTS:
        if r.exists():
            try:
                out += [p for p in r.rglob("*.md") if p.is_file()]
            except OSError as e:
                print(f"  跳过 {r}: {e}")
    return sorted(set(out))


failures: list[str] = []

print("=" * 60)
print("1. 代码围栏配对检查")
print("=" * 60)
files = collect()
bad = 0
for md in files:
    try:
        text = md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        continue
    n = sum(1 for line in text.splitlines() if line.lstrip().startswith("```"))
    if n % 2:
        print(f"  奇数围栏（{n} 个）: {md}")
        bad += 1
        failures.append(f"围栏不配对: {md}")
print(f"  检查 {len(files)} 个文件，{bad} 个围栏不配对" + ("  OK" if bad == 0 else ""))

print()
print("=" * 60)
print("2. 各角色 README 目录树 vs 磁盘实际")
print("=" * 60)
WS = Path("workspaces")
allok = True
for role in sorted(p for p in WS.iterdir() if p.is_dir()):
    readme = role / "README.md"
    if not readme.exists():
        continue
    text = readme.read_text(encoding="utf-8")
    tree_names = [t.strip() for t in re.findall(r"[├└]──\s*([^\s#]+)/", text)]
    disk_names = sorted(p.name for p in role.iterdir() if p.is_dir())
    missing = [d for d in disk_names if d not in tree_names]
    extra = [t for t in tree_names if t not in disk_names]
    order_ok = tree_names == sorted(tree_names)
    ok = not missing and not extra and order_ok
    allok = allok and ok
    print(f"  {role.name}: {'OK' if ok else '不一致'}")
    if missing:
        print(f"      磁盘有但 README 没写: {missing}")
        failures.append(f"{role.name} 目录树漏了 {missing}")
    if extra:
        print(f"      README 写了但磁盘没有: {extra}")
        failures.append(f"{role.name} 目录树多了 {extra}")
    if not order_ok:
        print(f"      顺序与编号不符: {tree_names}")
        failures.append(f"{role.name} 目录树顺序不符")
print("  总体: " + ("全部一致 OK" if allok else "存在不一致"))

print()
print("=" * 60)
if failures:
    print(f"结果：发现 {len(failures)} 个问题，退出码 1")
    for f in failures:
        print(f"  - {f}")
    print("=" * 60)
    sys.exit(1)

print("结果：全部通过，退出码 0")
print("=" * 60)
sys.exit(0)
