"""Sync the local deeptutor/ source to the remote host, rebuild the
deeptutor:chatv2 image (Dockerfile.chatv2), and recompose the deeptutor
service.

Env:
    DEPLOY_PASSWORD   — SSH password (required)
    DEPLOY_HOST       — default 111.230.73.161
    DEPLOY_USER       — default ubuntu
    DEPLOY_REMOTE_DIR — default /home/ubuntu/DeepTutor
"""

from __future__ import annotations

import os
import posixpath
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("DEPLOY_HOST", "111.230.73.161")
USER = os.environ.get("DEPLOY_USER", "ubuntu")
PASSWORD = os.environ.get("DEPLOY_PASSWORD")
REMOTE_DIR = os.environ.get("DEPLOY_REMOTE_DIR", "/home/ubuntu/DeepTutor")
LOCAL_ROOT = Path(__file__).resolve().parent.parent

# Sync exactly these top-level paths under LOCAL_ROOT.
SYNC_PATHS = ["deeptutor", "Dockerfile.backend-only", "Dockerfile.chatv2", "pyproject.toml", "requirements.txt"]

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                "node_modules", ".next", ".git"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".log", ".png", ".jpg")


def log(m: str) -> None:
    print(f"[backend-deploy] {m}", flush=True)


def connect() -> paramiko.SSHClient:
    if not PASSWORD:
        sys.exit("DEPLOY_PASSWORD required")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD,
              look_for_keys=False, allow_agent=False, timeout=30)
    return c


def run(c, cmd, check=True):
    log(f"$ {cmd}")
    _, o, e = c.exec_command(cmd, get_pty=False)
    rc = o.channel.recv_exit_status()
    out, err = o.read().decode(), e.read().decode()
    if out:
        print(out, end="" if out.endswith("\n") else "\n")
    if err:
        print(err, end="" if err.endswith("\n") else "\n", file=sys.stderr)
    if check and rc != 0:
        raise RuntimeError(f"exit {rc}: {cmd}")
    return rc, out, err


def sudo(c, cmd, **kw):
    return run(c, f"echo {PASSWORD!r} | sudo -S -p '' {cmd}", **kw)


def docker_available(c) -> bool:
    rc, out, _ = run(c, "docker version >/dev/null 2>&1 && echo OK || echo NO", check=False)
    return "OK" in out


def mkdir_p(sftp, p):
    parts = p.split("/")
    cur = ""
    for x in parts:
        if not x:
            cur = "/"
            continue
        cur = posixpath.join(cur, x) if cur != "/" else "/" + x
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            sftp.mkdir(cur)


def remote_meta(sftp, p):
    try:
        s = sftp.stat(p)
        return (s.st_size or 0, int(s.st_mtime or 0))
    except FileNotFoundError:
        return None


def sync(c):
    sftp = c.open_sftp()
    mkdir_p(sftp, REMOTE_DIR)
    uploaded = 0
    skipped = 0
    for rel in SYNC_PATHS:
        local = LOCAL_ROOT / rel
        if local.is_file():
            files = [(local, Path(rel))]
        else:
            files = []
            for p in local.rglob("*"):
                rp = p.relative_to(LOCAL_ROOT)
                if EXCLUDE_DIRS & set(rp.parts):
                    continue
                if p.suffix.lower() in EXCLUDE_SUFFIXES:
                    continue
                files.append((p, rp))
        for local_path, rp in files:
            remote_path = posixpath.join(REMOTE_DIR, rp.as_posix())
            if local_path.is_dir():
                mkdir_p(sftp, remote_path)
                continue
            st = local_path.stat()
            meta = remote_meta(sftp, remote_path)
            if meta and meta[0] == st.st_size and abs(meta[1] - int(st.st_mtime)) <= 2:
                skipped += 1
                continue
            mkdir_p(sftp, posixpath.dirname(remote_path))
            sftp.put(str(local_path), remote_path)
            sftp.utime(remote_path, (int(st.st_atime), int(st.st_mtime)))
            uploaded += 1
            if uploaded % 50 == 0:
                log(f"  uploaded {uploaded}…")
    sftp.close()
    log(f"sync done: {uploaded} uploaded, {skipped} skipped")


def main():
    c = connect()
    try:
        sync(c)
        use_sudo = not docker_available(c)
        d = sudo if use_sudo else run
        d(c, f"docker build -f {REMOTE_DIR}/Dockerfile.backend-only -t deeptutor:chatv2 {REMOTE_DIR}")
        d(c, f"cd {REMOTE_DIR} && docker compose -f docker-compose.ghcr.yml up -d --no-deps deeptutor")
        d(c, "docker ps --filter name=deeptutor --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}'")
        log("backend redeploy complete")
    finally:
        c.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
