#!/usr/bin/env python
"""Start the tutorbot-web dev server (port 3000) with pre-start cleanup."""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TUTORBOT_WEB = PROJECT_ROOT / "tutorbot-web"
PORT = 3000
READY_TIMEOUT = 120


def _kill_port_holders(port: int) -> None:
    """Windows: force-kill every process LISTENING on the port via netstat -ano."""
    if os.name != "nt":
        return
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except Exception:
        return
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[3] != "LISTENING":
            continue
        if parts[1].rsplit(":", 1)[-1] != str(port):
            continue
        try:
            pid = int(parts[4])
        except ValueError:
            continue
        if pid > 0:
            pids.add(pid)
    for pid in pids:
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid), "/T"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    if pids:
        print(f"  Killed {len(pids)} orphaned process(es) on port {port}.")
        # Wait up to 3 s for Windows to release the port.
        for _ in range(6):
            time.sleep(0.5)
            if _port_free(port):
                break


def _port_free(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return False
    except OSError:
        return True


def main() -> None:
    npm = shutil.which("npm")
    if not npm:
        print("ERROR: npm not found.", file=sys.stderr)
        raise SystemExit(1)

    print(f"\n  tutorbot-web  http://localhost:{PORT}\n")

    print("  Cleaning up any orphaned processes on port 3000 ...")
    _kill_port_holders(PORT)
    # Also kill re-parented webpack workers from previous tutorbot-web sessions.
    try:
        subprocess.run(
            ["wmic", "process", "where",
             f"name='node.exe' and CommandLine like '%tutorbot-web%'",
             "delete"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False,
        )
    except Exception:
        pass

    if not _port_free(PORT):
        print(f"ERROR: port {PORT} still in use after cleanup.", file=sys.stderr)
        raise SystemExit(1)

    env = os.environ.copy()
    env["PORT"] = str(PORT)
    env["PYTHONIOENCODING"] = "utf-8:replace"

    kwargs: dict = {
        "cwd": str(TUTORBOT_WEB),
        "env": env,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True

    print("  Starting tutorbot-web ...")
    proc = subprocess.Popen([npm, "run", "dev", "--", "--port", str(PORT)], **kwargs)

    # Wait for the server to accept connections
    deadline = time.monotonic() + READY_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            print(f"ERROR: tutorbot-web exited early (code {proc.returncode}).", file=sys.stderr)
            raise SystemExit(1)
        if not _port_free(PORT):
            print(f"  tutorbot-web ready at http://localhost:{PORT}")
            break
        time.sleep(0.5)
    else:
        print(f"ERROR: tutorbot-web did not start within {READY_TIMEOUT}s.", file=sys.stderr)
        proc.terminate()
        raise SystemExit(1)

    print(f"\n  Open http://localhost:{PORT} in your browser.\n")

    def _shutdown(signum: int, _frame: object) -> None:
        print("\n  Shutting down tutorbot-web ...")
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(proc.pid), "/T"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        else:
            proc.terminate()

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig:
            try:
                signal.signal(sig, _shutdown)
            except (OSError, ValueError):
                pass

    try:
        while proc.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        _shutdown(0, None)


if __name__ == "__main__":
    main()
