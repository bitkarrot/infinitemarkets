# Infinitemarkets qualification harness — canonical command surface (D-06, D-07, D-12).
#
# One canonical command (`make verify`) runs the complete qualification suite
# for the selected profile (SQLite when LNBITS_DATABASE_URL is unset/empty,
# PostgreSQL otherwise — exactly like the pinned host) and emits the durable
# evidence bundle. Named subsets are pure `pytest -m` selections over the same
# single test tree for the impact-based development loop (D-12); only
# `make verify` (and the CI profiles) produce durable evidence.

PYTHON ?= python3

# pytest exit code 5 means "no tests collected": a named subset with no tests
# yet (e.g. protocol before plan 01-02) is reported as empty, not failed —
# a FAILING test inside a subset still fails the subset.
SUBSET_OK = rc=$$?; if [ $$rc -eq 5 ]; then echo "subset empty: no tests collected"; exit 0; fi; exit $$rc

.PHONY: host verify verify-fast verify-sdk verify-db verify-protocol verify-host verify-runtime lint

# Idempotent checkout of the pinned LNbits host at 4fa70f3 (must run before any
# uv usage: pyproject resolves lnbits from this path source).
host:
	$(PYTHON) tools/checkout_host.py

# Complete suite for the selected profile + evidence emission (D-09, D-10).
verify: host
	GAMMA_QUAL_EVIDENCE=1 uv run pytest -q

# Named subsets (D-06) — same tree, marker-selected, no durable evidence.
verify-fast: host
	uv run pytest -m fast -q; $(SUBSET_OK)

verify-sdk: host
	uv run pytest -m sdk -q; $(SUBSET_OK)

verify-db: host
	uv run pytest -m db -q; $(SUBSET_OK)

verify-protocol: host
	uv run pytest -m protocol -q; $(SUBSET_OK)

verify-host: host
	uv run pytest -m host -q; $(SUBSET_OK)

# Extension runtime tests (02-01+): real host loader path, no evidence.
verify-runtime: host
	uv run pytest -m runtime -q; $(SUBSET_OK)

# Remote-install release artifacts: dist/infinitemarkets-<version>.zip +
# dist/manifest.json (LNbits ExplicitRelease manifest with real sha256).
package:
	$(PYTHON) tools/package_release.py

lint:
	uv run ruff check .
