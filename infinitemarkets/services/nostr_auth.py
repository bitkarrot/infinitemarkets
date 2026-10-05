"""Manual NIP-42 AUTH + paid-relay classification (section 9.2, D-26..D-28).

``ClientOptions.automatic_authentication`` stays OFF on every owned
client: automatic AUTH would require a signer (and therefore key
material) attached to long-lived transport. Instead a challenge that
arrives on a live connection is answered by building the kind-22242
event, signing it through ``keystore.sign_event`` inside the operation,
and sending ``ClientMessage.auth`` on the SAME connection only.

Keying rule: the response is keyed to the CONNECTION the challenge
arrived on — the ``relay`` tag is the delivered connection's URL, never a
URL carried inside the challenge or a foreign message. Oversized
challenges are ignored rather than answered. A relay the merchant does
not configure is never authenticated.
"""

from __future__ import annotations

import hmac

from loguru import logger

from .. import crypto
from ..db import DomainTransaction, db, table
from ..security import ProblemError, forbidden

#: Challenges over 1 KiB are never signed (§9.2 bound).
AUTH_CHALLENGE_MAX_BYTES = 1024

#: D-26..D-28 per-relay auth vocabulary on ``relay_configs.auth_state``.
AUTH_STATES = frozenset(
    {
        "auth-required",
        "auth-sent",
        "authenticated",
        "auth-failed",
        "payment-required",
    }
)


def classify_closed(message: str) -> str | None:
    """A relay CLOSED our REQ — map its reason prefix to the
    ``relay_configs.auth_state`` vocabulary (D-26..D-28). Some relays
    wrap the reason in a transport-level prefix (e.g. damus/strfry's
    ``ERROR: auth-required: ...``) — strip it before matching."""
    reason = (message or "").strip().lower()
    for prefix in ("error:", "notice:"):
        if reason.startswith(prefix):
            reason = reason[len(prefix):].strip()
            break
    if reason.startswith("auth-required"):
        return "auth-required"
    if reason.startswith("payment-required"):
        return "payment-required"
    return None


def classify_relay_ok(message: str) -> tuple[str | None, str | None]:
    """Classify a negative-OK message from a relay.

    A paid-write gate reads as ``payment-required`` — real relays phrase
    it several ways ("paid relay", "payment-required", "payment
    required"). Returns ``(state, invoice)``: invoice is the
    bolt11-shaped token embedded in the message when present (D-27 —
    surfaced, never paid automatically).
    """
    import re

    reason = (message or "").strip().lower()
    if "paid relay" in reason or "payment" in reason:
        invoice = None
        match = re.search(r"\b(lnbc|lntb|lnbcrt|lnsb)[0-9a-zA-Z]+\b", message or "")
        if match:
            invoice = match.group(0)
        return "payment-required", invoice
    return None, None


async def update_relay_auth_state(merchant_id: str, relay_url: str,
                                  state: str, *, note: str | None = None,
                                  invoice: str | None = None) -> None:
    """Persist the per-relay auth surface (D-26..D-28) — bounded state
    vocabulary only."""
    if state not in AUTH_STATES:
        raise ValueError(f"unknown auth_state {state!r}")
    import time as _t

    async with DomainTransaction() as tx:
        await tx.execute(
            f"UPDATE {tx.table('relay_configs')} SET auth_state = :s,"
            " auth_note = :n, paid_invoice = :p, auth_updated_at = :t"
            " WHERE merchant_id = :m AND relay_url = :r",
            {
                "s": state, "n": note, "p": invoice,
                "t": int(_t.time()), "m": merchant_id, "r": relay_url,
            },
        )


