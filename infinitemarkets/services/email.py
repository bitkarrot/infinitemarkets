"""Email notification worker — spec section 8.8.

Best-effort, never blocking order transitions. Rows are claimed with the
claim-token CAS discipline of §8.6; every leased write compares the token.
Suppression (marked ``suppressed``, no SMTP call) applies when the host
SMTP path is unconfigured, the extension email switch is off, a merchant
disabled its alert event, customer consent was revoked, or the merchant is
inactive.

Templates render at send time from current order state — subjects carry
only the merchant display name and event name (never buyer PII or internal
ids); bodies may include item summaries, totals, state, and the public
status link rendered from the protected token copy while it is live.

Messages are assembled as multipart/alternative by the extension-owned
``_build_message`` and sent by ``_smtp_send``. Only a confirmed transport
``True`` enters ``sent``; failure returns to ``pending`` with bounded
unclassified backoff — v1 does not claim to distinguish transient transport
errors from SMTP 5xx.
"""

from __future__ import annotations

import asyncio
import html
import json
import random
import re
import smtplib
import time
import unicodedata
import uuid
from decimal import Decimal
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from loguru import logger

from .. import crypto
from ..db import Database, DomainTransaction, db
from ..settings import ext_settings

EMAIL_BATCH = 16
CLAIM_LEASE_S = 120
BACKOFF_BASE_S = 30
BACKOFF_CAP_S = 4 * 3600
CUSTOMER_HOURLY_CAP = 8
MERCHANT_HOURLY_CAP = 60
ACCOUNT_HOURLY_CAP = 8

_EVENT_LABELS = {
    "order_received": "new order received",
    "confirmed": "order confirmed",
    "processing": "order processing",
    "shipped": "order shipped",
    "delivered": "order delivered",
    "cancelled": "order cancelled",
    "expired": "order expired",
    "on_hold": "order on hold",
    "refund_requested": "refund requested",
    "signin_link": "your sign-in link",
}

_EMAIL_LOGO_CID = "logo@infinitemarkets"
_EMAIL_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_HEADER_STRIP_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})
_DEFAULT_EMAIL_ACCENT = "#d69a3a"


def _now() -> int:
    return int(time.time())


def _backoff(attempts: int) -> int:
    return min(
        2 ** attempts * BACKOFF_BASE_S, BACKOFF_CAP_S
    ) + random.randint(0, 30)


# --- claim (section 8.8 step 1 — §8.6 discipline) -----------------------------


async def claim_batch(
    now: int, worker_id: str, database: Database | None = None,
) -> list[dict]:
    """Atomically claim due rows; claim_token fencing on every write."""
    settings = ext_settings()
    database = database or db
    async with DomainTransaction(database) as tx:
        select = (
            f"SELECT id FROM {tx.table('email_queue')} "
            "WHERE state IN ('pending') AND next_attempt_at <= :n"
            " AND attempts < :maxa ORDER BY next_attempt_at, id"
            " LIMIT :lim"
        )
        if tx.for_update:
            select += tx.for_update + " SKIP LOCKED"
        ids = [
            r["id"] for r in await tx.fetch_all(
                select, {"n": now, "maxa": settings.email_max_attempts,
                         "lim": EMAIL_BATCH},
            )
        ]
        if not ids:
            return []
        placeholders = ", ".join(f":i{k}" for k in range(len(ids)))
        params = {f"i{k}": v for k, v in enumerate(ids)}
        await tx.execute(
            f"UPDATE {tx.table('email_queue')} SET state = 'claimed',"
            " claimed_by = :w, claimed_at = :n, claimed_until = :u,"
            " claim_token = claim_token + 1"
            f" WHERE id IN ({placeholders}) AND state = 'pending'",
            {"w": worker_id, "n": now, "u": now + CLAIM_LEASE_S, **params},
        )
        return await tx.fetch_all(
            f"SELECT * FROM {tx.table('email_queue')} "
            f"WHERE id IN ({placeholders}) AND state = 'claimed' AND claimed_by = :w",
            {**params, "w": worker_id},
        )


