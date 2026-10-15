"""P0-09: email/token persistence evidence (QUAL-09).

Executable section 8.8/11.3/11.4 model runs proving:

(a) two merchant recipients of the same event produce two queue rows, both
    delivered independently, and a duplicate enqueue of the same
    (order, channel, event_type, recipient) is a successful no-op;
(b) revoked customer consent: opt-out sets email_opt_in=false and cancels
    that order's queued customer rows;
(c) delayed confirmation beyond idempotency retention: idempotency_records
    expire after 24h (checkout records retained through invoice expiry +
    24h) while the token's AEAD copy remains renderable for the
    notification lifetime and is erased on expiry — after expiry the magic
    link cannot be rendered and the hash no longer matches;
(d) token rotation/revocation invalidates the old hash and erases the
    encrypted copy immediately;
(e) no plaintext persistence: raw recipient addresses and raw tokens never
    appear in the database — byte-level search of the SQLite file, and
    per-column scan on PostgreSQL;
(f) hashes are not reversible and lookups succeed only via the equality
    hash with the correct key purpose (a wrong-purpose hash does not match).
"""

from __future__ import annotations

import json

import pytest

from harness import email as email_module
from harness import schema

pytestmark = [pytest.mark.db, pytest.mark.fast]

T0 = 2_000_000_000
BUYER = "buyer-secret-alpha@example.org"
MERCHANT_A = "owner-secret-beta@shop.example"
MERCHANT_B = "alerts-secret-gamma@shop.example"


async def _seed_order(
    qual_db,
    *,
    order_id: str = "o1",
    email_opt_in: bool = True,
):
    async with qual_db.connect() as conn:
        async with qual_db.transaction(conn) as t:
            await t.execute(
                f"INSERT INTO {qual_db.table('orders')}"
                " (id, merchant_id, state, email_opt_in, total_sat,"
                "  created_at, updated_at)"
                " VALUES (:o, 'merchant-1', 'received', :opt_in, 1000,"
                "  :now, :now)",
                {"o": order_id, "opt_in": email_opt_in, "now": T0},
            )


async def _queue_rows(qual_db, *, order_id: str | None = None) -> list[dict]:
    if order_id is None:
        return await qual_db.fetch_all(
            f"SELECT * FROM {qual_db.table('email_queue')}"
            " ORDER BY recipient_hash, created_at"
        )
    return await qual_db.fetch_all(
        f"SELECT * FROM {qual_db.table('email_queue')}"
        " WHERE order_id = :id ORDER BY recipient_hash, created_at",
        {"id": order_id},
    )


async def _order(qual_db, order_id: str = "o1") -> dict:
    rows = await qual_db.fetch_all(
        f"SELECT * FROM {qual_db.table('orders')} WHERE id = :id",
        {"id": order_id},
    )
    assert rows
    return rows[0]


# --- (a) per-recipient dedupe ---------------------------------------------------


async def test_two_merchant_recipients_two_rows_delivered_independently(
    qual_db_factory,
):
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        model = email_module.EmailModel(qual_db)

        for address in (MERCHANT_A, MERCHANT_B):
            result = await model.enqueue(
                merchant_id="merchant-1",
                order_id="o1",
                channel="merchant",
                event_type="order_received",
                recipient_address=address,
                now=T0,
            )
            assert result["action"] == "enqueued"

        rows = await _queue_rows(qual_db, order_id="o1")
        assert len(rows) == 2  # one row per RECIPIENT, never per event
        assert len({row["recipient_hash"] for row in rows}) == 2
        assert all(row["state"] == "pending" for row in rows)

        # A duplicate enqueue of the same (order, channel, event_type,
        # recipient) is a successful no-op.
        duplicate = await model.enqueue(
            merchant_id="merchant-1",
            order_id="o1",
            channel="merchant",
            event_type="order_received",
            recipient_address=MERCHANT_A,
            now=T0 + 1,
        )
        assert duplicate["action"] == "duplicate-noop"
        assert len(await _queue_rows(qual_db, order_id="o1")) == 2

        # Both recipients are delivered independently.
        claimed = await model.claim(now=T0 + 10)
        assert len(claimed) == 2
        for row in claimed:
            result = await model.send(row, now=T0 + 10)
            assert result["action"] == "sent"
        assert sorted(c["to"] for c in model.smtp.calls) == sorted(
            [MERCHANT_A, MERCHANT_B]
        )
        for row in await _queue_rows(qual_db, order_id="o1"):
            assert row["state"] == "sent"
            assert row["sent_at"] == T0 + 10


# --- (b) revoked customer consent -----------------------------------------------


