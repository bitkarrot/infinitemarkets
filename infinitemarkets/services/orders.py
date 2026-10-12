"""Order domain — spec sections 7.1–7.3, 8.3 admin actions, 8.8 intents.

``transition_order`` is the ONLY sanctioned way to change ``orders.state``:
legality check -> compare-and-swap (``WHERE state = :from_state``) -> the
``order_events`` audit row, all inside the caller's domain transaction. The
transition table is kept LITERAL against ``harness.state`` — a runtime test
asserts parity rather than re-deriving it.

Every mutation path also enqueues the matching §8.8 email intent in the
same transaction through ``enqueue_email_intents`` so dedupe rules apply
uniformly.
"""

from __future__ import annotations

import json
import re
import time
import uuid

from ..db import DomainTransaction
from ..security import not_found, unprocessable


class IllegalTransition(Exception):
    """The requested transition is not in the section 7.1 table."""


class TransitionConflict(Exception):
    """The compare-and-swap lost (the order was not in the expected state)."""


# --- Section 7.1 order state machine (literal — kept identical to
# --- harness/state.py; a runtime test asserts the tables match) -----------

ORDER_STATES = (
    "received",
    "invoice_pending",
    "awaiting_payment",
    "confirmed",
    "processing",
    "completed",
    "rejected",
    "expired",
    "cancelled",
)

ORDER_TRANSITIONS: dict[str, frozenset[str]] = {
    "received": frozenset({"rejected", "invoice_pending", "cancelled"}),
    "invoice_pending": frozenset({"awaiting_payment", "rejected", "cancelled"}),
    "awaiting_payment": frozenset({"confirmed", "expired", "cancelled"}),
    "confirmed": frozenset({"processing", "cancelled"}),
    "processing": frozenset({"completed", "cancelled"}),
    "expired": frozenset({"confirmed"}),
    "cancelled": frozenset({"confirmed"}),
    "completed": frozenset(),
    "rejected": frozenset(),
}

ORDER_TERMINAL_STATES = ("completed", "rejected")
ORDER_ARCHIVABLE_STATES = frozenset(
    {"completed", "rejected", "expired", "cancelled"}
)

REASON_REQUIRED_TRANSITIONS = frozenset(
    {
        ("confirmed", "cancelled"),
        ("expired", "confirmed"),
        ("cancelled", "confirmed"),
    }
)

BUYER_CANCELLABLE_STATES = ("received", "invoice_pending", "awaiting_payment")

# --- Section 7.2 shipping state machine (literal) -------------------------

SHIPPING_STATES = (
    "not_required",
    "pending",
    "processing",
    "shipped",
    "delivered",
    "exception",
)

SHIPPING_TRANSITIONS: dict[str, frozenset[str]] = {
    "not_required": frozenset({"pending"}),
    "pending": frozenset({"processing"}),
    "processing": frozenset({"shipped", "exception"}),
    "shipped": frozenset({"delivered", "exception"}),
    "exception": frozenset({"processing", "shipped"}),
    "delivered": frozenset(),
}

# --- Section 7.3 reservation state machine (literal) ----------------------

RESERVATION_STATES = ("held", "consumed", "released", "expired")

RESERVATION_TRANSITIONS: dict[str, frozenset[str]] = {
    "held": frozenset({"consumed", "released", "expired"}),
    "consumed": frozenset(),
    "released": frozenset(),
    "expired": frozenset(),
}

# --- Section 8.8 email event types ------------------------------------------

EMAIL_EVENT_TYPES = (
    "order_received",
    "confirmed",
    "processing",
    "shipped",
    "delivered",
    "cancelled",
    "expired",
    "on_hold",
    "refund_requested",
)

#: order-state -> customer-facing event type for admin/system transitions.
_STATE_EMAIL_EVENTS = {
    "confirmed": "confirmed",
    "processing": "processing",
    "shipped": "shipped",
    "delivered": "delivered",
    "cancelled": "cancelled",
    "expired": "expired",
}


def _now() -> int:
    return int(time.time())


# Digital delivery is revealed only once LNbits settlement has moved the
# order into a paid state and nothing about the payment is under review.
DELIVERY_STATES = frozenset({"confirmed", "processing", "completed"})


def delivery_unlocked(order: dict) -> bool:
    return (
        order.get("state") in DELIVERY_STATES
        and not order.get("payment_exception")
        and not order.get("oversold")
    )


def _read_connection(conn):
    from ..db import table as default_table

    return (
        conn.table if isinstance(conn, DomainTransaction) else default_table,
        getattr(conn, "fetchall", None) or conn.fetch_all,
    )


async def payment_settled(conn, order: dict) -> bool:
    table, fetch = _read_connection(conn)
    rows = await fetch(
        f"SELECT * FROM {table('payments')} WHERE order_id = :o LIMIT 2",
        {"o": order["id"]},
    )
    if len(rows) != 1:
        return False
    payment = dict(rows[0])
    from .settlement import _payment_snapshot

    return (
        payment["status"] == "settled"
        and payment["core_external_id"] == f"infinitemarkets:{order['id']}"
        and type(payment["amount_sat"]) is int
        and payment["amount_sat"] == order["total_sat"]
        and payment["amount_sat"] > 0
        and bool(payment["payment_hash"])
        and bool(payment["wallet_id_hash"])
        and type(payment["settled_at"]) is int
        and _payment_snapshot(order, payment) is not None
    )


async def inventory_accounted(conn, order: dict) -> bool:
    table, fetch = _read_connection(conn)
    try:
        items, expected = await inventory_items(conn, order)
    except TransitionConflict:
        return False
    by_id = {item["id"]: item for item in items}
    consumed = {}
    rows = await fetch(
        f"SELECT product_id, quantity, state FROM {table('inventory_reservations')} "
        "WHERE order_id = :o LIMIT 65",
        {"o": order["id"]},
    )
    if len(rows) > 64:
        return False
    for row in rows:
        if row["state"] in ("held",) or row["state"] not in RESERVATION_STATES:
            return False
        if row["state"] != "consumed":
            continue
        product_id, quantity = row["product_id"], row["quantity"]
        if (
            product_id not in expected
            or product_id in consumed
            or type(quantity) is not int
            or quantity <= 0
            or quantity > expected[product_id]
        ):
            return False
        consumed[product_id] = quantity
    if (order.get("payment_exception_resolution") != "accepted" and consumed == expected
            and all(item["backordered_qty"] == 0 for item in by_id.values())):
        return True
    if order.get("payment_exception_resolution") != "accepted":
        return False
    return await accepted_inventory_accounting(conn, order, by_id, consumed) is not None


