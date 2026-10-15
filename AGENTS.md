# Agent notes — Infinite Markets

## Verification (run before every push)

CI is `make verify` → `uv run pytest -q` over the ENTIRE tree, matrixed
on sqlite + postgres × amd64/arm. Most breakages come from changes that
pass `tests/runtime/` but violate the stricter `tests/qualification/`
contract tier — always run it when touching spec docs, routes, schema,
state machines, or `harness/registry.py`:

```bash
uv run pytest tests/qualification -q      # static contract checks, sub-second
uv run pytest tests/runtime -q            # host-boot runtime suite (~6 min)
uv run ruff check .
node --check <edited .js files>
```

Known fragile contract surfaces (touch them together, never alone):
- `docs/technical-specification.md` §5 routes ↔ `harness/registry.py::HTTP_ROUTES`
  (bidirectional parity test). Register EVERY implemented route; spec EVERY
  registered route.
- §7 state machines ↔ `registry.STATE_MACHINES`; §4 schema ↔
  `harness/schema.py` DDL.
- `test_public_pages.py` stock-count assertions compare raw page text —
  use `_buyer_visible` (strips scripts/styles/`?v=` asset hashes), never
  raw `resp.text`, when asserting digits are absent.

## Conventions

- Features/fixes land via PR (Devin Review may add fix commits); docs and
  `chore: release` commits go directly to main.
- Runtime tests boot a real LNbits host (`.cache/lnbits`, pinned e336fe1);
  `uv run` resolves it via `tools/checkout_host.py`.
- `_public_merchant` projections must never leak `*_enc`/`*_hash` fields;
  owner-scoped additions are fine.
- Public theme tokens never style admin chrome; arbitrary CSS/scripts/
  remote URLs are prohibited.

## Release flow

```bash
# bump infinitemarkets/config.json version, then:
uv run python tools/package_release.py      # -> dist/*.zip + dist/manifest.json
cp dist/manifest.json manifest.json
# commit both files: "chore: release vX.Y.Z — <summary>"
git tag vX.Y.Z && git push origin main vX.Y.Z
gh release create vX.Y.Z dist/infinitemarkets-X.Y.Z.zip dist/manifest.json \
  --title "Infinite Markets vX.Y.Z" --notes "..."
```
