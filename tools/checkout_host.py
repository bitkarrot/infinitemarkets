#!/usr/bin/env python3
"""Idempotent checkout of the pinned LNbits host source.

Clones https://github.com/lnbits/lnbits into the directory named by the
GAMMA_QUAL_LNBITS_DIR environment variable (default: <repo-root>/.cache/lnbits),
checks out the pinned commit in detached HEAD state, and hard-fails unless
``git rev-parse HEAD`` equals that exact commit.

There is no silent downgrade and no partial use of a wrong revision (D-01,
P0-01): any failure to reach the pinned revision raises SystemExit with a
diagnostic instead of returning a usable path.

The read-only research checkout at
/Users/bk/github/gamma-markets-research/lnbits is never touched: this script
only ever operates on GAMMA_QUAL_LNBITS_DIR (repo-relative by default).

Stdlib only: the script must run before the harness virtualenv exists.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

LNBITS_REPO_URL = "https://github.com/lnbits/lnbits"
# LNbits v1.7.1 -- the qualified host revision (spec section 2).
LNBITS_COMMIT = "4fa70f338d274e14fc82746a83fba5c2c658211f"
LNBITS_TAG = "v1.7.1"


def host_checkout_dir() -> Path:
    """Resolve the harness-owned LNbits checkout directory.

    A relative GAMMA_QUAL_LNBITS_DIR value is resolved against the repository
    root so the checkout location is independent of the caller's cwd.
    """
    raw = os.environ.get("GAMMA_QUAL_LNBITS_DIR", "").strip() or ".cache/lnbits"
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True
    )


def _require_git(args: list[str], cwd: Path) -> str:
    proc = _git(args, cwd)
    if proc.returncode != 0:
        raise SystemExit(
            f"checkout_host: git {' '.join(args)} failed in {cwd}\n"
            f"stdout: {proc.stdout.strip()}\n"
            f"stderr: {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def read_head(dest: Path) -> str | None:
    """Return the current HEAD commit of the checkout, or None if absent."""
    if not (dest / ".git").exists():
        return None
    proc = _git(["rev-parse", "HEAD"], dest)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def ensure_checkout(dest: Path | None = None) -> str:
    """Bring the harness checkout to the pinned commit and return HEAD.

    Idempotent: an existing checkout already at LNBITS_COMMIT is left
    untouched. Any other state is repaired by fetching and checking out the
    pinned commit. Returns the verified HEAD commit hash.
    """
    dest = dest or host_checkout_dir()
    head = read_head(dest)
    if head == LNBITS_COMMIT:
        print(f"checkout_host: {dest} already at pinned commit {LNBITS_COMMIT}")
        return head

    if head is None:
        dest.mkdir(parents=True, exist_ok=True)
        if dest.exists() and any(dest.iterdir()):
            # Non-empty, non-git directory: refuse to clobber unknown content.
            raise SystemExit(
                f"checkout_host: {dest} exists and is not a git checkout; "
                "refusing to clone into it. Remove it or point "
                "GAMMA_QUAL_LNBITS_DIR elsewhere."
            )
        print(f"checkout_host: cloning {LNBITS_REPO_URL} into {dest}")
        _require_git(["clone", LNBITS_REPO_URL, str(dest)], REPO_ROOT)

    # The pinned commit object may be missing from a shallow or partial
    # clone; fetch it (and tags) explicitly. GitHub allows fetching by SHA.
    _require_git(["fetch", "--tags", "origin", LNBITS_COMMIT], dest)

    _require_git(["checkout", "--detach", LNBITS_COMMIT], dest)

    head = read_head(dest)
    if head != LNBITS_COMMIT:
        raise SystemExit(
            "checkout_host: HEAD verification failed after checkout: "
            f"expected {LNBITS_COMMIT}, got {head}"
        )
    print(
        f"checkout_host: verified {LNBITS_TAG} at commit {LNBITS_COMMIT} in {dest}"
    )
    return head


def main() -> int:
    ensure_checkout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
