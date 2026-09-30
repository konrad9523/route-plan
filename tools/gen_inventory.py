"""重新生成《重建干净仓库操作清单》第 8 节的分组统计与完整文件清单。

以 `git ls-files` 为唯一事实来源，避免手工维护清单再次过期。
工具化保存，仓库文件变动后可重复执行。
"""

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DOC = Path("docs/operations/重建干净仓库操作清单.md")

files = sorted(subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                              encoding="utf-8").stdout.splitlines())

ORDER = ["(根文件)", ".github/", "src/", "api/", "web/", "tests/",
         "data/", "docs/", "workspaces/", "tools/"]
LABEL = {"(根文件)": "根文件（`.gitignore`、`CHANGELOG.md`、`LICENSE`、`README.md`）"}


def bucket(f):
    for p in ORDER:
        if p == "(根文件)":
            if "/" not in f:
                return p
        elif f.startswith(p):
            return p
    return "其他"


groups = {}
for f in files:
    groups.setdefault(bucket(f), []).append(f)

missing = [f for f in files if bucket(f) == "其他"]
if missing:
    print("未被分组的文件（需要补 ORDER）:", missing)
    raise SystemExit(1)

rows = ["| 分组 | 数量 |", "|---|---|"]
for p in ORDER:
    if p in groups:
        rows.append(f"| {LABEL.get(p, '`' + p + '`')} | {len(groups[p])} |")
table = "\n".join(rows)

blocks = ["\n".join(groups[p]) for p in ORDER if p in groups]
listing = "\n\n".join(blocks)

print(f"跟踪文件总数: {len(files)}")
for p in ORDER:
    if p in groups:
        print(f"  {len(groups[p]):>3}  {p}")

text = DOC.read_text(encoding="utf-8")
head_marker = "## 8. 附：本次重建要保留的完整文件清单"
tail_marker = "**明确不该出现**："
hi, ti = text.find(head_marker), text.find(tail_marker)
if hi < 0 or ti < 0 or ti < hi:
    raise SystemExit(f"未找到边界: {hi} {ti}")

new_section = (
    f"{head_marker}\n\n"
    f"重建后 `git ls-files` 应包含以下内容"
    f"（实测共 **{len(files)} 项**，按 2026-09-29 的仓库状态生成）：\n\n"
    f"{table}\n\n"
    f"完整清单：\n\n"
    f"```text\n{listing}\n```\n\n"
)

DOC.write_text(text[:hi] + new_section + text[ti:], encoding="utf-8")
print("已更新第 8 节。")
