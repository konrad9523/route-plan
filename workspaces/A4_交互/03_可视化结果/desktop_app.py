"""Windows desktop shell for the G4 vehicle-navigation application."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import webview


def project_dir() -> Path:
    if os.environ.get("G4_PROJECT_DIR"):
        return Path(os.environ["G4_PROJECT_DIR"]).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = project_dir()
PYTHON = Path(os.environ.get("G4_PYTHON", ""))
if not PYTHON.is_file():
    portable = ROOT / "runtime" / "python" / "python.exe"
    fallback = Path(r"E:\app\python\python.exe")
    PYTHON = portable if portable.is_file() else fallback
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

def free_port(preferred: int, excluded: set[int] | None = None) -> int:
    """Return a currently unused loopback port, preferring the normal port."""
    excluded = excluded or set()
    candidates = [preferred] if preferred > 0 else []
    candidates.append(0)
    for candidate in candidates:
        if candidate in excluded:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return int(probe.getsockname()[1])
    raise RuntimeError("无法为桌面服务分配本地端口")


A2_BUNDLED_DIR = ROOT / "a2-runtime" / "06_算法测试接口"
A2_DIR = A2_BUNDLED_DIR if A2_BUNDLED_DIR.is_dir() else ROOT / "a2-runtime"
if not A2_DIR.is_dir():
    A2_DIR = Path(os.environ.get("G4_A2_DIR", r"E:\路径规划_G4-A4数据\A2_算法\A2_算法\06_算法测试接口"))
A3_SCRIPT = ROOT / "a3_server.py"
WEB_SCRIPT = ROOT / "server.py"
WEB_PORT = int(os.environ.get("G4_WEB_PORT", "5173"))
WEB_SERVICE_VERSION = "2026-11-12-3"
A2_PORT = int(os.environ.get("G4_A2_PORT", "8000"))
A3_PORT = int(os.environ.get("G4_A3_PORT", "8100"))
WEB_URL = ""
A2_URL = ""
A3_URL = ""
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
CHILD_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
children: list[subprocess.Popen] = []
log_handles = []
CH_CACHE_NAME = "g4-guangdong-ch.cache"


def configure_ports() -> None:
    """Allocate ports for this desktop instance instead of reusing stale services."""
    global WEB_PORT, A2_PORT, A3_PORT, WEB_URL, A2_URL, A3_URL
    WEB_PORT = free_port(WEB_PORT)
    used = {WEB_PORT}
    A2_PORT = free_port(A2_PORT, used)
    used.add(A2_PORT)
    A3_PORT = free_port(A3_PORT, used)
    WEB_URL = (
        f"http://127.0.0.1:{WEB_PORT}/index.html"
        f"?a2_port={A2_PORT}&a3_port={A3_PORT}"
    )
    A2_URL = f"http://127.0.0.1:{A2_PORT}/api/config"
    A3_URL = f"http://127.0.0.1:{A3_PORT}/api/health"


def prepare_ch_cache() -> Path:
    """Copy the packaged CH index to an ASCII runtime cache directory."""
    cache_dir = Path(tempfile.gettempdir()) / "G4RouteCache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    packaged = ROOT / "data" / "ch-cache" / CH_CACHE_NAME
    target = cache_dir / CH_CACHE_NAME
    if packaged.is_file() and (
        not target.is_file() or target.stat().st_size != packaged.stat().st_size
    ):
        shutil.copy2(packaged, target)
    return cache_dir


def get_json(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def web_is_current() -> bool:
    try:
        health = get_json(f"http://127.0.0.1:{WEB_PORT}/api/health")
        if not health or health.get("service_version") != WEB_SERVICE_VERSION:
            return False
        with urllib.request.urlopen(WEB_URL, timeout=1.5) as response:
            html = response.read().decode("utf-8", errors="replace")
        return "styles.css?v=67" in html and "performance-dashboard.js?v=22" in html
    except Exception:
        return False


def start_process(command: list[str], cwd: Path, log_name: str, env: dict[str, str]) -> subprocess.Popen:
    log = (LOG_DIR / log_name).open("ab")
    log_handles.append(log)
    process = subprocess.Popen(
        command, cwd=str(cwd), env=env, stdout=log, stderr=subprocess.STDOUT,
        creationflags=CHILD_FLAGS,
    )
    children.append(process)
    return process


def wait_for(url: str, seconds: int = 40) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if get_json(url) is not None or (url == WEB_URL and web_is_current()):
            return
        time.sleep(.5)
    raise RuntimeError(f"服务启动超时：{url}")


def ensure_services() -> None:
    env = os.environ.copy()
    env.update({
        "G4_PROJECT_DIR": str(ROOT),
        "G4_A2_DIR": str(A2_DIR),
        "G4_A2_PORT": str(A2_PORT),
        "G4_A2_CACHE_ONLY": "1",
        "G4_A3_CACHE_ONLY": "1",
        "G4_A3_PORT": str(A3_PORT),
        "PORT": str(WEB_PORT),
        "G4_A3_GRAPHML_DIR": str(ROOT / "data" / "graphml"),
        "G4_A3_MANIFEST_PATH": str(ROOT / "a3-runtime" / "data" / "a3_network_manifest.json"),
    })
    a2_health = get_json(A2_URL)
    if not a2_health or a2_health.get("service_version") != "2026-11-04-4":
        if not A2_DIR.is_dir():
            raise RuntimeError(f"A2 运行目录不存在：{A2_DIR}")
        start_process(
            [str(PYTHON), "-B", "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", str(A2_PORT)],
            A2_DIR, "a2.log", env,
        )
        wait_for(A2_URL)
    a3_health = get_json(A3_URL)
    if not a3_health or a3_health.get("service_version") != "2026-11-06-1":
        start_process([str(PYTHON), "-B", str(ROOT / "a3_server.py")], ROOT, "a3.log", env)
        wait_for(A3_URL)
    if not web_is_current():
        start_process([str(PYTHON), "-B", str(ROOT / "server.py")], ROOT, "web.log", env)
        wait_for(WEB_URL)


def stop_children() -> None:
    for process in reversed(children):
        if process.poll() is None:
            process.terminate()
    for process in reversed(children):
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
    for log in log_handles:
        try:
            log.close()
        except OSError:
            pass


def acquire_single_instance():
    """Prevent two desktop windows from creating competing service groups."""
    if os.name != "nt":
        return None
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\G4VehicleNavigation")
    if not handle:
        raise RuntimeError("无法创建桌面程序实例锁")
    if kernel32.GetLastError() == 183:
        kernel32.CloseHandle(handle)
        raise RuntimeError("G4 车辆导航实验室已经在运行，请先关闭已有窗口")
    return handle


def release_single_instance(handle) -> None:
    if handle and os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.CloseHandle(handle)


def main() -> int:
    mutex = None
    try:
        mutex = acquire_single_instance()
        configure_ports()
        os.environ["G4_CH_CACHE_DIR"] = str(prepare_ch_cache())
        ensure_services()
        window = webview.create_window(
            "G4 车辆导航实验室", WEB_URL,
            width=1600, height=960, min_size=(1100, 720),
            background_color="#0b1115",
        )
        webview.start(debug=False)
        return 0
    except Exception as error:  # show a readable message instead of a console traceback
        import tkinter.messagebox as messagebox
        messagebox.showerror("G4 车辆导航实验室启动失败", str(error))
        return 1
    finally:
        stop_children()
        release_single_instance(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