async def confirmation_chain(conn, order: dict) -> list[dict] | None:
    from ..db import dialect

    table, fetch = _read_connection(conn)
    events = await fetch(
        f"SELECT * FROM {table('order_events')} WHERE order_id = :o "
        "AND to_state = 'confirmed' AND from_state != 'confirmed' LIMIT 129",
        {"o": order["id"]},
    )
    if len(events) > 128:
        return None
    if isinstance(conn, DomainTransaction):
        now = await conn.now()
    else:
        expression = ("CAST(strftime('%s', 'now') AS INTEGER)" if dialect() == "sqlite"
                      else "FLOOR(EXTRACT(EPOCH FROM clock_timestamp()))")
        now = int((await fetch(f"SELECT {expression} AS epoch", {}))[0]["epoch"])
    nodes, parents = {}, {}
    try:
        for row in events:
            event = dict(row)
            if (not re.fullmatch(r"[0-9a-f]{32}", event["id"])
                    or type(event["created_at"]) is not int
                    or not 0 <= event["created_at"] <= now):
                return None
            raw = event["detail_json"]
            if raw is not None and (not isinstance(raw, str) or len(raw) > 32_768):
                return None
            detail = json.loads(raw) if raw else {}
            if not isinstance(detail, dict):
                return None
            if event["actor"] == "system" and event["from_state"] == "awaiting_payment":
                parent = None
            elif event["actor"] == "merchant" and event["from_state"] in ("expired", "cancelled"):
                proof = detail.get("inventory_accounting")
                if (not isinstance(proof, dict) or type(proof.get("version")) is not int
                        or proof["version"] != 1 or "parent_confirmation_id" not in proof):
                    return None
                parent = proof["parent_confirmation_id"]
                if parent is not None and (not isinstance(parent, str)
                                          or not re.fullmatch(r"[0-9a-f]{32}", parent)):
                    return None
            else:
                return None
            event["detail"] = detail
            nodes[event["id"]] = event
            parents[event["id"]] = parent
        roots = [key for key, parent in parents.items() if parent is None]
        if not events:
            return []
        if len(roots) != 1:
            return None
        chain, visited = [], set()
        key = roots[0]
        while key is not None:
            if key in visited:
                return None
            visited.add(key)
            chain.append(nodes[key])
            children = [child for child, parent in parents.items() if parent == key]
            if len(children) > 1:
                return None
            key = children[0] if children else None
        if len(visited) != len(nodes):
            return None
        return chain
    except (ValueError, TypeError, KeyError):
        return None


async def accepted_inventory_accounting(conn, order: dict, by_id: dict, consumed: dict):
    chain = await confirmation_chain(conn, order)
    if not chain or chain[-1]["actor"] != "merchant":
        return None
    event = chain[-1]
    try:
        detail = json.loads(event["detail_json"])
        proof = detail.get("inventory_accounting")
        if (
            not isinstance(proof, dict)
            or type(proof.get("version")) is not int
            or proof["version"] != 1
        ):
            return None
        entries = proof.get("items")
        if not isinstance(entries, list) or len(entries) != len(by_id):
            return None
        proof_consumed = {}
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                return None
            item_id = entry.get("item_id")
            if not isinstance(item_id, str) or item_id not in by_id or item_id in seen:
                return None
            seen.add(item_id)
            item = by_id[item_id]
            if entry.get("product_id") != item["product_id"]:
                return None
            values = [
                entry.get(key)
                for key in (
                    "quantity",
                    "consumed_qty",
                    "accepted_allocated_qty",
                    "backordered_qty",
                )
            ]
            if any(type(value) is not int or value < 0 for value in values):
                return None
            quantity, used, allocated, shortfall = values
            if (
                quantity != item["quantity"]
                or used + allocated + shortfall != quantity
                or shortfall != item["backordered_qty"]
            ):
                return None
            product_id = item["product_id"]
            proof_consumed[product_id] = proof_consumed.get(product_id, 0) + used
        if {key: value for key, value in proof_consumed.items() if value} != consumed:
            return None
        accounting = {entry["item_id"]: entry for entry in entries}
        for predecessor in chain[:-1]:
            if predecessor["actor"] != "merchant":
                if any(entry["accepted_allocated_qty"] or entry["backordered_qty"]
                       for entry in entries):
                    return None
                continue
            previous = predecessor["detail"]["inventory_accounting"].get("items")
            if not isinstance(previous, list) or len(previous) != len(entries):
                return None
            seen_previous = set()
            for entry in previous:
                if not isinstance(entry, dict):
                    return None
                item_id = entry.get("item_id")
                if (not isinstance(item_id, str) or item_id not in by_id
                        or item_id in seen_previous):
                    return None
                seen_previous.add(item_id)
                values = [entry.get(key) for key in (
                    "quantity", "consumed_qty", "accepted_allocated_qty", "backordered_qty",
                )]
                if any(type(value) is not int or value < 0 for value in values):
                    return None
                quantity, used, allocated, shortfall = values
                if (entry.get("product_id") != by_id[item_id]["product_id"]
                        or quantity != by_id[item_id]["quantity"]
                        or used + allocated + shortfall != quantity
                        or shortfall != by_id[item_id]["backordered_qty"]):
                    return None
            if {entry["item_id"]: entry for entry in previous} != accounting:
                return None
        return {"items": accounting, "event_id": event["id"],
                "created_at": event["created_at"]}
    except (ValueError, TypeError, AttributeError):
        return None


async def fulfillment_authorized(conn, order: dict) -> bool:
    table, fetch = _read_connection(conn)
    rows = await fetch(
        f"SELECT * FROM {table('orders')} WHERE id = :o AND merchant_id = :m",
        {"o": order["id"], "m": order["merchant_id"]},
    )
    if len(rows) != 1:
        return False
    current = dict(rows[0])
    blocked_digital = await fetch(
        f"SELECT oi.id FROM {table('order_items')} oi "
        f"JOIN {table('products')} p ON p.id = oi.product_id "
        "WHERE oi.order_id = :o AND p.format = 'digital' "
        "AND (oi.backordered_qty != 0 OR :oversold)",
        {"o": current["id"], "oversold": bool(current["oversold"])},
    )
    return (
        not blocked_digital
        and current["state"] in DELIVERY_STATES
        and not current["payment_exception"]
        and current["payment_exception_resolution"] in (None, "unresolved", "accepted")
        and await payment_settled(conn, current)
        and await inventory_accounted(conn, current)
    )


