"""Gamma order-message adapters — spec sections 6.9, 8.1, 8.5, 8.6.

This module is the rumor <-> domain seam: validated kind-16/17/14 rumors
become checkout/orders/messages work here, and every outbound merchant
message (payment request, status, shipping, DM) is rendered as a
canonical NIP-17 rumor descriptor, encrypted at rest into
``outbox_events.payload_enc`` and published as two independent
recipient/sender wraps by the ``order_msg`` outbox branch.

Tag-shape rules (§6.9):

- kind-16 requires exactly one ``p``/``type``/``order``; ``subject`` is
  tolerated missing/non-``order`` on inbound type-1 for Plebeian-class
  clients (lenient interop envelope, D-32 register).
- ``item``/``shipping`` tag values split on the FIRST TWO colons only
  (``30402:<pk>:<d>`` — the d-tag may itself contain ``:``).
- Every ``item``/``shipping`` reference MUST carry the merchant pubkey —
  cross-merchant references reject before reservation (§8.5 step 8).
- Buyer ``amount`` is stored as ``buyer_amount_sat``, never trusted.
- Opaque (non-JSON) ``address`` strings map to an ``_opaque`` marker that
  forces §8.1 step-7 reject-before-reservation for physical orders while
  digital orders complete.

Outbound descriptor rules (§8.6 step 3): ``rumor_created_at`` is frozen
at enqueue time so retries rebuild the SAME canonical rumor id while
seals/wrappers/outer ids stay fresh. ``order_msg`` intents enqueue at
``aggregate_revision=0`` so they never supersede each other.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import uuid

from .. import crypto
from ..db import DomainTransaction, db, table
from ..security import unprocessable
from ..settings import ext_settings

KIND_DM = 14
KIND_ORDER_MESSAGE = 16
KIND_RECEIPT = 17

EXTERNAL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_DMS_PER_HOUR = 20  # §15 per-inner-buyer DM cap

#: §7.1 Gamma projection of order state -> type-3 ``status`` tag.
GAMMA_STATUS_PROJECTION = {
    "received": "pending",
    "invoice_pending": "pending",
    "awaiting_payment": "pending",
    "confirmed": "confirmed",
    "processing": "processing",
    "completed": "completed",
    "rejected": "cancelled",
    "expired": "cancelled",
    "cancelled": "cancelled",
}

TYPE4_STATUSES = frozenset({"processing", "shipped", "delivered", "exception"})


def _now() -> int:
    return int(time.time())


def _tag_values(tags, name: str) -> list[str]:
    return [
        t[1] for t in tags
        if isinstance(t, list) and len(t) >= 2 and t[0] == name
    ]


def _first_tag(tags, name: str) -> str | None:
    values = _tag_values(tags, name)
    return values[0] if values else None


def buyer_hash(settings, merchant_id: str, pubkey_hex: str) -> str:
    return crypto.hmac_index(
        settings.privacy_key, crypto.PURPOSE_BUYER_PUBKEY,
        merchant_id, crypto.normalize(pubkey_hex),
    )


# --- inbound type-1 -> checkout payload (§8.1 Gamma profile) ------------------


def build_checkout_payload(rumor_json, merchant: dict) -> dict:
    """Map a validated kind-16 type-1 rumor onto the checkout payload
    shape. Raises ``unprocessable`` (bounded codes) on every spec
    deviation — the caller marks the row ``rejected`` and issues the
    D-22 ``status=rejected`` reply."""
    rumor = (
        json.loads(rumor_json)
        if isinstance(rumor_json, str)
        else dict(rumor_json)
    )
    tags = rumor.get("tags") or []
    types = _tag_values(tags, "type")
    if types != ["1"]:
        raise unprocessable(
            "invalid-order-message", "Invalid order message",
            "expected a type-1 order rumor",
        )
    orders = _tag_values(tags, "order")
    if len(orders) != 1 or not EXTERNAL_ID_RE.match(orders[0]):
        raise unprocessable(
            "invalid-external-id", "Invalid order reference",
            "order tag missing or not ^[A-Za-z0-9_-]{1,64}$",
        )
    items: list[dict] = []
    for t in tags:
        if not (isinstance(t, list) and len(t) >= 3 and t[0] == "item"):
            continue
        parts = str(t[1]).split(":", 2)
        if len(parts) != 3 or parts[0] != "30402":
            raise unprocessable(
                "invalid-content", "Invalid item",
                "item must be '30402:<pubkey>:<d-tag>'",
            )
        if parts[1] != merchant["pubkey"]:
            raise unprocessable(
                "invalid-content", "Invalid item",
                "item references a different merchant",
            )
        try:
            qty = int(t[2])
        except (TypeError, ValueError):
            raise unprocessable(
                "invalid-content", "Invalid item",
                "item quantity must be an integer",
            ) from None
        items.append({"d_tag": parts[2], "quantity": qty})
    if not items:
        raise unprocessable(
            "invalid-content", "Invalid items",
            "a type-1 order requires at least one item tag",
        )
    shipping_option_d = None
    for t in tags:
        if not (isinstance(t, list) and len(t) >= 2 and t[0] == "shipping"):
            continue
        parts = str(t[1]).split(":", 2)
        if len(parts) == 3 and parts[0] == "30406" and parts[1] == merchant["pubkey"]:
            shipping_option_d = parts[2]
    address: dict | None = None
    country = _first_tag(tags, "country")
    region = _first_tag(tags, "region")
    if country or region:
        address = {}
        if country:
            address["country"] = country
        if region:
            address["region"] = region
    raw_address = _first_tag(tags, "address")
    if raw_address is not None:
        try:
            parsed = json.loads(raw_address)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            address = {**(address or {}), **parsed}
        else:
            # Opaque newline-joined/free-form address (Plebeian) — the
            # marker makes physical orders take the documented
            # reject-before-reservation path; digital orders complete.
            address = {"_opaque": raw_address}
    buyer_amount_sat = None
    raw_amount = _first_tag(tags, "amount")
    if raw_amount is not None:
        try:
            buyer_amount_sat = max(0, int(raw_amount))
        except (TypeError, ValueError):
            buyer_amount_sat = None
    return {
        "items": items,
        "shipping_option_d": shipping_option_d,
        "address": address,
        "external_id": orders[0],
        "buyer_amount_sat": buyer_amount_sat,
        "email": _first_tag(tags, "email"),
        "phone": _first_tag(tags, "phone"),
        "email_opt_in": False,
    }


# --- outbound descriptors (§8.6 step 3) ---------------------------------------


def _canonical_id(kind: int, content: str, created_at: int, tags, author_pubkey: str) -> str:
    """Canonical NIP-01 id of a rumor built from parts — through the SDK
    builder, never hand-rolled sha256."""
    from nostr_sdk import EventBuilder, Kind, PublicKey, Tag, Timestamp

    rebuilt = (
        EventBuilder(Kind(kind), content)
        .custom_created_at(Timestamp.from_secs(int(created_at)))
        .tags([Tag.parse(list(t)) for t in tags])
        .build(PublicKey.parse(author_pubkey))
    )
    return rebuilt.id().to_hex()


def rumor_descriptor(order: dict | None, msg_seq: int, payload: dict) -> dict:
    """Build the canonical rumor descriptor stored under ``payload_enc``.

    ``payload`` carries the semantic fields; ``rumor_created_at`` MUST be
    present (frozen at enqueue) so retries rebuild the same rumor id.
    """
    recipient = payload["recipient_pubkey"]
    author = payload["author_pubkey"]
    kind = int(payload["rumor_kind"])
    created_at = int(payload["rumor_created_at"])
    content = str(payload.get("content") or "")
    tags: list[list[str]] = [["p", recipient]]
    if payload.get("subject") is not None:
        tags.append(["subject", str(payload["subject"])])
    if payload.get("type") is not None:
        tags.append(["type", str(payload["type"])])
    if payload.get("order_external_id") is not None:
        tags.append(["order", str(payload["order_external_id"])])
    if payload.get("status") is not None:
        tags.append(["status", str(payload["status"])])
    if payload.get("amount") is not None:
        tags.append(["amount", str(payload["amount"])])
    if payload.get("payment") is not None:
        payment_tag = ["payment", "lightning", str(payload["payment"])]
        if payload.get("preimage") is not None:
            payment_tag.append(str(payload["preimage"]))
        tags.append(payment_tag)
    if payload.get("expiration") is not None:
        tags.append(["expiration", str(payload["expiration"])])
    for opt in ("tracking", "carrier", "eta"):
        if payload.get(opt) is not None:
            tags.append([opt, str(payload[opt])])
    rumor_id = _canonical_id(kind, content, created_at, tags, author)
    return {
        "rumor_created_at": created_at,
        "rumor_id": rumor_id,
        "rumor_kind": kind,
        "type": payload.get("type"),
        "subject": payload.get("subject"),
        "order_external_id": payload.get("order_external_id"),
        "recipient_pubkey": recipient,
        "author_pubkey": author,
        "tags": tags,
        "content": content,
    }


def rebuild_rumor(descriptor: dict):
    """Rebuild the stored descriptor's ``UnsignedEvent`` — identical
    created_at/tags/content/author reproduces the canonical rumor id."""
    from nostr_sdk import EventBuilder, Kind, PublicKey, Tag, Timestamp

    rumor = (
        EventBuilder(Kind(int(descriptor["rumor_kind"])), descriptor["content"])
        .custom_created_at(
            Timestamp.from_secs(int(descriptor["rumor_created_at"]))
        )
        .tags([Tag.parse(list(t)) for t in descriptor["tags"]])
        .build(PublicKey.parse(descriptor["author_pubkey"]))
    )
    if rumor.id().to_hex() != descriptor["rumor_id"]:
        raise ValueError("descriptor rumor id mismatch")
    return rumor


def _order_message_context(order: dict, settings) -> dict:
    """Decrypt the buyer-facing fields needed for outbound descriptors."""
    key_ver = crypto.envelope_version(order["buyer_pubkey_enc"])
    buyer = crypto.decrypt(
        order["buyer_pubkey_enc"], settings.master_keys[key_ver],
        record_id=order["id"], table="orders",
        column="buyer_pubkey_enc", key_version=key_ver,
    ).decode()
    ext_ver = crypto.envelope_version(order["external_id_enc"])
    external_id = crypto.decrypt(
        order["external_id_enc"], settings.master_keys[ext_ver],
        record_id=order["id"], table="orders",
        column="external_id_enc", key_version=ext_ver,
    ).decode()
    return {"buyer_pubkey": buyer, "external_id": external_id}


async def _next_msg_seq(tx, order_id: str) -> int:
    """Per-order monotonic message sequence = order_messages count + 1."""
    row = await tx.fetch_one(
        f"SELECT COUNT(*) AS n FROM {tx.table('order_messages')}"
        " WHERE order_id = :o",
        {"o": order_id},
    )
    return int(row["n"]) + 1


async def enqueue_order_msg(
    tx,
    merchant_id: str,
    order: dict | None,
    payload: dict,
    msg_seq: int,
    *,
    aggregate_id: str | None = None,
    conversation_id: str | None = None,
) -> str:
    """Descriptor -> ``payload_enc`` (record-bound AAD) -> revision-0
    ``order_msg`` intent + ``order_messages`` 'out' row — all inside the
    caller's domain transaction.

    ``msg_seq`` is per-order monotonic (order_messages count + 1); the
    aggregate id ``<order_id>:<msg_seq>`` preserves per-order ordering
    while revision 0 keeps order_msg rows immune to supersession (§7.4).
    """
    from . import outbox as outbox_service

    settings = ext_settings()
    payload = dict(payload)
    payload.setdefault("rumor_created_at", _now())
    if "author_pubkey" not in payload:
        row = await tx.fetch_one(
            f"SELECT pubkey FROM {tx.table('merchants')} WHERE id = :m",
            {"m": merchant_id},
        )
        payload["author_pubkey"] = row["pubkey"]
    descriptor = rumor_descriptor(order, msg_seq, payload)
    aid = aggregate_id or f"{order['id']}:{msg_seq}"
    intent_id = await outbox_service.enqueue_intent(
        tx, merchant_id, "order_msg", aid, int(payload["rumor_kind"]),
        revision=0, event_address=None,
    )
    existing = await tx.fetch_one(
        f"SELECT payload_enc FROM {tx.table('outbox_events')} WHERE id = :i",
        {"i": intent_id},
    )
    if existing and existing["payload_enc"] is not None:
        # Idempotent re-enqueue — the live descriptor is authoritative.
        return intent_id
    ver = settings.active_key_version
    key = settings.master_keys[ver]
    enc = crypto.encrypt(
        json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode(),
        key, record_id=intent_id, table="outbox_events",
        column="payload_enc", key_version=ver,
    )
    await tx.execute(
        f"UPDATE {tx.table('outbox_events')} SET payload_enc = :p"
        " WHERE id = :i",
        {"p": enc, "i": intent_id},
    )
    recipient_hash = buyer_hash(
        settings, merchant_id, descriptor["recipient_pubkey"]
    )
    msg_id = uuid.uuid4().hex
    content_enc = crypto.encrypt(
        (descriptor["content"] or "").encode(), key,
        record_id=msg_id, table="order_messages",
        column="content_enc", key_version=ver,
    )
    participant_enc = crypto.encrypt(
        descriptor["recipient_pubkey"].encode(), key,
        record_id=msg_id, table="order_messages",
        column="participant_keys_enc", key_version=ver,
    )
    await tx.execute(
        f"INSERT INTO {tx.table('order_messages')} "
        "(id, order_id, direction, protocol, semantic_kind, sender_hash,"
        " recipient_hash, participant_keys_enc, rumor_id, content_enc,"
        " conversation_id, created_at) "
        "VALUES (:i, :o, 'out', 'nip17', :sk, NULL, :rh, :pk, :r, :ce,"
        " :cv, :n)",
        {
            "i": msg_id,
            "o": order["id"] if order else None,
            "sk": payload.get("semantic"),
            "rh": recipient_hash,
            "pk": participant_enc,
            "r": descriptor["rumor_id"],
            "ce": content_enc,
            "cv": conversation_id or (
                f"order:{order['id']}" if order else None
            ),
            "n": _now(),
        },
    )
    return intent_id


async def enqueue_payment_request(
    tx, order: dict, *, bolt11: str, expiration: int | None,
) -> str | None:
    """§6.9 type-2 payment request — only orders carrying a buyer key."""
    if not order.get("buyer_pubkey_hash"):
        return None
    settings = ext_settings()
    ctx = _order_message_context(order, settings)
    seq = await _next_msg_seq(tx, order["id"])
    content = f"Payment request: {order['total_sat']} sats"
    if order.get("buyer_amount_sat") is not None and (
        order["buyer_amount_sat"] != order["total_sat"]
    ):
        content += (
            f" (amount differs from buyer-declared"
            f" {order['buyer_amount_sat']} sats — pay this total)"
        )
    payload = {
        "rumor_kind": KIND_ORDER_MESSAGE, "type": "2",
        "subject": "order-payment",
        "order_external_id": ctx["external_id"],
        "amount": order["total_sat"],
        "payment": bolt11, "expiration": expiration,
        "recipient_pubkey": ctx["buyer_pubkey"],
        "content": content, "semantic": "payment-request",
    }
    return await enqueue_order_msg(
        tx, order["merchant_id"], order, payload, seq,
        conversation_id=f"order:{order['id']}",
    )


async def enqueue_status(tx, order: dict, to_state: str,
                         *, reason: str | None = None) -> str | None:
    """§6.9 type-3 status (merchant->buyer) via the §7.1 projection.

    ``pending`` never emits: the type-2 payment request already signals
    the awaiting-payment state, and received/invoice_pending hops are
    internal saga plumbing rather than buyer-visible statuses."""
    if not order.get("buyer_pubkey_hash"):
        return None
    mapped = GAMMA_STATUS_PROJECTION.get(to_state)
    if mapped is None or mapped == "pending":
        return None
    settings = ext_settings()
    ctx = _order_message_context(order, settings)
    seq = await _next_msg_seq(tx, order["id"])
    payload = {
        "rumor_kind": KIND_ORDER_MESSAGE, "type": "3",
        "subject": "order-info",
        "order_external_id": ctx["external_id"],
        "status": mapped,
        "recipient_pubkey": ctx["buyer_pubkey"],
        "content": reason or "", "semantic": "status",
    }
    return await enqueue_order_msg(
        tx, order["merchant_id"], order, payload, seq,
        conversation_id=f"order:{order['id']}",
    )


async def enqueue_shipping(
    tx, order: dict, shipping_state: str, *,
    tracking: str | None = None, carrier: str | None = None,
    eta: str | None = None,
) -> str | None:
    """§6.9 type-4 shipping (merchant->buyer)."""
    if not order.get("buyer_pubkey_hash"):
        return None
    if shipping_state not in TYPE4_STATUSES:
        return None
    settings = ext_settings()
    ctx = _order_message_context(order, settings)
    seq = await _next_msg_seq(tx, order["id"])
    payload = {
        "rumor_kind": KIND_ORDER_MESSAGE, "type": "4",
        "subject": "shipping-info",
        "order_external_id": ctx["external_id"],
        "status": shipping_state,
        "tracking": tracking, "carrier": carrier, "eta": eta,
        "recipient_pubkey": ctx["buyer_pubkey"],
        "content": "", "semantic": "shipping",
    }
    return await enqueue_order_msg(
        tx, order["merchant_id"], order, payload, seq,
        conversation_id=f"order:{order['id']}",
    )


async def enqueue_rejected_reply(
    tx, merchant: dict, *, recipient_pubkey: str | None,
    order_external_id: str | None, inbox_row_id: str,
) -> str | None:
    """D-22 ``status=rejected`` type-3 reply for parseable-but-rejected
    intake. Unintelligible payloads (no recipient/order id) log only —
    returns None without enqueuing."""
    if not recipient_pubkey or not order_external_id:
        return None
    payload = {
        "rumor_kind": KIND_ORDER_MESSAGE, "type": "3",
        "subject": "order-info",
        "order_external_id": order_external_id,
        "status": "rejected",
        "recipient_pubkey": recipient_pubkey,
        "author_pubkey": merchant["pubkey"],
        "content": "rejected", "semantic": "rejected",
    }
    sender_hash = buyer_hash(
        ext_settings(), merchant["id"], recipient_pubkey
    )
    return await enqueue_order_msg(
        tx, merchant["id"], None, payload, 0,
        aggregate_id=f"rejected:{inbox_row_id}",
        conversation_id=f"unknown:{sender_hash}",
    )


# --- inbound handlers ----------------------------------------------------------


def thread_message(order_or_none: dict | None, sender_hash: str,
                   rumor=None) -> str:
    """D-14 conversation id: order thread only on a constant-time
    sender-hash match to ``orders.buyer_pubkey_hash``; otherwise the
    merchant-visible Unknown folder."""
    if (
        order_or_none
        and order_or_none.get("buyer_pubkey_hash")
        and hmac.compare_digest(
            order_or_none["buyer_pubkey_hash"], sender_hash
        )
    ):
        return f"order:{order_or_none['id']}"
    return f"unknown:{sender_hash}"


async def _order_for_external_id(
    merchant_id: str, external_id: str | None, sender_hash: str,
) -> dict | None:
    """Resolve an order by the buyer-supplied ``order`` tag + constant-time
    sender-hash match. Returns None for unknown/foreign ids — callers
    MUST treat every miss identically (no existence oracle, D-22)."""
    if not external_id or not EXTERNAL_ID_RE.match(external_id):
        return None
    settings = ext_settings()
    eih = crypto.hmac_index(
        settings.privacy_key, crypto.PURPOSE_ORDER_ID,
        merchant_id, crypto.normalize(external_id),
    )
    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT * FROM {table('orders')} "
            "WHERE merchant_id = :m AND external_id_hash = :h",
            {"m": merchant_id, "h": eih},
        )
    for row in rows:
        if row["buyer_pubkey_hash"] and hmac.compare_digest(
            row["buyer_pubkey_hash"], sender_hash
        ):
            return dict(row)
    return None


async def handle_inbound_status(
    *, merchant: dict, sender_hash: str, rumor: dict, now: int,
) -> dict:
    """Inbound kind-16 type-3: only ``cancelled`` is actionable, keyed to
    ``order`` tag + sender-hash match + §7.1 legality. Every other buyer
    status is audit-only and cannot mutate merchant state."""
    tags = rumor.get("tags") or []
    ext_ids = _tag_values(tags, "order")
    statuses = _tag_values(tags, "status")
    ext_id = ext_ids[0] if len(ext_ids) == 1 else None
    status = statuses[0] if len(statuses) == 1 else None
    order = await _order_for_external_id(
        merchant["id"], ext_id, sender_hash
    )
    if order is None or status != "cancelled":
        return {"outcome": "audit-only"}
    from . import orders as order_service

    if order["state"] not in order_service.BUYER_CANCELLABLE_STATES:
        return {"outcome": "audit-only", "order_id": order["id"]}
    try:
        await order_service.cancel_order(
            order_id=order["id"], actor="buyer",
            reason="buyer-nip17-cancel", merchant_context=None,
        )
    except Exception:  # noqa: BLE001 — illegal-transition races are audit-only
        return {"outcome": "audit-only", "order_id": order["id"]}
    return {"outcome": "cancelled", "order_id": order["id"]}


async def handle_receipt(
    *, merchant: dict, sender_hash: str, rumor: dict, now: int,
) -> dict:
    """Inbound kind-17 receipt: evidence only, never settlement.

    ``receipt_verified`` sets ONLY when sender-hash matches the order's
    buyer AND the ``bolt11`` tag equals the stored invoice AND
    ``sha256(preimage) == payments.payment_hash``. The buyer-claimed
    ``amount`` is recorded for dispute display — never reconciled.
    """
    settings = ext_settings()
    tags = rumor.get("tags") or []
    ext_ids = _tag_values(tags, "order")
    ext_id = ext_ids[0] if len(ext_ids) == 1 else None
    order = await _order_for_external_id(
        merchant["id"], ext_id, sender_hash
    )
    if order is None:
        return {"outcome": "audit-only"}
    payment_tag = next(
        (t for t in tags
         if isinstance(t, list) and len(t) >= 3
         and t[0] == "payment" and t[1] == "lightning"),
        None,
    )
    claimed_amount = _first_tag(tags, "amount")
    try:
        claimed_amount = int(claimed_amount) if claimed_amount is not None else None
    except (TypeError, ValueError):
        claimed_amount = None
    verified = False
    if payment_tag is not None:
        bolt11 = payment_tag[2]
        preimage = payment_tag[3] if len(payment_tag) >= 4 else None
        async with db.connect() as conn:
            projection = await conn.fetchone(
                f"SELECT payment_hash, bolt11_enc FROM {table('payments')}"
                " WHERE order_id = :o",
                {"o": order["id"]},
            )
        if projection and projection["bolt11_enc"] is not None:
            ver = crypto.envelope_version(projection["bolt11_enc"])
            stored = crypto.decrypt(
                projection["bolt11_enc"], settings.master_keys[ver],
                record_id=order["id"], table="payments",
                column="bolt11_enc", key_version=ver,
            ).decode()
            if stored == bolt11 and preimage and projection["payment_hash"]:
                try:
                    verified = (
                        hashlib.sha256(bytes.fromhex(preimage)).hexdigest()
                        == projection["payment_hash"]
                    )
                except (TypeError, ValueError):
                    verified = False
    async with DomainTransaction() as tx:
        if verified:
            await tx.execute(
                f"UPDATE {tx.table('orders')} SET receipt_verified = TRUE,"
                " updated_at = :n WHERE id = :i",
                {"n": now, "i": order["id"]},
            )
        # The buyer-claimed amount lands in the audit trail for dispute
        # display — cosmetic evidence, never a settlement input.
        await tx.execute(
            f"INSERT INTO {tx.table('order_events')} "
            "(id, order_id, from_state, to_state, actor, detail_json,"
            " created_at) "
            "SELECT :i, :o, state, state, 'buyer', :d, :n"
            f" FROM {tx.table('orders')} WHERE id = :o",
            {
                "i": uuid.uuid4().hex, "o": order["id"],
                "d": json.dumps({
                    "event": "nip17-receipt",
                    "verified": verified,
                    "buyer_claimed_amount_sat": claimed_amount,
                }),
                "n": now,
            },
        )
    return {"outcome": "receipt-verified" if verified else "audit-only"}


async def handle_dm(
    *, merchant: dict, sender_hash: str, author_pubkey: str,
    rumor: dict, rumor_id: str, now: int,
) -> dict:
    """Inbound kind-14: ``order_messages`` insert threaded by sender-hash
    match; strangers land in the Unknown folder (D-14). The §15 20/hour
    per-inner-buyer cap rejects excess."""
    settings = ext_settings()
    tags = rumor.get("tags") or []
    ext_ids = _tag_values(tags, "subject")
    ext_id = ext_ids[0] if len(ext_ids) == 1 else None
    order = await _order_for_external_id(
        merchant["id"], ext_id, sender_hash
    )
    conversation_id = thread_message(order, sender_hash, rumor)
    content = str(rumor.get("content") or "")
    window = now - (now % 3600)
    msg_id = uuid.uuid4().hex
    ver = settings.active_key_version
    key = settings.master_keys[ver]
    content_enc = crypto.encrypt(
        content.encode(), key, record_id=msg_id,
        table="order_messages", column="content_enc", key_version=ver,
    )
    participant_enc = crypto.encrypt(
        author_pubkey.encode(), key, record_id=msg_id,
        table="order_messages", column="participant_keys_enc",
        key_version=ver,
    )
    async with DomainTransaction() as tx:
        bucket = await tx.fetch_one(
            f"INSERT INTO {tx.table('rate_limit_buckets')} AS rate_bucket "
            "(scope_hash, bucket, window_start, count, expires_at) "
            "VALUES (:s, 'dm-inbound', :w, 1, :e) "
            "ON CONFLICT (scope_hash, bucket, window_start) DO UPDATE "
            "SET count = rate_bucket.count + 1"
            " WHERE rate_bucket.count < :cap RETURNING count",
            {"s": sender_hash, "w": window, "e": window + 7200,
             "cap": MAX_DMS_PER_HOUR},
        )
        if bucket is None:
            return {"outcome": "rate-limited"}
        await tx.execute(
            f"INSERT INTO {tx.table('order_messages')} "
            "(id, order_id, direction, protocol, semantic_kind,"
            " sender_hash, participant_keys_enc, rumor_id, content_enc,"
            " conversation_id, created_at) "
            "VALUES (:i, :o, 'in', 'nip17', 'dm', :sh, :pk, :r, :ce,"
            " :cv, :n)",
            {
                "i": msg_id,
                "o": order["id"] if order else None,
                "sh": sender_hash, "pk": participant_enc,
                "r": rumor_id, "ce": content_enc,
                "cv": conversation_id, "n": now,
            },
        )
    return {"outcome": "threaded" if order else "unknown",
            "conversation_id": conversation_id}


# --- merchant outbound kind-14 --------------------------------------------------


async def compose_dm(
    merchant_id: str, *, recipient_pubkey: str, content: str,
    order: dict | None = None,
) -> dict:
    """Merchant-authored kind-14 to any npub — dual-copy via the
    ``order_msg`` intent + an 'out' order_messages row."""
    from nostr_sdk import PublicKey

    settings = ext_settings()
    try:
        recipient_hex = PublicKey.parse(recipient_pubkey).to_hex()
    except Exception:
        raise unprocessable(
            "invalid-content", "Invalid recipient",
            "recipient must be a hex or npub nostr pubkey",
        ) from None
    if not content or len(content.encode()) > 8 * 1024:
        raise unprocessable(
            "invalid-content", "Invalid message",
            "content must be 1..8192 bytes",
        )
    async with db.connect() as conn:
        merchant = await conn.fetchone(
            f"SELECT * FROM {table('merchants')} WHERE id = :m",
            {"m": merchant_id},
        )
    if merchant is None:
        raise unprocessable("invalid-content", "Unknown merchant")
    async with DomainTransaction() as tx:
        recipient_h = buyer_hash(settings, merchant_id, recipient_hex)
        payload = {
            "rumor_kind": KIND_DM, "author_pubkey": merchant["pubkey"],
            "recipient_pubkey": recipient_hex,
            "order_external_id": None,
            "content": content, "semantic": "dm",
        }
        if order is not None:
            ver = crypto.envelope_version(order["external_id_enc"])
            payload["order_external_id"] = crypto.decrypt(
                order["external_id_enc"], settings.master_keys[ver],
                record_id=order["id"], table="orders",
                column="external_id_enc", key_version=ver,
            ).decode()
            payload["subject"] = payload["order_external_id"]
        seq = (
            await _next_msg_seq(tx, order["id"]) if order else 0
        )
        conversation = (
            f"order:{order['id']}" if order
            else f"unknown:{recipient_h}"
        )
        intent_id = await enqueue_order_msg(
            tx, merchant_id, order, payload, seq,
            aggregate_id=f"dm:{uuid.uuid4().hex[:16]}",
            conversation_id=conversation,
        )
    return {
        "queued": True, "intent_id": intent_id,
        "conversation_id": conversation,
    }


async def reply_dm(
    merchant_id: str, *, conversation_id: str, content: str,
) -> dict:
    """Reply inside an existing conversation — resolves the counterparty
    from stored participant ciphertext (owner-side decrypt)."""
    settings = ext_settings()
    if not content or len(content.encode()) > 8 * 1024:
        raise unprocessable(
            "invalid-content", "Invalid message",
            "content must be 1..8192 bytes",
        )
    order = None
    if conversation_id.startswith("order:"):
        order_id = conversation_id.split(":", 1)[1]
        async with db.connect() as conn:
            row = await conn.fetchone(
                f"SELECT * FROM {table('orders')} WHERE id = :o"
                " AND merchant_id = :m",
                {"o": order_id, "m": merchant_id},
            )
        if row is None:
            raise unprocessable(
                "invalid-content", "Unknown conversation",
            )
        order = dict(row)
    elif not conversation_id.startswith("unknown:"):
        raise unprocessable(
            "invalid-content", "Unknown conversation",
        )
    # Resolve the counterparty pubkey: order-bound -> buyer_pubkey_enc;
    # unknown -> the stored participant ciphertext on any row in the
    # conversation.
    recipient_pubkey = None
    if order is not None:
        ctx = _order_message_context(order, settings)
        recipient_pubkey = ctx["buyer_pubkey"]
    else:
        async with db.connect() as conn:
            row = await conn.fetchone(
                f"SELECT id, participant_keys_enc FROM {table('order_messages')}"
                " WHERE conversation_id = :c"
                " AND participant_keys_enc IS NOT NULL LIMIT 1",
                {"c": conversation_id},
            )
        if row is not None and row["participant_keys_enc"] is not None:
            ver = crypto.envelope_version(row["participant_keys_enc"])
            recipient_pubkey = crypto.decrypt(
                row["participant_keys_enc"], settings.master_keys[ver],
                record_id=row["id"], table="order_messages",
                column="participant_keys_enc", key_version=ver,
            ).decode()
    if not recipient_pubkey:
        raise unprocessable(
            "invalid-content", "Unknown conversation",
            "no resolvable counterparty",
        )
    async with db.connect() as conn:
        merchant = await conn.fetchone(
            f"SELECT * FROM {table('merchants')} WHERE id = :m",
            {"m": merchant_id},
        )
    async with DomainTransaction() as tx:
        payload = {
            "rumor_kind": KIND_DM, "author_pubkey": merchant["pubkey"],
            "recipient_pubkey": recipient_pubkey,
            "order_external_id": None,
            "content": content, "semantic": "dm",
        }
        if order is not None:
            ctx = _order_message_context(order, settings)
            payload["order_external_id"] = ctx["external_id"]
            payload["subject"] = ctx["external_id"]
        seq = await _next_msg_seq(tx, order["id"]) if order else 0
        intent_id = await enqueue_order_msg(
            tx, merchant_id, order, payload, seq,
            aggregate_id=f"dm:{uuid.uuid4().hex[:16]}",
            conversation_id=conversation_id,
        )
    return {
        "queued": True, "intent_id": intent_id,
        "conversation_id": conversation_id,
    }


# --- §8.7 reconciliation support --------------------------------------------------


async def reenqueue_payment_requests(now: int | None = None) -> int:
    """§8.7: an ``awaiting_payment`` buyer-keyed order with an attached
    invoice but no payment-request message row gets the type-2
    re-enqueued — idempotent by the ``semantic_kind`` check + live-intent
    dedupe."""
    settings = ext_settings()
    now = _now() if now is None else now
    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT o.*, p.bolt11_enc FROM {table('orders')} o"
            f" JOIN {table('payments')} p ON p.order_id = o.id"
            " WHERE o.state = 'awaiting_payment'"
            " AND o.buyer_pubkey_hash IS NOT NULL"
            " AND p.status = 'pending'"
            " AND NOT EXISTS ("
            f"SELECT 1 FROM {table('order_messages')} m"
            " WHERE m.order_id = o.id AND m.semantic_kind = 'payment-request'"
            " AND m.direction = 'out')",
        )
    enqueued = 0
    for row in rows:
        order = dict(row)
        try:
            ver = crypto.envelope_version(order["bolt11_enc"])
            bolt11 = crypto.decrypt(
                order["bolt11_enc"], settings.master_keys[ver],
                record_id=order["id"], table="payments",
                column="bolt11_enc", key_version=ver,
            ).decode()
            async with DomainTransaction() as tx:
                await enqueue_payment_request(
                    tx, order, bolt11=bolt11,
                    expiration=order["invoice_expiry"],
                )
            enqueued += 1
        except Exception:  # noqa: BLE001 — report-only per row
            continue
    return enqueued


# --- GAM-04 merchant Messages surface (plan 03-03, D-12..D-15, D-18..D-20) -------
#
# Conversation folders: ``order:<order_id>`` rows render in the Customer
# folder; ``unknown:<sender_hash>`` rows in Unknown (D-14 — unknown
# senders are NEVER dropped or hidden). Ownership is verified per
# conversation: order folders join the orders table; unknown folders
# prove the stored participant pubkey hashes (PURPOSE_BUYER_PUBKEY,
# merchant-scoped) to the conversation's hash — order_messages carries
# no merchant_id column, so the HMAC scope IS the boundary.

_CONVERSATION_FOLDERS = ("customer", "unknown")
_PREVIEW_LEN = 160
_CONVERSATION_LIMIT = 200


def _folder_filter(folder: str) -> str:
    if folder == "customer":
        return "conversation_id LIKE 'order:%'"
    return "conversation_id LIKE 'unknown:%'"


def _decrypt_text(row: dict, column: str, settings) -> str | None:
    blob = row.get(column)
    if blob is None:
        return None
    try:
        ver = crypto.envelope_version(blob)
        return crypto.decrypt(
            blob, settings.master_keys[ver],
            record_id=row["id"], table="order_messages",
            column=column, key_version=ver,
        ).decode()
    except Exception:  # noqa: BLE001 — display-only decrypt
        return None


def _npub(pubkey_hex: str | None) -> str | None:
    if not pubkey_hex:
        return None
    try:
        from nostr_sdk import PublicKey

        return PublicKey.parse(pubkey_hex).to_bech32()
    except Exception:  # noqa: BLE001 — display-only
        return None


async def _conversation_owned(
    conn, merchant_id: str, conversation_id: str, settings
) -> bool:
    """Verify the conversation belongs to THIS merchant — no cross-tenant
    reads, even though order_messages carries no merchant_id column."""
    if conversation_id.startswith("order:"):
        row = await conn.fetchone(
            f"SELECT 1 AS x FROM {table('orders')} "
            "WHERE id = :o AND merchant_id = :m",
            {"o": conversation_id[6:], "m": merchant_id},
        )
        return row is not None
    if conversation_id.startswith("unknown:"):
        sender_hash = conversation_id.split(":", 1)[1]
        row = await conn.fetchone(
            f"SELECT id, participant_keys_enc FROM {table('order_messages')}"
            " WHERE conversation_id = :c"
            " AND participant_keys_enc IS NOT NULL LIMIT 1",
            {"c": conversation_id},
        )
        if row is None:
            return False
        pubkey = _decrypt_text(row, "participant_keys_enc", settings)
        if not pubkey:
            return False
        # The stored sender/recipient hash is merchant-scoped — a
        # foreign merchant's HMAC can never equal it.
        return hmac.compare_digest(
            buyer_hash(settings, merchant_id, pubkey), sender_hash
        )
    return False


async def _owned_conversations(conn, merchant_id: str, folder: str,
                               settings) -> list[dict]:
    """Aggregate groups for one folder, ownership-filtered."""
    rows = await conn.fetchall(
        f"SELECT conversation_id, MAX(created_at) AS last_at,"
        " COUNT(*) AS n,"
        " SUM(CASE WHEN direction = 'in' AND read_at IS NULL"
        "     THEN 1 ELSE 0 END) AS unread"
        f" FROM {table('order_messages')}"
        f" WHERE conversation_id IS NOT NULL AND {_folder_filter(folder)}"
        " GROUP BY conversation_id ORDER BY last_at DESC LIMIT :l",
        {"l": _CONVERSATION_LIMIT},
    )
    if folder == "customer":
        order_ids = [r["conversation_id"][6:] for r in rows]
        owned: set[str] = set()
        if order_ids:
            placeholders = ", ".join(f":o{i}" for i in range(len(order_ids)))
            params = {f"o{i}": oid for i, oid in enumerate(order_ids)}
            params["m"] = merchant_id
            owned_rows = await conn.fetchall(
                f"SELECT id FROM {table('orders')} "
                f"WHERE id IN ({placeholders}) AND merchant_id = :m",
                params,
            )
            owned = {r["id"] for r in owned_rows}
        return [r for r in rows if r["conversation_id"][6:] in owned]
    out = []
    for row in rows:
        if await _conversation_owned(
            conn, merchant_id, row["conversation_id"], settings
        ):
            out.append(row)
    return out


async def list_conversations(
    merchant_id: str, folder: str = "customer", refresh_profiles: bool = False
) -> dict:
    """Conversation list for one folder — last message preview,
    unread flag, counterparty npub, order linkage."""
    settings = ext_settings()
    if folder not in _CONVERSATION_FOLDERS:
        raise unprocessable(
            "invalid-content", "Unknown folder",
            "folder must be customer or unknown",
        )
    async with db.connect() as conn:
        groups = await _owned_conversations(
            conn, merchant_id, folder, settings
        )
        conversations = []
        for group in groups:
            cid = group["conversation_id"]
            last = await conn.fetchone(
                f"SELECT * FROM {table('order_messages')}"
                " WHERE conversation_id = :c"
                " ORDER BY created_at DESC, id DESC LIMIT 1",
                {"c": cid},
            )
            preview = (
                _decrypt_text(last, "content_enc", settings) if last else ""
            ) or ""
            counterparty_pubkey = None
            if last:
                counterparty_pubkey = _decrypt_text(
                    last, "participant_keys_enc", settings
                )
            order_id = None
            order_ref = None
            if cid.startswith("order:"):
                order_id = cid[6:]
                orow = await conn.fetchone(
                    f"SELECT external_id_enc, state FROM {table('orders')}"
                    " WHERE id = :o",
                    {"o": order_id},
                )
                if orow and orow["external_id_enc"] is not None:
                    try:
                        ver = crypto.envelope_version(
                            orow["external_id_enc"]
                        )
                        order_ref = crypto.decrypt(
                            orow["external_id_enc"],
                            settings.master_keys[ver],
                            record_id=order_id, table="orders",
                            column="external_id_enc", key_version=ver,
                        ).decode()
                    except crypto.CryptoError:
                        order_ref = None
            conversations.append(
                {
                    "conversation_id": cid,
                    "folder": folder,
                    "order_id": order_id,
                    "order_ref": order_ref,
                    "unread": int(group["unread"] or 0),
                    "message_count": int(group["n"]),
                    "last_at": group["last_at"],
                    "preview": preview[:_PREVIEW_LEN],
                    "counterparty_npub": _npub(counterparty_pubkey),
                    "_counterparty_pubkey": counterparty_pubkey,
                }
            )
    pubkeys = [
        c["_counterparty_pubkey"] for c in conversations
        if c.get("_counterparty_pubkey")
    ]
    from . import profiles

    cached = await profiles.refresh_profiles(
        merchant_id, pubkeys, settings=settings, force=refresh_profiles
    )
    for conv in conversations:
        pubkey = conv.pop("_counterparty_pubkey", None)
        conv["counterparty"] = (
            cached.get(pubkey) if pubkey else None
        )
    return {"conversations": conversations}


async def get_thread(merchant_id: str, conversation_id: str) -> dict:
    """One conversation's decrypted thread — owner-side only."""
    settings = ext_settings()
    async with db.connect() as conn:
        if not await _conversation_owned(
            conn, merchant_id, conversation_id, settings
        ):
            from ..security import not_found

            raise not_found("conversation not found")
        rows = await conn.fetchall(
            f"SELECT * FROM {table('order_messages')}"
            " WHERE conversation_id = :c ORDER BY created_at, id",
            {"c": conversation_id},
        )
        messages = [
            {
                "id": r["id"],
                "direction": r["direction"],
                "semantic_kind": r["semantic_kind"],
                "content": _decrypt_text(r, "content_enc", settings) or "",
                "created_at": r["created_at"],
                "read": r["read_at"] is not None,
            }
            for r in rows
        ]
        counterparty_pubkey = next(
            (
                _decrypt_text(r, "participant_keys_enc", settings)
                for r in rows
                if r["participant_keys_enc"] is not None
            ),
            None,
        )
    counterparty = None
    if counterparty_pubkey:
        from . import profiles

        counterparty = (
            await profiles.refresh_profiles(
                merchant_id, [counterparty_pubkey], settings=settings
            )
        ).get(counterparty_pubkey)
    return {
        "conversation_id": conversation_id,
        "counterparty": counterparty,
        "order_id": (
            conversation_id[6:]
            if conversation_id.startswith("order:")
            else None
        ),
        "messages": messages,
    }


