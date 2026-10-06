"""Storefront mode — the four-state shop-mode settings key (03-03, D-07).

Single source of truth (locked D-07 option): a ``settings`` row keyed
``storefront_mode`` per merchant, one of ``full | showcase | browse_only
| nostr_only`` (default ``full`` when the row is absent).

Gate matrix (D-07..D-11):

- ``checkout_allowed`` — NEW purchases (quote + checkout POST) only in
  ``full``. The Nostr order channel is never mode-gated.
- ``browse_page_allowed`` — product/collection/merchant browse pages
  render normally except ``nostr_only`` (Nostr-notice page).
- ``publish_allowed`` — commerce aggregates pause in ``browse_only``
  (D-09); ``order_msg``/``merchant_profile`` publish in every mode.

D-08 hard invariant: modes gate NEW purchases and browse depth only —
private order links, in-flight invoices, order-status, digital
delivery, sign-in, and claim work in EVERY mode. Mode changes never
touch in-flight orders (D-11); ``showcase``/``nostr_only`` require an
active inbox profile (D-10).
"""

from __future__ import annotations

from ..db import DomainTransaction, db, table
from ..security import conflict, unprocessable

SETTINGS_KEY = "storefront_mode"

#: The four storefront modes (locked D-07 enum).
MODES = ("full", "showcase", "browse_only", "nostr_only")
DEFAULT_MODE = "full"

#: Modes whose selection requires ``inbox_state == 'active'`` (D-10).
INBOX_GATED_MODES = frozenset({"showcase", "nostr_only"})

#: Commerce aggregates paused under ``browse_only`` (D-09). Everything
#: else — ``order_msg``, ``merchant_profile``, ``merchant`` (kind-10050),
#: tombstones — publishes in every mode.
COMMERCE_AGGREGATES = frozenset(
    {"products", "collections", "shipping_options", "categories"}
)

#: Human-facing effect list, surfaced by the two-step admin confirm.
MODE_IMPACT = {
    "full": [
        "Browse, cart and web checkout work normally.",
        "Product, collection, and shipping changes publish to Nostr relays as usual.",
    ],
    "showcase": [
        "Web checkout and instant quotes are turned off.",
        "Product pages show 'Order via Nostr' guidance instead.",
        "Existing order links and in-flight payments still work.",
        "Product and collection changes keep publishing to Nostr relays.",
    ],
    "browse_only": [
        "Web checkout and instant quotes are turned off.",
        "Product, collection, and shipping changes stop publishing to Nostr relays.",
        "Existing order links and in-flight payments still work.",
        "Visitors can still browse the storefront.",
    ],
    "nostr_only": [
        "The public storefront becomes a Nostr-only notice.",
        "Web checkout and instant quotes are turned off.",
        "Existing order links and in-flight payments still work.",
        "Buyers can still order through Nostr and track orders.",
    ],
}

_CHECKOUT_BLOCKED = {
    "showcase": (
        "This shop takes orders over Nostr — check the product page "
        "for instructions."
    ),
    "browse_only": "This shop is not accepting online orders right now.",
    "nostr_only": (
        "This shop sells through Nostr only — check the shop page "
        "for instructions."
    ),
}


async def get_mode(merchant_id: str, *, conn=None) -> str:
    """Read the merchant's mode — ``full`` when no row exists."""
    async def _read(c):
        row = await c.fetchone(
            f"SELECT value FROM {table('settings')} "
            "WHERE merchant_id = :m AND key = :k",
            {"m": merchant_id, "k": SETTINGS_KEY},
        )
        return row["value"] if row else DEFAULT_MODE

    if conn is not None:
        value = await _read(conn)
    else:
        async with db.connect() as conn:
            value = await _read(conn)
    return value if value in MODES else DEFAULT_MODE


def checkout_allowed(mode: str) -> bool:
    """New web purchases (quote + checkout) only in ``full``."""
    return mode == "full"


def checkout_blocked_detail(mode: str) -> str:
    return _CHECKOUT_BLOCKED.get(mode, "Checkout is unavailable.")


def browse_page_allowed(mode: str, page_kind: str) -> bool:
    """Browse pages render except ``nostr_only`` — order pages are never
    gated here (D-08: they are not browse depth)."""
    assert page_kind in ("product", "collection", "merchant")
    return mode != "nostr_only"


def publish_allowed(mode: str) -> bool:
    """Commerce aggregates pause under ``browse_only`` (D-09)."""
    return mode != "browse_only"


def buy_controls_visible(mode: str) -> bool:
    """Whether product pages render the web checkout card — only
    ``full``; ``showcase``/``browse_only`` render their notice cards."""
    return mode == "full"


async def set_mode(
    merchant: dict, mode: str, *, confirm: bool = False
) -> dict:
    """Two-step mode change with the D-10 inbox gate.

    ``confirm=False`` returns the impact list without writing;
    ``confirm=True`` applies. ``showcase``/``nostr_only`` require
    ``inbox_state == 'active'`` — the check happens on BOTH steps so a
    client can never preview-confirm past the gate.
    """
    if mode not in MODES:
        raise unprocessable(
            "invalid-storefront-mode", "Unknown storefront mode",
            "mode must be one of full|showcase|browse_only|nostr_only",
        )
    if mode in INBOX_GATED_MODES and merchant.get("inbox_state") != "active":
        raise conflict(
            "inbox-required",
            "Inbox required",
            "this mode requires an active Nostr inbox — enable and wait "
            "for the kind-10050 relay acknowledgement first",
        )
    impact = MODE_IMPACT[mode]
    if not confirm:
        return {
            "current_mode": await get_mode(merchant["id"]),
            "requested_mode": mode,
            "impact": impact,
            "requires_confirmation": True,
            "applied": False,
        }
    async with DomainTransaction() as tx:
        await tx.execute(
            f"DELETE FROM {tx.table('settings')} "
            "WHERE merchant_id = :m AND key = :k",
            {"m": merchant["id"], "k": SETTINGS_KEY},
        )
        if mode != DEFAULT_MODE:
            await tx.execute(
                f"INSERT INTO {tx.table('settings')} "
                "(merchant_id, key, value) VALUES (:m, :k, :v)",
                {"m": merchant["id"], "k": SETTINGS_KEY, "v": mode},
            )
    return {
        "current_mode": mode,
        "requested_mode": mode,
        "mode": mode,
        "impact": impact,
        "applied": True,
    }