async def payable_invoice(conn, order: dict) -> dict | None:
    from .settlement import _payment_snapshot

    if not isinstance(conn, DomainTransaction):
        async with DomainTransaction() as tx:
            return await payable_invoice(tx, order)
    current = await conn.fetch_one(
        f"SELECT * FROM {conn.table('orders')} WHERE id = :o AND merchant_id = :m"
        + conn.for_update, {"o": order["id"], "m": order["merchant_id"]},
    )
    if not current:
        return None
    order.update(dict(current))
    if (order["state"] != "awaiting_payment" or order["payment_exception"]
            or order["payment_exception_resolution"] not in (None, "unresolved")):
        return None
    payments = await conn.fetch_all(
        f"SELECT * FROM {conn.table('payments')} WHERE order_id = :o LIMIT 2",
        {"o": order["id"]},
    )
    if len(payments) != 1 or payments[0]["status"] != "pending":
        return None
    coverage = await reservation_coverage(conn, order, await conn.now())
    if not coverage["complete"]:
        return None
    snapshot = _payment_snapshot(order, dict(payments[0]))
    if snapshot is None:
        return None
    now = await conn.now()
    if snapshot["expiry"] <= now or any(row["expires_at"] <= now for row in coverage["held"]):
        return None
    return {**snapshot, "now": now,
            "allocation_deadline": min(row["expires_at"] for row in coverage["held"])}


async def digital_delivery(conn, order: dict) -> list[dict]:
    """Buyer-facing delivery content for the order's digital items —
    ``[]`` until :func:`delivery_unlocked`. ``conn`` is any connection or
    transaction exposing ``fetchall``/``fetch_all``."""
    if not isinstance(conn, DomainTransaction):
        async with DomainTransaction() as tx:
            return await digital_delivery(tx, order)
    current = await conn.fetch_one(
        f"SELECT * FROM {conn.table('orders')} WHERE id = :o AND merchant_id = :m"
        + conn.for_update,
        {"o": order["id"], "m": order["merchant_id"]},
    )
    if not current:
        return []
    order.update(dict(current))
    if not delivery_unlocked(order) or not await fulfillment_authorized(conn, order):
        return []
    from ..db import table as default_table
    from .catalog import decrypt_delivery

    table = conn.table if isinstance(conn, DomainTransaction) else default_table
    sql = (
        f"SELECT oi.title, p.id AS product_id, p.delivery_enc"
        f" FROM {table('order_items')} oi"
        f" JOIN {table('products')} p ON p.id = oi.product_id"
        " WHERE oi.order_id = :o AND p.format = 'digital'"
        " AND p.delivery_enc IS NOT NULL ORDER BY oi.title"
    )
    fetch = getattr(conn, "fetchall", None) or conn.fetch_all
    rows = await fetch(sql, {"o": order["id"]})
    return [
        {"title": r["title"], "content": decrypt_delivery(r["product_id"], r["delivery_enc"])}
        for r in rows
    ]


# --- transition_order (section 7.1 single entry path) ------------------------


async def transition_order(
    tx: DomainTransaction,
    *,
    order_id: str,
    to_state: str,
    from_state: str | None = None,
    actor: str = "system",
    reason: str | None = None,
    detail: dict | None = None,
    now: int | None = None,
) -> str:
    """Transition one order through the section 7.1 machine.

    Runs inside the caller's open domain transaction. Raises
    ``IllegalTransition`` for a transition outside the table (or a missing
    required reason) and ``TransitionConflict`` when the CAS loses.
    Returns the effective from-state.
    """
    now = _now() if now is None else now
    orders = tx.table("orders")

    if from_state is None:
        row = await tx.fetch_one(
            f"SELECT state FROM {orders} WHERE id = :i", {"i": order_id}
        )
        if not row:
            raise TransitionConflict(f"order {order_id!r} does not exist")
        from_state = row["state"]

    if to_state not in ORDER_TRANSITIONS.get(from_state, frozenset()):
        raise IllegalTransition(
            f"illegal order transition {from_state!r} -> {to_state!r}"
        )
    if (from_state, to_state) in REASON_REQUIRED_TRANSITIONS and not reason:
        raise IllegalTransition(
            f"transition {from_state!r} -> {to_state!r} requires a reason"
        )

    rc = await tx.execute(
        f"UPDATE {orders} SET state = :to WHERE id = :i AND state = :f",
        {"to": to_state, "i": order_id, "f": from_state},
    )
    if rc != 1:
        raise TransitionConflict(
            f"order CAS lost for {order_id!r}"
            f" (expected {from_state!r}, target {to_state!r})"
        )
    await tx.execute(
        f"UPDATE {orders} SET updated_at = :n, archived_at = NULL WHERE id = :i",
        {"n": now, "i": order_id},
    )
    payload: dict = {}
    if reason is not None:
        payload["reason"] = reason
    if detail:
        payload.update(detail)
    await tx.execute(
        f"INSERT INTO {tx.table('order_events')} "
        "(id, order_id, from_state, to_state, actor, detail_json, created_at)"
        " VALUES (:i, :o, :f, :t, :a, :d, :n)",
        {
            "i": uuid.uuid4().hex,
            "o": order_id,
            "f": from_state,
            "t": to_state,
            "a": actor,
            "d": json.dumps(payload) if payload else None,
            "n": now,
        },
    )
    # GAM-03 §6.9: buyer-keyed (gamma) orders emit the matching type-3
    # order_msg inside the SAME transaction — a crash before the intent
    # lands makes the transition atomically absent too. Web orders have
    # buyer_pubkey_hash NULL -> no-op.
    order_row = await tx.fetch_one(
        f"SELECT * FROM {orders} WHERE id = :i", {"i": order_id}
    )
    if order_row and order_row["buyer_pubkey_hash"]:
        from . import order_messages

        await order_messages.enqueue_status(
            tx, dict(order_row), to_state, reason=reason,
        )
    return from_state


# --- shared helpers -------------------------------------------------------


async def get_order(order_id: str, merchant_id: str | None = None) -> dict:
    """Fetch one order (merchant-scoped when merchant_id is given)."""
    from ..db import db, table

    async with db.connect() as conn:
        if merchant_id is None:
            row = await conn.fetchone(
                f"SELECT * FROM {table('orders')} WHERE id = :i",
                {"i": order_id},
            )
        else:
            row = await conn.fetchone(
                f"SELECT * FROM {table('orders')} "
                "WHERE id = :i AND merchant_id = :m",
                {"i": order_id, "m": merchant_id},
            )
    if not row:
        raise not_found("order not found")
    return dict(row)


