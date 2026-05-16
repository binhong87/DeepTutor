"""Deploy tutorbot-web to a remote Docker host over SSH.

Reads SSH credentials from environment:

    DEPLOY_HOST       — host/IP                 (default: 111.230.73.161)
    DEPLOY_USER       — SSH user                (default: ubuntu)
    DEPLOY_PASSWORD   — SSH password            (required)
    DEPLOY_API_BASE   — NEXT_PUBLIC_API_BASE    (default: http://${DEPLOY_HOST}:8001)
    DEPLOY_AUTH       — AUTH_ENABLED            (default: true)
    DEPLOY_REMOTE_DIR — server build dir        (default: /home/ubuntu/tutorbot-web)
    DEPLOY_PORT       — host port for container (default: 3000)
    DEPLOY_STAGE      — one of: check | upload | build | run | all (default: all)

Usage (PowerShell):

    $env:DEPLOY_PASSWORD = '...'
    python scripts/deploy_tutorbot_web.py

The script is idempotent: re-running uploads only changed files (mtime+size) and
recreates the container.
"""

from __future__ import annotations

import os
import posixpath
import stat
import sys
from pathlib import Path
from typing import Optional

import paramiko

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HOST = os.environ.get("DEPLOY_HOST", "111.230.73.161")
USER = os.environ.get("DEPLOY_USER", "ubuntu")
PASSWORD = os.environ.get("DEPLOY_PASSWORD")
API_BASE = os.environ.get("DEPLOY_API_BASE", f"http://{HOST}:8001")
AUTH_ENABLED = os.environ.get("DEPLOY_AUTH", "true")
REMOTE_DIR = os.environ.get("DEPLOY_REMOTE_DIR", "/home/ubuntu/tutorbot-web")
HOST_PORT = os.environ.get("DEPLOY_PORT", "3000")
STAGE = os.environ.get("DEPLOY_STAGE", "all")

LOCAL_ROOT = Path(__file__).resolve().parent.parent / "tutorbot-web"

# Patterns mirroring .dockerignore — kept narrow so the upload is small.
EXCLUDE_DIRS = {"node_modules", ".next", "out", ".git", "coverage",
                "playwright-report", "test-results", ".vscode", ".idea"}
EXCLUDE_FILE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".log")
EXCLUDE_FILES = {".DS_Store", ".env.local"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[deploy] {msg}", flush=True)


def connect() -> paramiko.SSHClient:
    if not PASSWORD:
        sys.exit("DEPLOY_PASSWORD env var is required.")
    log(f"connecting to {USER}@{HOST}")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=HOST,
        username=USER,
        password=PASSWORD,
        look_for_keys=False,
        allow_agent=False,
        timeout=30,
    )
    return client


