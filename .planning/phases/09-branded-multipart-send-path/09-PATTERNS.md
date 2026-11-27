# Phase 9: Branded Multipart Send Path - Pattern Map

**Mapped:** 2026-10-18
**Files analyzed:** 11. Nine are required. Two are optional discretion items: a file-based template and the admin copy.
**Analogs found:** 11 / 11 files have at least a partial in-repo analog. Four sub-components have no in-repo precedent and fall back to RESEARCH.md code examples (see "No Analog Found").
**Inputs:** `09-CONTEXT.md` (D-01..D-27), `09-RESEARCH.md` (test inventory, Code Examples 1–6, Pitfalls 1–16), `09-VALIDATION.md` (`-k` selectors), `AGENTS.md`.

Scope guards for the planner:
- **D-24:** no routes, migrations, or `merchants` columns. `harness/registry.py`, `harness/schema.py`, and `docs/technical-specification.md` stay untouched.
- **D-27:** no stdlib vendoring.
- **Phase 10/11 items are excluded:** logo upload, `email_*` columns, preview `html` key, and the multipart harness model.
- **The host helper is read-only.** The pinned `lnbits/core/services/notifications.py::send_email` (e336fe1) is a mechanics reference only. It is never an analog and is never edited. RESEARCH.md §"Host `send_email` (what to mirror)" quotes lines 205-240 verbatim.

---

## File Classification

| # | New/Modified File | Change | Role | Data Flow | Closest Analog | Match Quality |
|---|-------------------|--------|------|-----------|----------------|---------------|
| 1 | `infinitemarkets/services/email.py` | modify (primary) | service: queue worker + renderer + transport | event-driven batch worker → transform (render) → request-response (SMTP) | **self**, plus `services/og_images.py` (thread-offloaded stdlib I/O, `_color`), `services/blossom.py` (`to_thread` transport), `services/nip89.py::render_markdown` (escaping), `services/themes.py` + `views.py:1050-1070` (theme→accent), `services/orders.py:858-872` (merchant-only gate) | exact (self) + role-match for new pieces |
| 2 | `infinitemarkets/settings.py` | modify (optional kill switch) | config | env parse at call time | **self**: `email_enabled` / `_bool_env` | exact |
| 3 | `tests/runtime/test_email_render.py` | **create** | test (unit, `fast`, no host boot) | transform (pure functions) + fake transport | `tests/runtime/test_catalog_events.py` (structure), `test_crypto_keystore.py` (`ExtSettings` factory), `test_keystore_nip17.py:472-487` (source guard), `harness/email.py::SmtpStub` (recording fake) | role-match (structure exact) |
| 4 | `tests/runtime/conftest.py` | modify | test fixture (fail-closed guard + capture) | pytest fixture lifecycle | **self**: `frozen_inbox_clock`, `window_headroom`, `_EXT_ENV` `RELAY_IO=off` precedent | exact |
| 5 | `tests/runtime/test_email_queue.py` | modify (migrate 5 tests / 6 patch statements; add scenarios) | test (runtime, host boot) | event-driven worker | **self** | exact |
| 6 | `tests/runtime/test_email_signin.py` | modify (migrate 2 tests) | test (runtime, host boot) | event-driven worker | **self** + the migrated `test_email_queue.py` pattern | exact |
| 7 | `tests/runtime/test_financial_review.py` | modify (migrate 1 site, PG-only) | test (runtime, host boot) | event-driven worker, live background loop | **self** | exact |
| 8 | `harness/email.py` | modify (1 condition + docstrings) | model (executable §8.8) | event-driven | **self** + production precedent `orders.py:858-860` | exact |
| 9 | `tests/qualification/test_p0_10_smtp_boundary.py` | modify (case 2 only) | test (qualification, `fast`) | model CRUD | **self**: lines 285-299 (merchant enqueue), 55-63 (customer enqueue) | exact |
| 10 | *(optional)* git-tracked HTML template file, only if the planner picks `FileSystemLoader` (Pitfall 13) | create | template | transform | `infinitemarkets/templates/infinitemarkets/admin.html` (Jinja file conventions) + `tools/package_release.py:143-151` (tracked files ship) | partial |
| 11 | *(optional)* `infinitemarkets/templates/infinitemarkets/admin.html` | modify, copy text only | component (template) | request-response | **self**: lines 2435, 2461-2464 | exact |

---

## Pattern Assignments

### 1. `infinitemarkets/services/email.py` (service: worker, renderer, transport)

The research recommendation is to keep all Phase 9 code in this module. It imports with no host boot, and a split would break the monkeypatch seams that tests rely on (`email._render_body`, `email._smtp_send`).

#### 1.0 Imports and module conventions (analog: self, lines 19-31)
```python
from __future__ import annotations

import asyncio
import json
import random
import time
import uuid

from loguru import logger

from .. import crypto
from ..db import Database, DomainTransaction, db
from ..settings import ext_settings
```
- Add stdlib imports alphabetically into the first block (ruff `I`): `import re`, `import smtplib`, `import unicodedata`, `from email.headerregistry import Address`, `from email.message import EmailMessage`, `from email.utils import formatdate, make_msgid`. Absolute imports resolve to the stdlib `email` package even though this file is named `email.py` (PEP 328; verified in RESEARCH Code Example 1).
- **Use `import smtplib` and call `smtplib.SMTP(...)` by attribute.** Never use `from smtplib import SMTP`. The conftest fail-closed guard (§4) patches `smtplib.SMTP` on the module object, and a captured alias would bypass it.
- **Host and heavy imports stay lazy, inside functions.** This is the existing convention, and it keeps the module importable by the fast test without a host boot:
  ```python
  # email.py:275-278 (current)
      from lnbits.settings import settings as host_settings

      host_ready = host_settings.is_email_notifications_configured()
      from lnbits.core.services.notifications import send_email   # <- DELETE in Phase 9
  ```
  ```python
  # email.py:317 and 480 — in-function sibling imports (copy this style for themes/nip89)
                  from .orders import digital_delivery
  ...
          from . import metrics
  ```
  Use the same style for `from lnbits.helpers import is_valid_email_address` (inside `_build_message`) and `from .themes import contrast_ratio, parse_theme, resolve_tokens` (inside the accent helper). `themes.py` imports `..security`, which pulls in fastapi. Avoid `nip89` at module top: it imports `.catalog`.

#### 1.1 `_smtp_send` — thin transport (analog: `og_images.py` + `blossom.py`)
**Pattern to copy:** a blocking stdlib network call in a sync inner function, a socket-level timeout, offload with `asyncio.to_thread`, and an outer `asyncio.wait_for` that the caller owns.