async def resolve_creation_uncertainty(tx: DomainTransaction, order: dict, now: int) -> bool:
    if (order["state"] not in ("invoice_pending", "awaiting_payment")
            or not order["payment_exception"]
            or order["payment_exception_reason"] != "invoice-creation-unknown"
            or order["payment_exception_resolution"] not in (None, "unresolved")):
        return False
    changed = await tx.execute(
        f"UPDATE {tx.table('orders')} SET payment_exception = FALSE, "
        "payment_exception_reason = NULL, payment_exception_resolution = NULL, updated_at = :n "
        "WHERE id = :i AND state IN ('invoice_pending', 'awaiting_payment') "
        "AND payment_exception = TRUE AND payment_exception_reason = 'invoice-creation-unknown' "
        "AND (payment_exception_resolution IS NULL OR payment_exception_resolution = 'unresolved')",
        {"i": order["id"], "n": now},
    )
    return changed == 1


async def lock_inventory_products(
    tx: DomainTransaction, merchant_id: str, product_ids,
) -> dict[str, dict]:
    leaves = {}
    ids = set(product_ids)
    for product_id in sorted(ids):
        row = await tx.fetch_one(
            f"SELECT * FROM {tx.table('products')} WHERE id = :p",
            {"p": product_id},
        )
        if not row or row["merchant_id"] != merchant_id:
            raise TransitionConflict("Inventory product provenance requires review")
        leaves[product_id] = dict(row)
    ids.update(row["parent_product_id"] for row in leaves.values() if row["parent_product_id"])
    locked = {}
    for product_id in sorted(ids):
        row = await tx.fetch_one(
            f"SELECT * FROM {tx.table('products')} WHERE id = :p" + tx.for_update,
            {"p": product_id},
        )
        if not row or row["merchant_id"] != merchant_id:
            raise TransitionConflict("Inventory parent provenance requires review")
        locked[product_id] = dict(row)
    if any(locked[key]["parent_product_id"] != row["parent_product_id"]
           for key, row in leaves.items()):
        raise TransitionConflict("Inventory parent changed during locking")
    return locked


async def inventory_items(conn, order: dict) -> tuple[list[dict], dict[str, int]]:
    table, fetch = _read_connection(conn)
    rows = await fetch(
        f"SELECT oi.*, p.merchant_id AS product_merchant_id "
        f"FROM {table('order_items')} oi LEFT JOIN {table('products')} p "
        "ON p.id = oi.product_id WHERE oi.order_id = :o ORDER BY oi.id LIMIT 65",
        {"o": order["id"]},
    )
    expected = {}
    seen = set()
    if not rows or len(rows) > 64:
        raise TransitionConflict("Inventory item map requires review")
    for row in rows:
        if (not row["id"] or row["id"] in seen or not row["product_id"]
                or row["product_merchant_id"] != order["merchant_id"]
                or type(row["quantity"]) is not int or not 1 <= row["quantity"] <= 10_000
                or type(row["backordered_qty"]) is not int
                or not 0 <= row["backordered_qty"] <= row["quantity"]):
            raise TransitionConflict("Inventory item map requires review")
        seen.add(row["id"])
        expected[row["product_id"]] = expected.get(row["product_id"], 0) + row["quantity"]
    return [dict(row) for row in rows], expected


async def inventory_counters_coherent(tx: DomainTransaction, products: dict) -> bool:
    for product_id, product in products.items():
        rows = await tx.fetch_all(
            f"SELECT quantity FROM {tx.table('inventory_reservations')} "
            "WHERE product_id = :p AND state = 'held' LIMIT 101",
            {"p": product_id},
        )
        if len(rows) > 100:
            return False
        if any(type(row["quantity"]) is not int or row["quantity"] <= 0 for row in rows):
            return False
        reserved, stock = product["stock_reserved"], product["stock_on_hand"]
        if (type(reserved) is not int or reserved != sum(row["quantity"] for row in rows)
                or reserved < 0 or (stock is not None and
                (type(stock) is not int or stock < reserved))):
            return False
    return True


async def reservation_coverage(tx: DomainTransaction, order: dict, now: int) -> dict:
    rows = await tx.fetch_all(
        f"SELECT * FROM {tx.table('inventory_reservations')} WHERE order_id = :o LIMIT 65",
        {"o": order["id"]},
    )
    if len(rows) > 64:
        return {"complete": False, "releasable": False, "held": [], "now": await tx.now()}
    held = [dict(row) for row in rows if row["state"] == "held"]
    try:
        items, expected = await inventory_items(tx, order)
        products = await lock_inventory_products(
            tx, order["merchant_id"], set(expected) | {row["product_id"] for row in held},
        )
    except TransitionConflict:
        return {"complete": False, "releasable": False, "held": held, "now": await tx.now()}
    coherent = await inventory_counters_coherent(tx, products)
    now = await tx.now()
    quantities = {}
    valid = len(held) == len(rows) and all(item["backordered_qty"] == 0 for item in items)
    for row in held:
        product_id, quantity = row["product_id"], row["quantity"]
        if (product_id in quantities or type(quantity) is not int or quantity <= 0
                or type(row["expires_at"]) is not int or row["expires_at"] <= now):
            valid = False
        quantities[product_id] = quantity
    return {"complete": valid and coherent and quantities == expected,
            "releasable": coherent, "held": held, "products": products, "expected": expected,
            "now": now}


async def consume_reservations(tx: DomainTransaction, held: list[dict], now: int) -> int:
    from .catalog import enqueue_stock_projection

    for row in held:
        rc = await tx.execute(
            f"UPDATE {tx.table('inventory_reservations')} SET state = 'consumed', updated_at = :n "
            "WHERE id = :i AND state = 'held'", {"n": now, "i": row["id"]},
        )
        if rc != 1:
            raise TransitionConflict("Reservation consumption conflict")
        await tx.execute(
            f"UPDATE {tx.table('products')} SET stock_on_hand = stock_on_hand - :q, "
            "stock_reserved = stock_reserved - :q, revision = revision + 1, updated_at = :n "
            "WHERE id = :p", {"q": row["quantity"], "n": now, "p": row["product_id"]},
        )
        # Stock/state republication for each affected product (§8.3 step 5).
        await enqueue_stock_projection(tx, row["product_id"])
    return sum(row["quantity"] for row in held)


