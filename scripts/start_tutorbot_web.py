#!/usr/bin/env python
"""Start backend (port 8001) + tutorbot-web (port 3000)."""

from __future__ import annotations

import atexit
import os
import shutil
import signal
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
for _p in (str(SCRIPTS_DIR), str(PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Re-use helpers from start_web so cleanup logic stays in one place.
from start_web import (  # noqa: E402
    KILL_SIGNAL,
    ManagedProcess,
    _install_signal_handlers,
    _kill_port_holders_win,
    _kill_webpack_workers_win,
    _remove_state,
    _spawn,
    _terminate,
    _wait_for_http,
    _write_state,
    bold,
    log_error,
    log_info,
    log_success,
)

TUTORBOT_WEB = PROJECT_ROOT / "tutorbot-web"
BACKEND_PORT = 8001
FRONTEND_PORT = 3000
STATE_PATH = PROJECT_ROOT / "data" / "user" / "settings" / "start_tutorbot_state.json"
BACKEND_READY_TIMEOUT = 60
FRONTEND_READY_TIMEOUT = 120


def _cleanup_ports() -> None:
    _kill_port_holders_win([BACKEND_PORT, FRONTEND_PORT])
    _kill_webpack_workers_win(TUTORBOT_WEB)


def main() -> None:
    npm = shutil.which("npm")
    if not npm:
        log_error("npm not found.")
        raise SystemExit(1)

    print(f"\n  backend       http://localhost:{BACKEND_PORT}")
    print(f"  tutorbot-web  http://localhost:{FRONTEND_PORT}\n")

    log_info("Cleaning up orphaned processes ...")
    _cleanup_ports()

    backend_env = os.environ.copy()
    backend_env["BACKEND_PORT"] = str(BACKEND_PORT)
    backend_env["PYTHONUNBUFFERED"] = "1"
    backend_env["PYTHONIOENCODING"] = "utf-8:replace"

    frontend_env = os.environ.copy()
    frontend_env["PYTHONIOENCODING"] = "utf-8:replace"
    frontend_env["NODE_OPTIONS"] = "--max-old-space-size=4096"

    processes: list[ManagedProcess] = []
    frontend: ManagedProcess | None = None
    backend: ManagedProcess | None = None
    shutdown_requested = False
    cleanup_started = False

    def request_shutdown(signal_name: str | None = None) -> None:
        nonlocal shutdown_requested
        if shutdown_requested:
            return
        shutdown_requested = True
        if signal_name:
            print()
            log_info(f"Received {signal_name}; shutting down ...")

    def cleanup() -> None:
        nonlocal cleanup_started
        if cleanup_started:
            return
        cleanup_started = True
        _terminate(frontend, "en")
        _terminate(backend, "en")
        _remove_state(STATE_PATH)
        _kill_webpack_workers_win(TUTORBOT_WEB)

    _install_signal_handlers(request_shutdown)
    atexit.register(cleanup)

    try:
        log_info("Starting backend ...")
        backend = _spawn(
            [sys.executable, "-m", "deeptutor.api.run_server"],
            cwd=PROJECT_ROOT,
            env=backend_env,
            name="backend",
        )
        processes.append(backend)
        _write_state(processes, backend_port=BACKEND_PORT, frontend_port=FRONTEND_PORT, path=STATE_PATH)
        _wait_for_http(
            name="Backend",
            url=f"http://127.0.0.1:{BACKEND_PORT}/",
            process=backend,
            timeout=BACKEND_READY_TIMEOUT,
            language="en",
            waiting_key="waiting_backend",
            ready_key="ready_backend",
            should_stop=lambda: shutdown_requested,
        )

        log_info("Starting tutorbot-web ...")
        frontend = _spawn(
            [npm, "run", "dev", "--", "--port", str(FRONTEND_PORT)],
            cwd=TUTORBOT_WEB,
            env=frontend_env,
            name="frontend",
        )
        processes.append(frontend)
        _write_state(processes, backend_port=BACKEND_PORT, frontend_port=FRONTEND_PORT, path=STATE_PATH)
        _wait_for_http(
            name="tutorbot-web",
            url=f"http://127.0.0.1:{FRONTEND_PORT}/",
            process=frontend,
            timeout=FRONTEND_READY_TIMEOUT,
            language="en",
            waiting_key="waiting_frontend",
            ready_key="ready_frontend",
            should_stop=lambda: shutdown_requested,
        )

        log_success(f"Open {bold(f'http://localhost:{FRONTEND_PORT}')} in your browser.")
        print()

        while not shutdown_requested:
            if backend.process.poll() is not None:
                log_error(f"Backend exited with code {backend.process.returncode}.")
                break
            if frontend.process.poll() is not None:
                log_error(f"tutorbot-web exited with code {frontend.process.returncode}.")
                break
            time.sleep(1)

    except KeyboardInterrupt:
        print()
        log_info("Shutting down ...")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
