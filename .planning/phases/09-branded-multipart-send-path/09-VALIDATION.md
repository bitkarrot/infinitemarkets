---
phase: "9"
slug: "branded-multipart-send-path"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-17"
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded from `09-RESEARCH.md` → "Validation Architecture". Task IDs are
> assigned when the PLAN.md files land.

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

Requirement-level map from research. The planner binds task IDs (`09-NN-MM`)
and threat refs (`T-09-NN`) to these rows. The executor flips Status.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | EMAIL-01 | — | Tree = alternative{plain, html}; synthetic logo → alternative{plain, related{html, image}} with `Content-ID: <logo@infinitemarkets>`; unusable logo → no related part, no `cid:` | unit (fast) | `uv run pytest tests/runtime/test_email_render.py -k tree -q` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | EMAIL-01 | log/credential exposure | `_smtp_send`: SMTP(server, port, timeout) → starttls → login(username or from) → sendmail(from, [to], ASCII wire); exceptions propagate; never logs; no `set_debuglevel` | unit (fast, fake SMTP) | `uv run pytest tests/runtime/test_email_render.py -k smtp_send -q` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | EMAIL-01 | — | Worker: fake `_smtp_send` True → `sent` + wipe; False/raise → `pending` + backoff; exhaustion → `failed`; expired claim never calls `_smtp_send` | runtime (host boot) | `uv run pytest tests/runtime/test_email_queue.py -q` | ✅ migrate | ⬜ pending |
| TBD | TBD | TBD | EMAIL-02 | CSS injection / remote fetch | Wordmark/logo, accent (hex `fullmatch` else default), title + state, item rows with line totals + backordered badge, subtotal/shipping/total, CTA iff live link | unit (fast) | `uv run pytest tests/runtime/test_email_render.py -k sections -q` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | EMAIL-03 | stored XSS in email | `<script>"'&` in name/title/delivery/labels/header/footer args → escaped; template has no `\|safe`/`Markup`/`autoescape`; no `src="http`, `url(`, `<link`, `<script` | unit (fast) | `uv run pytest tests/runtime/test_email_render.py -k escap -q` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | EMAIL-03 | bearer/PII leakage | Delivery only in customer `confirmed` (both parts); merchant `confirmed` lacks it; subject unchanged | runtime | `uv run pytest tests/runtime/test_email_queue.py -k "hard01 or delivery" -q` | ✅ migrate + add | ⬜ pending |
| TBD | TBD | TBD | EMAIL-08 | consent bypass | `notify_events {"shipped": false}`: customer shipped row **sent**; merchant shipped row `event-disabled`; consent revocation still `consent-revoked` | runtime | `uv run pytest tests/runtime/test_email_queue.py -k "notify_events or consent" -q` | ❌ add (consent ✅) | ⬜ pending |
| TBD | TBD | TBD | EMAIL-08 | — | Model parity: harness event gate merchant-only; customer row not gated | qualification (fast) | `uv run pytest tests/qualification/test_p0_10_smtp_boundary.py -q` | ✅ update case (2) | ⬜ pending |
| TBD | TBD | TBD | EMAIL-09 | bearer leakage into preview | Footers in BOTH parts (customer opt-in + opt-out link, no-link variant when token dead; account sign-in; merchant/test neutral); preview carries the redacted footer link | unit (fast) + runtime | `uv run pytest tests/runtime/test_email_render.py -k footer -q` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | EMAIL-10 | — | `notify_events {"order_received": false}` + POST `/notifications/test` → `sent`; HTML has sample marker + sample items; no real order data | runtime | `uv run pytest tests/runtime/test_email_queue.py -k orderless -q` | ✅ extend | ⬜ pending |
| TBD | TBD | TBD | EMAIL-11 | header injection / hostname leak | Date parses; Message-ID `@<sender domain>>`, no hostname; `Auto-Submitted: auto-generated`; From display == sanitized name (CR/LF/NUL/ESC/U+2028/bidi stripped); empty → bare address; no Reply-To / List-Unsubscribe | unit (fast) | `uv run pytest tests/runtime/test_email_render.py -k header -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/runtime/test_email_render.py` — new, `pytestmark = [pytest.mark.runtime, pytest.mark.fast]`, no host boot; covers EMAIL-01/02/03/09/11 unit behavior
- [ ] `tests/runtime/conftest.py` — fail-closed autouse `smtplib.SMTP` guard; optional shared `smtp_capture` fixture
- [ ] Migrate the 8 host-`send_email` patch sites (`test_email_queue.py` ×5, `test_email_signin.py` ×2, `test_financial_review.py` ×1) plus the `test_worker_errors_do_not_log_private_exception_text` hermeticity fix — same plan as the transport swap
- [ ] `harness/email.py` event gate merchant-only + `test_p0_10` case (2) update (D-23)
- [ ] New runtime cases: EMAIL-08 scenario, EMAIL-10 scenario, customer-preview redaction, merchant-`confirmed` no-delivery

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| HTML part renders legibly in real clients (Gmail web, Apple Mail, Outlook desktop) | EMAIL-02 | Client rendering engines can't be automated here; research assumption A2 (Outlook ignores `max-width`) | Configure host SMTP to a real inbox, press Notifications "send test", and open the message in each client: header band/accent, item table, footer visible, no remote-content prompt |
| Live delivery through the operator's real SMTP relay | EMAIL-01, EMAIL-10 | Automated tests use a fake `smtplib.SMTP`; no local SMTP server (`smtpd` removed in 3.12) | With host SMTP configured, press "send test" → queue row reaches `sent`; the received message shows `multipart/alternative` with both parts and the EMAIL-11 headers |

*Frozen single-binary smoke is Phase 11 (CONTEXT D-27), not this phase.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