async def answer_auth_challenge(client, keystore, merchant_id: str,
                                *, relay_url: str, challenge: str) -> bool:
    """Answer one delivered AUTH challenge through the manual chain.

    Guards (any failure -> return False, nothing signed):
    - ``len(challenge) > 1 KiB``;
    - ``relay_url`` is not an exact member of the client's live
      connection set;
    - the merchant owns no enabled ``inbox``/``both`` relay_config row
      covering that URL (OQ4 — per-merchant auth scoping).

    On success the kind-22242 event is signed inside the keystore op and
    sent via ``ClientMessage.auth``/``send_msg_to`` on the same
    connection; ``relay_configs.auth_state`` moves to ``'auth-sent'``
    (upgraded to ``'authenticated'`` when a post-AUTH REQ is served).
    """
    from nostr_sdk import ClientMessage, EventBuilder, PublicKey, RelayUrl

    if len(challenge.encode()) > AUTH_CHALLENGE_MAX_BYTES:
        logger.info(
            "event=infinitemarkets.inbox.auth_rejected"
            " reason=challenge-oversize"
        )
        return False
    live = {str(u) for u in (await client.relays()).keys()}
    if relay_url not in live:
        logger.info(
            "event=infinitemarkets.inbox.auth_rejected"
            " reason=foreign-connection"
        )
        return False
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT id FROM {table('relay_configs')} "
            "WHERE merchant_id = :m AND relay_url = :r AND enabled"
            " AND direction IN ('inbox', 'both')",
            {"m": merchant_id, "r": relay_url},
        )
        merchant = await conn.fetchone(
            f"SELECT pubkey FROM {table('merchants')} WHERE id = :m",
            {"m": merchant_id},
        )
    if row is None or merchant is None:
        logger.info(
            "event=infinitemarkets.inbox.auth_rejected"
            " reason=unconfigured-relay"
        )
        return False

    builder = EventBuilder.auth(challenge, RelayUrl.parse(relay_url))
    unsigned = builder.build(PublicKey.parse(merchant["pubkey"]))
    signed = await keystore.sign_event(merchant_id, unsigned)
    await client.send_msg_to(
        [RelayUrl.parse(relay_url)], ClientMessage.auth(signed)
    )
    await update_relay_auth_state(merchant_id, relay_url, "auth-sent")
    logger.info(
        "event=infinitemarkets.inbox.auth_answered relay={}",
        relay_url,
    )
    return True


# --- NIP-07 buyer sign-in (plan 03-03, D-01 locked) -----------------------------
#
# A buyer proves pubkey ownership by signing a one-time server-issued
# challenge in a kind-22242 event (``window.nostr.signEvent``). A verified,
# fresh, correctly-scoped signature mints a ``buyer_sessions`` row whose
# raw token is returned exactly once inside the ``gm_nostr_session``
# cookie — HttpOnly + Secure + SameSite=Strict, scoped to the extension
# prefix, and revocable server-side via ``revoked_at``.
#
# No-oracle posture: every failure class (malformed JSON, bad signature,
# wrong kind, stale event, unknown/used/expired challenge, foreign scope)
# raises the SAME 401 problem. ``session_from_cookie`` is equally uniform
# — malformed, unknown, expired, and revoked tokens all return ``None``.

#: Session cookie contract (T-303-04).
SESSION_COOKIE = "gm_nostr_session"
SESSION_COOKIE_PATH = "/infinitemarkets"

#: Challenge window — 300 s, single-use, merchant+IP scope-bound.
CHALLENGE_TTL_S = 300
#: Signed-event freshness bound — ``abs(now - created_at)`` tolerance.
SIGNIN_EVENT_MAX_AGE_S = 300
#: NIP-42 auth event kind is reused for web sign-in (D-01).
SIGNIN_EVENT_KIND = 22242
#: Buyer session lifetime — ~7 days, revocable.
NOSTR_SESSION_TTL_S = 7 * 86400
#: Signed-event JSON bound — oversized envelopes reject before parse.
SIGNIN_EVENT_MAX_BYTES = 16384

#: Identical failure for every sign-in rejection class (no oracle).
SIGNIN_INVALID = ProblemError(
    401, "unauthorized", "Sign-in failed",
    "the sign-in could not be verified",
)
#: Identical failure for session-cookie lookups (no oracle).
SESSION_INVALID = ProblemError(
    401, "unauthorized", "Sign-in required",
    "a valid Nostr sign-in is required",
)


def _now() -> int:
    import time as _t

    return int(_t.time())