`services/og_images.py:126-131` (wait_for + to_thread under a remaining-budget deadline):
```python
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        _fetch_image, parsed.hostname, str(address), path
                    ),
                    timeout=min(4.5, remaining),
                )
```
`services/og_images.py:34-48` (socket timeout set at construction, so a cancelled `wait_for` cannot leave the thread hanging):
```python
class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a checked IP while retaining the original TLS hostname."""

    def __init__(self, host: str, address: str):
        super().__init__(host, port=443, timeout=3.0,
                         context=ssl.create_default_context())
```
`services/blossom.py:174-177` and `200-202` (docstring convention for thread-run helpers):
```python
def _put_once(host: str, address: str, port: int, body: bytes,
              headers: dict) -> tuple[int, bytes]:
    """One PUT through a pinned connection; bounded descriptor read.
    Runs in a worker thread — never awaited inline on the loop."""
...
            status, raw = await asyncio.to_thread(
                _put_once, host, str(address), port, body, headers
            )
```
**Deliberate differences from the analogs (D-03/D-04/D-25):**
- **Exceptions must propagate.** `og_images._fetch_image` swallows `(OSError, ValueError, HTTPException)` and returns `None`. `_smtp_send` instead lets every exception reach the worker's existing `except Exception: sent = False` (email.py:438-439).
- **No TLS context.** og_images uses `ssl.create_default_context()`. D-25 requires host parity, which is `starttls()` with no context. Add a code comment at the `starttls()` call: unverified certificate on Python 3.12, ASVS 9.2.1 is L2 while the project runs L1, and a pointer to `.planning/STATE.md` → Deferred Items.
- **Never log and never call `set_debuglevel`.** The host helper logs `f"Sending Email failed. {e!s}"`, which leaks recipients through `SMTPRecipientsRefused`.
- **Target shape:** RESEARCH Code Example 2. It reads `host_settings.lnbits_email_notifications_{server,port,username,password,email}`, uses `username or from_addr`, calls `smtplib.SMTP(server, port, timeout=timeout)`, then `starttls()`, `login()`, and `sendmail(from_addr, [to], msg.as_string())`, and returns `True`.

#### 1.2 `_build_message` — pure MIME builder (no in-repo analog → RESEARCH Code Example 1)
No file in `infinitemarkets/`, `tests/`, `harness/`, or `tools/` uses `smtplib`, `EmailMessage`, `email.policy`, or `get_body` (verified by grep). Copy RESEARCH Code Example 1 verbatim in shape:
- `set_content(..., cte="quoted-printable")`, then `add_alternative(..., cte="quoted-printable")`, then `get_payload()[1].add_related(..., cid="<logo@infinitemarkets>")`.
- `make_msgid(domain=from_addr.rpartition("@")[2])`, `formatdate(localtime=True)`, and `Auto-Submitted: auto-generated`.

Two adjacent in-repo conventions apply:
- **Keyword-only pure builder with no I/O.** Mirror `_preview_enc` (email.py:220-232), which builds a payload from arguments and touches nothing else. `_build_message` must call no DB, network, or `socket.getfqdn()` (Pitfall 5).
- **Branding never fails the operation (D-06).** Mirror the og_images fallback stance (`og_images.py:160-163`):
  ```python
      except Exception:
          # A missing, unsafe, or unsupported merchant image must not break
          # the generated card; the brand initials remain as the fallback.
          return None
  ```
  An unusable logo (empty bytes, or a subtype other than `png`/`jpeg`) becomes `logo = None`. The builder must not emit `cid:` without the related part.
- **View model type.** If `_EmailView` is a dataclass, copy the frozen-dataclass-with-defaults convention of `ExtSettings` (settings.py:385-407; `@dataclass(frozen=True)`, defaulted fields, `field(default_factory=...)` for containers).

#### 1.3 `_header_safe` + `_subject` / `From` (analog: `crypto.normalize` + self)
There is no control-character sanitizer anywhere in the package. The closest in-repo shape is a tiny `unicodedata`-based normalizer, `infinitemarkets/crypto.py:135-137`:
```python
def normalize(value: str) -> str:
    """Canonical form for equality indexes: NFC + strip + lowercase."""
    return unicodedata.normalize("NFC", value).strip().lower()
```
Apply the sanitizer in the current `_subject` (email.py:169-173). Keep the existing fallback spelling `"Infinitemarkets"`; it is closure-safe (§S10):
```python
def _subject(merchant: dict, event_type: str) -> str:
    """Subjects carry only display name + event name — never PII/ids."""
    name = (merchant.get("display_name") or "Infinitemarkets").strip()
    label = _EVENT_LABELS.get(event_type, "order update")
    return f"{name}: {label}"[:150]
```
- Body of `_header_safe`: RESEARCH Code Example 1. It replaces Unicode categories `Cc/Cf/Zl/Zp` with a space, collapses whitespace, and truncates.
- Apply it to both `_subject` and the `From` display name. Normal names are unchanged, so `test_subject_has_no_pii` (test_email_queue.py:499-509) keeps passing: it asserts `subject == "Email Shop: order confirmed"`.
- If the sanitized name is empty, fall back to the bare host address.

#### 1.4 `_render_html` + template (analogs: `nip89.render_markdown`, `og_images._color` / `render_branded_card`)
**Escaping, string-building option.** Analog `services/nip89.py:305-316`: lazy `import html`, then escape before emitting markup:
```python
def render_markdown(text: str | None) -> str:
    ...
    import html

    if not text:
        return ""
    out = []
    for raw_line in text.split("\n"):
        line = html.escape(raw_line)
```
**Escaping, Jinja option (research primary).** The extension never builds its own `Environment`. It only uses the host's `template_renderer` (views.py:26, 71-72 → host `Jinja2Templates`). A dedicated `Environment(autoescape=True, undefined=StrictUndefined)` is therefore new. Copy RESEARCH Code Example 5. Banned constructs are `|safe`, `Markup(`, and `{% autoescape false %}` (Pitfall 9).

**CSS color guard: copy this exactly.** `services/og_images.py:31` and `166-167` use `fullmatch`, which is safe against a trailing `\n`:
```python
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
...
def _color(value: str | None, fallback: str) -> str:
    return value if isinstance(value, str) and _HEX.fullmatch(value) else fallback
```
**Do NOT copy** the `themes.py` write-time checks `_HEX_COLOR.match(...)` (lines 296, 421, 462). `.match` with `$` accepts `"#ffffff\n"` (Pitfall 8). Do not "fix" themes.py in this phase.

**Branded-render signature with literal-default colors.** Analog `og_images.py:314-328`. Defaults are fixed literals, and callers pass resolved tokens:
```python
async def render_branded_card(
    cache_key: str,
    *,
    brand_name: str,
    title: str,
    subtitle: str = "",
    price: str = "",
    eyebrow: str = "FEATURED PRODUCT",
    accent: str = "#a34f2a",
    ...
    logo_url: str = "",
```
For email, the logo is **CID bytes only**. Never pass `brand.logo_url` or `profile.picture`, which are remote URLs (D-07, out of scope). Phase 10 seams: optional `header_text=None`, `footer_text=None` keyword arguments that are escaped and unused in Phase 9.

