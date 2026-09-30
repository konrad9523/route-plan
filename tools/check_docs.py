"""检查文档结构：Markdown 代码围栏是否配对、角色 README 目录树是否与磁盘一致。

用法（在仓库根目录执行）：

    python tools/check_docs.py

退出码：**全部通过返回 0，发现任何问题返回 1**——便于以后接 CI。

**核心原则：没完成检查 ≠ 检查通过。**
凡是"本该检查却没能检查"的情况（文件读不了、必需文件不存在、
角色目录没有 README、路径不存在），一律**记为失败**，而不是跳过。

它检查什么、不检查什么（别过度信任它）：
  ✅ 代码围栏是否成对（漏写 ``` 会让后面整段渲染错乱）
  ✅ 各角色 README 里声明的子目录是否与磁盘实际一致（含顺序）
  ✅ 必需文件与目录是否存在、是否可读
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
FILES = [Path("README.md"), Path("CHANGELOG.md"), Path(".gitignore")]

# 必须存在的目录与文件：缺失即失败
REQUIRED_DIRS = [
    Path("docs"), Path("docs/operations"), Path("workspaces"),
    Path("src/path_planning"), Path("tests"), Path("tools"), Path("data"),
]
REQUIRED_FILES = [
    Path("README.md"), Path("CHANGELOG.md"), Path("LICENSE"), Path(".gitignore"),
    Path("docs/operations/团队协作与项目管理原则.md"),
    Path("src/path_planning/router.py"),
    Path("tests/_bootstrap.py"),
    Path("data/campus_552.graphml"),
]

# 参与检查的角色目录（每个都应有一个可读的 README.md）
ROLE_PREFIX = "A"

failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


print("=" * 62)
print("0. 必需文件与目录是否存在、是否可读")
print("=" * 62)
for d in REQUIRED_DIRS:
    if not d.is_dir():
        print(f"  ❌ 缺少目录: {d}")
        fail(f"缺少目录 {d}")
    else:
        print(f"  ✅ {d}/")
for f in REQUIRED_FILES:
    if not f.is_file():
        print(f"  ❌ 缺少文件: {f}")
        fail(f"缺少文件 {f}")
    else:
        try:
            f.read_text(encoding="utf-8", errors="strict")
            print(f"  ✅ {f}")
        except (OSError, UnicodeDecodeError) as e:
            print(f"  ❌ 无法读取: {f}  ({type(e).__name__})")
            fail(f"无法读取 {f}: {type(e).__name__}")

print()
print("=" * 62)
print("1. 代码围栏配对检查")
print("=" * 62)


def collect() -> list[Path]:
    out: list[Path] = []
    for f in FILES:
        if f.exists():
            out.append(f)
    for r in ROOTS:
        if not r.exists():
            continue
        try:
            out += [p for p in r.rglob("*.md") if p.is_file()]
        except OSError as e:
            print(f"  ❌ 无法遍历 {r}: {e}")
            fail(f"无法遍历 {r}")
    return sorted(set(out))


files = collect()
bad = 0
for md in files:
    try:
        text = md.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as e:
        print(f"  ❌ 无法读取（记为失败）: {md}  ({type(e).__name__})")
        fail(f"无法读取 {md}")
        bad += 1
        continue
    n = sum(1 for line in text.splitlines() if line.lstrip().startswith("```"))
    if n % 2:
        print(f"  ❌ 奇数围栏（{n} 个）: {md}")
        fail(f"围栏不配对: {md}")
        bad += 1
print(f"  检查 {len(files)} 个文件，{bad} 个有问题" + ("  OK" if bad == 0 else ""))

print()
print("=" * 62)
print("2. 各角色 README 目录树 vs 磁盘实际")
print("=" * 62)
WS = Path("workspaces")
roles = sorted(p for p in WS.iterdir() if p.is_dir() and p.name.startswith(ROLE_PREFIX)) \
    if WS.is_dir() else []
if not roles:
    print(f"  ❌ {WS}/ 下没有角色目录（以 {ROLE_PREFIX} 开头）")
    fail("workspaces 下没有角色目录")

allok = True
for role in roles:
    readme = role / "README.md"
    if not readme.is_file():
        print(f"  ❌ {role.name}: 缺少 README.md")
        fail(f"{role.name} 缺少 README.md")
        allok = False
        continue
    try:
        text = readme.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as e:
        print(f"  ❌ {role.name}: README.md 无法读取（{type(e).__name__}）")
        fail(f"{role.name} README.md 无法读取")
        allok = False
        continue

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
        fail(f"{role.name} 目录树漏了 {missing}")
    if extra:
        print(f"      README 写了但磁盘没有: {extra}")
        fail(f"{role.name} 目录树多了 {extra}")
    if not order_ok:
        print(f"      顺序与编号不符: {tree_names}")
        fail(f"{role.name} 目录树顺序不符")
print("  总体: " + ("全部一致 OK" if allok else "存在不一致"))

print()
print("=" * 62)
print("3. Markdown 相对链接是否指向存在的文件")
print("=" * 62)
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
md_files = [p for p in files if p.suffix == ".md"]
link_total = 0
link_bad = 0
for md in md_files:
    try:
        text = md.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        continue
    for m in LINK.finditer(text):
        target = m.group(1).strip()
        if target.startswith(("http://", "https://", "mailto:", "#", "tel:")):
            continue
        rel = target.split("#", 1)[0].strip()
        if not rel:
            continue
        link_total += 1
        if not (md.parent / rel).exists():
            print(f"  ❌ {md}  ->  {target}")
            fail(f"坏链接: {md} -> {target}")
            link_bad += 1
if link_bad == 0:
    print(f"  检查 {link_total} 个相对链接，全部有效 OK")
else:
    print(f"  检查 {link_total} 个相对链接，{link_bad} 个无效")

print()
print("=" * 62)
if failures:
    print(f"结果：发现 {len(failures)} 个问题，退出码 1")
    for f in failures:
        print(f"  - {f}")
    print("=" * 62)
    sys.exit(1)

print("结果：全部通过，退出码 0")
print("=" * 62)
sys.exit(0)
