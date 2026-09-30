"""Start background pipeline processes and wait for them (used by e2e_check and latency)."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

PY = sys.executable
LOGS = Path("logs")


def start(name: str, args: list[str]) -> subprocess.Popen:
    LOGS.mkdir(exist_ok=True)
    fh = open(LOGS / f"{name}.log", "w")
    return subprocess.Popen([PY, "-m", *args], stdout=fh, stderr=subprocess.STDOUT)


def wait_for_line(name: str, text: str, proc: subprocess.Popen, timeout: float = 60) -> None:
    path = LOGS / f"{name}.log"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists() and text in path.read_text():
            return
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    sys.exit(f"'{text}' not seen in {path}; see that log")


def stop(*procs: subprocess.Popen | None) -> None:
    for proc in procs:
        if proc is None or proc.poll() is not None:
            continue
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def pipeline_running() -> bool:
    return any(Path(".run").glob("*.pid"))
