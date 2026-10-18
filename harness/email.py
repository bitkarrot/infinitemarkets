"""Executable model of the email notification worker (section 8.8) and the
public-token/cryptography surface (sections 11.3/11.4) against the Task-1
schema.

What the model proves (the PITFALLS this exists to make visible):

- recipient dedupe: one queue row per RECIPIENT ADDRESS under
  UNIQUE(order_id, channel, event_type, recipient_hash) — never one row per
  event regardless of recipients; a duplicate enqueue is a successful no-op;
- customer rows are strictly opt-in per order; opt-out sets
  ``email_opt_in=false`` and cancels that order's queued customer rows;
- the SMTP boundary is a BOOLEAN: only ``True`` enters ``sent``; ``False``,
  raised exceptions, and recipient rejection all surface identically as
  unclassified failure with bounded retry ``min(2^attempts * 30s, 4h)`` and
  ``EMAIL_MAX_ATTEMPTS`` (5) -> ``failed``; v1 never invents
  transient-vs-5xx classification;
- suppressed (not sent, no SMTP call) when email is not configured, a
  merchant order event is disabled, or customer consent was revoked;
- rate limiting before delivery via ``rate_limit_buckets`` keyed on
  ``recipient_hash`` (customer, 8/hour) and merchant id (merchant alerts,
  60/hour) — never the raw address; excess waits rather than delivering;
- structured logs correlate by order id and event type ONLY: no recipient
  address or bearer link (the magic-link token) ever appears;
- queue uniqueness dedupes INTENT, not SMTP delivery: a crash after SMTP
  acceptance before commit may re-deliver on resume (exactly-once intent,
  at-least-once delivery — documented and exhibited);
- public tokens per section 11.4: 256 random bits base64url, SHA-256(token
  bytes) for lookup compared with ``hmac.compare_digest``,
  malformed/noncanonical encodings rejected BEFORE lookup, a separate
  AEAD-encrypted copy retained only while the token is valid and an
  opted-in delayed notification may need to render the magic link,
  rotation/revocation immediately invalidating the old hash and erasing the
  encrypted copy, expiry doing the same;
- recipient addresses and tokens are encrypted-at-rest blobs with keyed
  HMAC equality hashes (purpose-separated, length-prefixed — the section
  11.3 envelope discipline) under a synthetic TEST master key.

The AES-256-GCM envelope comes from ``cryptography`` (already a locked
dependency of the pinned host; no new pin). Synthetic keys only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import uuid

from harness import tx

# --- section 11.3-modeled crypto helpers (synthetic test keys) -----------------


def hmac_equality_hash(
    privacy_key: bytes, purpose: str, value: bytes, *, merchant_id: str = ""
) -> str:
    """Keyed HMAC-SHA256 equality hash over length-prefixed purpose +
    merchant id + normalized value (section 11.3).

    Purposes are distinct: ``email-recipient`` never matches a hash computed
    under another purpose, and the hash is not reversible.
    """

    def len_prefix(data: bytes) -> bytes:
        return len(data).to_bytes(4, "big") + data

    purpose_key = hmac.new(privacy_key, purpose.encode(), hashlib.sha256).digest()
    payload = (
        len_prefix(purpose.encode())
        + len_prefix(merchant_id.encode())
        + len_prefix(value)
    )
    return hmac.new(purpose_key, payload, hashlib.sha256).hexdigest()


def _aesgcm(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM(key)


def encrypt_field(key: bytes, plaintext: bytes, *, aad: bytes) -> bytes:
    """AES-256-GCM envelope with per-record AAD (nonce || ciphertext+tag)."""
    nonce = os.urandom(12)
    return nonce + _aesgcm(key).encrypt(nonce, plaintext, aad)


def decrypt_field(key: bytes, blob: bytes, *, aad: bytes) -> bytes:
    nonce, ciphertext = blob[:12], blob[12:]
    return _aesgcm(key).decrypt(nonce, ciphertext, aad)


# --- section 11.4 public tokens -------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")


def generate_public_token() -> tuple[str, bytes]:
    """256 random bits, base64url encoded (canonical, unpadded, 43 chars)."""
    raw = secrets.token_bytes(32)
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return encoded, raw


def validate_token_encoding(encoded: str) -> bytes | None:
    """Reject malformed/noncanonical encodings BEFORE lookup (section 11.4).

    Returns the decoded token bytes, or None for anything that is not the
    canonical base64url encoding of exactly 256 bits.
    """
    if not isinstance(encoded, str) or _TOKEN_RE.fullmatch(encoded) is None:
        return None
    raw = base64.urlsafe_b64decode(encoded + "=")
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != encoded:
        return None  # noncanonical encoding
    return raw


def token_lookup_hash(raw_token: bytes) -> str:
    """SHA-256(token bytes) — the stored lookup hash."""
    return hashlib.sha256(raw_token).hexdigest()


# --- section 8.8 SMTP boundary stub --------------------------------------------


class SmtpStub:
    """The host boolean SMTP boundary (section 8.8 step 5).

    Programmable outcomes: ``"true"`` (classified success), ``"false"``
    (unclassified failure), ``"raise"`` (transport exception), and
    ``"recipient-rejected"`` — which surfaces as ``False`` exactly like
    every other failure, because the host erases SMTP failure categories.
    """

    def __init__(self, outcome: str = "true") -> None:
        self.outcome = outcome
        self.calls: list[dict] = []

    async def send_email(self, *, to: str, subject: str, body: str) -> bool:
        self.calls.append({"to": to, "subject": subject, "body": body})
        if self.outcome == "raise":
            raise RuntimeError("smtp transport failure")
        if self.outcome in ("false", "recipient-rejected"):
            return False
        return True


class EmailModel:
    """The executable section 8.8 email worker + section 11.4 token model."""

    EMAIL_MAX_ATTEMPTS = 5
    CUSTOMER_PER_HOUR = 8
    MERCHANT_PER_HOUR = 60

    #: Bounded unclassified retry: min(2^attempts * 30s, 4h) (section 8.8).
    RETRY_BASE_S = 30
    RETRY_MAX_S = 14_400

    def __init__(
        self,
        qual_db,
        *,
        smtp: SmtpStub | None = None,
        master_key: bytes = b"\x11" * 32,
        privacy_key: bytes = b"\x22" * 32,
        email_configured: bool = True,
        enabled_event_types: set[str] | None = None,
    ) -> None:
        self.qual_db = qual_db
        self.smtp = smtp or SmtpStub()
        self.master_key = master_key
        self.privacy_key = privacy_key
        self.email_configured = email_configured
        # Default subscribed alert set (section 4.1: order_received,
        # confirmed, on_hold).
        self.enabled_event_types = enabled_event_types or {
            "order_received",
            "confirmed",
            "processing",
            "shipped",
            "delivered",
            "cancelled",
            "expired",
            "on_hold",
            "refund_requested",
        }
        #: Structured logs: correlation by order id and event type ONLY.
        self.logs: list[dict] = []

    # --- logging (no PII, no bearer links) ---------------------------------

    def _log(self, *, order_id: str | None, event_type: str, code: str, **extra):
        entry = {"order_id": order_id, "event_type": event_type, "code": code}
        entry.update({k: v for k, v in extra.items() if k not in ("to", "body")})
        self.logs.append(entry)

    # --- enqueue (dedupe per recipient) --------------------------------------

    async def enqueue(
        self,
        *,
        merchant_id: str,
        order_id: str | None,
        channel: str,
        event_type: str,
        recipient_address: str,
        now: int | None = None,
    ) -> dict:
        """Enqueue one notification intent — one row per RECIPIENT address.

        Customer rows are strictly opt-in per order: when the order's
        ``email_opt_in`` is false, no customer row is created. A duplicate
        (order, channel, event_type, recipient) enqueue is a successful
        no-op (UNIQUE ... ON CONFLICT DO NOTHING).
        """
        now = tx.db_now() if now is None else now
        assert channel in ("merchant", "customer")
        if channel == "customer" and order_id is not None:
            opt_in = await self.qual_db.fetch_all(
                f"SELECT email_opt_in FROM {self.qual_db.table('orders')}"
                " WHERE id = :id",
                {"id": order_id},
            )
            if opt_in and not bool(opt_in[0]["email_opt_in"]):
                self._log(
                    order_id=order_id,
                    event_type=event_type,
                    code="enqueue-skipped-no-consent",
                )
                return {"action": "skipped-no-consent"}
        recipient_hash = hmac_equality_hash(
            self.privacy_key, "email-recipient", recipient_address.encode()
        )
        recipient_enc = encrypt_field(
            self.master_key,
            recipient_address.encode(),
            aad=f"email-recipient:{merchant_id}:{order_id}".encode(),
        )
        row_id = f"emq-{uuid.uuid4().hex[:16]}"
        async with self.qual_db.connect() as conn:
            async with self.qual_db.transaction(conn) as t:
                rc = await t.execute(
                    f"INSERT INTO {self.qual_db.table('email_queue')}"
                    " (id, merchant_id, order_id, channel, event_type,"
                    "  recipient_enc, recipient_hash, state, next_attempt_at,"
                    "  created_at)"
                    " VALUES (:id, :merchant_id, :order_id, :channel,"
                    "  :event_type, :recipient_enc, :recipient_hash,"
                    "  'pending', 0, :now)"
                    " ON CONFLICT DO NOTHING",
                    {
                        "id": row_id,
                        "merchant_id": merchant_id,
                        "order_id": order_id,
                        "channel": channel,
                        "event_type": event_type,
                        "recipient_enc": recipient_enc,
                        "recipient_hash": recipient_hash,
                        "now": now,
                    },
                )
                duplicate = rc == 0
        if duplicate:
            self._log(
                order_id=order_id, event_type=event_type, code="enqueue-duplicate-noop"
            )
        return {"action": "duplicate-noop" if duplicate else "enqueued"}

    async def opt_out(self, *, order_id: str, now: int | None = None) -> int:
        """Public opt-out: email_opt_in=false + cancel queued customer rows.

        "Cancels" per section 8.8 means the queued customer rows become
        ``suppressed`` (not sent, no SMTP call) with a bounded code — the
        queue has no separate cancelled state.
        """
        now = tx.db_now() if now is None else now
        async with self.qual_db.connect() as conn:
            async with self.qual_db.transaction(conn) as t:
                await t.execute(
                    f"UPDATE {self.qual_db.table('orders')} SET email_opt_in = FALSE,"
                    " updated_at = :now WHERE id = :order_id",
                    {"now": now, "order_id": order_id},
                )
                rc = await t.execute(
                    f"UPDATE {self.qual_db.table('email_queue')}"
                    " SET state = 'suppressed', last_error = 'consent-revoked'"
                    " WHERE order_id = :order_id AND channel = 'customer'"
                    " AND state IN ('pending', 'claimed')",
                    {"now": now, "order_id": order_id},
                )
        self._log(order_id=order_id, event_type="opt-out", code="consent-revoked")
        return rc

    # --- claim (like section 8.6) ---------------------------------------------

    async def claim(
        self,
        *,
        worker: str = "email-worker-1",
        now: int | None = None,
        limit: int = 32,
        lease_seconds: int = 60,
    ) -> list[dict]:
        now = tx.db_now() if now is None else now
        return await tx.claim_due_rows(
            self.qual_db,
            self.qual_db.table("email_queue"),
            states=["pending"],
            now=now,
            max_attempts=self.EMAIL_MAX_ATTEMPTS,
            limit=limit,
            worker=worker,
            lease_seconds=lease_seconds,
            touch_updated_at=False,  # email_queue has no updated_at (4.18)
        )

    async def requeue_stale(self, *, now: int | None = None) -> int:
        """Reclaim rows left ``claimed`` with an expired lease (section 8.7
        queue recovery): back to pending via claim-token CAS, incrementing
        the token so the stale worker's leased write fails."""
        now = tx.db_now() if now is None else now
        queue = self.qual_db.table("email_queue")
        stale = await self.qual_db.fetch_all(
            f"SELECT * FROM {queue} WHERE state = 'claimed' AND claimed_until <= :now",
            {"now": now},
        )
        for row in stale:
            async with self.qual_db.connect() as conn:
                async with self.qual_db.transaction(conn) as t:
                    rc = await t.execute(
                        f"UPDATE {queue} SET state = 'pending', claimed_by = NULL,"
                        " claimed_at = NULL, claimed_until = NULL,"
                        " claim_token = claim_token + 1, next_attempt_at = :now"
                        " WHERE id = :id AND claim_token = :claim_token"
                        " AND claimed_until <= :now",
                        {
                            "now": now,
                            "id": row["id"],
                            "claim_token": row["claim_token"],
                        },
                    )
                    if rc != 1:  # pragma: no cover - another actor requeued first
                        raise tx.StaleClaim(
                            f"stale-claim requeue CAS lost for {row['id']!r}"
                        )
        return len(stale)

    # --- rate limiting (section 8.8 step 6) --------------------------------------

    def _rate_limit(self, row: dict) -> tuple[int, int]:
        """(limit, scope) for the row: customer -> per recipient_hash,
        merchant alerts -> per merchant id. Never the raw address."""
        if row["channel"] == "customer":
            return self.CUSTOMER_PER_HOUR, row["recipient_hash"]
        return self.MERCHANT_PER_HOUR, row["merchant_id"]

    async def _consume_rate_window(self, row: dict, now: int) -> bool:
        """Atomically consume one hourly slot; False when over the limit."""
        limit, scope_value = self._rate_limit(row)
        scope_hash = hmac_equality_hash(
            self.privacy_key, "email-rate-limit", scope_value.encode()
        )
        window_start = now // 3600 * 3600
        async with self.qual_db.connect() as conn:
            async with self.qual_db.transaction(conn) as t:
                rc = await t.execute(
                    f"UPDATE {self.qual_db.table('rate_limit_buckets')}"
                    " SET count = count + 1, expires_at = :expires_at"
                    " WHERE scope_hash = :scope_hash AND bucket = 'hourly'"
                    " AND window_start = :window_start AND count < :limit",
                    {
                        "scope_hash": scope_hash,
                        "window_start": window_start,
                        "limit": limit,
                        "expires_at": window_start + 7200,
                    },
                )
                if rc == 1:
                    return True
                rc = await t.execute(
                    f"INSERT INTO {self.qual_db.table('rate_limit_buckets')}"
                    " (scope_hash, bucket, window_start, count, expires_at)"
                    " VALUES (:scope_hash, 'hourly', :window_start, 1,"
                    " :expires_at) ON CONFLICT DO NOTHING",
                    {
                        "scope_hash": scope_hash,
                        "window_start": window_start,
                        "expires_at": window_start + 7200,
                    },
                )
                return rc == 1

    # --- send path ---------------------------------------------------------------

    async def _suppressed_write(self, row: dict, *, code: str, now: int) -> None:
        async with self.qual_db.connect() as conn:
            async with self.qual_db.transaction(conn) as t:
                await tx.leased_write(
                    t,
                    self.qual_db.table("email_queue"),
                    "state = 'suppressed', last_error = :code",
                    {
                        "id": row["id"],
                        "claim_token": row["claim_token"],
                        "now": now,
                        "code": code[:128],
                    },
                )

    async def send(
        self, row: dict, *, now: int | None = None, crash_after_smtp: bool = False
    ) -> dict:
        """One send attempt for a claimed row (the section 8.8 send path).

        Suppression first (no SMTP call): unconfigured, disabled merchant
        order event, or revoked customer consent. Rate limiting before delivery:
        excess waits rather than sending. The SMTP boundary returns a
        boolean: only ``True`` enters ``sent``; every failure (False,
        exception, recipient rejection) returns the row to pending with a
        bounded unclassified retry, and after ``EMAIL_MAX_ATTEMPTS`` the
        row enters ``failed``.

        ``crash_after_smtp`` simulates a crash AFTER SMTP acceptance but
        BEFORE the commit: the delivery happened (at-least-once), the
        queue intent is still exactly one row.
        """
        now = tx.db_now() if now is None else now

        # Suppression checks (section 8.8 step 2) — never an SMTP call.
        if not self.email_configured:
            self._log(
                order_id=row["order_id"],
                event_type=row["event_type"],
                code="suppressed-smtp-not-configured",
            )
            await self._suppressed_write(row, code="smtp-not-configured", now=now)
            return {"action": "suppressed", "reason": "smtp-not-configured"}
        if (
            row["channel"] == "merchant"
            and row["order_id"]
            and row["event_type"] not in self.enabled_event_types
        ):
            self._log(
                order_id=row["order_id"],
                event_type=row["event_type"],
                code="suppressed-event-type-disabled",
            )
            await self._suppressed_write(row, code="event-type-disabled", now=now)
            return {"action": "suppressed", "reason": "event-type-disabled"}
        if row["channel"] == "customer" and row["order_id"]:
            opt_in = await self.qual_db.fetch_all(
                f"SELECT email_opt_in FROM {self.qual_db.table('orders')}"
                " WHERE id = :id",
                {"id": row["order_id"]},
            )
            if opt_in and not bool(opt_in[0]["email_opt_in"]):
                self._log(
                    order_id=row["order_id"],
                    event_type=row["event_type"],
                    code="suppressed-consent-revoked",
                )
                await self._suppressed_write(
                    row, code="consent-revoked", now=now
                )
                return {"action": "suppressed", "reason": "consent-revoked"}

        # Rate limit before delivery (section 8.8 step 6): excess WAITS.
        allowed = await self._consume_rate_window(row, now)
        if not allowed:
            window_end = now // 3600 * 3600 + 3600
            self._log(
                order_id=row["order_id"],
                event_type=row["event_type"],
                code="rate-limited-waiting",
            )
            async with self.qual_db.connect() as conn:
                async with self.qual_db.transaction(conn) as t:
                    await tx.leased_write(
                        t,
                        self.qual_db.table("email_queue"),
                        "state = 'pending', attempts = :attempts,"
                        " next_attempt_at = :next_attempt_at",
                        {
                            "id": row["id"],
                            "claim_token": row["claim_token"],
                            "now": now,
                            "attempts": row["attempts"],
                            "next_attempt_at": window_end,
                        },
                    )
            return {"action": "rate-limited", "wait_until": window_end}

        # Deliver through the boolean SMTP boundary.
        recipient = decrypt_field(
            self.master_key,
            bytes(row["recipient_enc"]),
            aad=f"email-recipient:{row['merchant_id']}:{row['order_id']}".encode(),
        ).decode()
        # The subject carries only the merchant display name and event name
        # (section 8.8 step 3) — no PII.
        subject = f"Infinitemarkets merchant: {row['event_type']}"
        body = "transactional order notification"
        try:
            sent = await self.smtp.send_email(
                to=recipient, subject=subject, body=body
            )
        except Exception:  # noqa: BLE001 — unclassified transport failure
            sent = False
            failure_code = "smtp-failed"
        else:
            failure_code = "smtp-failed"  # never a transient-vs-5xx label

        if crash_after_smtp:
            # The crash point: SMTP accepted, the commit never happened. The
            # delivery is real (at-least-once); the queue intent is exactly
            # one row that will retry.
            raise CrashAfterSmtpAcceptance(row["id"])

        if sent:
            async with self.qual_db.connect() as conn:
                async with self.qual_db.transaction(conn) as t:
                    await tx.leased_write(
                        t,
                        self.qual_db.table("email_queue"),
                        "state = 'sent', sent_at = :now, last_error = NULL",
                        {
                            "id": row["id"],
                            "claim_token": row["claim_token"],
                            "now": now,
                        },
                    )
            self._log(
                order_id=row["order_id"],
                event_type=row["event_type"],
                code="sent",
            )
            return {"action": "sent"}

        # Bounded unclassified retry: min(2^attempts * 30s, 4h).
        attempts = row["attempts"] + 1
        delay = min(2 ** attempts * self.RETRY_BASE_S, self.RETRY_MAX_S)
        new_state = "failed" if attempts >= self.EMAIL_MAX_ATTEMPTS else "pending"
        async with self.qual_db.connect() as conn:
            async with self.qual_db.transaction(conn) as t:
                await tx.leased_write(
                    t,
                    self.qual_db.table("email_queue"),
                    "state = :new_state, attempts = :attempts,"
                    " next_attempt_at = :next_attempt_at,"
                    " last_error = :code",
                    {
                        "id": row["id"],
                        "claim_token": row["claim_token"],
                        "now": now,
                        "new_state": new_state,
                        "attempts": attempts,
                        "next_attempt_at": now + delay,
                        "code": failure_code[:128],
                    },
                )
        self._log(
            order_id=row["order_id"],
            event_type=row["event_type"],
            code="retry" if new_state == "pending" else "failed",
            attempts=attempts,
        )
        return {"action": new_state, "attempts": attempts}

    # --- section 11.4 public tokens -----------------------------------------------

    async def issue_public_token(
        self,
        *,
        order_id: str,
        now: int | None = None,
        lifetime_s: int = 30 * 24 * 3600,
    ) -> str:
        """Issue the order's bearer token; returned exactly once.

        The database stores the SHA-256 lookup hash and a separate
        AEAD-encrypted copy (renderable for the notification lifetime); the
        plaintext token exists only in this return value.
        """
        now = tx.db_now() if now is None else now
        encoded, raw = generate_public_token()
        token_hash = token_lookup_hash(raw)
        token_enc = encrypt_field(
            self.master_key,
            encoded.encode(),
            aad=f"public-token:{order_id}".encode(),
        )
        async with self.qual_db.connect() as conn:
            async with self.qual_db.transaction(conn) as t:
                await t.execute(
                    f"UPDATE {self.qual_db.table('orders')}"
                    " SET public_token_hash = :token_hash,"
                    " public_token_enc = :token_enc,"
                    " public_token_expires_at = :expires_at,"
                    " updated_at = :now WHERE id = :order_id",
                    {
                        "token_hash": token_hash,
                        "token_enc": token_enc,
                        "expires_at": now + lifetime_s,
                        "now": now,
                        "order_id": order_id,
                    },
                )
        return encoded

    async def lookup_public_token(
        self, encoded: str, *, now: int | None = None
    ) -> dict | None:
        """Token-gated lookup: canonical encoding -> constant-time hash
        compare -> live expiry. Returns the order row or None."""
        now = tx.db_now() if now is None else now
        raw = validate_token_encoding(encoded)
        if raw is None:
            return None  # malformed/noncanonical rejected BEFORE lookup
        token_hash = token_lookup_hash(raw)
        rows = await self.qual_db.fetch_all(
            f"SELECT * FROM {self.qual_db.table('orders')}"
            " WHERE public_token_hash = :token_hash",
            {"token_hash": token_hash},
        )
        for row in rows:
            # Constant-time comparison (section 11.4).
            if hmac.compare_digest(row["public_token_hash"], token_hash):
                if row["public_token_expires_at"] and row["public_token_expires_at"] > now:
                    return row
                return None  # expired
        return None

    async def render_magic_link(
        self, *, order_id: str, now: int | None = None
    ) -> str | None:
        """Render the bearer link from the protected AEAD copy.

        Possible only while the token is valid; after expiry/revocation the
        encrypted copy is erased and the hash no longer matches.
        """
        now = tx.db_now() if now is None else now
        rows = await self.qual_db.fetch_all(
            f"SELECT public_token_enc, public_token_expires_at FROM"
            f" {self.qual_db.table('orders')} WHERE id = :order_id",
            {"order_id": order_id},
        )
        if not rows or not rows[0]["public_token_enc"]:
            return None
        if rows[0]["public_token_expires_at"] and rows[0]["public_token_expires_at"] <= now:
            return None
        encoded = decrypt_field(
            self.master_key,
            bytes(rows[0]["public_token_enc"]),
            aad=f"public-token:{order_id}".encode(),
        ).decode()
        return f"/infinitemarkets/order#{encoded}"

    async def revoke_public_token(
        self, *, order_id: str, now: int | None = None
    ) -> None:
        """Revocation: immediately invalidate the hash AND erase the
        encrypted copy (section 11.4)."""
        now = tx.db_now() if now is None else now
        await self._clear_public_token(order_id, now)

    async def rotate_public_token(
        self,
        *,
        order_id: str,
        now: int | None = None,
        lifetime_s: int = 30 * 24 * 3600,
    ) -> str:
        """Rotation: the old hash stops matching immediately, the encrypted
        copy is replaced by the new token's, and the new token is returned
        once."""
        now = tx.db_now() if now is None else now
        await self.revoke_public_token(order_id=order_id, now=now)
        return await self.issue_public_token(
            order_id=order_id, now=now, lifetime_s=lifetime_s
        )

    async def expire_public_tokens(self, *, now: int | None = None) -> int:
        """Expiry does the same as revocation: erase the hash and the
        encrypted copy for every token past its lifetime (section 11.4)."""
        now = tx.db_now() if now is None else now
        async with self.qual_db.connect() as conn:
            async with self.qual_db.transaction(conn) as t:
                rc = await t.execute(
                    f"UPDATE {self.qual_db.table('orders')}"
                    " SET public_token_hash = NULL, public_token_enc = NULL,"
                    " updated_at = :now"
                    " WHERE public_token_expires_at IS NOT NULL"
                    " AND public_token_expires_at <= :now",
                    {"now": now},
                )
        return rc

    async def _clear_public_token(self, order_id: str, now: int) -> None:
        async with self.qual_db.connect() as conn:
            async with self.qual_db.transaction(conn) as t:
                await t.execute(
                    f"UPDATE {self.qual_db.table('orders')}"
                    " SET public_token_hash = NULL, public_token_enc = NULL,"
                    " updated_at = :now WHERE id = :order_id",
                    {"now": now, "order_id": order_id},
                )

    # --- idempotency retention (section 14) ----------------------------------------

    async def expire_idempotency_records(self, *, now: int | None = None) -> int:
        """Records expire after 24h; checkout records are retained through
        invoice expiry + 24h (their ``expires_at`` already encodes that)."""
        now = tx.db_now() if now is None else now
        async with self.qual_db.connect() as conn:
            async with self.qual_db.transaction(conn) as t:
                rc = await t.execute(
                    f"DELETE FROM {self.qual_db.table('idempotency_records')}"
                    " WHERE expires_at <= :now",
                    {"now": now},
                )
        return rc


class CrashAfterSmtpAcceptance(Exception):
    """The crash point after SMTP acceptance but before commit (P0-10 (e)).

    Documents the delivery semantics: queue uniqueness dedupes INTENT, not
    SMTP delivery — a crash here may re-deliver on resume (at-least-once
    delivery under exactly-once intent)."""