async def release_reservations(
    tx: DomainTransaction, *, order_id: str, to_state: str, now: int
) -> int:
    """Release held reservations exactly once, decrementing stock_reserved.

    Only rows still in state ``held`` flip; the stock decrement is bound to
    that flip in the same transaction, so a second pass is a no-op.
    """
    released = 0
    order = await _order_row(tx, order_id)
    held = await tx.fetch_all(
        f"SELECT id, product_id, quantity FROM"
        f" {tx.table('inventory_reservations')}"
        " WHERE order_id = :o AND state = 'held' LIMIT 65",
        {"o": order_id},
    )
    if len(held) > 64:
        raise TransitionConflict("Reservation cardinality requires review before release")
    if held:
        products = await lock_inventory_products(
            tx, order["merchant_id"], {row["product_id"] for row in held},
        )
        if not await inventory_counters_coherent(tx, products):
            raise TransitionConflict("Inventory counters require review before release")
    for row in held:
        rc = await tx.execute(
            f"UPDATE {tx.table('inventory_reservations')}"
            " SET state = :s, updated_at = :n"
            " WHERE id = :i AND state = 'held'",
            {"s": to_state, "n": now, "i": row["id"]},
        )
        if rc != 1:
            raise TransitionConflict(
                f"reservation CAS lost for {row['id']}"
            )
        await tx.execute(
            f"UPDATE {tx.table('products')}"
            " SET stock_reserved = stock_reserved - :q, updated_at = :n,"
            " revision = revision + 1 WHERE id = :p",
            {"q": row["quantity"], "n": now, "p": row["product_id"]},
        )
        from .catalog import enqueue_stock_projection

        await enqueue_stock_projection(tx, row["product_id"])
        released += row["quantity"]
    return released


# --- section 8.8 email intents (shared by every mutation path) --------------

#: Which notify_events keys gate merchant-channel rows (merchant config).
_MERCHANT_EVENT_KEYS = {
    "order_received": "order_received",
    "confirmed": "confirmed",
    "processing": "processing",
    "shipped": "shipped",
    "delivered": "delivered",
    "cancelled": "cancelled",
    "expired": "expired",
    "on_hold": "on_hold",
    "refund_requested": "refund_requested",
}

#: Customer sends are strictly opt-in per order (orders.email_opt_in) AND
#: transactional-only — order_received is never sent to the customer
#: (placed + paid arrive as one combined ``confirmed`` email, §8.8).
_CUSTOMER_EVENTS = frozenset(set(EMAIL_EVENT_TYPES) - {"order_received"})


async def enqueue_email_intents(
    tx: DomainTransaction,
    *,
    order: dict,
    event_type: str,
    merchant_notify_emails: list[str],
    merchant_notify_events: dict,
    customer_email: str | None,
    now: int | None = None,
) -> int:
    """Enqueue §8.8 per-recipient rows for one order event, in-tx.

    Merchant rows: one per configured notify_emails address, gated by the
    merchant's notify_events flags (default ON when unconfigured). Customer
    row: only when the order's email_opt_in is true, an address exists, and
    the event is a customer-facing type. ``UNIQUE(order_id, channel,
    event_type, recipient_hash)`` dedupes via ON CONFLICT DO NOTHING.
    Returns the number of rows inserted.
    """
    from ..crypto import encrypt, hmac_index, normalize
    from ..settings import ext_settings

    if event_type not in EMAIL_EVENT_TYPES:
        raise unprocessable(
            "invalid-transition", f"unknown email event {event_type!r}"
        )
    now = _now() if now is None else now
    settings = ext_settings()
    key = settings.master_keys[settings.active_key_version]
    ver = settings.active_key_version
    inserted = 0

    async def _insert(recipient: str, channel: str) -> bool:
        enc = encrypt(
            recipient.encode(), key,
            record_id=order["id"], table="email_queue",
            column="recipient_enc", key_version=ver,
        )
        digest = hmac_index(
            settings.privacy_key, "email-recipient",
            order["merchant_id"], normalize(recipient),
        )
        rc = await tx.execute(
            f"INSERT INTO {tx.table('email_queue')} "
            "(id, merchant_id, order_id, channel, event_type,"
            " recipient_enc, recipient_hash, state, attempts,"
            " next_attempt_at, claim_token, created_at) "
            "VALUES (:i, :m, :o, :c, :e, :re, :rh, 'pending', 0, :n,"
            " 0, :n) ON CONFLICT DO NOTHING",
            {
                "i": uuid.uuid4().hex,
                "m": order["merchant_id"],
                "o": order["id"],
                "c": channel,
                "e": event_type,
                "re": enc,
                "rh": digest,
                "n": now,
            },
        )
        return rc == 1

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
        if await _insert(customer_email, "customer"):
            inserted += 1

    return inserted


# --- section 8.1 step 4 cancellation (shared by admin + settlement paths) ----


async def cancel_order(
    *,
    order_id: str,
    actor: str,
    reason: str | None,
    merchant_context: dict | None = None,
) -> dict:
    """Cancellation releases held stock exactly once (§7.1/§8.2 step 4).

    All cancels in Release A are merchant-initiated (there is no public
    cancel route); §7.1 legality governs — confirmed->cancelled requires a
    reason, terminal states reject. An already-cancelled order is a no-op
    that releases nothing.
    """
    now = _now()
    async with DomainTransaction() as tx:
        order = await _order_row(tx, order_id)
        return await _cancel_order_in_tx(
            tx, order, actor=actor, reason=reason,
            merchant_context=merchant_context, now=now,
        )


async def _cancel_order_in_tx(
    tx: DomainTransaction, order: dict, *, actor: str, reason: str | None,
    merchant_context: dict | None, now: int,
) -> dict:
    order_id = order["id"]
    if order["state"] == "cancelled":
        return {"order_id": order_id, "action": "no-op-already-cancelled"}
    if actor == "buyer" and (
        order["state"] not in BUYER_CANCELLABLE_STATES or await payment_settled(tx, order)
    ):
        raise IllegalTransition("Buyer cancellation is only permitted before verified payment")
    reason = reason.strip() if reason is not None else None
    if reason and len(reason) > 500:
        raise IllegalTransition("Cancellation reason exceeds 500 characters")
    if actor == "merchant" and (
        order["state"] in DELIVERY_STATES or await payment_settled(tx, order)
    ) and not reason:
        raise IllegalTransition(
            "Paid cancellation requires an explicit reason via /cancel; it does not refund money"
        )
    await transition_order(
        tx, order_id=order_id, from_state=order["state"],
        to_state="cancelled", actor=actor, reason=reason, now=now,
    )
    released = await release_reservations(
        tx, order_id=order_id, to_state="released", now=now,
    )
    if merchant_context is not None:
        await enqueue_email_intents(
            tx, order=order, event_type="cancelled",
            merchant_notify_emails=merchant_context["notify_emails"],
            merchant_notify_events=merchant_context["notify_events"],
            customer_email=merchant_context.get("customer_email"), now=now,
        )
    return {"order_id": order_id, "action": "cancelled", "released": released}