async def test_opt_out_revokes_consent_and_cancels_queued_customer_rows(
    qual_db_factory,
):
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        model = email_module.EmailModel(qual_db)
        await model.enqueue(
            merchant_id="merchant-1",
            order_id="o1",
            channel="customer",
            event_type="confirmed",
            recipient_address=BUYER,
            now=T0,
        )
        await model.enqueue(
            merchant_id="merchant-1",
            order_id="o1",
            channel="merchant",
            event_type="confirmed",
            recipient_address=MERCHANT_A,
            now=T0,
        )
        assert len(await _queue_rows(qual_db, order_id="o1")) == 2

        # The public opt-out action.
        cancelled = await model.opt_out(order_id="o1", now=T0 + 5)
        assert cancelled == 1
        order = await _order(qual_db)
        assert not bool(order["email_opt_in"])

        rows = await _queue_rows(qual_db, order_id="o1")
        by_channel = {row["channel"]: row for row in rows}
        # The queued CUSTOMER row is cancelled (suppressed, bounded code).
        assert by_channel["customer"]["state"] == "suppressed"
        assert by_channel["customer"]["last_error"] == "consent-revoked"
        # The merchant row is untouched.
        assert by_channel["merchant"]["state"] == "pending"

        # The suppressed customer row is never claimed, never sent.
        claimed = await model.claim(now=T0 + 10)
        assert [row["channel"] for row in claimed] == ["merchant"]
        # A new customer enqueue after opt-out creates no row.
        skipped = await model.enqueue(
            merchant_id="merchant-1",
            order_id="o1",
            channel="customer",
            event_type="shipped",
            recipient_address=BUYER,
            now=T0 + 15,
        )
        assert skipped["action"] == "skipped-no-consent"
        assert len(await _queue_rows(qual_db, order_id="o1")) == 2
        assert model.smtp.calls == []  # nothing sent in this test


# --- (c) delayed confirmation beyond idempotency retention ----------------------


async def test_token_survives_idempotency_retention_then_expires(qual_db_factory):
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        model = email_module.EmailModel(qual_db)

        token = await model.issue_public_token(order_id="o1", now=T0)
        invoice_expiry = T0 + 1800

        # Idempotency records: a generic record expires after 24h; a
        # checkout record is retained through invoice expiry + 24h
        # (section 14).
        async with qual_db.connect() as conn:
            async with qual_db.transaction(conn) as t:
                await t.execute(
                    f"INSERT INTO {qual_db.table('idempotency_records')}"
                    " (scope_hash, request_hash, state, order_id, owner_id,"
                    "  created_at, expires_at)"
                    " VALUES ('scope-generic', 'req-1', 'completed', NULL,"
                    "  'user-1', :t0, :generic_expiry),"
                    " ('scope-checkout', 'req-2', 'completed', 'o1',"
                    "  'user-1', :t0, :checkout_expiry)",
                    {
                        "t0": T0,
                        "generic_expiry": T0 + 24 * 3600,
                        "checkout_expiry": invoice_expiry + 24 * 3600,
                    },
                )

        # The generic record expires at 24h — before the checkout record.
        removed = await model.expire_idempotency_records(now=T0 + 24 * 3600 + 1)
        assert removed == 1
        remaining = await qual_db.fetch_all(
            f"SELECT scope_hash FROM {qual_db.table('idempotency_records')}"
        )
        assert [row["scope_hash"] for row in remaining] == ["scope-checkout"]

        # Delayed confirmation BEYOND idempotency retention: the token's
        # AEAD copy remains renderable for the notification lifetime
        # (default 30 days) and the hash still matches.
        now_late = invoice_expiry + 24 * 3600 + 3600
        link = await model.render_magic_link(order_id="o1", now=now_late)
        assert link is not None and link.startswith("/infinitemarkets/order#")
        assert token in link
        looked_up = await model.lookup_public_token(token, now=now_late)
        assert looked_up is not None and looked_up["id"] == "o1"

        # The checkout record expires through its retention too.
        removed = await model.expire_idempotency_records(now=now_late + 1)
        assert removed == 1
        assert await qual_db.fetch_all(
            f"SELECT * FROM {qual_db.table('idempotency_records')}"
        ) == []

        # Expiry does the same as revocation: after the token lifetime the
        # magic link cannot be rendered and the hash no longer matches.
        token_expiry = T0 + 30 * 24 * 3600
        expired = await model.expire_public_tokens(now=token_expiry + 1)
        assert expired == 1
        order = await _order(qual_db)
        assert order["public_token_hash"] is None
        assert order["public_token_enc"] is None
        assert await model.render_magic_link(order_id="o1", now=token_expiry + 2) is None
        assert (
            await model.lookup_public_token(token, now=token_expiry + 2) is None
        )
        # The raw token never granted a lookup after expiry: even the
        # pre-expiry render is gone (the copy was erased, not just gated).
        assert await model.render_magic_link(order_id="o1", now=token_expiry - 1) is None


# --- (d) rotation/revocation -------------------------------------------------------


