# PINS — Infinitemarkets Qualification Profile

Frozen pins, platform claims, artifact identities, provenance, and evidence
pointers for the Infinitemarkets conformance profile. Surfaced per technical
specification section 2 (Pinned inputs). Any candidate other than the
host-resolved `nostr-sdk==0.44.8` requires an explicit spec decision and the
identical qualification profile (D-13, D-14). The host MUST NOT be silently
downgraded.

**Status: APPROVED** (D-11) — see [Approval](#approval).

---

## 1. Normative Pins

| Input | Pin |
|---|---|
| Infinitemarkets market-spec | commit `5dc79c5` (`main` @ 2025-05-10) |
| Nostr NIPs | commit `a2494f4f81d46684e5814a9bf35e2b1df978f955` (2026-09-09); files 09, 15, 17, 32, 37, 42, 44, 59, 65, 89, 99 |
| NIP-15 status | draft/unrecommended — compatibility only |
| NIP-44 version | v2 payload only |
| Nostr library (Phase 0 candidate) | Python `nostr-sdk==0.44.8` — host-resolved; a candidate, not a safety certification |
| LNbits host | `v1.7.1`, commit `4fa70f338d274e14fc82746a83fba5c2c658211f` (Python >=3.10,<3.14) |

Version `0.44.8` is a candidate because the pinned host resolves it, not a
safety certification by version number (spec section 2).

## 2. Platform Claim (D-01, D-02, D-03, D-04)

**Blocking profiles (all four must pass the complete suite clean — D-10):**

| # | Architecture | OS | Database |
|---|---|---|---|
| 1 | Linux x86_64 | ubuntu-24.04 | SQLite |
| 2 | Linux x86_64 | ubuntu-24.04 | PostgreSQL |
| 3 | Linux ARM64 | ubuntu-24.04-arm | SQLite |
| 4 | Linux ARM64 | ubuntu-24.04-arm | PostgreSQL |

**Advisory profile (non-blocking, D-04):** macOS ARM64 (SQLite smoke).
Failures are visible but do not block Release A; local developer runs on
macOS are advisory evidence only.

**Python claim (D-02):** Python 3.12 only (`>=3.12,<3.13`) — deliberately
narrower than the pinned LNbits host, which permits Python 3.10–3.12. The
extension's packaging metadata, startup/install checks, and release
documentation state this narrower claim explicitly.

## 3. SDK Artifact Identities (nostr-sdk 0.44.8)

Wheel filename and SHA-256 per platform tag are **parsed at verification
time from the pinned host checkout's `uv.lock`** (`.cache/lnbits/uv.lock`,
the source of truth for P0-01) — never hand-copied into prose. The
qualification suite (`tests/qualification/test_p0_01_pins.py`) verifies that
the harness's own lock resolves the same artifact hashes as the host lock
for the executing platform's tag; any parity mismatch blocks (no silent
downgrade, D-01).

Recorded identities (parsed from the host lock at pin-freeze time, for
review only — runtime verification re-parses the lock):

| Platform tag | Wheel | SHA-256 |
|---|---|---|
| manylinux_2_17_x86_64 | `nostr_sdk-0.44.8-cp39-abi3-manylinux_2_17_x86_64.whl` | `e6b2f1b44ae95b35712008c2e0335ab833a30545a80c4afa45992b439b20e66b` |
| manylinux_2_17_aarch64 | `nostr_sdk-0.44.8-cp39-abi3-manylinux_2_17_aarch64.whl` | `7b7a684afbfc9118aa2dd3adc7f06fa0d0f872e7ccfdf7542d2ba649f4b3689b` |
| macosx_11_0_arm64 | `nostr_sdk-0.44.8-cp39-abi3-macosx_11_0_arm64.whl` | `d781526da09550a8ca7b11abf0ee270bda53fabe191a2abfc8851dd1f3f4235c` |

musllinux, x86_64-macOS, and Windows wheel identities are also recorded in
the host lock; the complete set is parsed and compared by the P0-01 suite.