def _challenge_digest(challenge: str) -> str:
    """SHA-256 hex of a candidate challenge — the stored lookup value."""
    import hashlib

    return hashlib.sha256(challenge.encode()).hexdigest()


def _scope_hash(settings, merchant_id: str, client_ip: str) -> str:
    """Challenge scope — HMAC over merchant + client IP (§11.4 posture)."""
    return crypto.hmac_index(
        settings.privacy_key, "nostr-challenge",
        merchant_id, str(client_ip),
    )


async def issue_challenge(
    merchant_id: str, client_ip: str, *, settings=None, now: int | None = None
) -> dict:
    """Mint a 256-bit single-use challenge; only its hash persists."""
    import uuid

    from ..settings import ext_settings

    settings = settings or ext_settings()
    now = _now() if now is None else now
    challenge = crypto.generate_public_token()
    scope = _scope_hash(settings, merchant_id, client_ip)
    async with DomainTransaction() as tx:
        for _ in range(3):
            rc = await tx.execute(
                f"INSERT INTO {tx.table('nostr_challenges')} "
                "(id, merchant_id, challenge_hash, scope_hash,"
                " expires_at, created_at) "
                "VALUES (:i, :m, :h, :s, :e, :n)"
                " ON CONFLICT (challenge_hash) DO NOTHING",
                {
                    "i": uuid.uuid4().hex,
                    "m": merchant_id,
                    "h": _challenge_digest(challenge),
                    "s": scope,
                    "e": now + CHALLENGE_TTL_S,
                    "n": now,
                },
            )
            if rc == 1:
                break
            # UNIQUE collision — remint (astronomically unlikely).
            challenge = crypto.generate_public_token()
    return {
        "challenge": challenge,
        "ttl": CHALLENGE_TTL_S,
        "expires_at": now + CHALLENGE_TTL_S,
    }


def _candidate_challenges(event) -> list[str]:
    """Challenge strings the event may carry: content + ``challenge``
    tag values (both spellings are tolerated; lookup binds either)."""
    candidates: list[str] = []
    content = event.content()
    if isinstance(content, str) and content:
        candidates.append(content)
    for tag in event.tags().to_vec():
        vec = tag.as_vec()
        if len(vec) >= 2 and vec[0] == "challenge":
            candidates.append(vec[1])
    return candidates


async def verify_signin(
    merchant_id: str,
    signed_event_json: str,
    client_ip: str,
    *,
    settings=None,
    now: int | None = None,
) -> dict:
    """Verify a signed kind-22242 challenge event and mint the session.

    Returns the raw session token exactly once (alongside the buyer
    pubkey) — only ``token_lookup_hash(token)`` persists.
    """
    from nostr_sdk import Event

    from ..settings import ext_settings

    settings = settings or ext_settings()
    now = _now() if now is None else now
    if (
        not isinstance(signed_event_json, str)
        or len(signed_event_json.encode()) > SIGNIN_EVENT_MAX_BYTES
    ):
        raise SIGNIN_INVALID
    try:
        event = Event.from_json(signed_event_json)
    except Exception:
        raise SIGNIN_INVALID from None
    try:
        if not event.verify():
            raise SIGNIN_INVALID
    except ProblemError:
        raise
    except Exception:
        raise SIGNIN_INVALID from None
    if event.kind().as_u16() != SIGNIN_EVENT_KIND:
        raise SIGNIN_INVALID
    if abs(now - event.created_at().as_secs()) > SIGNIN_EVENT_MAX_AGE_S:
        raise SIGNIN_INVALID

    scope = _scope_hash(settings, merchant_id, client_ip)
    pubkey_hex = event.author().to_hex()
    async with DomainTransaction() as tx:
        matched = None
        for candidate in _candidate_challenges(event):
            if not isinstance(candidate, str) or len(candidate) != 43:
                continue
            row = await tx.fetch_one(
                f"SELECT * FROM {tx.table('nostr_challenges')} "
                "WHERE challenge_hash = :h AND merchant_id = :m"
                " AND used_at IS NULL AND expires_at > :n",
                {
                    "h": _challenge_digest(candidate),
                    "m": merchant_id,
                    "n": now,
                },
            )
            if row is not None and hmac.compare_digest(
                row["scope_hash"], scope
            ):
                matched = row
                break
        if matched is None:
            raise SIGNIN_INVALID
        # Single-use CAS — a raced second claim fails identically.
        rc = await tx.execute(
            f"UPDATE {tx.table('nostr_challenges')} SET used_at = :n"
            " WHERE id = :i AND used_at IS NULL AND expires_at > :n",
            {"n": now, "i": matched["id"]},
        )
        if rc != 1:
            raise SIGNIN_INVALID
        account = await _get_or_create_account(
            tx, merchant_id, pubkey=pubkey_hex, settings=settings, now=now
        )
        return await _mint_session(tx, merchant_id, account, settings, now)