async def _order_row(tx: DomainTransaction, order_id: str) -> dict:
    row = await tx.fetch_one(
        f"SELECT * FROM {tx.table('orders')} WHERE id = :i" + tx.for_update, {"i": order_id}
    )
    if not row:
        raise not_found("order not found")
    return dict(row)


# --- section 5.3 admin order actions -------------------------------------------

_MERCHANT_NOTIFY_SQL = (
    "SELECT notify_emails, notify_events FROM {m} WHERE id = :mid"
)


async def _merchant_notify(merchant_id: str) -> tuple[list[str], dict]:
    from ..db import db, table

    async with db.connect() as conn:
        row = await conn.fetchone(
            _MERCHANT_NOTIFY_SQL.format(m=table("merchants")),
            {"mid": merchant_id},
        )
    emails = json.loads(row["notify_emails"]) if (
        row and row["notify_emails"]
    ) else []
    events = json.loads(row["notify_events"]) if (
        row and row["notify_events"]
    ) else {}
    return emails, events


async def _customer_email(order: dict) -> str | None:
    from .. import crypto
    from ..settings import ext_settings

    if not order.get("contact_enc"):
        return None
    settings = ext_settings()
    try:
        ver = crypto.envelope_version(order["contact_enc"])
        contact = json.loads(
            crypto.decrypt(
                order["contact_enc"], settings.master_keys[ver],
                record_id=order["id"], table="orders",
                column="contact_enc", key_version=ver,
            )
        )
        return contact.get("email")
    except Exception:
        return None


async def _notify_ctx(order: dict) -> dict:
    emails, events = await _merchant_notify(order["merchant_id"])
    return {
        "notify_emails": emails,
        "notify_events": events,
        "customer_email": await _customer_email(order),
    }


async def list_orders(
    merchant_id: str, user, *, state: str | None = None,
    protocol: str | None = None, q: str | None = None,
    archived: bool = False,
) -> list[dict]:
    from . import merchant as merchant_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    from ..db import db, table

    clauses = ["o.merchant_id = :m"]
    clauses.append(
        "o.archived_at IS NOT NULL"
        if archived
        else "(o.archived_at IS NULL OR o.payment_exception OR o.oversold)"
    )
    params: dict = {"m": merchant_id}
    if state:
        # The UI-SPEC filter set adds "needs_attention" (payment exception
        # or oversold) on top of the §7.1 states.
        if state == "needs_attention":
            clauses.append("(o.payment_exception OR o.oversold)")
        elif state not in ORDER_STATES:
            raise unprocessable("invalid-transition", "Unknown state")
        else:
            clauses.append("o.state = :s")
            params["s"] = state
    if protocol:
        if protocol not in ("web", "gamma", "nip15"):
            raise unprocessable("invalid-transition", "Unknown protocol")
        clauses.append("o.protocol = :p")
        params["p"] = protocol
    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT o.id, o.protocol, o.state, o.shipping_state, o.total_sat,"
            " o.payment_exception, o.oversold, o.email_opt_in, o.archived_at,"
            " o.created_at, o.updated_at, o.contact_enc, CASE WHEN"
            " o.state IN ('completed', 'rejected', 'expired', 'cancelled')"
            " AND NOT o.payment_exception AND NOT o.oversold"
            f" AND NOT EXISTS (SELECT 1 FROM {table('inventory_reservations')} r"
            " WHERE r.order_id = o.id AND r.state = 'held')"
            f" AND NOT EXISTS (SELECT 1 FROM {table('payments')} p"
            " WHERE p.order_id = o.id"
            " AND p.status IN ('creating', 'creation_unknown', 'pending'))"
            " THEN TRUE ELSE FALSE END AS archive_eligible FROM "
            f"{table('orders')} o WHERE {' AND '.join(clauses)}"
            " ORDER BY o.created_at DESC LIMIT 200",
            params,
        )
        order_ids = [r["id"] for r in rows]
        item_rows: dict[str, list] = {}
        if order_ids:
            marks = ",".join(f"'{i}'" for i in order_ids)
            for it in await conn.fetchall(
                f"SELECT order_id, title, quantity FROM"
                f" {table('order_items')} WHERE order_id IN ({marks})"
                " ORDER BY id"
            ):
                item_rows.setdefault(it["order_id"], []).append(dict(it))
    out = []
    for r in rows:
        row = dict(r)
        items = item_rows.get(row["id"], [])
        row["item_count"] = len(items)
        row["first_item"] = items[0]["title"] if items else None
        row["first_item_qty"] = items[0]["quantity"] if items else None
        row["payment_exception"] = bool(row["payment_exception"])
        row["oversold"] = bool(row["oversold"])
        row["archive_eligible"] = bool(row["archive_eligible"])
        row["buyer"] = _buyer_handle(row)
        row.pop("contact_enc", None)
        out.append(row)
    if q:
        # "Search order or buyer": id-prefix OR decrypted-handle substring —
        # contact_enc can't match in SQL, so the buyer arm filters here.
        needle = q.strip().lower()
        out = [
            r for r in out
            if r["id"].lower().startswith(needle)
            or (r["buyer"] or "").lower().find(needle) >= 0
        ]
    return out


def _buyer_handle(order: dict) -> str | None:
    """List-row buyer handle (UI-SPEC §B1): web orders show the supplied
    email; protocol orders show the buyer npub — decrypted owner-side."""
    enc = order.get("contact_enc")
    if enc is None:
        return None
    from .. import crypto
    from ..settings import ext_settings

    settings = ext_settings()
    try:
        ver = crypto.envelope_version(enc)
        raw = crypto.decrypt(
            enc, settings.master_keys[ver],
            record_id=order["id"], table="orders", column="contact_enc",
            key_version=ver,
        ).decode()
        contact = json.loads(raw)
    except Exception:
        return None
    return contact.get("email") or contact.get("npub")


