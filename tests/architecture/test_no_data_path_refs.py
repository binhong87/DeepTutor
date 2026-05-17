"""Architecture guard: no Python source may hard-code the old global paths.

After the multi-user migration (T2-T11) all memory and tutorbot data lives
under multi-user/<uid>/. Any reference to data/memory or data/tutorbot in
Python source is a bug that would re-introduce cross-user data leaks.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

_BANNED = [
    re.compile(r"""["'/]data/memory["'/]"""),
    re.compile(r"""["'/]data/tutorbot["'/]"""),
]

_SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
}

_SKIP_FILES = {
    Path(__file__).resolve(),
}


def _python_sources() -> list[Path]:
    sources: list[Path] = []
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.resolve() in _SKIP_FILES:
            continue
        sources.append(path)
    return sources


def test_no_data_memory_or_data_tutorbot_in_python_source() -> None:
    violations: list[str] = []
    for src in _python_sources():
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = src.relative_to(_REPO_ROOT)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in _BANNED:
                if pattern.search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")

    if violations:
        joined = "\n  ".join(violations)
        raise AssertionError(
            f"Found {len(violations)} reference(s) to banned legacy paths "
            f"(data/memory or data/tutorbot) in Python source:\n  {joined}"
        )