async def _leased_write(
    tx: DomainTransaction, row: dict, set_clause: str, params: dict
) -> None:
    """One claim-token-CAS write; a lost CAS raises."""
    rc = await tx.execute(
        f"UPDATE {tx.table('email_queue')} SET {set_clause}"
        " WHERE id = :i AND claim_token = :ct AND claimed_until > :n"
        " AND state = 'claimed' AND claimed_by = :w",
        {**params, "i": row["id"], "ct": row["claim_token"],
         "n": await tx.now(), "w": row["claimed_by"]},
    )
    if rc != 1:
        raise RuntimeError(
            f"email row {row['id']!r} lost its claim-token CAS"
        )


async def _rate_bucket_ok(
    tx: DomainTransaction, *, scope: str, bucket: str, cap: int, now: int
) -> bool:
    """Hourly fixed-window cap — the bucket key is already an HMAC/hash
    (recipient_hash or merchant id), never a raw address (§15/§8.8)."""
    window = now - (now % 3600)
    row = await tx.fetch_one(
        f"INSERT INTO {tx.table('rate_limit_buckets')} AS rate_bucket "
        "(scope_hash, bucket, window_start, count, expires_at) "
        "VALUES (:s, :b, :w, 1, :e) "
        "ON CONFLICT (scope_hash, bucket, window_start) DO UPDATE "
        "SET count = rate_bucket.count + 1 WHERE rate_bucket.count < :cap RETURNING count",
        {"s": scope, "b": bucket, "w": window, "e": window + 7200, "cap": cap},
    )
    return row is not None


# --- suppression + rendering -----------------------------------------------------


async def _suppression_reason(
    tx: DomainTransaction, row: dict, merchant: dict | None,
    order: dict | None, host_email_ready: bool,
) -> str | None:
    """Bounded suppression code, or None when the send may proceed."""
    settings = ext_settings()
    if not settings.email_enabled:
        return "email-disabled"
    if not host_email_ready:
        return "host-email-unconfigured"
    if merchant is None or merchant["state"] == "inactive":
        return "merchant-inactive"
    # Merchant event preferences apply to order alerts, not customer consent
    # or orderless test messages.
    if row["channel"] == "merchant" and row["order_id"]:
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


def _subject(merchant: dict, event_type: str) -> str:
    """Subjects carry only display name + event name — never PII/ids."""
    name = _header_safe(merchant.get("display_name"), limit=64) or "Infinitemarkets"
    label = _EVENT_LABELS.get(event_type, "order update")
    return _header_safe(f"{name}: {label}", limit=150)


def _header_safe(value: str | None, *, limit: int) -> str:
    """Remove header controls/bidi separators and normalize whitespace."""
    clean = "".join(
        " " if unicodedata.category(char) in _HEADER_STRIP_CATEGORIES else char
        for char in value or ""
    )
    return " ".join(clean.split())[:limit].strip()


def _render_body(
    row: dict, order: dict | None, items: list[dict],
    merchant: dict, status_link: str | None,
    delivery: list[dict] | None = None,
) -> str:
    """Plain-text body — item summaries, totals, state, status link, and
    (on the paid confirmation only) the merchant's digital delivery.

    Never carries decrypted addresses, keys, payment secrets, or full
    BOLT11/preimage material (§8.8).
    """
    label = _EVENT_LABELS.get(row["event_type"], "order update")
    lines = [f"{label[0].upper()}{label[1:]}."]
    if order is not None:
        lines.append(f"State: {order['state']}")
        if order.get("total_sat") is not None:
            lines.append(f"Total: {order['total_sat']} sats")
    for item in items:
        lines.append(
            f"- {item.get('title') or 'item'} x{item['quantity']}"
        )
    channel = row.get("channel", "customer")
    if channel == "merchant" and order is None:
        lines.extend([
            "",
            "Sample email preview — not a real order.",
            "- Sample item x1",
            "Total: 1,000 sats",
        ])
    if channel == "customer" and row["event_type"] == "confirmed":
        for entry in delivery or []:
            lines.append(
                f"\nYour digital item — {entry['title']}:\n{entry['content']}"
            )
    if status_link:
        lines.append(f"Order status: {status_link}")
    if channel == "customer":
        lines.append("You opted in to order emails.")
        if status_link:
            lines.append(f"To opt out: {status_link}")
        else:
            lines.append("To opt out, use the order page from your order.")
    else:
        lines.append("This is a transactional order notification.")
    return "\n".join(lines)


