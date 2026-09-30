"""把仓库根目录与 src/ 加入 sys.path，让测试能在任意工作目录下导入。

为什么需要它：
`path_planning` 已移到 `src/` 下，而它**不是已安装的包**。
Python 只把"脚本所在目录"和（`-m` 模式下）当前目录放进 sys.path，
所以从不同位置运行时导入会失败。这个文件把两个必要路径显式补上。

用法（每个测试文件在导入 path_planning 之前先导入它）：

    import _bootstrap  # noqa: F401

注意：
- 用 `python -m unittest discover -s tests` 从仓库根目录运行时，
  discover 会把 tests/ 的父目录加进 sys.path，因此能直接 `import _bootstrap`。
- 单独运行某个测试文件（`python tests/test_router.py`）时，
  Python 把 tests/ 放进 sys.path，同样能导入到 _bootstrap。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"

for _p in (SRC_DIR, REPO_ROOT):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)
