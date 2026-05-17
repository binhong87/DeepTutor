"""One-shot migration: retire data/memory and data/tutorbot; create multi-user/admin/ tree.

Usage:
    python scripts/migrate_to_user_isolated_layout.py [--project-root PATH]

The script is idempotent in the conservative direction: if multi-user/admin/memory/
or multi-user/admin/tutorbot/ already contain files it refuses to proceed, preserving
existing data.

What it does:
  - Creates multi-user/admin/memory/ and multi-user/admin/tutorbot/
  - Creates multi-user/_shared/knowledge_bases/
  - Deletes data/memory/ and data/tutorbot/
  - Leaves data/user/, data/knowledge_bases/, and everything else untouched
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def _has_content(path: Path) -> bool:
    return path.exists() and any(True for _ in path.iterdir())


def migrate(project_root: Path) -> None:
    admin_memory = project_root / "multi-user" / "admin" / "memory"
    admin_tutorbot = project_root / "multi-user" / "admin" / "tutorbot"
    shared_kb = project_root / "multi-user" / "_shared" / "knowledge_bases"

    if _has_content(admin_memory):
        print(
            f"ERROR: {admin_memory} already exists and is non-empty.\n"
            "Refusing to overwrite existing user data. Migration not performed.",
            file=sys.stderr,
        )
        sys.exit(1)

    if _has_content(admin_tutorbot):
        print(
            f"ERROR: {admin_tutorbot} already exists and is non-empty.\n"
            "Refusing to overwrite existing user data. Migration not performed.",
            file=sys.stderr,
        )
        sys.exit(1)

    admin_memory.mkdir(parents=True, exist_ok=True)
    admin_tutorbot.mkdir(parents=True, exist_ok=True)
    shared_kb.mkdir(parents=True, exist_ok=True)
    print(f"Created: {admin_memory}")
    print(f"Created: {admin_tutorbot}")
    print(f"Created: {shared_kb}")

    data_memory = project_root / "data" / "memory"
    if data_memory.exists():
        shutil.rmtree(data_memory)
        print(f"Deleted: {data_memory}")

    data_tutorbot = project_root / "data" / "tutorbot"
    if data_tutorbot.exists():
        shutil.rmtree(data_tutorbot)
        print(f"Deleted: {data_tutorbot}")

    print("Migration complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Path to the DeepTutor project root (default: parent of this script)",
    )
    args = parser.parse_args()
    migrate(args.project_root)


if __name__ == "__main__":
    main()