def _render_signin_body(merchant: dict, link: str) -> str:
    """Magic-link body — the fragment-bearing URL is the only secret;
    the bare token and the recipient address never appear anywhere."""
    name = _header_safe(merchant.get("display_name"), limit=120) or "Infinitemarkets"
    return "\n".join(
        [
            f"Use this link to sign in to {name}: {link}",
            "The link expires in 15 minutes and works once.",
            "If you didn't request it, you can ignore this email.",
            "You requested a sign-in link.",
        ]
    )


def _preview_enc(
    row: dict, subject: str, body: str, settings
) -> bytes:
    """Encrypted owner-only message preview; bearer/digital content omitted."""
    payload = json.dumps(
        {"subject": subject, "body": body},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    ver = settings.active_key_version
    return crypto.encrypt(
        payload, settings.master_keys[ver], record_id=row["id"],
        table="email_queue", column="preview_enc", key_version=ver,
    )


def _html_escape(value) -> str:
    """Escape dynamic values in both HTML text and attribute contexts."""
    return html.escape("" if value is None else str(value), quote=True)


def _email_colors(theme_raw: str | None) -> tuple[str, str]:
    """Resolve a validated accent and a WCAG AA foreground for the CTA."""
    from .themes import contrast_ratio, parse_theme, resolve_tokens

    tokens = resolve_tokens(parse_theme(theme_raw))
    candidate = tokens.get("--color-accent")
    accent = (
        candidate
        if isinstance(candidate, str) and _EMAIL_HEX_COLOR.fullmatch(candidate)
        else _DEFAULT_EMAIL_ACCENT
    )
    if contrast_ratio("#ffffff", accent) >= 4.5:
        return accent, "#ffffff"
    return accent, "#000000"


def _price_label(item: dict) -> str:
    amount = item.get("unit_price_minor")
    if amount is None:
        return ""
    currency = (item.get("currency") or "SAT").upper()
    if currency in {"SAT", "SATS"}:
        return f"{int(amount):,} sats"
    decimals = item.get("currency_decimals")
    places = 2 if decimals is None else max(0, min(18, int(decimals)))
    major = Decimal(int(amount)).scaleb(-places)
    return f"{major:,.{places}f} {currency}"


def _sats_label(amount) -> str:
    return "—" if amount is None else f"{int(amount):,} sats"


def _render_html(view: dict, *, has_logo: bool = False) -> str:
    """Render a complete branded HTML part without remote resources."""
    display_name = _html_escape(
        _header_safe(view.get("display_name"), limit=120) or "Infinitemarkets"
    )
    channel = view.get("channel", "merchant")
    event_type = view.get("event_type", "")
    test_send = bool(view.get("test_send"))
    accent, on_accent = _email_colors(view.get("theme"))
    status_link = view.get("status_link")
    if test_send:
        items = [{
            "title": "Sample item",
            "quantity": 1,
            "unit_price_minor": 1000,
            "currency": "SAT",
            "currency_decimals": 0,
            "line_total_sat": 1000,
            "backordered_qty": 0,
        }]
        subtotal_sat, shipping_sat, total_sat = 1000, 0, 1000
        delivery = []
    else:
        items = view.get("items") or []
        subtotal_sat = view.get("subtotal_sat")
        shipping_sat = view.get("shipping_sat")
        total_sat = view.get("total_sat")
        delivery = view.get("delivery") or []
    if channel != "customer" or event_type != "confirmed":
        delivery = []

    event_label = _EVENT_LABELS.get(event_type, "order update")
    if channel == "account":
        title = "Your sign-in link"
        state_row = ""
    else:
        title = _html_escape(event_label.capitalize())
        state = _html_escape(view.get("state") or "unknown")
        state_row = (
            '<tr><td style="padding:0 24px 16px;">'
            f'<span style="color:#75685c;">State:</span> {state}'
            "</td></tr>"
        )

    if has_logo:
        header = (
            f'<img src="cid:{_EMAIL_LOGO_CID}" height="40" alt="{display_name}" '
            'style="display:block;height:40px;border:0;">'
        )
    else:
        header = (
            '<div style="font-size:20px;font-weight:600;">'
            f"{display_name}</div>"
        )

    content_rows = []
    if channel == "account":
        content_rows.append(
            '<tr><td style="padding:8px 24px 16px;font-size:20px;font-weight:600;">'
            "Your sign-in link</td></tr>"
        )
    else:
        if test_send:
            content_rows.append(
                '<tr><td style="padding:8px 24px;">'
                "Sample email preview — not a real order.</td></tr>"
            )
        content_rows.append(
            '<tr><td style="padding:8px 24px 4px;font-size:20px;font-weight:600;">'
            f"{title}</td></tr>"
        )
        content_rows.append(state_row)
        content_rows.append(
            '<tr><td style="padding:8px 24px;"><table role="presentation" '
            'width="100%" cellpadding="0" cellspacing="0">'
            "<thead><tr><th align=\"left\">Item</th>"
            '<th align="right">Quantity</th><th align="right">Unit price</th>'
            '<th align="right">Line total</th></tr></thead><tbody>'
        )
        if items:
            for item in items:
                title_value = _html_escape(item.get("title") or "item")
                quantity = _html_escape(item.get("quantity", 0))
                unit_price = _html_escape(_price_label(item) or "—")
                line_total = _html_escape(_sats_label(item.get("line_total_sat")))
                backordered = ""
                if int(item.get("backordered_qty") or 0) > 0:
                    backordered = (
                        '<div style="color:#75685c;font-size:12px;">'
                        "Backordered</div>"
                    )
                content_rows.append(
                    '<tr><td style="padding:8px 4px;">'
                    f"{title_value}{backordered}</td>"
                    f'<td align="right" style="padding:8px 4px;">{quantity}</td>'
                    f'<td align="right" style="padding:8px 4px;">{unit_price}</td>'
                    f'<td align="right" style="padding:8px 4px;">{line_total}</td></tr>'
                )
        elif not test_send:
            content_rows.append(
                '<tr><td colspan="4" style="padding:8px 4px;">'
                "No items in this order.</td></tr>"
            )
        content_rows.append("</tbody></table></td></tr>")
        content_rows.append(
            '<tr><td style="padding:8px 24px 16px;"><table role="presentation" '
            'width="100%" cellpadding="0" cellspacing="0">'
        )
        for label, amount in (
            ("Subtotal", subtotal_sat),
            ("Shipping", shipping_sat),
            ("Total", total_sat),
        ):
            if amount is not None or test_send:
                content_rows.append(
                    '<tr><td style="padding:3px 0;">'
                    f"{label}</td><td align=\"right\">"
                    f"{_html_escape(_sats_label(amount))}</td></tr>"
                )
        content_rows.append("</table></td></tr>")

    if delivery:
        for entry in delivery:
            content_rows.append(
                '<tr><td style="padding:8px 24px;">'
                f'<strong>Your digital item — {_html_escape(entry.get("title") or "item")}'
                "</strong>"
                '<div style="white-space:pre-wrap;padding:8px 0;">'
                f"{_html_escape(entry.get('content') or '')}</div></td></tr>"
            )

    cta_url = None if test_send else status_link
    if cta_url:
        cta_label = "Sign in" if channel == "account" else "View order status"
        content_rows.append(
            '<tr><td style="padding:8px 24px 24px;">'
            '<table role="presentation" cellpadding="0" cellspacing="0"><tr>'
            f'<td style="background:{accent};border-radius:6px;">'
            f'<a href="{_html_escape(cta_url)}" '
            f'style="display:inline-block;padding:12px 20px;color:{on_accent};'
            'font-weight:600;text-decoration:none;">'
            f"{cta_label}</a></td></tr></table></td></tr>"
        )

    if channel == "customer":
        opt_out = (
            f'<a href="{_html_escape(status_link)}">visit the order page</a>'
            if status_link
            else "use the order page from your order"
        )
        footer = (
            "<div>You opted in to order emails.</div>"
            f"<div>To opt out: {opt_out}.</div>"
        )
    elif channel == "account":
        footer = "<div>You requested a sign-in link.</div>"
    else:
        footer = "<div>This is a transactional order notification.</div>"

    if test_send:
        preheader = "Sample email preview — not a real order."
    elif channel == "account":
        preheader = "Your sign-in link"
    else:
        preheader = (
            f"{_EVENT_LABELS.get(event_type, 'Order update').capitalize()} — "
            f"{view.get('display_name') or 'Infinitemarkets'}"
        )
    rows = "".join(content_rows)
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        "<title>Transactional notification</title></head>"
        '<body style="margin:0;padding:0;background:#f4f4f5;">'
        '<span style="display:none;max-height:0;overflow:hidden;mso-hide:all;">'
        f"{_html_escape(preheader)}</span>"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        "<tr><td align=\"center\" style=\"padding:24px 12px;\">"
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        f'style="width:100%;max-width:600px;background:#ffffff;border-top:3px solid {accent};'
        "font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
        'color:#1f2328;">'
        f'<tr><td style="padding:20px 24px;background:{accent};">{header}</td></tr>'
        f"{rows}"
        '<tr><td style="padding:16px 24px;border-top:1px solid #dfcfbb;'
        'color:#75685c;font-size:13px;line-height:1.5;">'
        f"{footer}</td></tr>"
        "</table></td></tr></table></body></html>"
    )