async def order_thread(merchant_id: str, order_id: str) -> dict:
    """The order-detail embedded thread — same shape as get_thread."""
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT id FROM {table('orders')} "
            "WHERE id = :o AND merchant_id = :m",
            {"o": order_id, "m": merchant_id},
        )
    if row is None:
        from ..security import not_found

        raise not_found("order not found")
    return await get_thread(merchant_id, f"order:{order_id}")


async def mark_read(merchant_id: str, conversation_id: str) -> dict:
    """Flip every inbound row in the conversation to read (D-15)."""
    settings = ext_settings()
    async with db.connect() as conn:
        if not await _conversation_owned(
            conn, merchant_id, conversation_id, settings
        ):
            from ..security import not_found

            raise not_found("conversation not found")
    async with DomainTransaction() as tx:
        rc = await tx.execute(
            f"UPDATE {tx.table('order_messages')} SET read_at = :n"
            " WHERE conversation_id = :c AND direction = 'in'"
            " AND read_at IS NULL",
            {"n": _now(), "c": conversation_id},
        )
    return {"updated": rc}


async def unread_count(merchant_id: str) -> dict:
    """Conversations with unread inbound rows, split by folder — drives
    the nav badge."""
    settings = ext_settings()
    counts = {"customer": 0, "unknown": 0}
    async with db.connect() as conn:
        for folder in _CONVERSATION_FOLDERS:
            groups = await _owned_conversations(
                conn, merchant_id, folder, settings
            )
            counts[folder] = sum(
                1 for g in groups if int(g["unread"] or 0) > 0
            )
    counts["total"] = counts["customer"] + counts["unknown"]
    return counts