### Release-source and native provenance

The host lock records **wheels only** for `nostr-sdk` — there is **no sdist
entry** — and PyPI confirms nostr-sdk 0.44.8 is a wheels-only release (13
wheels, no sdist artifact). Release-source provenance is therefore pinned
from the source repository the package metadata points to:

| Field | Value |
|---|---|
| Repository | `rust-nostr/nostr-sdk-ffi` (https://github.com/rust-nostr/nostr-sdk-ffi) |
| Release-source revision | `a600c2a7186559b371030fe5fc5585c37b3a0931` |
| Identification | "Release v0.44.8" commit on the `v0.44` maintenance branch (2026-08-02T11:29:43Z), 11 minutes before the PyPI wheel upload (2026-08-02T11:40:50Z) — no git tag exists for 0.44.8 (repo tags jump v0.44.2 → v0.45.0) |

Native Cargo dependency revisions, parsed from the `Cargo.lock` at that
revision (cached under `.cache/nostr-sdk-src/` and re-verified by the P0-01
suite against the pins below):

| Cargo package | Version |
|---|---|
| `secp256k1` | 0.29.1 |
| `secp256k1-sys` | 0.10.1 |
| `chacha20poly1305` | 0.10.1 |
| `chacha20` | 0.9.1 |
| `aes` | 0.8.4 |
| `nostr` | 0.44.7 |
| `nostr-relay-pool` | 0.44.3 |
| `nostr-sdk` (Rust) | 0.44.1 |
| `uniffi` | 0.29.4 |

### D-15 contingency (source-built SDK)

A source-built SDK may become authoritative **only with a
pinned native revision, a reproducible build, hashed artifacts, recorded
review evidence, and all blocking tests passing — and only with explicit
owner approval**.
Absent every one of these, the host-resolved wheel pin remains authoritative
(D-13, D-14, D-15).

## 4. Installation / Lockfile Path (supported, reproducible)

```text
tools/checkout_host.py   # idempotent; hard-fails unless HEAD == 4fa70f338d274e14fc82746a83fba5c2c658211f
uv sync                  # resolves lnbits (path source) + nostr-sdk==0.44.8 into uv.lock
make verify              # canonical verification command (D-07)
```

Lock identities (recorded in the evidence manifest pins block on every
`make verify`):

- **Harness lockfile**: `uv.lock` (repo root), file SHA-256 recorded per run
  by `harness/pins.py`.
- **Host checkout**: `.cache/lnbits` at commit
  `4fa70f338d274e14fc82746a83fba5c2c658211f`; its `uv.lock` is the
  wheel-hash source of truth for P0-01 parity.
- The harness's FULL `uv.lock` resolution (every direct and transitive
  package with name, version, and per-artifact hashes) is recorded into the
  evidence manifest pins block, so divergence between the harness's
  transitives and the host checkout's resolution is visible at review
  instead of silently accepted.
- The read-only research checkout at
  `/Users/bk/github/gamma-markets-research/lnbits` (revision `74cccac`) is
  never used by the harness — it is not the qualified source.

## 5. Qualification Results (spec §2 — executable evidence summaries)

Results recorded here are pass/fail summaries of the committed evidence;
the full per-test detail lives in `evidence/manifest.json` (§6) for the
run that produced them.

### Protocol constants

- **NIP-32 namespace** (§6.8): `org.infinitemarkets.protocol` — pinned; carried
  by public commerce events (30402/30405/30406, optionally 30017/30018) and
  never on kind-0, NIP-89, NIP-04, seals, or gift wraps.
- **Frozen identifiers** (§21.25): package `infinitemarkets`, route prefix
  `/infinitemarkets`, hooks `infinitemarkets_start`/`infinitemarkets_stop`, env
  prefix `INFINITEMARKETS_`, payment correlation `infinitemarkets:`.

### SDK security / FFI / crypto (P0-02)

