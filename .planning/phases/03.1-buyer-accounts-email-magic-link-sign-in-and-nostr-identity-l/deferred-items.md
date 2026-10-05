# Deferred Items — Phase 03.1

Out-of-scope discoveries logged during 03.1-01 execution. Pre-existing at
HEAD (verified on the unmodified tree); not caused by this plan's changes.

## Pre-existing lint debt — `make lint` red

`uv run ruff check .` reports 14 errors in `tools/demo/` (`demo.py`,
`demo_tail.py`, `reshoot.py`, `verify_gen.py` — committed in `dd3feb3
tools: commit narrated demo pipeline`): E501 line-too-long in HTML
f-strings, I001 unsorted imports, F841 unused variables, E702 semicolon
compound statement. No plan-touched file contributes to this; `ruff check`
on all files modified by 03.1-01 is clean. Fixing the demo tooling is a
separate cleanup — recommend `chore:` commit or `tools/` exclusion
discussion with maintainers.

## Pre-existing pytest exit hang — `test_db.py` + `test_install.py` pairing

`uv run pytest -q tests/runtime/test_db.py tests/runtime/test_install.py`
runs all 17 tests green (`17 passed in ~3.4s`), then the pytest process
sleeps forever at teardown (main thread in `futex_wait_queue`; tokio /
async-compat threads idle in `do_epoll_wait`). Reproduced identically on
the unmodified HEAD tree and in both file orderings — NOT caused by m008.
Each file passes cleanly alone, and the full `pytest -m runtime -q` suite
(359 passed) exits normally. Likely an interaction between test_db's
un-disposed module-scoped `Database` engine and the host boot's async
runtime teardown; worth a `runtime teardown: dispose module-scoped
Database engines` investigation if it recurs on other pairs.