**Money formatting.** Analog `services/nip89.py:181-189`:
```python
def price_label(amount_minor, currency, decimals) -> str:
    """Buyer-facing price in major units: ``2,500 sats`` / ``15.00 USD``."""
    if amount_minor is None:
        return ""
    code = (currency or "SAT").upper()
    if code in ("SAT", "SATS"):
        return f"{int(amount_minor):,} sats"
```
- Line totals and order totals use inline `f"{n:,} sats"`, or `"—"` when the value is `None`. All money columns are nullable (migrations.py:478-480, 514-517).
- If a unit price is shown, lazy-import `price_label` inside the function.

**Ruff:** line-length 100 applies inside triple-quoted template strings (Pitfall 13). Wrap template lines, or use option #10 (template file).

#### 1.5 Accent / on-accent resolution (analog: `views.py:1050-1070` + `themes.py`)
The existing call site that bridges theme → branded output is `views.py:1050` and `1058-1068`:
```python
    tokens = theme_service.resolve_tokens(theme)
    ...
    png, etag = await og_images.render_branded_card(
        cache_key,
        brand_name=brand_name,
        ...
        accent=tokens.get("--color-primary", "#a34f2a"),
```
Email differences:
- Use the `--color-accent` token (D-09; set from `brand.accent` at `themes.py:524-525`).
- Parse the raw JSON the worker already holds (`merchant` comes from `SELECT *` at email.py:299-302) with `parse_theme(merchant.get("theme"))`. Do not issue a new DB query inside the claim transaction. `themes.get_theme` (themes.py:776-782) opens its own connection, so do not call it from the worker.

`themes.py:764-773` (never raises; falls back to `DEFAULT_THEME`):
```python
def parse_theme(raw: str | None) -> dict:
    if not raw:
        return dict(DEFAULT_THEME)
    try:
        theme = json.loads(raw)
    except (TypeError, ValueError):
        return dict(DEFAULT_THEME)
    if not isinstance(theme, dict) or theme.get("preset") not in PRESETS:
        return dict(DEFAULT_THEME)
    return theme
```
`themes.py:519-525`:
```python
def resolve_tokens(theme: dict | None) -> dict[str, str]:
    """Flatten preset + brand + advanced into the emitted token set."""
    theme = theme or DEFAULT_THEME
    tokens = dict(PRESET_TOKENS[theme.get("preset", "warm-market")])
    brand = theme.get("brand") or {}
    if brand.get("accent"):
        tokens["--color-accent"] = brand["accent"]
```
`themes.py:259-262` (reuse; do not reimplement the luminance math):
```python
def contrast_ratio(fg: str, bg: str) -> float:
    l1, l2 = _luminance(fg), _luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)
```
- Recipe (RESEARCH Pattern 4): `accent = _color(tokens["--color-accent"], "#d69a3a")`, with `#d69a3a` taken from the warm-market preset at `themes.py:57`. Then `on_accent = "#ffffff" if contrast_ratio("#ffffff", accent) >= 4.5 else "#111111"`.
- **Do NOT reuse `views._brand_ctx`** (views.py:97-116). It applies a Brand Basics `brand.name` override and returns a remote `brand_logo` URL. D-08, D-13, and D-19 lock `merchant["display_name"]`, and D-07 forbids remote images. `views.py` also imports host/FastAPI request machinery, which would be a layering violation.

#### 1.6 `_suppression_reason` — D-16/D-17 (analog: self + `orders.py:858-872`)
Current code (email.py:156-166) applies the gate to every channel:
```python
    events = json.loads(merchant["notify_events"]) if (
        merchant["notify_events"]
    ) else {}
    if row["event_type"] in events and not events[row["event_type"]]:
        return "event-disabled"
    # ``channel == 'account'`` rows (magic links) skip the consent check by
    # construction — the mailbox itself is the credential being proven.
    if row["channel"] == "customer":
        if order is None or not order["email_opt_in"]:
            return "consent-revoked"
    return None
```
The enqueue-side precedent already gates on the merchant channel only (`services/orders.py:858-872`). Mirror it at send time:
```python
    # Merchant channel — notify_events flags default ON per event.
    flag = _MERCHANT_EVENT_KEYS[event_type]
    if merchant_notify_events.get(flag, True):
        for addr in merchant_notify_emails:
            if await _insert(addr, "merchant"):
                inserted += 1

    # Customer channel — strictly per-order opt-in.
    if (
        event_type in _CUSTOMER_EVENTS
        and order.get("email_opt_in")
        and customer_email
    ):
```
- **Test-row discriminator (D-16):** `row["channel"] == "merchant" and not row["order_id"]`. This is unique: only `enqueue_test_send` inserts orderless merchant rows (email.py:524-525: `VALUES (:i, :m, NULL, 'merchant', 'order_received', ...)`).
- Target body: RESEARCH Code Example 4. The global gates at email.py:149-155 are unchanged, and the bounded codes stay `event-disabled` and `consent-revoked`.

#### 1.7 `_render_body` — D-26 one-line fix (analog: self)
email.py:187-188:
```python
    label = _EVENT_LABELS.get(row["event_type"], "order update")
    lines = [f"Order {label}."]
```
Change only line 188, e.g. to `f"{label.capitalize()}."`. Verified: no test asserts the old "Order order …" text (grep). **Hard constraints on this function:**
- **Signature unchanged.** `test_order_saga.py:295-299` calls it positionally with a row that has no `channel` key:
  ```python
      body = svcs["email"]._render_body(  # noqa: SLF001
          {"event_type": "confirmed"}, {"state": "confirmed", "total_sat": total},
          [], {}, None, [{"title": "zine", "content": secret}],
      )
      assert secret in body
  ```
- **Call stays outside the send `try` and resolves through the module global, including for test-send rows.** `test_worker_errors_do_not_log_private_exception_text` (test_email_queue.py:545-567) enqueues a test send, monkeypatches `email._render_body` to raise, and expects outcome `"error"`. D-16 sample content must therefore render through the same module-global `_render_body`, not a separate renderer.
- The trailing line `"This is a transactional order notification."` (email.py:201-203) is already the merchant/test neutral footer. Do not append it twice (RESEARCH Pattern 6).