async def order_detail(merchant_id: str, user, order_id: str) -> dict:
    """Full detail — decrypted contact/address for the OWNER only."""
    from .. import crypto
    from ..settings import ext_settings
    from . import merchant as merchant_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    order = await get_order(order_id, merchant_id)
    settings = ext_settings()

    def _dec(envelope: bytes | None, column: str) -> str | None:
        if envelope is None:
            return None
        try:
            ver = crypto.envelope_version(envelope)
            return crypto.decrypt(
                envelope, settings.master_keys[ver],
                record_id=order_id, table="orders", column=column,
                key_version=ver,
            ).decode()
        except Exception:
            return None

    async with DomainTransaction() as tx:
        order = await _order_row(tx, order_id)
        if order["merchant_id"] != merchant_id:
            raise not_found("order not found")
        authorized = await fulfillment_authorized(tx, order)
        items = await tx.fetch_all(
            f"SELECT product_id, product_d, title, quantity,"
            " unit_price_minor, currency, line_total_sat, backordered_qty"
            f" FROM {tx.table('order_items')} WHERE order_id = :o",
            {"o": order_id},
        )
        payment = await tx.fetch_one(
            f"SELECT status, amount_sat, settled_at, created_at"
            f" FROM {tx.table('payments')} WHERE order_id = :o",
            {"o": order_id},
        )
        fulfil = await tx.fetch_one(
            f"SELECT tracking_enc, carrier, eta, updated_at"
            f" FROM {tx.table('order_fulfillment')} WHERE order_id = :o",
            {"o": order_id},
        )
    tracking = None
    if fulfil and fulfil["tracking_enc"] is not None:
        try:
            ver = crypto.envelope_version(fulfil["tracking_enc"])
            tracking = crypto.decrypt(
                fulfil["tracking_enc"], settings.master_keys[ver],
                record_id=order_id, table="order_fulfillment",
                column="tracking_enc", key_version=ver,
            ).decode()
        except Exception:
            tracking = None
    contact = _dec(order.get("contact_enc"), "contact_enc")
    address = _dec(order.get("address_enc"), "address_enc")
    return {
        "id": order["id"],
        "protocol": order["protocol"],
        "state": order["state"],
        "shipping_state": order["shipping_state"],
        "currency": order["currency"],
        "subtotal_sat": order["subtotal_sat"],
        "shipping_sat": order["shipping_sat"],
        "total_sat": order["total_sat"],
        "buyer_amount_sat": order["buyer_amount_sat"],
        "payment_exception": bool(order["payment_exception"]),
        "payment_exception_reason": order["payment_exception_reason"],
        "payment_exception_resolution": (
            order["payment_exception_resolution"]
        ),
        "oversold": bool(order["oversold"]),
        "email_opt_in": bool(order["email_opt_in"]),
        "invoice_expiry": order["invoice_expiry"],
        "shipping_option_id": order["shipping_option_id"],
        "contact": json.loads(contact) if contact else None,
        "address": json.loads(address) if address else None,
        "items": [dict(i) for i in items],
        "payment": dict(payment) if payment else None,
        "fulfillment_authorized": authorized,
        "fulfillment": (
            {"tracking": tracking, "carrier": fulfil["carrier"],
             "eta": fulfil["eta"], "updated_at": fulfil["updated_at"]}
            if fulfil else None
        ),
        "archived_at": order["archived_at"],
        "created_at": order["created_at"],
        "updated_at": order["updated_at"],
    }


async def admin_bulk_archive(
    merchant_id: str,
    user,
    order_ids: list[str],
    action: str,
) -> dict:
    from . import merchant as merchant_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    ids = list(dict.fromkeys(order_ids))
    if not 1 <= len(ids) <= 100 or any(
        not isinstance(order_id, str)
        or not re.fullmatch(r"[0-9a-f]{32}", order_id)
        for order_id in ids
    ):
        raise unprocessable(
            "invalid-content", "order_ids must contain 1 to 100 order IDs"
        )
    if action not in {"archive", "restore"}:
        raise unprocessable("invalid-content", "unsupported order bulk action")

    async with DomainTransaction() as tx:
        placeholders = ", ".join(f":o{i}" for i in range(len(ids)))
        params = {f"o{i}": order_id for i, order_id in enumerate(ids)}
        params["m"] = merchant_id
        rows = await tx.fetch_all(
            f"SELECT id, state, payment_exception, oversold, archived_at "
            f"FROM {tx.table('orders')} WHERE merchant_id = :m "
            f"AND id IN ({placeholders}){tx.for_update}",
            params,
        )
        if len(rows) != len(ids):
            raise not_found("one or more orders not found")

        if action == "archive":
            if any(
                row["state"] not in ORDER_ARCHIVABLE_STATES
                or bool(row["payment_exception"])
                or bool(row["oversold"])
                for row in rows
            ):
                raise unprocessable(
                    "invalid-transition",
                    "Orders cannot be archived",
                    "Only closed orders without exceptions can be archived",
                )
            held = await tx.fetch_one(
                f"SELECT COUNT(*) AS n FROM {tx.table('inventory_reservations')} "
                f"WHERE state = 'held' AND order_id IN ({placeholders})",
                params,
            )
            pending = await tx.fetch_one(
                f"SELECT COUNT(*) AS n FROM {tx.table('payments')} "
                f"WHERE status IN ('creating', 'creation_unknown', 'pending') "
                f"AND order_id IN ({placeholders})",
                params,
            )
            if held["n"] or pending["n"]:
                raise unprocessable(
                    "invalid-transition",
                    "Orders cannot be archived",
                    "Resolve pending payment or inventory work before archiving",
                )
            now = await tx.now()
            updated = await tx.execute(
                f"UPDATE {tx.table('orders')} SET archived_at = :n "
                f"WHERE archived_at IS NULL AND id IN ({placeholders})",
                {**params, "n": now},
            )
            return {"archived": updated, "order_ids": ids}

        updated = await tx.execute(
            f"UPDATE {tx.table('orders')} SET archived_at = NULL "
            f"WHERE archived_at IS NOT NULL AND id IN ({placeholders})",
            params,
        )
        return {"restored": updated, "order_ids": ids}


async def admin_set_status(
    merchant_id: str, user, order_id: str, to_state: str,
) -> dict:
    """§5.3 status transition — §7.1 legality only; illegal ->
    ``invalid-transition``."""
    from . import merchant as merchant_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    now = _now()
    async with DomainTransaction() as tx:
        order = await _order_row(tx, order_id)
        if order["merchant_id"] != merchant_id:
            raise not_found("order not found")
        if to_state != "cancelled" and (
            (order["state"], to_state) not in (
                ("confirmed", "processing"), ("processing", "completed")
            )
            or not await fulfillment_authorized(tx, order)
        ):
            raise unprocessable("invalid-transition", "Fulfillment is not authorized")
        try:
            if to_state == "cancelled":
                await _cancel_order_in_tx(
                    tx, order, actor="merchant", reason=None,
                    merchant_context=await _notify_ctx(order), now=now,
                )
                return {"id": order_id, "state": to_state}
            await transition_order(
                tx, order_id=order_id, from_state=order["state"],
                to_state=to_state, actor="merchant", now=now,
            )
        except IllegalTransition as exc:
            raise unprocessable(
                "invalid-transition", "Invalid transition", str(exc)
            ) from exc
        event = _STATE_EMAIL_EVENTS.get(to_state)
        if event:
            ctx = await _notify_ctx(order)
            await enqueue_email_intents(
                tx, order=order, event_type=event,
                merchant_notify_emails=ctx["notify_emails"],
                merchant_notify_events=ctx["notify_events"],
                customer_email=ctx["customer_email"], now=now,
            )
        return {"id": order_id, "state": to_state}