| Probe | Result |
|---|---|
| Pinned artifact identity (SHA-256 vs host lock) | pass |
| Event id/signature verification; malformed/tampered rejection | pass |
| NIP-44 v2 encrypt/decrypt round-trip + wrong-key failure | pass |
| Bounded-input behavior (oversize event/CT, AUTH-flood) | pass |
| NIP-59 gift-wrap chain construction | pass |

Detail: `evidence/manifest.json` → results `tests/qualification/test_p0_02_sdk_security.py::*`.

### Per-relay ACK classification (P0-04)

| Relay behavior | Classified as | Result |
|---|---|---|
| Positive OK (accepted) | `accepted` | pass |
| Negative OK (rejected + message) | `rejected`, relay message verbatim | pass |
| No OK (silent relay) | `timeout` — never send success | pass |

Structured per-relay outcomes are recorded per run in the manifest as the
`relay_ack_classification` observation on
`tests/qualification/test_p0_04_relay_ack.py::test_positive_negative_and_timeout_acks_classified_per_relay`.

### FX float boundary (P0-13)

Host/provider floats cross into the domain through exactly one
`Decimal(str(value))` boundary; per-line and per-shipping-component
`ROUND_CEILING`. Measured bound (deterministic seed, recorded per run in
`evidence/manifest.json` → `fx_measurement`):

- Max relative float error: `7.46e-17` (30-sample seeded corpus)
- Max absolute sat error after ceiling: `0` sats

### Platform matrix

| Profile | Status |
|---|---|
| linux-x86_64 · py3.12 · sqlite | CI blocking (`.github/workflows/qualification.yml`) |
| linux-x86_64 · py3.12 · postgres | CI blocking |
| linux-aarch64 · py3.12 · sqlite | CI blocking |
| linux-aarch64 · py3.12 · postgres | CI blocking |
| darwin-arm64 · py3.12 · sqlite/postgres | advisory local — 221/221 green (last `make verify`) |

The durable committed evidence bundle is refreshed from the canonical
blocking CI profile (Linux x86_64 + PostgreSQL) at phase end; a local
single-profile `make verify` regenerating `evidence/` is development-only.

### Known vulnerabilities in the pinned tree (Dependabot disposition)

Host `v1.7.1` (`4fa70f3`) pins `pyjwt~=2.15.1`, which resolves the
patched 2.15.1. The 13 earlier pyjwt alerts on `uv.lock` are closed as
fixed. Where the host constraint still admits a vulnerable release, the
harness forces the patched line through `[tool.uv] override-dependencies`:
`pillow>=13.0.0,<14` (the host declares `pillow~=12.3.0`),
`oauthlib>=4.0.1` (the host lock resolves 4.0.0) and `multidict>=6.9.1`.
These overrides cover CI and development only. LNbits does not install
extension dependencies, so a production host runs its own resolution.
Operators get those fixes by upgrading the host, not this extension.

Two host-pinned packages keep alerts that are dismissed as `tolerable_risk`
rather than overridden, so CI keeps qualifying the versions the host ships:

- **starlette 0.48.0** (unchanged at v1.7.1; GHSA-7f5h, wqp7, 82w8, 86qp, jp82, x746):
  - FileResponse Range-header DoS (GHSA-7f5h).
  - StaticFiles UNC/NTLM on Windows (GHSA-wqp7). N/A: the pins claim
    Linux/macOS only.
  - `request.form()` limit bypass (GHSA-82w8).
  - Host-header / `request.url` poisoning (GHSA-86qp, jp82).
  - `HTTPEndpoint` getattr method dispatch (GHSA-x746).

  The qualification harness serves no HTTP. Extension routes run inside
  the host's starlette, and the extension mitigates each advisory: it
  accepts JSON-only request bodies (no `request.form()`), uses no
  `FileResponse`/`StaticFiles` in extension code, uses `APIRouter` only
  (no `HTTPEndpoint` subclassing, which is also the LNbits convention),
  and never derives security decisions or absolute URLs from
  `request.url`/Host.