async def _account_by_hash(
    tx, merchant_id: str, *, pubkey_hash=None, email_hash=None
) -> dict | None:
    """The non-retired ``buyer_accounts`` row for one identity hash."""
    if pubkey_hash is not None:
        return await tx.fetch_one(
            f"SELECT * FROM {tx.table('buyer_accounts')}"
            " WHERE merchant_id = :m AND pubkey_hash = :h"
            " AND retired_at IS NULL",
            {"m": merchant_id, "h": pubkey_hash},
        )
    if email_hash is not None:
        return await tx.fetch_one(
            f"SELECT * FROM {tx.table('buyer_accounts')}"
            " WHERE merchant_id = :m AND email_hash = :h"
            " AND retired_at IS NULL",
            {"m": merchant_id, "h": email_hash},
        )
    return None


def _decrypt_account_field(
    account: dict, column: str, settings
) -> str | None:
    """Best-effort decrypt of ``email_enc``/``pubkey_enc`` — AAD binds the
    ciphertext to the account row (``record_id`` = account id). A corrupt
    or unreadable ciphertext degrades the field to ``None``, never a
    crash (``_customer_email`` posture)."""
    enc = account.get(column)
    if enc is None:
        return None
    try:
        ver = crypto.envelope_version(enc)
        return crypto.decrypt(
            enc, settings.master_keys[ver], record_id=account["id"],
            table="buyer_accounts", column=column, key_version=ver,
        ).decode()
    except Exception:  # noqa: BLE001 — corrupt field is data, not a crash
        return None


async def _get_or_create_account(
    tx, merchant_id: str, *, pubkey=None, email=None, settings, now: int
) -> dict:
    """Resolve or create the ``buyer_accounts`` row for a verified
    identity (D-01).

    The caller supplies the verified plaintext — ``pubkey`` from the
    signed kind-22242 event / nsec, ``email`` from a verified sign-in
    token. Returns the row plus ``pubkey``/``email`` plaintext keys:
    caller-supplied for the proven identity, decrypted from ``*_enc`` for
    any other identity the account already holds."""
    import uuid

    pubkey_hash = (
        crypto.hmac_index(
            settings.privacy_key, crypto.PURPOSE_BUYER_PUBKEY,
            merchant_id, crypto.normalize(pubkey),
        )
        if pubkey
        else None
    )
    email_hash = (
        crypto.hmac_index(
            settings.privacy_key, crypto.PURPOSE_BUYER_EMAIL,
            merchant_id, crypto.normalize(email),
        )
        if email
        else None
    )
    row = await _account_by_hash(tx, merchant_id, pubkey_hash=pubkey_hash)
    if row is None:
        row = await _account_by_hash(tx, merchant_id, email_hash=email_hash)
    if row is None:
        account_id = uuid.uuid4().hex
        ver = settings.active_key_version
        key = settings.master_keys[ver]

        def _enc(plaintext: str | None, column: str):
            if plaintext is None:
                return None
            return crypto.encrypt(
                plaintext.encode(), key, record_id=account_id,
                table="buyer_accounts", column=column, key_version=ver,
            )

        row = {
            "id": account_id,
            "merchant_id": merchant_id,
            "email_enc": _enc(email, "email_enc"),
            "email_hash": email_hash,
            "pubkey_enc": _enc(pubkey, "pubkey_enc"),
            "pubkey_hash": pubkey_hash,
            "retired_at": None,
            "created_at": now,
            "updated_at": now,
        }
        await tx.execute(
            f"INSERT INTO {tx.table('buyer_accounts')} (id, merchant_id,"
            " email_enc, email_hash, pubkey_enc, pubkey_hash,"
            " created_at, updated_at) "
            "VALUES (:i, :m, :ee, :eh, :pe, :ph, :n, :n)",
            {
                "i": row["id"],
                "m": merchant_id,
                "ee": row["email_enc"],
                "eh": row["email_hash"],
                "pe": row["pubkey_enc"],
                "ph": row["pubkey_hash"],
                "n": now,
            },
        )
    account = dict(row)
    account["pubkey"] = pubkey or _decrypt_account_field(
        account, "pubkey_enc", settings
    )
    account["email"] = email or _decrypt_account_field(
        account, "email_enc", settings
    )
    return account