async def delivery_evidence(
    merchant_id: str, conversation_id: str
) -> dict:
    """Per-message per-relay publication evidence for a conversation's
    outbound rows — BOTH ``delivery_copy`` classes (recipient|sender)
    with verbatim relay outcomes. Intent->message linkage resolves
    through the frozen ``rumor_id`` in ``payload_enc`` (D-19)."""
    settings = ext_settings()
    async with db.connect() as conn:
        if not await _conversation_owned(
            conn, merchant_id, conversation_id, settings
        ):
            from ..security import not_found

            raise not_found("conversation not found")
        out_rows = await conn.fetchall(
            f"SELECT id, rumor_id, created_at FROM {table('order_messages')}"
            " WHERE conversation_id = :c AND direction = 'out'"
            " AND rumor_id IS NOT NULL ORDER BY created_at",
            {"c": conversation_id},
        )
        intents = await conn.fetchall(
            f"SELECT id, aggregate_id, state, attempts, last_error,"
            " next_attempt_at, payload_enc"
            f" FROM {table('outbox_events')}"
            " WHERE merchant_id = :m AND aggregate_type = 'order_msg'"
            " ORDER BY created_at DESC LIMIT 500",
            {"m": merchant_id},
        )
        rumor_to_intent: dict[str, dict] = {}
        for intent in intents:
            if intent["payload_enc"] is None:
                continue
            try:
                ver = crypto.envelope_version(intent["payload_enc"])
                descriptor = json.loads(
                    crypto.decrypt(
                        intent["payload_enc"], settings.master_keys[ver],
                        record_id=intent["id"], table="outbox_events",
                        column="payload_enc", key_version=ver,
                    ).decode()
                )
            except Exception:  # noqa: BLE001 — skip undecryptable intents
                continue
            rumor_to_intent.setdefault(descriptor.get("rumor_id"), intent)
        messages = []
        for row in out_rows:
            intent = rumor_to_intent.get(row["rumor_id"])
            copies = {"recipient": [], "sender": []}
            state = None
            intent_id = None
            last_error = None
            if intent is not None:
                intent_id = intent["id"]
                state = intent["state"]
                last_error = intent["last_error"]
                pubs = await conn.fetchall(
                    f"SELECT delivery_copy, relay_url, result, message,"
                    " attempted_at, attempt_no"
                    f" FROM {table('relay_publications')}"
                    " WHERE outbox_event_id = :i"
                    " ORDER BY attempted_at",
                    {"i": intent["id"]},
                )
                for p in pubs:
                    copies.setdefault(p["delivery_copy"], []).append(
                        {
                            "relay_url": p["relay_url"],
                            "result": p["result"],
                            "message": p["message"],
                            "attempt_no": p["attempt_no"],
                            "attempted_at": p["attempted_at"],
                        }
                    )
            messages.append(
                {
                    "message_id": row["id"],
                    "intent_id": intent_id,
                    "intent_state": state,
                    "last_error": last_error,
                    "created_at": row["created_at"],
                    "copies": copies,
                }
            )
    return {"messages": messages}