def _build_message(
    *,
    subject: str,
    text: str,
    view: dict,
    from_addr: str,
    to_addr: str,
    logo: tuple[bytes, str] | None = None,
) -> EmailMessage:
    """Build a complete UTF-8 alternative message without performing I/O."""
    from lnbits.helpers import is_valid_email_address

    if not (
        is_valid_email_address(from_addr)
        and is_valid_email_address(to_addr)
    ):
        raise ValueError("invalid sender or recipient")
    if (
        not isinstance(logo, tuple)
        or len(logo) != 2
        or not isinstance(logo[0], bytes)
        or not logo[0]
        or logo[1] not in {"png", "jpeg"}
    ):
        logo = None

    message = EmailMessage()
    message["Subject"] = _header_safe(subject, limit=150)
    display_name = _header_safe(view.get("display_name"), limit=64)
    try:
        message["From"] = (
            Address(display_name=display_name, addr_spec=from_addr)
            if display_name
            else from_addr
        )
    except (TypeError, ValueError):
        message["From"] = from_addr
    # Keep the recipient only in the SMTP envelope, not in message headers.
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=from_addr.rpartition("@")[2])
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(
        text,
        subtype="plain",
        charset="utf-8",
        cte="quoted-printable",
    )
    rendered = _render_html(view, has_logo=logo is not None)
    message.add_alternative(
        rendered,
        subtype="html",
        charset="utf-8",
        cte="quoted-printable",
    )
    if logo is not None:
        message.get_payload()[1].add_related(
            logo[0],
            maintype="image",
            subtype=logo[1],
            cid=f"<{_EMAIL_LOGO_CID}>",
            disposition="inline",
        )
    return message


