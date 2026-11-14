"""Build the CH C ABI library used by the shared RoutePlanner."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path


CPP_DIR = Path(__file__).resolve().parent
REPO_ROOT = CPP_DIR.parents[3]
CALLS_DIR = REPO_ROOT / "workspaces" / "A3_性能" / "06_算法调用与出图"
HEADER_DIR = REPO_ROOT / "workspaces" / "A2_算法"
OUTPUT_DIR = CALLS_DIR / ".build"
BUILD_FLAGS = ("/std:c++17", "/O2", "/EHsc", "/LD", "/DNDEBUG", "/utf-8")
INPUTS = (
    CPP_DIR / "ch_c_api.cpp",
    CPP_DIR / "ch.cpp",
    HEADER_DIR / "algorithms.hpp",
    HEADER_DIR / "graph_types.hpp",
)


def _output_path() -> Path:
    source_hash = hashlib.sha256(b"\0".join(path.read_bytes() for path in INPUTS)).hexdigest()
    build_key = hashlib.sha256(
        (source_hash + "|".join(BUILD_FLAGS)).encode("utf-8")
    ).hexdigest()[:12]
    return OUTPUT_DIR / "ch_cpp" / f"ch_cpp_{build_key}.dll"


def build_ch_library() -> Path:
    """Compile CH for Windows from a Visual Studio Developer Command Prompt."""
    output_dll = _output_path()
    if output_dll.is_file():
        return output_dll
    if sys.platform != "win32":
        raise RuntimeError("当前构建脚本面向 Windows/MSVC；请在 Visual Studio 开发者终端运行")
    compiler = shutil.which("cl")
    if compiler is None:
        raise RuntimeError("找不到 cl.exe；请先打开 Visual Studio Developer Command Prompt")

    output_dll.parent.mkdir(parents=True, exist_ok=True)
    command = [
        compiler, "/nologo", *BUILD_FLAGS,
        f"/I{HEADER_DIR}", str(INPUTS[0]), str(INPUTS[1]),
        "/link", f"/OUT:{output_dll}",
    ]
    subprocess.run(command, cwd=output_dll.parent, check=True)
    return output_dll


if __name__ == "__main__":
    print(build_ch_library())