#### 1.8 Worker wiring in `worker_tick._send` (analog: self)
- **Widen the items query.** Today (email.py:310-314):
  ```python
                  items = await tx.fetch_all(
                      f"SELECT title, quantity FROM {tx.table('order_items')}"
                      " WHERE order_id = :o",
                      {"o": row["order_id"]},
                  )
  ```
  Becomes `SELECT title, quantity, line_total_sat, backordered_qty, unit_price_minor, currency, currency_decimals`. All of these columns are verified at migrations.py:506-519. `_render_body` reads only `title`/`quantity`, so the wider dicts are safe.
- **Delivery gate stays at load** (email.py:315-319, `order and channel == "customer" and event_type == "confirmed"`). Add a render-side double gate in the HTML view (D-11).
- **Replace the send block** (email.py:420-439, shown below) with RESEARCH Code Example 3. `_build_message(...)` goes inside the existing `try`, so validation or template errors become `sent = False` and a bounded retry (Pitfall 3). Call `_smtp_send` through the module global (§S2). Use `budget = min(30, remaining)` for both `wait_for` and the socket timeout.
  ```python
          preview = _preview_enc(row, subject, preview_body, settings)
          remaining = deadline - time.monotonic()
          if remaining <= 0:
              return "lost_claim"
          try:
              sent = await asyncio.wait_for(
                  send_email(
                      host_settings.lnbits_email_notifications_server,
                      ...
                      [recipient],
                      subject,
                      body,
                  ),
                  timeout=min(30, remaining),
              )
          except Exception:
              sent = False
  ```
- **Kill switch:** `with_html=settings.email_html`. `settings = ext_settings()` already exists at email.py:269, so the switch is one argument (CONTEXT discretion).
- **Outcome writes are unchanged** (email.py:440-469): `sent` wipes `recipient_enc`/`payload_enc`, and a failure triggers backoff or `failed`.
- **Per-row isolation is unchanged** (email.py:471-482). It logs the class name only.

#### 1.9 Footer, sample-content constants, and preview redaction (analog: `_EVENT_LABELS`, `orders.py` `#:` constants, email.py:395-419)
Module-constant style (email.py:41-52):
```python
_EVENT_LABELS = {
    "order_received": "new order received",
    "confirmed": "order confirmed",
    ...
    "signin_link": "your sign-in link",
}
```
`#:` doc-comment convention for module constants (orders.py:777-778, 790-793):
```python
#: Which notify_events keys gate merchant-channel rows (merchant config).
_MERCHANT_EVENT_KEYS = {
...
#: Customer sends are strictly opt-in per order (orders.email_opt_in) AND
#: transactional-only — order_received is never sent to the customer
#: (placed + paid arrive as one combined ``confirmed`` email, §8.8).
_CUSTOMER_EVENTS = frozenset(set(EMAIL_EVENT_TYPES) - {"order_received"})
```
Redaction placeholders to extend (email.py:401-403, 410-419):
```python
            preview_body = _render_signin_body(
                merchant or {}, "[sign-in link omitted]"
            )
        ...
            preview_delivery = [
                {"title": d.get("title") or "digital item",
                 "content": "[digital content omitted]"}
                for d in delivery
            ]
            preview_body = _render_body(
                row, order, items, merchant or {},
                "[order-status link omitted]" if link else None,
                preview_delivery,
            )
```
- **Customer opt-out footer.** Its link is `_status_link` (email.py:235-257). The preview must carry `"[order-status link omitted]"` in the footer too (Pitfall 4; D-22).
- **Preview key stays `body`.** `get_email_preview` reads `payload["body"]` at merchant.py:867-871.
- **Copy without apostrophes**, because MarkupSafe emits `&#39;` (Pitfall 10). Note that the existing `_render_signin_body` line `"If you didn't request it, you can ignore this email."` (email.py:215) contains one. Tests on HTML copy must therefore `html.unescape(...)`.
- **Account rows** are always bound to a real shop merchant (email.py:570, worker loads merchant at 299-302). The `"Infinitemarkets"` wordmark plus the default accent is only a defensive fallback.

#### 1.10 Module docstring (self, lines 1-17): stale statements to update
- Lines 5-7: "the merchant disabled the event type". This now applies to merchant alerts only (D-17).
- Lines 14-16: "Only a host ``send_email`` ``True`` enters ``sent``". This becomes "Only a confirmed `_smtp_send` `True`…" (D-04).

---

### 2. `infinitemarkets/settings.py` (config, optional kill switch)

**Analog:** self. Copy `email_enabled` exactly.

`_bool_env` (settings.py:374-382), reused as is:
```python
def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise SettingsError(f"{name} must be a boolean")
```
Field (settings.py:399-400). Add `email_html: bool = True` directly below:
```python
    email_enabled: bool = True
    email_max_attempts: int = 5
```
Parse (settings.py:464-465). Add `email_html=_bool_env("INFINITEMARKETS_EMAIL_HTML", True),` directly below:
```python
        email_enabled=_bool_env("INFINITEMARKETS_EMAIL_ENABLED", True),
        email_max_attempts=_int_env("INFINITEMARKETS_EMAIL_MAX_ATTEMPTS", 5),
```
- The field is defaulted, so existing direct constructions such as `test_crypto_keystore._ext_settings(**over)` (lines 22-30) keep working.
- Do NOT add to `harness/registry.py::SETTINGS`. `test_p0_14` checks `registry.SETTINGS ⊆ §12` in one direction only, and `INFINITEMARKETS_NSEC_SIGNIN` (settings.py:470) has the same precedent. The §12 doc row is a Phase 11 item.

---

### 3. `tests/runtime/test_email_render.py` (new; unit; `fast`; no host boot)

**Primary analog:** `tests/runtime/test_catalog_events.py`.

Header + marker (lines 1-14). Copy this shape:
```python
"""Deterministic event builders (§6) + outbox supersession/deps (§8.6).

Pure unit tests — builders are pure functions of domain rows; outbox tests
use the ``keystore_env`` tmp database with m001 applied.
"""

from __future__ import annotations

import importlib
import json

import pytest

pytestmark = [pytest.mark.runtime, pytest.mark.fast]
```
Lazy module import (lines 62-63). Prefer this over a top-level import. `email.py` imports `..db`, and `tests/runtime/conftest.py:151-155` purges `infinitemarkets*` modules on every host boot, so resolve the module at test time:
```python
def _events():
    return importlib.import_module("infinitemarkets.services.events")
```
→ `def _email(): return importlib.import_module("infinitemarkets.services.email")`