async def _smtp_send(
    message: EmailMessage, *, to: str, timeout: float
) -> bool:
    """Mirror the pinned host SMTP mechanics, bounded at socket and caller."""
    from lnbits.settings import settings as host_settings

    server = host_settings.lnbits_email_notifications_server
    port = host_settings.lnbits_email_notifications_port
    from_addr = host_settings.lnbits_email_notifications_email
    username = host_settings.lnbits_email_notifications_username or from_addr
    password = host_settings.lnbits_email_notifications_password
    wire = message.as_string()

    def _send() -> bool:
        with smtplib.SMTP(server, port, timeout=timeout) as smtp:
            # Host parity: no context means Python 3.12 does not verify the
            # relay certificate. Verified TLS (ASVS 9.2.1, Level 2) is
            # deferred in .planning/STATE.md → Deferred Items.
            smtp.starttls()
            smtp.login(username, password)
            smtp.sendmail(from_addr, [to], wire)
        return True

    return await asyncio.to_thread(_send)


async def _status_link(
    order: dict | None, settings
) -> str | None:
    """Render the magic link only while the order's token is live and the
    AEAD copy still exists (erased on expiry/revocation)."""
    if not order or not order.get("public_token_enc"):
        return None
    now = _now()
    if (
        order.get("public_token_expires_at") is not None
        and order["public_token_expires_at"] <= now
    ):
        return None
    try:
        ver = crypto.envelope_version(order["public_token_enc"])
        token = crypto.decrypt(
            order["public_token_enc"], settings.master_keys[ver],
            record_id=order["id"], table="orders",
            column="public_token_enc", key_version=ver,
        ).decode()
    except Exception:
        return None
    return f"{settings.public_base_url}/infinitemarkets/order#{token}"