- **pydantic-settings 2.12.0** (GHSA-4xgf): the host pins
  `pydantic-settings~=2.12.0`. The flaw is in
  `NestedSecretsSettingsSource`, which follows symlinks out of
  `secrets_dir` when `secrets_nested_subdir=True`. LNbits `Settings` is
  configured with `env_file=".env"` only, with no `secrets_dir`
  (`lnbits/settings.py:1393` at `4fa70f3`). infinitemarkets does not use
  pydantic-settings, so the vulnerable path is unreachable.

If a future host pin resolves patched versions, these alerts re-dispatch
against the new lock naturally.

## 6. Evidence Pointers (D-09)

- `evidence/manifest.json` — machine-readable normalized results (schema
  version, UTC timestamp, exact verify command, profile block, pins block,
  per-test results, P0-01..P0-14 coverage map).
- `evidence/REPORT.md` — concise human report rendered from the manifest
  (profile, pins summary, P0 coverage table, failures, D-16 disclosure).
- CI artifacts (raw pytest output) are uploaded per profile job by
  `.github/workflows/qualification.yml`; raw output is never committed.
- Reruns do not flip recorded outcomes (D-10 clean-pass policy): the tooling
  performs single runs only.

## 7. Approval

**APPROVED** — owner approved the pins and the evidence summary on
2026-09-20; Phase 2 planning is unlocked (D-11).

| Field | Value |
|---|---|
| Approved pins | nostr-sdk 0.44.8 (release-source `a600c2a7`, wheel sha256 per §1), LNbits `v1.7.1` @ `4fa70f338d27`, Python 3.12, SQLite + PostgreSQL dialects, Linux x86_64/aarch64 blocking matrix |
| Approved evidence bundle | canonical CI run `35535526249` (linux-x86_64 + postgres, 220/221 passed, 1 optional-relay skip) committed at `2abeb30`; all P0-01..P0-14 green |
| Owner / date | bitkarrot / 2026-09-20 |

## 8. Release-B Conformance Tooling + Operator Egress (D-33)

### Operator egress requirement (normative for the Release-B claim)

Per `docs/technical-specification.md` §21 decision 30 (the D-33 §9.5
disposition), Release-B conformance is proven by in-code relay-target
egress checks (syntactic + DNS-resolve private-range rejection at
discover/connect/reconnect), this documented operator requirement, and
self-hosted recipient-gated relay evidence. **Deployments claiming
Release B MUST block loopback/private/link-local/multicast/reserved/
metadata ranges (IPv4+IPv6, including 169.254.169.254) at OS or container
egress, or restrict relay targets to an operator-curated allowlist.** The
OS/container egress policy itself is an operator deployment
responsibility — it is not part of the Release-B conformance
precondition.

### External-client conformance pins (dev/test tooling only — never
runtime dependencies)

| Input | Pin |
|---|---|
| External Gamma client | `PlebeianApp/market` @ `4bc7f8c0c73ae4ba2ff2a78f0c66d28347d1c1ce` (HEAD re-verified at matrix run time; drift fails the gate) |
| Reference gated inbox | LNbits `nostrrelay` extension @ `a87bc1fd3da7ceb8f2fdf3d6b80e3ff54cbbdb30` (reference deployment only, D-34) |
| `nak` (local relay) | go-install build, `nak version` reports `debug` — unversioned dev tool |
| `bun` (Plebeian driver) | `1.3.11` |
| Runtime requirements | none added — nostr-sdk 0.44.8 covers the protocol surface |

Conformance artifacts live at `evidence/conformance/` (durable JSON
reports; raw logs are never committed) and are merged into
`evidence/manifest.json` under `conformance.release_b` by
`tests/conformance/run_matrix.sh matrix`. Divergences from the strict
rumor model are recorded in the known-delta register
(`tests/conformance/README.md` + the matrix report), per D-32.