Dict-factory-with-overrides for rows (lines 19-45). Use this for order, items, and merchant fixtures; `_product(**over)` is the analog:
```python
def _product(**over):
    base = {
        "d_tag": "beans-0001",
        ...
    }
    base.update(over)
    return base
```
Async test style (lines 80-85; asyncio auto mode, session loop forced by runtime conftest:39-42):
```python
async def test_product_event_deterministic():
    events = _events()
    e1 = _build(events)
```
**`ExtSettings` factory.** Needed for `_status_link` live/dead CTA cases. Analog `test_crypto_keystore.py:22-30`:
```python
def _ext_settings(**over) -> gsettings.ExtSettings:
    base = {
        "master_keys": _keyring(),
        "active_key_version": "v1",
        "privacy_key": bytes([9]) * 32,
        "public_base_url": "https://shop.example.com",
    }
    base.update(over)
    return gsettings.ExtSettings(**base)
```
Build a live `public_token_enc` with the exact AEAD parameters `_status_link` decrypts with (email.py:249-254): `record_id=order["id"], table="orders", column="public_token_enc", key_version=ver`.

**Static source guards.** These cover: no `|safe`/`Markup`/`autoescape` in the template, no `set_debuglevel`, no `notifications import send_email`, and `make_msgid` called with `domain=`. Analog `test_keystore_nip17.py:472-487` (a fast test):
```python
async def test_nsec_deleted_in_finally_source():
    """Source assertion: every new crypto entry path releases keys in
    ``finally`` (same discipline as sign_event)."""
    import inspect

    import infinitemarkets.keystore as ks_mod
    ...
    file_src = inspect.getsource(ks_mod)
    assert "UnwrappedGift(" not in file_src
    assert "from_gift_wrap(" not in file_src
```
For "never CALLED" checks that tolerate docstring mentions, use the AST variant at `tests/qualification/test_p0_13_decimal_fx.py:355-367`:
```python
    tree = ast.parse(inspect.getsource(fx))
    called = {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    }
    assert "fiat_amount_as_satoshis" not in called
```
**Fake `smtplib.SMTP` for the `_smtp_send` tests.** No fake stdlib transport exists. The structural analog is `harness/email.py:130-149` `SmtpStub`, which records calls and has programmable outcomes including `"raise"`:
```python
class SmtpStub:
    ...
    def __init__(self, outcome: str = "true") -> None:
        self.outcome = outcome
        self.calls: list[dict] = []

    async def send_email(self, *, to: str, subject: str, body: str) -> bool:
        self.calls.append({"to": to, "subject": subject, "body": body})
        if self.outcome == "raise":
            raise RuntimeError("smtp transport failure")
```
Build a sync context-manager class with these members: `__init__(host, port, timeout=None)`, `__enter__` returning `self`, `__exit__` returning `False`, `starttls()`, `login(u, p)`, and `sendmail(from_addr, to_addrs, msg)`.
- Record the call order. Install it with `monkeypatch.setattr(smtplib, "SMTP", Fake)`; this overrides the autouse guard from §4 for that test.
- Set `lnbits.settings.settings.lnbits_email_notifications_*` via `monkeypatch.setattr(host_settings, ...)`. `infinitemarkets/settings.py:38` already imports `lnbits.settings` at module top, so this works without a host boot.

**MIME assertions:** RESEARCH Code Example 6. Use `msg.get_body(preferencelist=("plain",)).get_content()` and the `"html"` variant, `msg.as_string().isascii()`, `.rstrip("\n")` before equality (Pitfall 11), and a round-trip through `email.message_from_string(..., policy=email.policy.default)`.

**Test names must contain the VALIDATION `-k` keywords** (see the selector map below): `tree`, `smtp_send`, `sections`, `escap`, `footer`, `header`.

---

### 4. `tests/runtime/conftest.py` (fixtures: fail-closed guard + shared capture)

**Analog:** self. There are function-scoped `monkeypatch` fixtures at lines 416-441 and a fail-closed transport precedent at lines 88-90.

Fail-closed precedent and comment style (conftest.py:81-91):
```python
_EXT_ENV = {
    ...
    # Never dial real relays from a host-boot test — workers stay live
    # (claim/evidence paths exercised) but the transport never connects.
    "INFINITEMARKETS_RELAY_IO": "off",
}
```
Function-scoped monkeypatch fixture shape (conftest.py:433-441):
```python
@pytest.fixture
def frozen_inbox_clock(monkeypatch):
    """Pin the inbox admission clock so a multi-second burst of wraps is
    counted in a single fixed window (see ``window_headroom``)."""
    from infinitemarkets.services import inbox

    now = int(time.time())
    monkeypatch.setattr(inbox, "_now", lambda: now)
    return now
```
- **Guard.** New `@pytest.fixture(autouse=True)` (sync, function-scoped). It does `monkeypatch.setattr(smtplib, "SMTP", <callable raising ConnectionRefusedError>)`, with a docstring in the RELAY_IO comment style. This is the first function-scoped autouse fixture in the repo; every existing autouse fixture is module-scoped (`_setup`, `_isolated_postgres_schema`). No test, harness, or tool uses `smtplib` today, so nothing collides.
- **`smtp_capture`.** New function-scoped fixture (RESEARCH Code Example 6). It sets `type(host_settings).is_email_notifications_configured → True` (the same idiom as test_email_queue.py:190) **and** `host_settings.lnbits_email_notifications_email = "shop@example.com"`, both via `monkeypatch` (Pitfall 2). It replaces `svc._smtp_send` on `importlib.import_module("infinitemarkets.services.email")` with a recorder.
  - Recommended: record `{"to", "msg", "subject", "text", "html"}` at capture time so migrated asserts map 1:1 onto the old positional args (`args[5]` → `to`, `args[6]` → `subject`, `args[7]` → `text`).
  - Request it after `runtime_env` in test signatures. The module-scoped `_setup(runtime_env)` autouse fixture guarantees the host boots before the module object is resolved.
- **Background loop note.** `tasks.email_sender` (tasks.py:179-203) resolves `email_service.worker_tick` by attribute at line 192, so a module-level `_smtp_send` patch also reaches the background loop in modules that do not cancel `_owned_tasks` (test_financial_review.py). Outside a test's function scope, host email is unconfigured, so background rows suppress before any SMTP call.

---

### 5. `tests/runtime/test_email_queue.py` (runtime; migrate + add)

**Analog:** self. Seam lookup is via `_svc()` (lines 81-87). The module cancels `_owned_tasks` (lines 20-25), so no background loop runs.
```python
def _svc():
    import importlib

    return {
        n: importlib.import_module(f"infinitemarkets.services.{n}")
        for n in ("checkout", "orders", "email", "settlement")
    }
```
Migration sites (all verified by grep; VALIDATION counts these as 5 tests):