def run(client: paramiko.SSHClient, cmd: str, *, check: bool = True,
        quiet: bool = False) -> tuple[int, str, str]:
    if not quiet:
        log(f"$ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, get_pty=False)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    if out and not quiet:
        print(out, end="" if out.endswith("\n") else "\n")
    if err and not quiet:
        print(err, end="" if err.endswith("\n") else "\n", file=sys.stderr)
    if check and rc != 0:
        raise RuntimeError(f"remote command failed (rc={rc}): {cmd}")
    return rc, out, err


def sudo(client: paramiko.SSHClient, cmd: str, **kw):
    """Run cmd via sudo, feeding the password on stdin to -S."""
    return run(client, f"echo {PASSWORD!r} | sudo -S -p '' {cmd}", **kw)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

def stage_check(client: paramiko.SSHClient) -> None:
    log("=== check ===")
    run(client, "uname -a")
    run(client, "df -h / | tail -n 2")
    rc, out, _ = run(client, "command -v docker || true", quiet=True)
    if "docker" not in out:
        log("docker not found — installing via apt")
        sudo(client, "apt-get update")
        sudo(client, "apt-get install -y docker.io")
        sudo(client, f"usermod -aG docker {USER}")
    rc, out, _ = run(client, "docker version --format '{{.Server.Version}}' 2>/dev/null || true",
                     quiet=True)
    if not out.strip():
        log("docker daemon not reachable as user — using sudo for docker commands")
        # Verify daemon works via sudo
        sudo(client, "docker version --format '{{.Server.Version}}'")
    else:
        log(f"docker server: {out.strip()}")


def _should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if EXCLUDE_DIRS & parts:
        return True
    if path.name in EXCLUDE_FILES:
        return True
    if path.suffix.lower() in EXCLUDE_FILE_SUFFIXES:
        return True
    return False


def _mkdir_p(sftp: paramiko.SFTPClient, remote_path: str) -> None:
    parts = remote_path.split("/")
    cur = ""
    for p in parts:
        if not p:
            cur = "/"
            continue
        cur = posixpath.join(cur, p) if cur != "/" else "/" + p
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            sftp.mkdir(cur)


def _remote_size_mtime(sftp: paramiko.SFTPClient, remote_path: str) -> Optional[tuple[int, int]]:
    try:
        st = sftp.stat(remote_path)
        return (st.st_size or 0, int(st.st_mtime or 0))
    except FileNotFoundError:
        return None


def stage_upload(client: paramiko.SSHClient) -> None:
    log(f"=== upload {LOCAL_ROOT} -> {REMOTE_DIR} ===")
    sftp = client.open_sftp()
    _mkdir_p(sftp, REMOTE_DIR)

    uploaded = 0
    skipped = 0
    for local_path in LOCAL_ROOT.rglob("*"):
        rel = local_path.relative_to(LOCAL_ROOT)
        if _should_skip(rel):
            continue
        remote_path = posixpath.join(REMOTE_DIR, rel.as_posix())
        if local_path.is_dir():
            _mkdir_p(sftp, remote_path)
            continue
        # Skip if remote file matches size + mtime closely.
        local_stat = local_path.stat()
        meta = _remote_size_mtime(sftp, remote_path)
        if meta and meta[0] == local_stat.st_size and abs(meta[1] - int(local_stat.st_mtime)) <= 2:
            skipped += 1
            continue
        _mkdir_p(sftp, posixpath.dirname(remote_path))
        sftp.put(str(local_path), remote_path)
        sftp.utime(remote_path, (int(local_stat.st_atime), int(local_stat.st_mtime)))
        uploaded += 1
        if uploaded % 50 == 0:
            log(f"  uploaded {uploaded} files so far…")
    sftp.close()
    log(f"upload complete: {uploaded} sent, {skipped} skipped (unchanged)")


def _docker(client: paramiko.SSHClient, cmd: str, **kw):
    """Run docker, automatically using sudo if the user isn't in the docker group."""
    rc, _, _ = run(client, "docker version >/dev/null 2>&1; echo $?", quiet=True, check=False)
    # Re-test cleanly:
    rc, out, _ = run(client, "docker version >/dev/null 2>&1 && echo OK || echo NO",
                     quiet=True, check=False)
    if "OK" in out:
        return run(client, f"docker {cmd}", **kw)
    return sudo(client, f"docker {cmd}", **kw)


def stage_build(client: paramiko.SSHClient) -> None:
    log("=== build image ===")
    build_cmd = (
        f"cd {REMOTE_DIR} && "
        f"docker build "
        f"--build-arg NEXT_PUBLIC_API_BASE={API_BASE!s} "
        f"--build-arg AUTH_ENABLED={AUTH_ENABLED!s} "
        f"-t tutorbot-web:latest ."
    )
    # Decide once whether sudo is needed for docker.
    rc, out, _ = run(client, "docker version >/dev/null 2>&1 && echo OK || echo NO",
                     quiet=True, check=False)
    if "OK" in out:
        run(client, build_cmd)
    else:
        sudo(client, build_cmd)


def stage_run(client: paramiko.SSHClient) -> None:
    log("=== run container ===")
    rc, out, _ = run(client, "docker version >/dev/null 2>&1 && echo OK || echo NO",
                     quiet=True, check=False)
    use_sudo = "OK" not in out

    def d(cmd: str, **kw):
        return (sudo if use_sudo else run)(client, f"docker {cmd}", **kw)

    d("rm -f tutorbot-web", check=False)
    d(
        f"run -d --name tutorbot-web --restart unless-stopped "
        f"-p {HOST_PORT}:3000 tutorbot-web:latest"
    )
    d("ps --filter name=tutorbot-web --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}'")


def main() -> None:
    client = connect()
    try:
        stages = ["check", "upload", "build", "run"] if STAGE == "all" else [STAGE]
        for s in stages:
            globals()[f"stage_{s}"](client)
        log(f"done — container should be at http://{HOST}:{HOST_PORT}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