async def admin_set_shipping(
    merchant_id: str, user, order_id: str, *, shipping_state: str,
    tracking: str | None = None, carrier: str | None = None,
    eta: str | None = None,
) -> dict:
    """§5.3 shipping update — §7.2 transition; tracking_enc at rest."""
    from .. import crypto
    from ..settings import ext_settings
    from . import merchant as merchant_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    if shipping_state not in SHIPPING_STATES:
        raise unprocessable("invalid-transition", "Unknown shipping state")
    settings = ext_settings()
    now = _now()
    async with DomainTransaction() as tx:
        order = await _order_row(tx, order_id)
        if order["merchant_id"] != merchant_id:
            raise not_found("order not found")
        if not await fulfillment_authorized(tx, order) or order["shipping_state"] == "not_required":
            raise unprocessable("invalid-transition", "Fulfillment is not authorized")
        current = order["shipping_state"]
        if shipping_state not in SHIPPING_TRANSITIONS.get(
            current, frozenset()
        ):
            raise unprocessable(
                "invalid-transition", "Invalid transition",
                f"{current!r} -> {shipping_state!r} is not legal",
            )
        rc = await tx.execute(
            f"UPDATE {tx.table('orders')} SET shipping_state = :s,"
            " updated_at = :n WHERE id = :i AND shipping_state = :c",
            {"s": shipping_state, "n": now, "i": order_id, "c": current},
        )
        if rc != 1:
            raise unprocessable(
                "invalid-transition", "Invalid transition",
                "shipping state changed concurrently",
            )
        tracking_enc = None
        if tracking is not None:
            tracking_enc = crypto.encrypt(
                tracking.encode(),
                settings.master_keys[settings.active_key_version],
                record_id=order_id, table="order_fulfillment",
                column="tracking_enc",
                key_version=settings.active_key_version,
            )
        await tx.execute(
            f"INSERT INTO {tx.table('order_fulfillment')} "
            "(order_id, tracking_enc, carrier, eta, updated_at) "
            "VALUES (:o, :t, :c, :e, :n) "
            "ON CONFLICT (order_id) DO UPDATE SET"
            " tracking_enc = COALESCE(:t, order_fulfillment.tracking_enc),"
            " carrier = COALESCE(:c, order_fulfillment.carrier),"
            " eta = COALESCE(:e, order_fulfillment.eta),"
            " updated_at = :n",
            {"o": order_id, "t": tracking_enc, "c": carrier, "e": eta,
             "n": now},
        )
        event = _STATE_EMAIL_EVENTS.get(shipping_state)
        if event:
            ctx = await _notify_ctx(order)
            await enqueue_email_intents(
                tx, order=order, event_type=event,
                merchant_notify_emails=ctx["notify_emails"],
                merchant_notify_events=ctx["notify_events"],
                customer_email=ctx["customer_email"], now=now,
            )
        # GAM-03 §6.9: gamma shipping transitions emit type-4
        # (processing|shipped|delivered|exception) in the same tx.
        if order["buyer_pubkey_hash"]:
            from . import order_messages

            await order_messages.enqueue_shipping(
                tx, dict(order), shipping_state,
                tracking=tracking, carrier=carrier, eta=eta,
            )
        return {"id": order_id, "shipping_state": shipping_state}


async def admin_cancel(
    merchant_id: str, user, order_id: str, reason: str | None,
) -> dict:
    """§5.3 merchant-initiated cancel (reason required post-confirm)."""
    from . import merchant as merchant_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    order = await get_order(order_id, merchant_id)
    ctx = await _notify_ctx(order)
    try:
        return await cancel_order(
            order_id=order_id, actor="merchant", reason=reason,
            merchant_context=ctx,
        )
    except IllegalTransition as exc:
        raise unprocessable(
            "invalid-transition", "Invalid transition", str(exc)
        ) from exc


async def admin_resolve_exception(
    merchant_id: str, user, order_id: str, *, action: str,
    refund_reference: str | None = None,
) -> dict:
    from . import merchant as merchant_service
    from . import settlement

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    await get_order(order_id, merchant_id)
    return await settlement.resolve_exception(
        order_id=order_id, action=action,
        refund_reference=refund_reference,
    )


async def admin_reissue_token(
    merchant_id: str, user, order_id: str,
) -> dict:
    """§5.3 token reissue — old token revoked immediately (the lookup hash
    is replaced) and the AEAD copy rotated; the new link is returned once."""
    from .. import crypto
    from ..settings import ext_settings
    from . import merchant as merchant_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    settings = ext_settings()
    order = await get_order(order_id, merchant_id)
    if order["protocol"] != "web":
        raise unprocessable(
            "invalid-transition", "Not a web order",
            "public tokens apply to web orders only",
        )
    now = _now()
    token = crypto.generate_public_token()
    token_enc = crypto.encrypt(
        token.encode(), settings.master_keys[settings.active_key_version],
        record_id=order_id, table="orders", column="public_token_enc",
        key_version=settings.active_key_version,
    )
    async with DomainTransaction() as tx:
        await tx.execute(
            f"UPDATE {tx.table('orders')} SET public_token_hash = :h,"
            " public_token_enc = :e, public_token_expires_at = :x,"
            " updated_at = :n WHERE id = :i",
            {
                "h": crypto.token_lookup_hash(token),
                "e": token_enc,
                "x": now + 30 * 86400,
                "n": now,
                "i": order_id,
            },
        )
    return {
        "id": order_id,
        "public_token": token,
        "expires_at": now + 30 * 86400,
    }


async def order_events(merchant_id: str, user, order_id: str) -> list[dict]:
    from . import merchant as merchant_service

    await merchant_service.get_merchant_row(merchant_id, str(user.id))
    await get_order(order_id, merchant_id)
    from ..db import db, table

    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT from_state, to_state, actor, detail_json, created_at"
            f" FROM {table('order_events')} WHERE order_id = :o"
            " ORDER BY created_at ASC, id ASC",
            {"o": order_id},
        )
    return [
        {
            "from_state": r["from_state"],
            "to_state": r["to_state"],
            "actor": r["actor"],
            "detail": json.loads(r["detail_json"]) if r["detail_json"] else {},
            "created_at": r["created_at"],
        }
        for r in rows
    ]