| Test (lines) | Current pattern | Migrate to |
|---|---|---|
| `test_hard01_settled_without_accounting_email` (187-201; 18 param cases) | `monkeypatch.setattr(notifications, "send_email", fake_send)`; `args[5]` recipients, `args[7]` body | `smtp_capture`; filter `c["to"] == address`; assert `secret in c["text"]` |
| `test_send_classification` (301-323, 342-346, 391) | direct `host_settings.lnbits_email_notifications_enabled = True` / `_email = ...`; True fake then `fail_send` | `_smtp_send` fake → True, then a fake returning False or raising. Keep the preview asserts at 325-340. Prefer `monkeypatch.setattr` for host settings: today `_email` leaks because only `enabled` is reset at line 391 |
| `test_consent_revocation_suppresses` (415-431) | manual `notif.send_email` swap in `try/finally`; merchant rows really send | add `monkeypatch` + `smtp_capture` to the signature |
| `test_orderless_test_send` (463-490) | `sent_to[0][5]` contains recipient | `c["to"] == "merchant@example.com"`. EMAIL-10 extension: sample marker and sample items in `c["html"]` and `c["text"]`; set `notify_events {"order_received": false}` first and restore it in `finally`, because the merchant from `_setup` is shared by the module |
| `test_expired_claim_never_calls_smtp` (530-542) | `fake_send` on host, asserts `sent == []` (**passes vacuously after the swap**) | patch `_smtp_send` with a recorder; keep `assert sent == []` |
| `test_worker_errors_do_not_log_private_exception_text` (545-567) | no send patch; relies on `_render_body` raising | unchanged code; now hermetic via the §4 guard. Keep the module-global `_render_body` call outside the `try` (§1.7) |

Current shape to replace (test_email_queue.py:187-201):
```python
    import lnbits.core.services.notifications as notifications
    from lnbits.settings import settings

    monkeypatch.setattr(type(settings), "is_email_notifications_configured", lambda self: True)
    sent = []

    async def fake_send(*args):
        if address in args[5]:
            sent.append(args[7])
        return True

    monkeypatch.setattr(notifications, "send_email", fake_send)
    await svcs["email"].worker_tick("hard01-email")
    assert sent
    assert any(secret in body for body in sent) is (damage == "healthy")
```
Preview assertions to keep and extend (lines 336-340). Add the footer-link redaction check, e.g. `"/infinitemarkets/order#" not in body["body"]` for a customer row:
```python
    body = preview.json()
    assert body["redacted"] is True
    assert "email shop: new order received" == body["subject"]
    assert "Order status: [order-status link omitted]" in body["body"]
    assert "/infinitemarkets/order#" not in body["body"]
```
**New scenarios, closest analog `test_consent_revocation_suppresses` (394-436).** It enqueues via `enqueue_email_intents`, mutates the DB between enqueue and send, ticks, then filters rows by channel:
```python
    async with DomainTransaction() as tx:
        await svcs["orders"].enqueue_email_intents(
            tx, order=order, event_type="confirmed",
            merchant_notify_emails=["merchant@example.com"],
            merchant_notify_events={},
            customer_email="c2@example.com",
            now=int(time.time()),
        )
    # Revoke consent after enqueue.
    async with DomainTransaction() as tx:
        await tx.execute(
            "UPDATE orders SET email_opt_in = FALSE WHERE id = :i",
            {"i": order["id"]},
        )
    ...
    rows = await _queue_rows(order["id"])
    customer = [r for r in rows if r["channel"] == "customer"]
```
- **EMAIL-08 (`-k notify_events`):** enqueue `shipped` (in both `_MERCHANT_EVENT_KEYS` and `_CUSTOMER_EVENTS`, orders.py:778-793) with `merchant_notify_events={}`. Then set the merchant `notify_events` to `{"shipped": false}` by direct `UPDATE merchants` (the email.py gate reads the DB row) or by `PATCH /merchants/{mid}/notifications` with `{"notify_events": {...}}` (views_api.py:119-121, 507). Expect the customer row `sent` and the merchant row `suppressed`/`event-disabled`. Restore `notify_events` in `finally`.
- **Merchant `confirmed` has no delivery content (`-k delivery`):** reuse the `test_hard01` setup (delivery content PATCH at lines 143-148) and assert the merchant capture's text and HTML lack `secret`.
- **Customer preview redaction:** customer preview body contains no `/infinitemarkets/order#`.

---

### 6. `tests/runtime/test_email_signin.py` (runtime; migrate 2 tests)

**Analog:** self, plus the §5 pattern. Helpers available: `_svc()` (117), `_crypto()` (105), `_settings()` (111), `_merchant(env)` (152), `_account_rows(env)` (247), `_reset_buckets(env)` (161).

`test_magic_link_send_renders_fragment_and_wipes` (397-448). Current asserts to translate:
```python
    assert sent_calls, "host send_email was not invoked"
    args = sent_calls[0]
    recipients, subject, body = args[5], args[6], args[7]
    assert recipients == ["buyer@example.com"]
    merchant = await _merchant(env)
    assert "your sign-in link" in subject
    assert merchant["display_name"] in subject
    assert token not in subject
    assert "buyer@example.com" not in subject
    # The token appears EXACTLY once — inside the URL fragment.
    assert f"/infinitemarkets/auth/email?shop={merchant['pubkey']}#{token}" in body
    assert body.count(token) == 1
    assert "expires in 15 minutes" in body
```
- Target: `c["to"] == "buyer@example.com"`.
- Assert `c["text"].count(token) == 1` and `html.unescape(c["html"]).count(token) == 1` **per part** (RESEARCH OQ7).
- The token must appear in no header (`for k, v in c["msg"].items()`).
- The HTML `href` holds the escaped fragment link (`quote=True`, D-15).

`test_account_channel_uses_email_account_bucket` (490-500): replace the `notif.send_email` True fake with `smtp_capture`. The bucket assertions at 503-539 are unchanged.

Not affected (verified): 451-475 (suppressed before send) and 1284-1314 (page render).

---

### 7. `tests/runtime/test_financial_review.py` (runtime, PG-only, live background loop)

**Analog:** self.
- `pytestmark = pytest.mark.runtime` (line 20).
- The module does **not** cancel `_owned_tasks`, so the background `email_sender` can tick concurrently.
- The test is PostgreSQL-only (skip at lines 347-348).

Site to migrate (lines 386-402):
```python
    async def read_surface():
        if surface == "email":
            import lnbits.core.services.notifications as notifications
            from lnbits.settings import settings

            monkeypatch.setattr(
                type(settings), "is_email_notifications_configured", lambda self: True,
            )

            async def send(*args):
                if address in args[5]:
                    sent.append(args[7])
                return True

            monkeypatch.setattr(notifications, "send_email", send)
            await svcs["email"].worker_tick("review-email")
            return any("atomic entitlement" in body for body in sent)
```
- Patch `_smtp_send` on the live module object (`svcs["email"]`, already `importlib`-resolved), which also covers the background loop.
- Set a valid `lnbits_email_notifications_email` via `monkeypatch`.
- Filter on `to == address` and assert on the text part.
- The recipient `f"{uuid.uuid4().hex}@example.invalid"` (line 350) passes `is_valid_email_address`, whose TLD rule is `[A-Za-z]{2,63}`.