async def _mint_session(tx, merchant_id: str, account: dict,
                        settings, now: int) -> dict:
    """Insert the account-scoped buyer_sessions row (D-02) — returns the
    raw token exactly once (only ``token_lookup_hash(token)`` persists).

    ``buyer_pubkey_enc``/``buyer_pubkey_hash`` stay populated for pubkey
    accounts — cheap compat: legacy readers resolve the pubkey without a
    join — and stay NULL for email-only accounts."""
    import uuid

    from nostr_sdk import PublicKey

    token = crypto.generate_public_token()
    session_id = uuid.uuid4().hex
    ver = settings.active_key_version
    key = settings.master_keys[ver]
    buyer_pubkey = account.get("pubkey")
    await tx.execute(
        f"INSERT INTO {tx.table('buyer_sessions')} "
        "(id, merchant_id, token_hash, buyer_pubkey_enc,"
        " buyer_pubkey_hash, account_id, expires_at, created_at) "
        "VALUES (:i, :m, :th, :pe, :ph, :a, :e, :n)",
        {
            "i": session_id,
            "m": merchant_id,
            "th": crypto.token_lookup_hash(token).hex(),
            "pe": (
                crypto.encrypt(
                    buyer_pubkey.encode(), key, record_id=session_id,
                    table="buyer_sessions", column="buyer_pubkey_enc",
                    key_version=ver,
                )
                if buyer_pubkey
                else None
            ),
            "ph": account.get("pubkey_hash"),
            "a": account["id"],
            "e": now + NOSTR_SESSION_TTL_S,
            "n": now,
        },
    )
    return {
        "token": token,
        "pubkey": buyer_pubkey,
        "npub": (
            PublicKey.parse(buyer_pubkey).to_bech32()
            if buyer_pubkey
            else None
        ),
        "expires_at": now + NOSTR_SESSION_TTL_S,
    }


async def signin_nsec(
    merchant_id: str,
    nsec: str,
    *,
    settings=None,
    now: int | None = None,
) -> dict:
    """nsec sign-in — a dev/e2e affordance gated by
    ``INFINITEMARKETS_NSEC_SIGNIN`` at the route layer: possession of the
    secret key proves ownership, so no challenge round-trip is needed.
    Mints the identical ``buyer_sessions`` row as ``verify_signin``."""
    from nostr_sdk import Keys

    from ..settings import ext_settings

    settings = settings or ext_settings()
    now = _now() if now is None else now
    if (
        not isinstance(nsec, str)
        or not nsec.startswith("nsec1")
        or len(nsec) > 128
    ):
        raise SIGNIN_INVALID
    try:
        pubkey_hex = Keys.parse(nsec.strip()).public_key().to_hex()
    except Exception:
        raise SIGNIN_INVALID from None
    async with DomainTransaction() as tx:
        account = await _get_or_create_account(
            tx, merchant_id, pubkey=pubkey_hex, settings=settings, now=now
        )
        return await _mint_session(tx, merchant_id, account, settings, now)