async def test_token_rotation_and_revocation_invalidate_immediately(qual_db_factory):
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        model = email_module.EmailModel(qual_db)

        token1 = await model.issue_public_token(order_id="o1", now=T0)
        assert await model.lookup_public_token(token1, now=T0 + 1) is not None

        # Rotation: the old hash stops matching IMMEDIATELY and the old
        # encrypted copy is replaced.
        token2 = await model.rotate_public_token(order_id="o1", now=T0 + 10)
        assert token2 != token1
        assert await model.lookup_public_token(token1, now=T0 + 11) is None
        assert await model.lookup_public_token(token2, now=T0 + 11) is not None
        link = await model.render_magic_link(order_id="o1", now=T0 + 11)
        assert link is not None and token2 in link and token1 not in link

        # Revocation: hash invalidated and encrypted copy erased immediately.
        await model.revoke_public_token(order_id="o1", now=T0 + 20)
        order = await _order(qual_db)
        assert order["public_token_hash"] is None
        assert order["public_token_enc"] is None
        assert await model.lookup_public_token(token2, now=T0 + 21) is None
        assert await model.render_magic_link(order_id="o1", now=T0 + 21) is None


async def test_malformed_and_noncanonical_tokens_rejected_before_lookup(
    qual_db_factory,
):
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        model = email_module.EmailModel(qual_db)
        token = await model.issue_public_token(order_id="o1", now=T0)

        # Malformed encodings never reach the hash lookup.
        for bad in [
            "",
            "not-a-token",
            token[:-1],  # wrong length
            token + "A",  # wrong length
            token.replace(token[0], "=", 1),  # invalid base64url character
            token.lower(),  # noncanonical (case change) — different bytes
        ]:
            assert await model.lookup_public_token(bad, now=T0 + 1) is None
        # The canonical encoding still works.
        assert await model.lookup_public_token(token, now=T0 + 1) is not None


# --- (e) no plaintext persistence ----------------------------------------------------


async def test_no_plaintext_recipients_or_tokens_in_database(qual_db_factory):
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        model = email_module.EmailModel(qual_db)
        await model.enqueue(
            merchant_id="merchant-1",
            order_id="o1",
            channel="customer",
            event_type="confirmed",
            recipient_address=BUYER,
            now=T0,
        )
        token = await model.issue_public_token(order_id="o1", now=T0)
        # Deliver once so decrypted values flow through the send path.
        claimed = await model.claim(now=T0 + 10)
        assert len(claimed) == 1
        await model.send(claimed[0], now=T0 + 10)

        secrets_ = [BUYER.encode(), token.encode()]

        # Per-column scan on every dialect: no column stores the plaintext.
        for table in schema.MODEL_TABLES:
            rows = await qual_db.fetch_all(f"SELECT * FROM {qual_db.table(table)}")
            for row in rows:
                serialized = json.dumps(
                    {
                        k: (v.hex() if isinstance(v, (bytes, memoryview)) else v)
                        for k, v in row.items()
                    },
                    default=str,
                )
                for secret in secrets_:
                    assert secret.decode() not in serialized, (
                        f"plaintext leaked into {table}.{list(row)[:3]}"
                    )

        # SQLite: the raw bytes of the database file contain neither the
        # plaintext address nor the raw token (byte-level search).
        if qual_db.file_path is not None:
            raw = open(qual_db.file_path, "rb").read()
            for secret in secrets_:
                assert secret not in raw, "plaintext present in SQLite file bytes"


# --- (f) non-reversible, purpose-separated hashes ---------------------------------------


async def test_equality_hashes_are_purpose_separated_and_irreversible(
    qual_db_factory,
):
    async with qual_db_factory() as qual_db:
        await _seed_order(qual_db)
        model = email_module.EmailModel(qual_db)
        await model.enqueue(
            merchant_id="merchant-1",
            order_id="o1",
            channel="customer",
            event_type="confirmed",
            recipient_address=BUYER,
            now=T0,
        )
        rows = await _queue_rows(qual_db, order_id="o1")
        stored_hash = rows[0]["recipient_hash"]

        correct = email_module.hmac_equality_hash(
            model.privacy_key, "email-recipient", BUYER.encode()
        )
        wrong_purpose = email_module.hmac_equality_hash(
            model.privacy_key, "order-id", BUYER.encode()
        )
        wrong_key = email_module.hmac_equality_hash(
            b"\x99" * 32, "email-recipient", BUYER.encode()
        )

        # Lookups succeed only via the equality hash with the correct key
        # purpose: a wrong-purpose (or wrong-key) hash matches nothing.
        assert correct == stored_hash
        assert wrong_purpose != stored_hash
        assert wrong_key != stored_hash

        # The stored value is not the plaintext and is not reversible into
        # it (a Keyed HMAC under a secret key, not an encoding).
        assert stored_hash != BUYER
        assert BUYER not in stored_hash
        lookup = await qual_db.fetch_all(
            f"SELECT * FROM {qual_db.table('email_queue')}"
            " WHERE recipient_hash = :h",
            {"h": wrong_purpose},
        )
        assert lookup == []
