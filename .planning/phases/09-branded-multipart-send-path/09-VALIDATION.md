---
phase: "9"
slug: "branded-multipart-send-path"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: "2026-10-17"
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded from `09-RESEARCH.md` → "Validation Architecture", then reconciled
> against the completed Phase 9 plans and summaries.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (markers `fast`, `runtime`, `db`, `protocol`, `host`, `sdk`); `tests/conftest.py`; `tests/runtime/conftest.py` (host boot per module) |
| **Quick run command** | `uv run pytest tests/runtime/test_email_render.py -q` (new file, `pytest.mark.fast`, no host boot) |
| **Fast gate** | `make verify-fast` (= `uv run pytest -m fast -q`) |
| **Targeted runtime** | `uv run pytest tests/runtime/test_email_queue.py tests/runtime/test_email_signin.py tests/runtime/test_financial_review.py -q` |
| **Full suite command** | `make verify` (= `uv run pytest -q`) plus `uv run ruff check .` |
| **Estimated runtime** | quick ~5 s; fast gate ~50 s; targeted runtime a few minutes; full runtime suite ~6 min |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/runtime/test_email_render.py -q` + `uv run ruff check infinitemarkets tests harness`
- **After every plan wave:** Run `make verify-fast` + the targeted runtime command above
- **Before `/gsd-verify-work`:** `make verify` (full) must be green on SQLite; PostgreSQL × amd64/arm runs in the CI matrix (no local PG server)
- **Max feedback latency:** ~60 seconds (fast gate)

---

## Per-Task Verification Map

Requirement-level verification map from research and completed execution.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 09-01-01 | 09-01 | 1 | EMAIL-01 | — | `multipart/alternative` order, UTF-8 text/HTML, optional CID-related logo, bare HTML fallback | unit (fast) | `uv run pytest tests/runtime/test_email_render.py -k "mime_tree or unicode_parts" -q` | ✅ | ✅ green |
| 09-01-01 | 09-01 | 1 | EMAIL-01 | SMTP boundary | Fake transport proves settings, timeout, STARTTLS/login/sendmail order, ASCII wire and propagated errors; no network | unit (fast) | `uv run pytest tests/runtime/test_email_render.py -k smtp_send -q` | ✅ | ✅ green |
| 09-01-01 | 09-01 | 1 | EMAIL-01 | queue integrity | Success enters `sent` and wipes ciphertext; false/raise retries or fails; expired claims never send; builder errors retry | runtime (host boot) | `uv run pytest tests/runtime/test_email_queue.py -q` | ✅ | ✅ green |
| 09-01-01, 09-02-01 | 09-01, 09-02 | 1, 2 | EMAIL-02 | CSS injection / remote fetch | Real item lines/totals, backorder state, event/state, live-only CTA, validated accent and readable contrast; nullable amounts never fabricated | unit (fast) | `uv run pytest tests/runtime/test_email_render.py -k sections -q` | ✅ | ✅ green |
| 09-01-01, 09-02-01 | 09-01, 09-02 | 1, 2 | EMAIL-03 | stored XSS | Hostile text/attributes/delivery/custom copy stay escaped; CSS cannot inject remote content | unit (fast) | `uv run pytest tests/runtime/test_email_render.py -k escaping -q` | ✅ | ✅ green |
| 09-01-01, 09-01-02, 09-02-01 | 09-01, 09-02 | 1, 2 | EMAIL-03 | bearer/PII leakage | Delivery only for customer `confirmed`; other channels/events omit it; subjects and headers omit private data | runtime + unit | `uv run pytest tests/runtime/test_email_queue.py -k "hard01 or delivery" -q` | ✅ | ✅ green |
| 09-01-03 | 09-01 | 1 | EMAIL-08 | consent bypass | Merchant `notify_events` gates merchant alerts only; customer consent is rechecked at send time | runtime | `uv run pytest tests/runtime/test_email_queue.py -k "notify_events or consent" -q` | ✅ | ✅ green |
| 09-01-03 | 09-01 | 1 | EMAIL-08 | — | Harness model matches merchant-only event gate | qualification (fast) | `uv run pytest tests/qualification/test_p0_10_smtp_boundary.py -q` | ✅ | ✅ green |
| 09-01-01, 09-02-02 | 09-01, 09-02 | 1, 2 | EMAIL-09 | bearer leakage into preview | Channel footers in both parts; live opt-out/sign-in links stay fragment-only; preview redacts links | unit (fast) + runtime | `uv run pytest tests/runtime/test_email_render.py -k footer -q` | ✅ | ✅ green |
| 09-01-01, 09-02-02 | 09-01, 09-02 | 1, 2 | EMAIL-10 | — | Test send uses conspicuous synthetic items despite disabled event flag; global gates and rate limit remain | runtime | `uv run pytest tests/runtime/test_email_queue.py -k orderless -q` | ✅ | ✅ green |
| 09-01-01, 09-02-02 | 09-01, 09-02 | 1, 2 | EMAIL-11 | header injection / hostname leak | Date, sender-domain Message-ID, Auto-Submitted and sanitized From; no Reply-To/List-Unsubscribe | unit (fast) | `uv run pytest tests/runtime/test_email_render.py -k header -q` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/runtime/test_email_render.py` — host-free `pytest.mark.fast` MIME, rendering, escaping, header, and footer coverage
- [x] `tests/runtime/conftest.py` — session-lifetime fail-closed SMTP guard and `smtp_capture`
- [x] Migrate the eight host-`send_email` patch functions and preserve the render-error hermeticity case
- [x] `harness/email.py` merchant-only event gate and `test_p0_10` case (2) update
- [x] Runtime coverage for EMAIL-08/10, preview redaction, and merchant delivery exclusion

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| HTML part renders legibly in real clients (Gmail web, Apple Mail, Outlook desktop) | EMAIL-02 | Client rendering engines can't be automated here; research assumption A2 (Outlook ignores `max-width`) | Configure host SMTP to a real inbox, press Notifications "send test", and open the message in each client: header band/accent, item table, footer visible, no remote-content prompt |
| Live delivery through the operator's real SMTP relay | EMAIL-01, EMAIL-10 | Automated tests use a fake `smtplib.SMTP`; no local SMTP server (`smtpd` removed in 3.12) | With host SMTP configured, press "send test" → queue row reaches `sent`; the received message shows `multipart/alternative` with both parts and the EMAIL-11 headers |

*Frozen single-binary smoke is Phase 11 (CONTEXT D-27), not this phase.*

---

## Validation Sign-Off

- [x] All tasks have automated verification
- [x] Sampling continuity: every task has focused automated verification
- [x] Wave 0 covers all previously missing references
- [x] No watch-mode flags
- [x] Feedback latency < 60s for fast validation; full suite completed separately
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated 2026-10-18

## Validation Audit 2026-10-18

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

Automated coverage is confirmed by the focused plan checks and the full suite
(`uv run python -m pytest -x -q`: 1122 passed, 8 skipped). PostgreSQL-only
concurrency tests and real-mail-client/relay checks remain in the explicit
manual/CI verification rows above.
