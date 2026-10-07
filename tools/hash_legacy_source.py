#!/usr/bin/env python3
"""Compute a deterministic hash for the audited same-instance old source.

The hash covers only the operator-supplied directory's ``*.py`` files (plus
``config.json`` when present), sorted by relative path. Bytecode, caches,
data files, and unrelated directories are ignored. The output is JSON for
the operator to record in a future source-contract import. It does not
inspect a database, load Python modules, or modify the source.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def _digest(root: Path) -> tuple[str, list[dict[str, object]]]:
    if not root.is_dir() or not root.is_absolute() or ".." in root.parts:
        raise SystemExit("source directory must be an absolute existing path")
    if (root / ".git").is_file():
        raise SystemExit("git worktrees are not supported")
    if root.is_symlink():
        raise SystemExit("symlinks are not supported")
    candidates = list(root.rglob("*"))
    if any(path.is_symlink() for path in candidates):
        raise SystemExit("symlinks are not supported")
    files = sorted(
        path
        for path in candidates
        if path.is_file() and not path.is_symlink()
        and (path.suffix == ".py" or path.name == "config.json")
    )
    if not files:
        raise SystemExit("source directory contains no auditable Python files")
    payload = []
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        file_hash = hashlib.sha256(data).hexdigest()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative.encode())
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
        payload.append({"path": relative, "sha256": file_hash, "bytes": len(data)})
    return digest.hexdigest(), payload


def _git_commit(root: Path) -> str | None:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root,
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    if dirty:
        return None
    return head


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: hash_legacy_source.py /absolute/source-directory")
    root = Path(sys.argv[1]).resolve()
    digest, files = _digest(root)
    print(json.dumps({
        "source_id": root.name,
        "code_hash": digest,
        "git_commit": _git_commit(root),
        "file_count": len(files),
        "files": files,
    }, indent=2))


if __name__ == "__main__":
    main()
