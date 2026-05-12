#!/usr/bin/env python
"""Stop all DeepTutor web processes (main app + tutorbot-web)."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from start_web import stop_recorded_processes, _kill_port_holders_win, _kill_webpack_workers_win  # noqa: E402


def main() -> None:
    stop_recorded_processes()
    # Kill orphaned tutorbot-web and web webpack workers by project path.
    _kill_port_holders_win([3000])
    _kill_webpack_workers_win(PROJECT_ROOT / "web")
    _kill_webpack_workers_win(PROJECT_ROOT / "tutorbot-web")


if __name__ == "__main__":
    main()