---

### 8. `harness/email.py` (executable §8.8 model; minimal D-23 update)

**Analog:** self, plus production `orders.py:858-860`. Scope is limited to the event gate and the two docstrings. The multipart model is Phase 11.

Gate to change (harness/email.py:442-449):
```python
        if row["event_type"] not in self.enabled_event_types:
            self._log(
                order_id=row["order_id"],
                event_type=row["event_type"],
                code="suppressed-event-type-disabled",
            )
            await self._suppressed_write(row, code="event-type-disabled", now=now)
            return {"action": "suppressed", "reason": "event-type-disabled"}
```
→ `if row["channel"] == "merchant" and row["event_type"] not in self.enabled_event_types:` (RESEARCH §Contract-test exposure).

Docstrings to align: module docstring lines 17-18 ("suppressed … when email is not configured, the event type is disabled, or consent was revoked") and the `send()` docstring lines 419-420.

**Keep** `SmtpStub.send_email(*, to, subject, body)` naming (lines 130-149), the `enabled_event_types` constructor parameter (lines 171, 180-190), and the reason strings. Identifier closure applies to this file (§S10).

---

### 9. `tests/qualification/test_p0_10_smtp_boundary.py` (qualification; `fast`; case (2) only)

**Analog:** self. Case (2) today (lines 207-218) proves the gate on a **customer** row:
```python
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        # (2) the merchant disabled the event type.
        model = email_module.EmailModel(
            qual_db, enabled_event_types={"order_received"}
        )
        await _enqueue_customer(qual_db, model, event_type="shipped")
        row = await _claim_one(model, now=T0 + 10)
        result = await model.send(row, now=T0 + 10)
        assert result == {"action": "suppressed", "reason": "event-type-disabled"}
        stored = await _queue_row(qual_db)
        assert stored["state"] == "suppressed"
```
Merchant-row enqueue shape to copy (lines 292-299):
```python
            await model.enqueue(
                merchant_id="merchant-1",
                order_id="o1",
                channel="merchant",
                event_type="order_received",
                recipient_address=f"owner{i:03d}@shop.example",
                now=T0,
            )
```
**Pitfall: the helpers assume exactly one row.** `_queue_row` asserts `len(rows) == 1` (lines 66-71) and `_claim_one` asserts exactly one claimed row (lines 74-77). Either:
- put the suppressed merchant row and the not-suppressed customer row in **separate** `async with qual_db_factory() as qual_db:` blocks (the file's existing per-case structure), or
- use `model.claim(...)` plus filtering, as at lines 127-143.

Expected results: merchant `shipped` gives `{"action": "suppressed", "reason": "event-type-disabled"}`, and customer `shipped` gives `result["action"] == "sent"` (lines 183-188 show the success shape). The module docstring (b) at lines 10-11 can stay. The `pytestmark = [pytest.mark.db, pytest.mark.fast]` marker (line 30) is unchanged.

---

### 10. *(Optional)* File-based HTML template (only if `FileSystemLoader` is chosen)

**Analog (partial):** `infinitemarkets/templates/infinitemarkets/admin.html`. It uses Jinja comment headers (`{#- … -#}`, lines 1-7). It is rendered by the host `template_renderer`, so do not reuse that loader: the email needs its own `Environment(autoescape=True, undefined=StrictUndefined)`. `tools/package_release.py:143-151` packages every `git ls-files infinitemarkets/` path, so a tracked template ships automatically. If the template lives outside `services/email.py`, the source-guard test (§3) must read the template file, not `inspect.getsource(email)`. The research's primary path is an in-module `from_string` template with lines wrapped at 100 characters.

### 11. *(Optional)* Admin copy correction (text only)

**Analog:** self. The heading `<div class="text-subtitle2 q-mt-md q-mb-sm">Events</div>` (admin.html:2435) sits under the merchant address list. The caption at 2461-2464 already says "Customer email is strictly per-order opt-in and transactional only." Pinned strings that must survive are in `test_admin_ui.py:524-539`: "Recent email queue", "Email preview", "Clear history", "Bearer links and digital content are redacted", and in the JS `order_received`, `confirmed`, `on_hold`, `"/notifications/test"`, `"Suppressed"`, `"Failed after"`. "Events" is not pinned. Running `node --check` is needed only if `admin_notifications.js` changes.

---

## Shared Patterns

### S1. Never log recipients, bodies, tokens, credentials, or exception text
**Source:** `services/email.py:471-478`, `services/tasks.py:202`
**Apply to:** `_smtp_send`, `_build_message`, worker wiring.
```python
        except Exception as exc:  # noqa: BLE001 — per-row isolation
            logger.warning(
                f"infinitemarkets email row {row['id']} failed: {type(exc).__name__}"
            )
```
The send `except Exception: sent = False` (email.py:438-439) logs nothing. Keep it that way.

### S2. Module-global seams that `monkeypatch` can reach
**Source:** `tests/runtime/test_email_queue.py:81-87` (`importlib` resolution at call time), `services/tasks.py:182,192` (attribute lookup)
**Apply to:** `worker_tick` must call `_smtp_send(...)`, `_build_message(...)`, and `_render_body(...)` as bare module globals, never aliases captured at import or closure time. `_smtp_send` must call `smtplib.SMTP` by attribute.

### S3. Lazy in-function imports for host and heavy modules
**Source:** `services/email.py:275, 317, 480`
**Apply to:** `lnbits.helpers.is_valid_email_address`, `lnbits.settings`, `.themes`, and optionally `.nip89`. This keeps `infinitemarkets.services.email` importable in the fast test without a host boot.

### S4. Deadline / remaining-budget discipline
**Source:** `services/email.py:421-437` (`remaining = deadline - time.monotonic()`; `<= 0` → `"lost_claim"`; `min(30, remaining)`), `services/og_images.py:111-131`
**Apply to:** worker wiring (one `budget` drives both `wait_for` and `smtplib.SMTP(timeout=)`).

### S5. CSS color guard with literal fallback
**Source:** `services/og_images.py:31, 166-167` (`fullmatch`)
**Apply to:** every color interpolated into inline CSS (accent, on-accent). Never use the `.match`-based `themes._HEX_COLOR` (lines 296, 421, 462).

### S6. Branding never fails the operation
**Source:** `services/og_images.py:160-163`
**Apply to:** logo handling in `_build_message` (unusable logo → no related part, no `cid:`), accent fallback, and display-name fallback.

### S7. Bearer links are fragment-only; previews are redacted
**Source:** `services/email.py:257` (`f"{settings.public_base_url}/infinitemarkets/order#{token}"`), `395-398` (sign-in fragment link), `401-419` (placeholders)
**Apply to:** CTA `href`, the customer opt-out footer link, and the account sign-in `href`. All are escaped with `quote=True` in HTML, and the preview substitutes `[… omitted]` in **every** link position, including footers.

### S8. Host-settings idiom in runtime tests
**Source:** `tests/runtime/test_email_queue.py:190`, `test_email_signin.py:405-408`
```python
    monkeypatch.setattr(type(settings), "is_email_notifications_configured", lambda self: True)
```
**Apply to:** all migrated tests, via `smtp_capture`. Phase 9 adds the companion `monkeypatch.setattr(host_settings, "lnbits_email_notifications_email", "shop@example.com")`, because `_build_message` validates the sender the way the host does (Pitfall 2).

### S9. Test module header and markers
**Source:** `test_catalog_events.py:14`, `test_crypto_keystore.py:15`, `test_keystore_nip17.py:19` use `pytestmark = [pytest.mark.runtime, pytest.mark.fast]`. Host-boot modules use `pytestmark = pytest.mark.runtime` (test_email_queue.py:14).
**Apply to:** the new `test_email_render.py` (fast). Migrated host-boot modules keep their markers.

### S10. Identifier closure + lint
**Source:** `tests/qualification/test_p0_14_contract_closure.py:409-415`
```python
    variants = {
        m.lower()
        for m in re.findall(r"(?i)(?:gamma|infinite)[-_ ]?markets?", qual_src)
    }
    assert variants == {"infinitemarkets"}, (
```
**Apply to:** any edit in `harness/*.py` and `tests/qualification/*.py`. Only the spelling `infinitemarkets` may appear, so never write "Infinite Markets". The production fallback `"Infinitemarkets"` (email.py:171) lowercases to the canonical form. Ruff runs with `line-length = 100` and `select = ["E","F","I","W"]` (pyproject.toml:52-56), and E501 applies inside template strings.

### S11. Cross-module test helper imports
**Source:** `test_email_queue.py:136-137` (`from test_order_admin import _hard01_snapshot`, `from test_order_saga import _settle_core_payment`), `test_financial_review.py:405`
**Apply to:** sharing MIME helpers. Either import them from a sibling test module, or capture the parsed `text`/`html` inside `smtp_capture` (recommended).

---

## Verify-only surfaces (no edit expected; planner must not break them)

| Surface | Lines | Why it matters |
|---|---|---|
| `tests/runtime/test_order_saga.py` | 295-299 | Positional `_render_body` call; the row has no `channel` key, so the signature must not change |
| `infinitemarkets/services/merchant.py` | 844-871, 887-960 | `get_email_preview` reads `payload["body"]`; `send_test_notification` → `enqueue_test_send` (958-960) is unchanged |
| `infinitemarkets/services/orders.py` | 777-874 | Enqueue already gates `notify_events` on the merchant channel only; SPEC §11 says `orders.py` needs no change |
| `infinitemarkets/services/tasks.py` | 179-203 | Background loop resolves `email_service.worker_tick` by attribute |
| `tools/e2e_server.py` | 87-96, 686-740 | Dummy SMTP at `127.0.0.1:10025` with valid `e2e@example.com`. Connection refused → exception → bounded retry, same outcome as today. `/_e2e/mailbox` reads `payload_enc` |
| `tests/runtime/test_admin_ui.py` | 524-539 | Pinned notification copy strings |
| `docs/technical-specification.md` §8.8 | n/a | Stale prose is not parsed by any test. Leave it for Phase 11 (CONTEXT discretion) |
| `harness/registry.py`, `harness/schema.py` | n/a | D-24 parity surfaces, untouched |
| `tools/package_release.py` | 116-139 | Stdlib vendoring stays deferred (D-27) |

## Test-name ↔ VALIDATION `-k` selector map

| Selector (09-VALIDATION.md) | File | Name must contain |
|---|---|---|
| `-k tree` | `test_email_render.py` | `tree` (alternative/related structure, unusable-logo collapse) |
| `-k smtp_send` | `test_email_render.py` | `smtp_send` (fake SMTP call order, propagation, no debuglevel) |
| `-k sections` | `test_email_render.py` | `sections` (wordmark/logo, accent, items, totals, CTA iff live) |
| `-k escap` | `test_email_render.py` | `escap` (`<script>"'&` payloads, banned template constructs) |
| `-k footer` | `test_email_render.py` | `footer` (all channels, both parts, no-link variant) |
| `-k header` | `test_email_render.py` | `header` (Date, Message-ID domain, Auto-Submitted, From sanitize, no Reply-To/List-Unsubscribe) |
| `-k "hard01 or delivery"` | `test_email_queue.py` | existing `hard01`; new merchant-confirmed test contains `delivery` |
| `-k "notify_events or consent"` | `test_email_queue.py` | new EMAIL-08 test contains `notify_events`; existing `test_consent_revocation_suppresses` |
| `-k orderless` | `test_email_queue.py` | existing `test_orderless_test_send` (extend for EMAIL-10) |

## No Analog Found

These are sub-components inside mapped files that have no in-repo precedent. The planner should use the RESEARCH.md patterns.

| Sub-component | File | Role | Data Flow | Reason | Use |
|---|---|---|---|---|---|
| MIME tree + header assembly (`_build_message`) | `services/email.py` | utility (pure) | transform | No `email.*` stdlib usage anywhere in the repo | RESEARCH Code Example 1, Pitfalls 5/11/12 |
| Unicode-category header sanitizer (`_header_safe`) | `services/email.py` | utility | transform | No control-character stripping helper exists (only `crypto.normalize` NFC) | RESEARCH Code Example 1, Pitfall 6 |
| Dedicated autoescape Jinja `Environment` | `services/email.py` (or template file) | utility | transform | The extension only uses host `template_renderer` (views.py:26, 71-72) | RESEARCH Code Example 5, Pitfall 9; fallback is the `nip89.render_markdown` escaping style |
| Fake `smtplib.SMTP` + MIME part extraction | `tests/runtime/test_email_render.py`, `conftest.py` | test helper | fake transport | No `smtplib`/`EmailMessage`/`get_body` usage in tests | RESEARCH Code Example 6; structure from `harness/email.py::SmtpStub` |

## Metadata

**Analog search scope:**
- `infinitemarkets/` (services, views, settings, templates, static js), `tests/runtime/`, `tests/qualification/`, `harness/`, `tools/`
- `pyproject.toml`
- Read-only host reference: pinned `lnbits/helpers.py`, consulted to confirm the `template_renderer` and `is_valid_email_address` shapes.

**Files scanned:** 34 read or grepped in targeted ranges.

**Tracked-source gate:** every analog path above passed `git ls-files` (all TRACKED). The pinned host checkout is untracked and is cited only as a do-not-edit reference, never as an analog.

**Pattern extraction date:** 2026-10-18
