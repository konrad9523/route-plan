"""检查 markdown 代码围栏配对，以及 workspaces 目录树与实际磁盘是否一致。"""

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOTS = [Path("docs"), Path("workspaces"), Path("tests")]
FILES = [Path("README.md"), Path("CHANGELOG.md")]


def collect():
    out = list(FILES)
    for r in ROOTS:
        if r.exists():
            try:
                out += [p for p in r.rglob("*.md") if p.is_file()]
            except OSError as e:
                print(f"  跳过 {r}: {e}")
    return sorted(set(out))


print("=" * 60)
print("1. 代码围栏配对检查")
print("=" * 60)
bad = 0
files = collect()
for md in files:
    try:
        text = md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        continue
    n = sum(1 for line in text.splitlines() if line.lstrip().startswith("```"))
    if n % 2:
        print(f"  奇数围栏({n}) {md}")
        bad += 1
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
    ok = not missing and not extra
    allok = allok and ok
    print(f"  {role.name}: {'OK' if ok else '不一致'}")
    if missing:
        print(f"      树里漏了: {missing}")
    if extra:
        print(f"      树里多了: {extra}")
    if tree_names != sorted(tree_names):
        print(f"      顺序不符: {tree_names}")
print("  总体: " + ("全部一致 OK" if allok else "存在不一致"))
