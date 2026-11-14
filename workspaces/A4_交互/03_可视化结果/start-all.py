from __future__ import annotations

import os
import json
import subprocess
import time
import urllib.request
import webbrowser
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
A2_DIR = Path(r"E:\路径规划_G4-A4数据\A2_算法\A2_算法\06_算法测试接口")
A3_DIR = Path(__file__).resolve().parent / "a3-runtime"
PYTHON = Path(r"E:\app\python\python.exe")
A2_URL = "http://127.0.0.1:8000/api/config"
A3_URL = "http://127.0.0.1:8100/api/health"
A2_SERVICE_VERSION = "2026-11-04-4"
A3_SERVICE_VERSION = "2026-11-06-1"
WEB_SERVICE_VERSION = "2026-11-12-3"
WEB_URL = "http://127.0.0.1:5173/index.html"
WEB_HEALTH_URL = "http://127.0.0.1:5173/api/health"
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CHILD_FLAGS = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
LOG_DIR = Path(os.environ.get("TEMP", "."))
A2_LOG = LOG_DIR / "g4-a2-service.log"
A3_LOG = LOG_DIR / "g4-a3-service.log"
WEB_LOG = LOG_DIR / "g4-web-service.log"


def can_open(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def current_a2_is_running() -> bool:
    try:
        with urllib.request.urlopen(A2_URL, timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("service_version") == A2_SERVICE_VERSION
    except Exception:
        return False


def current_web_is_running() -> bool:
    try:
        with urllib.request.urlopen(WEB_HEALTH_URL, timeout=1) as response:
            health = json.loads(response.read().decode("utf-8"))
        if health.get("service_version") != WEB_SERVICE_VERSION:
            return False
        with urllib.request.urlopen(WEB_URL, timeout=1) as response:
            html = response.read().decode("utf-8", errors="replace")
        return 'styles.css?v=65' in html and 'a2-api.js?v=12' in html and 'a3-api.js?v=4' in html and 'ch-api.js?v=2' in html and 'ch-replay.js?v=9' in html and 'performance-dashboard.js?v=22' in html and 'app.js?v=52' in html
    except Exception:
        return False


def current_a3_is_running() -> bool:
    try:
        with urllib.request.urlopen(A3_URL, timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("service_version") == A3_SERVICE_VERSION
    except Exception:
        return False


def listener_pids(port: int) -> list[int]:
    result = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True,
        encoding="mbcs", errors="replace", check=False,
    )
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        if "LISTENING" not in line or f":{port} " not in line:
            continue
        fields = line.split()
        if fields and fields[-1].isdigit():
            pids.add(int(fields[-1]))
    return sorted(pids)


def stop_port(port: int) -> None:
    for pid in listener_pids(port):
        if pid != os.getpid():
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )


def wait_for(url: str, process: subprocess.Popen[bytes] | None, seconds: int) -> bool:
    for _ in range(seconds * 2):
        if can_open(url):
            return True
        if process is not None and process.poll() is not None:
            return False
        time.sleep(0.5)
    return False


def main() -> int:
    if not PYTHON.exists():
        print(f"Python not found: {PYTHON}")
        return 1
    if not A2_DIR.exists():
        print(f"A2 directory not found: {A2_DIR}")
        return 1
    if not A3_DIR.exists():
        print(f"A3 runtime directory not found: {A3_DIR}")
        return 1

    a2_process: subprocess.Popen[bytes] | None = None
    try:
        if not current_a2_is_running():
            stop_port(8000)
            if listener_pids(8000):
                print("A2 service could not be replaced: port 8000 is still occupied.")
                print("Please close the old A2 service and run start-server.bat again.")
                return 1
            a2_process = subprocess.Popen(
                [str(PYTHON), "-B", "-m", "uvicorn", "server.app:app",
                 "--host", "127.0.0.1", "--port", "8000"],
                cwd=A2_DIR,
                stdout=A2_LOG.open("ab"), stderr=subprocess.STDOUT,
                creationflags=CHILD_FLAGS,
            )
            if not wait_for(A2_URL, a2_process, 30) or not current_a2_is_running():
                print("A2 service failed to start. Check the A2 start_server.bat for details.")
                return 1
            print("A2 service ready: http://127.0.0.1:8000")
        else:
            print("A2 service already running.")

        if not current_a3_is_running():
            stop_port(8100)
            if listener_pids(8100):
                print("A3 service could not be replaced: port 8100 is still occupied.")
                return 1
            a3_process = subprocess.Popen(
                [str(PYTHON), "-B", "a3_server.py"],
                cwd=PROJECT_DIR,
                stdout=A3_LOG.open("ab"), stderr=subprocess.STDOUT,
                creationflags=CHILD_FLAGS,
            )
            if not wait_for(A3_URL, a3_process, 30) or not current_a3_is_running():
                print("A3 service failed to start. Check g4-a3-service.log for details.")
                return 1
            print("A3 service ready: http://127.0.0.1:8100")
        else:
            print("A3 service already running.")

        if not current_web_is_running():
            stop_port(5173)
            web_process = subprocess.Popen(
                [str(PYTHON), "-B", "server.py"],
                cwd=PROJECT_DIR,
                stdout=WEB_LOG.open("ab"), stderr=subprocess.STDOUT,
                creationflags=CHILD_FLAGS,
            )
            if not wait_for(WEB_URL, web_process, 15):
                print("Web service failed to start.")
                return 1
            print("Web service ready: http://127.0.0.1:5173")
        else:
            print("Current web service already running.")

        webbrowser.open(WEB_URL)
        print("Both services are ready. They will continue running after this launcher closes.")
        return 0
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