async def session_from_cookie(
    token: str | None, *, settings=None, now: int | None = None
) -> dict | None:
    """Strict token lookup — every failure class returns ``None``
    (malformed, unknown, expired, revoked, retired-account are
    indistinguishable).

    Post-m008 sessions resolve identities through the ``buyer_accounts``
    row (authoritative — merges re-point identities); pre-m008 rows with
    ``account_id IS NULL`` resolve on the unchanged legacy pubkey path.
    Returns ``{id, merchant_id, account_id, buyer_pubkey, email,
    pubkey_hash, email_hash, expires_at}`` — ``buyer_pubkey``/``email``
    are legitimately ``None`` for identities the account does not hold
    (an email-only session is data, not a failure)."""
    from ..settings import ext_settings

    if not token:
        return None
    settings = settings or ext_settings()
    now = _now() if now is None else now
    try:
        digest = crypto.token_lookup_hash(token).hex()
    except crypto.CryptoError:
        return None
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table('buyer_sessions')} WHERE token_hash = :h",
            {"h": digest},
        )
        account = None
        if row and row["account_id"]:
            account = await conn.fetchone(
                f"SELECT * FROM {table('buyer_accounts')}"
                " WHERE id = :a AND merchant_id = :m"
                " AND retired_at IS NULL",
                {"a": row["account_id"], "m": row["merchant_id"]},
            )
    if not row or row["revoked_at"] is not None or row["expires_at"] <= now:
        return None
    if row["account_id"] is None:
        # Legacy pre-m008 row — identical resolution to before the rebuild.
        buyer_pubkey = None
        if row["buyer_pubkey_enc"] is not None:
            try:
                ver = crypto.envelope_version(row["buyer_pubkey_enc"])
                buyer_pubkey = crypto.decrypt(
                    row["buyer_pubkey_enc"], settings.master_keys[ver],
                    record_id=row["id"], table="buyer_sessions",
                    column="buyer_pubkey_enc", key_version=ver,
                ).decode()
            except crypto.CryptoError:
                buyer_pubkey = None
        if not buyer_pubkey:
            return None
        return {
            "id": row["id"],
            "merchant_id": row["merchant_id"],
            "account_id": None,
            "buyer_pubkey": buyer_pubkey,
            "email": None,
            "pubkey_hash": row["buyer_pubkey_hash"],
            "email_hash": None,
            "expires_at": row["expires_at"],
        }
    if account is None:
        # Session points at a missing/retired account — an anomaly (merge
        # re-points sessions inside the merge tx), so fail closed.
        return None
    return {
        "id": row["id"],
        "merchant_id": row["merchant_id"],
        "account_id": account["id"],
        "buyer_pubkey": _decrypt_account_field(
            account, "pubkey_enc", settings
        ),
        "email": _decrypt_account_field(account, "email_enc", settings),
        "pubkey_hash": account["pubkey_hash"],
        "email_hash": account["email_hash"],
        "expires_at": row["expires_at"],
    }


async def revoke_session(token: str | None, *, now: int | None = None) -> bool:
    """Revoke the session row behind a cookie token — idempotent."""
    if not token:
        return False
    try:
        digest = crypto.token_lookup_hash(token).hex()
    except crypto.CryptoError:
        return False
    now = _now() if now is None else now
    async with DomainTransaction() as tx:
        rc = await tx.execute(
            f"UPDATE {tx.table('buyer_sessions')} SET revoked_at = :n"
            " WHERE token_hash = :h AND revoked_at IS NULL",
            {"n": now, "h": digest},
        )
    return rc == 1


def require_origin(request) -> None:
    """Exact-Origin enforcement on session-cookie mutations (T-303-04).

    Same canonical-origin rule as the admin cookie path
    (``Origin == INFINITEMARKETS_PUBLIC_BASE_URL``; missing/``null``
    fails) — minus the double-submit CSRF token (SameSite=Strict +
    exact Origin is the agreed session posture, PATTERNS §6a).
    """
    from ..settings import ext_settings

    origin = request.headers.get("origin")
    canonical = ext_settings().public_base_url
    if not origin or origin.lower() == "null" or origin != canonical:
        raise forbidden("cross-origin session mutation rejected")


