"""HARD-07 / CI-01 process-lifecycle regression.

The db/install pair once printed its passes and then the interpreter
never exited: an extension worker task cancelled inside
``Database.connect()``'s engine checkout left an ``AsyncConnection``
that nothing closed — on SQLite a non-daemon aiosqlite worker thread
survived and ``threading._shutdown`` joined it forever.

This parent test spawns each explicit file order in a fresh child
process (never itself, never the whole tree) with a 120-second
deadline, a fresh ``LNBITS_DATA_FOLDER`` and the inherited DB profile.
Timeout, kill or any nonzero exit is FAIL — only a natural exit 0 with
a nonempty ``passed`` summary counts as clean lifecycle evidence.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.runtime

REPO_ROOT = Path(__file__).resolve().parents[1]
_DB_THEN_INSTALL = [
    "tests/runtime/test_db.py",
    "tests/runtime/test_install.py",
]
_ORDERS = {
    "db-then-install": _DB_THEN_INSTALL,
    "install-then-db": list(reversed(_DB_THEN_INSTALL)),
}
_TIMEOUT_S = 120
_DIAG_S = 15


def _run_pair(label: str, argv_files: list[str]) -> str:
    env = dict(os.environ)
    # The child's run must never overwrite the durable evidence bundle.
    env.pop("GAMMA_QUAL_EVIDENCE", None)
    env["LNBITS_DATA_FOLDER"] = tempfile.mkdtemp(prefix=f"im-exit-{label}-")
    env.setdefault("UV_NO_ENV_FILE", "1")
    env.setdefault("UV_NO_SYNC", "1")
    env.setdefault("UV_OFFLINE", "1")
    env.setdefault("TZ", "UTC")
    env["PYTHONFAULTHANDLER"] = "1"
    # sys.executable -m pytest == the current uv-run environment: the
    # direct child IS pytest, so deadline signals reach the actual test
    # process (a `uv run` wrapper would orphan the pytest grandchild and
    # keep the output pipe open).
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", *argv_files, "-q"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        output, _ = proc.communicate(timeout=_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        # Deadline hit — capture faulthandler stacks via SIGABRT for
        # evidence, then terminate the owned child and FAIL. Killing is
        # cleanup, never success.
        try:
            proc.send_signal(signal.SIGABRT)
            output, _ = proc.communicate(timeout=_DIAG_S)
        except Exception:
            proc.kill()
            output, _ = proc.communicate()
        pytest.fail(
            f"child pytest ({label}) did not exit within {_TIMEOUT_S}s "
            f"(returncode={proc.returncode}); tail:\n"
            f"{(output or '')[-4000:]}"
        )
    assert proc.returncode == 0, (
        f"child pytest ({label}) exit {proc.returncode}:\n"
        f"{(output or '')[-4000:]}"
    )
    return output or ""


@pytest.mark.parametrize("order", list(_ORDERS), ids=list(_ORDERS))
def test_hard07_db_install_orders_exit_cleanly(order: str) -> None:
    output = _run_pair(order, _ORDERS[order])
    passed = re.search(r"(\d+) passed", output)
    assert passed and int(passed.group(1)) >= 1, (
        f"child pytest ({order}) collected/passed nothing:\n"
        f"{output[-2000:]}"
    )