# --- the worker --------------------------------------------------------------------


async def worker_tick(
    worker_id: str, *, now: int | None = None,
    database: Database | None = None,
) -> dict:
    """One §8.8 pass: claim -> suppress-or-send -> classify."""
    now = _now() if now is None else now
    settings = ext_settings()
    rows = await claim_batch(now, worker_id, database)
    outcomes: dict[str, int] = {}
    if not rows:
        return {"claimed": 0, "outcomes": outcomes}

    from lnbits.settings import settings as host_settings

    host_ready = host_settings.is_email_notifications_configured()

    async def _send(row: dict) -> str:
        async with DomainTransaction(database) as tx:
            deadline = time.monotonic()
            db_now = await tx.now()
            if row["order_id"]:
                await tx.fetch_one(
                    f"SELECT id FROM {tx.table('orders')} WHERE id = :o" + tx.for_update,
                    {"o": row["order_id"]},
                )
            live = await tx.fetch_one(
                f"SELECT * FROM {tx.table('email_queue')} WHERE id = :i"
                " AND state = 'claimed' AND claimed_by = :w AND claim_token = :t"
                " AND claimed_until > :n" + tx.for_update,
                {"i": row["id"], "w": worker_id, "t": row["claim_token"], "n": db_now},
            )
            if not live:
                return "lost_claim"
            row = live
            deadline += row["claimed_until"] - db_now
            merchant = await tx.fetch_one(
                f"SELECT * FROM {tx.table('merchants')} WHERE id = :m",
                {"m": row["merchant_id"]},
            )
            order = None
            items: list[dict] = []
            if row["order_id"]:
                order = await tx.fetch_one(
                    f"SELECT * FROM {tx.table('orders')} WHERE id = :o",
                    {"o": row["order_id"]},
                )
                items = await tx.fetch_all(
                    f"SELECT title, quantity, unit_price_minor, currency,"
                    f" currency_decimals, line_total_sat, backordered_qty"
                    f" FROM {tx.table('order_items')} WHERE order_id = :o"
                    " ORDER BY id",
                    {"o": row["order_id"]},
                )
            delivery: list[dict] = []
            if order and row["channel"] == "customer" and row["event_type"] == "confirmed":
                from .orders import digital_delivery

                delivery = await digital_delivery(tx, order)
            reason = await _suppression_reason(
                tx, row, merchant, order, host_ready
            )
            if reason:
                await _leased_write(
                    tx, row,
                    "state = 'suppressed', last_error = :e",
                    {"e": reason},
                )
                return "suppressed"

            # §8.8 step 6: per-recipient rate limit before the SMTP call.
            # ``channel == 'account'`` needs its own explicit branch —
            # scoped on the recipient hash; the else-branch would silently
            # bucket account rows under ``email-merchant``.
            if row["channel"] == "account":
                ok = await _rate_bucket_ok(
                    tx, scope=row["recipient_hash"],
                    bucket="email-account", cap=ACCOUNT_HOURLY_CAP,
                    now=now,
                )
            elif row["channel"] == "customer":
                ok = await _rate_bucket_ok(
                    tx, scope=row["recipient_hash"],
                    bucket="email-customer", cap=CUSTOMER_HOURLY_CAP,
                    now=now,
                )
            else:
                ok = await _rate_bucket_ok(
                    tx, scope=row["merchant_id"],
                    bucket="email-merchant", cap=MERCHANT_HOURLY_CAP,
                    now=now,
                )
            if not ok:
                # Defer to the next window — the row stays claimed only
                # until we return it to pending with a bounded retry time.
                await _leased_write(
                    tx, row,
                    "state = 'pending', next_attempt_at = :na,"
                    " claimed_by = NULL, claimed_at = NULL,"
                    " claimed_until = NULL",
                    {"na": now - (now % 3600) + 3600},
                )
                return "rate-deferred"
        # The SMTP boundary is outside the transaction (never hold the
        # claim across network I/O).
        ver = crypto.envelope_version(row["recipient_enc"])
        recipient = crypto.decrypt(
            row["recipient_enc"], settings.master_keys[ver],
            # encrypt-time record ids: order rows bind to the order,
            # orderless rows (test sends) bind to the merchant.
            record_id=row["order_id"] or row["merchant_id"],
            table="email_queue",
            column="recipient_enc", key_version=ver,
        ).decode()
        if (
            row["channel"] == "account"
            and row["event_type"] == "signin_link"
        ):
            # Magic-link render: the token lives only in ``payload_enc``
            # until this point; the link carries it in the URL fragment
            # (§5.4 contract — never path/query/subject/logs).
            pver = crypto.envelope_version(row["payload_enc"])
            token = json.loads(
                crypto.decrypt(
                    row["payload_enc"], settings.master_keys[pver],
                    record_id=row["id"], table="email_queue",
                    column="payload_enc", key_version=pver,
                )
            )["token"]
            shop_q = (
                f"?shop={merchant['pubkey']}"
                if merchant and merchant.get("pubkey")
                else ""
            )
            link = (
                f"{settings.public_base_url}/infinitemarkets/auth/email"
                f"{shop_q}#{token}"
            )
            subject = _subject(merchant or {}, row["event_type"])
            body = _render_signin_body(merchant or {}, link)
            preview_body = _render_signin_body(
                merchant or {}, "[sign-in link omitted]"
            )
            view = {
                "channel": "account",
                "event_type": row["event_type"],
                "display_name": (merchant or {}).get("display_name"),
                "state": None,
                "items": [],
                "subtotal_sat": None,
                "shipping_sat": None,
                "total_sat": None,
                "delivery": [],
                "status_link": link,
                "theme": (merchant or {}).get("theme"),
                "test_send": False,
            }
        else:
            link = await _status_link(order, settings)
            subject = _subject(merchant or {}, row["event_type"])
            body = _render_body(
                row, order, items, merchant or {}, link, delivery
            )
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
            view = {
                "channel": row["channel"],
                "event_type": row["event_type"],
                "display_name": (merchant or {}).get("display_name"),
                "state": (order or {}).get("state"),
                "items": items,
                "subtotal_sat": (order or {}).get("subtotal_sat"),
                "shipping_sat": (order or {}).get("shipping_sat"),
                "total_sat": (order or {}).get("total_sat"),
                "delivery": delivery,
                "status_link": link,
                "theme": (merchant or {}).get("theme"),
                "test_send": row["channel"] == "merchant" and order is None,
            }
        preview = _preview_enc(row, subject, preview_body, settings)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "lost_claim"
        try:
            message = _build_message(
                subject=subject,
                text=body,
                view=view,
                from_addr=host_settings.lnbits_email_notifications_email,
                to_addr=recipient,
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "lost_claim"
            budget = min(30, remaining)
            sent = await asyncio.wait_for(
                _smtp_send(message, to=recipient, timeout=budget),
                timeout=budget,
            )
        except Exception:
            sent = False
        async with DomainTransaction(database) as tx:
            if sent:
                # Sent rows retain no bearer material: recipient_enc AND
                # any payload_enc (magic-link token) are wiped together.
                await _leased_write(
                    tx, row,
                    "state = 'sent', sent_at = :t, recipient_enc = :empty,"
                    " payload_enc = :empty, preview_enc = :preview",
                    {"t": now, "empty": b"", "preview": preview},
                )
                return "sent"
            attempts = row["attempts"] + 1
            if attempts >= settings.email_max_attempts:
                await _leased_write(
                    tx, row,
                    "state = 'failed', attempts = :a, last_error = 'send-failed',"
                    " preview_enc = :preview",
                    {"a": attempts, "preview": preview},
                )
                return "failed"
            await _leased_write(
                tx, row,
                "state = 'pending', attempts = :a,"
                " next_attempt_at = :na, last_error = 'send-failed',"
                " claimed_by = NULL, claimed_at = NULL,"
                " claimed_until = NULL, preview_enc = :preview",
                {"a": attempts, "na": now + _backoff(attempts),
                 "preview": preview},
            )
            return "retry"

    for row in rows:
        try:
            outcome = await _send(row)
        except Exception as exc:  # noqa: BLE001 — per-row isolation
            logger.warning(
                f"infinitemarkets email row {row['id']} failed: {type(exc).__name__}"
            )
            outcome = "error"
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        from . import metrics
        metrics.incr(f"email.{outcome}")
    return {"claimed": len(rows), "outcomes": outcomes}


async def recover_stale_claims(
    now: int | None = None, database: Database | None = None
) -> int:
    """Return rows whose claim lease expired to pending (§8.6 recovery)."""
    now = _now() if now is None else now
    database = database or db
    async with DomainTransaction(database) as tx:
        rc = await tx.execute(
            f"UPDATE {tx.table('email_queue')} SET state = 'pending',"
            " claimed_by = NULL, claimed_at = NULL, claimed_until = NULL"
            " WHERE state = 'claimed' AND claimed_until <= :n",
            {"n": now},
        )
    return rc


async def enqueue_test_send(
    *, merchant_id: str, recipient: str, now: int | None = None
) -> str:
    """Enqueue the §5.1 test notification through the same durable path."""
    settings = ext_settings()
    now = _now() if now is None else now
    enc = crypto.encrypt(
        recipient.encode(),
        settings.master_keys[settings.active_key_version],
        record_id=merchant_id, table="email_queue",
        column="recipient_enc", key_version=settings.active_key_version,
    )
    digest = crypto.hmac_index(
        settings.privacy_key, crypto.PURPOSE_EMAIL_RECIPIENT,
        merchant_id, crypto.normalize(recipient),
    )
    row_id = uuid.uuid4().hex
    async with DomainTransaction() as tx:
        await tx.execute(
            f"INSERT INTO {tx.table('email_queue')} "
            "(id, merchant_id, order_id, channel, event_type,"
            " recipient_enc, recipient_hash, state, attempts,"
            " next_attempt_at, claim_token, created_at) "
            "VALUES (:i, :m, NULL, 'merchant', 'order_received',"
            " :re, :rh, 'pending', 0, :n, 0, :n)",
            {"i": row_id, "m": merchant_id, "re": enc, "rh": digest,
             "n": now},
        )
    return row_id


async def enqueue_magic_link(
    tx: DomainTransaction, *, merchant_id: str, recipient: str,
    token: str, now: int,
) -> str:
    """Enqueue one orderless sign-in link — ``channel='account'`` /
    ``event_type='signin_link'`` (D-07).

    Called INSIDE the caller's ``DomainTransaction`` so the
    ``email_signin_tokens`` row and this queue row commit atomically.
    The raw token persists ONLY inside ``payload_enc`` (AEAD'd like the
    ``orders.public_token_enc`` custody posture) and is decrypted at send
    time to render the fragment link; ``email_queue`` rows with NULL
    ``order_id`` never dedupe — the request-side per-email/IP caps are
    the only volume bound.
    """
    settings = ext_settings()
    ver = settings.active_key_version
    key = settings.master_keys[ver]
    row_id = uuid.uuid4().hex
    enc = crypto.encrypt(
        recipient.encode(), key,
        record_id=merchant_id, table="email_queue",
        column="recipient_enc", key_version=ver,
    )
    digest = crypto.hmac_index(
        settings.privacy_key, crypto.PURPOSE_EMAIL_RECIPIENT,
        merchant_id, crypto.normalize(recipient),
    )
    payload = crypto.encrypt(
        json.dumps({"token": token}).encode(), key,
        record_id=row_id, table="email_queue",
        column="payload_enc", key_version=ver,
    )
    await tx.execute(
        f"INSERT INTO {tx.table('email_queue')} "
        "(id, merchant_id, order_id, channel, event_type,"
        " recipient_enc, recipient_hash, payload_enc, state, attempts,"
        " next_attempt_at, claim_token, created_at) "
        "VALUES (:i, :m, NULL, 'account', 'signin_link', :re, :rh, :pe,"
        " 'pending', 0, :n, 0, :n)",
        {"i": row_id, "m": merchant_id, "re": enc, "rh": digest,
         "pe": payload, "n": now},
    )
    return row_id