#: Identical-401 outcome shared with ``_order_for_token`` — claim must
#: never distinguish dead/malformed/foreign-bound tokens (D-05 no-oracle).
CLAIM_INVALID = ProblemError(
    401, "unauthorized", "Token invalid",
    "this order link is no longer valid",
)


async def claim_order(
    session: dict, order: dict, *, settings=None, now: int | None = None
) -> dict:
    """Bind the session account's offered identities to a token-resolved
    order (D-04, D-05).

    Identity-symmetric: whichever of ``pubkey_hash``/``email_hash`` the
    account holds must be unbound on the order or already bound to the
    same value — a bound-column mismatch is the identical no-oracle
    ``CLAIM_INVALID`` (a foreign-bound column is never distinguishable).
    Idempotent: a repeat claim whose offered identities are all bound to
    the same values is a success no-op. Per-column CAS guards keep racing
    claims single-writer; ``buyer_email_hash`` is hash-only (the
    plaintext already lives in ``contact_enc``) and ``buyer_pubkey_enc``
    is written as before when the pubkey side binds. Binds and audits
    inside one ``DomainTransaction``.
    """
    from ..settings import ext_settings

    settings = settings or ext_settings()
    now = _now() if now is None else now
    offered = {}
    if session.get("pubkey_hash"):
        offered["buyer_pubkey_hash"] = session["pubkey_hash"]
    if session.get("email_hash"):
        offered["buyer_email_hash"] = session["email_hash"]
    if not offered:
        raise CLAIM_INVALID
    for column, bound in offered.items():
        existing = order.get(column)
        if existing and not hmac.compare_digest(existing, bound):
            raise CLAIM_INVALID
    if all(order.get(column) for column in offered):
        return {
            "claimed": True,
            "order_id": order["id"],
            "already_linked": True,
        }
    sets = ["updated_at = :n"]
    wheres = ["id = :i"]
    params: dict = {"i": order["id"], "n": now}
    if "buyer_pubkey_hash" in offered:
        wheres.append(
            "(buyer_pubkey_hash IS NULL OR buyer_pubkey_hash = :bph)"
        )
        params["bph"] = offered["buyer_pubkey_hash"]
        if not order.get("buyer_pubkey_hash"):
            sets.append("buyer_pubkey_hash = :bph")
            if session.get("buyer_pubkey"):
                ver = settings.active_key_version
                sets.append("buyer_pubkey_enc = :bpe")
                params["bpe"] = crypto.encrypt(
                    session["buyer_pubkey"].encode(),
                    settings.master_keys[ver], record_id=order["id"],
                    table="orders", column="buyer_pubkey_enc",
                    key_version=ver,
                )
    if "buyer_email_hash" in offered:
        wheres.append(
            "(buyer_email_hash IS NULL OR buyer_email_hash = :beh)"
        )
        params["beh"] = offered["buyer_email_hash"]
        if not order.get("buyer_email_hash"):
            sets.append("buyer_email_hash = :beh")
    async with DomainTransaction() as tx:
        rc = await tx.execute(
            f"UPDATE {tx.table('orders')} SET {', '.join(sets)}"
            f" WHERE {' AND '.join(wheres)}",
            params,
        )
        if rc != 1:
            row = await tx.fetch_one(
                f"SELECT {', '.join(offered)} FROM {tx.table('orders')}"
                " WHERE id = :i",
                {"i": order["id"]},
            )
            if row and all(
                row[column]
                and hmac.compare_digest(row[column], bound)
                for column, bound in offered.items()
            ):
                return {
                    "claimed": True,
                    "order_id": order["id"],
                    "already_linked": True,
                }
            raise CLAIM_INVALID
        await tx.execute(
            f"INSERT INTO {tx.table('order_events')} "
            "(id, order_id, from_state, to_state, actor, detail_json,"
            " created_at) "
            f"SELECT :i, :o, state, state, 'buyer', :d, :n"
            f" FROM {tx.table('orders')} WHERE id = :o",
            {
                "i": __import__("uuid").uuid4().hex,
                "o": order["id"],
                "d": '{"type":"buyer-claimed"}',
                "n": now,
            },
        )
    return {"claimed": True, "order_id": order["id"], "already_linked": False}
