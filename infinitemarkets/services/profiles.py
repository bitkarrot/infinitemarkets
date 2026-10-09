"""Merchant-scoped Nostr counterparty profile cache for Messages.

Kind-0 metadata is public relay data, but buyer pubkeys remain encrypted in
extension tables; the cache stores both the pubkey and sanitized profile under
AEAD. Lookups use the merchant-scoped PURPOSE_BUYER_PUBKEY HMAC, preserving the
same tenant boundary as order_messages. Expired entries remain displayable while
a refresh fails, but are not treated as fresh evidence.
"""

from __future__ import annotations

import json
import time
import uuid

from .. import crypto
from ..db import DomainTransaction, db, table
from ..settings import ext_settings

KIND_PROFILE = 0
PROFILE_TTL_S = 24 * 3600
PROFILE_MISS_TTL_S = 3600
PROFILE_FETCH_TIMEOUT_S = 4
PROFILE_REFRESH_MAX = 12
_MAX_NAME = 120
_MAX_URL = 500
_MAX_NIP05 = 200


def _now() -> int:
    return int(time.time())


def _pubkey_hash(settings, merchant_id: str, pubkey_hex: str) -> str:
    return crypto.hmac_index(
        settings.privacy_key, crypto.PURPOSE_BUYER_PUBKEY,
        merchant_id, crypto.normalize(pubkey_hex),
    )


def _npub(pubkey_hex: str) -> str | None:
    try:
        from nostr_sdk import PublicKey

        return PublicKey.parse(pubkey_hex).to_bech32()
    except Exception:  # noqa: BLE001 — display-only
        return None


def _sanitize_profile(raw) -> dict:
    """Keep the small public display set; reject non-HTTPS avatars."""
    if not isinstance(raw, dict):
        return {}
    display = raw.get("display_name") or raw.get("name") or ""
    username = raw.get("name") or raw.get("username") or ""
    nip05 = raw.get("nip05") or ""
    picture = raw.get("picture") or ""
    out: dict[str, str] = {}
    if isinstance(display, str) and display.strip():
        out["display_name"] = display.strip()[:_MAX_NAME]
    if isinstance(username, str) and username.strip():
        out["username"] = username.strip()[:_MAX_NAME]
    if isinstance(nip05, str) and nip05.strip():
        from lnbits.helpers import is_valid_email_address

        value = nip05.strip()
        if len(value) <= _MAX_NIP05 and is_valid_email_address(value):
            out["nip05"] = value
    if (
        isinstance(picture, str)
        and picture.startswith("https://")
        and len(picture) <= _MAX_URL
    ):
        out["avatar_url"] = picture
    return out


def _public_profile(pubkey_hex: str, payload: dict | None) -> dict:
    npub = _npub(pubkey_hex)
    profile = payload or {}
    return {
        "pubkey": pubkey_hex,
        "npub": npub,
        "profile_url": f"https://nostr.at/{npub}" if npub else None,
        "display_name": profile.get("display_name"),
        "username": profile.get("username"),
        "nip05": profile.get("nip05"),
        "avatar_url": profile.get("avatar_url"),
        "has_profile": bool(profile),
    }


async def _profile_rows(merchant_id: str, pubkeys: list[str],
                        settings=None) -> dict[str, dict]:
    settings = settings or ext_settings()
    if not pubkeys:
        return {}
    hashes = {
        _pubkey_hash(settings, merchant_id, p): p for p in pubkeys
    }
    keys = list(hashes)
    placeholders = ", ".join(f":h{i}" for i in range(len(keys)))
    params = {f"h{i}": h for i, h in enumerate(keys)}
    params["m"] = merchant_id
    async with db.connect() as conn:
        rows = await conn.fetchall(
            f"SELECT id, pubkey_hash, profile_enc, expires_at"
            f" FROM {table('counterparty_profiles')}"
            f" WHERE merchant_id = :m AND pubkey_hash IN ({placeholders})",
            params,
        )
    return {
        hashes[r["pubkey_hash"]]: dict(r) for r in rows
        if r["pubkey_hash"] in hashes
    }


async def profiles_for(
    merchant_id: str, pubkeys: list[str], *, settings=None
) -> dict[str, dict]:
    """Decrypt cached profiles; missing/stale entries still get npub data."""
    settings = settings or ext_settings()
    rows = await _profile_rows(merchant_id, pubkeys, settings)
    out = {}
    for pubkey in pubkeys:
        payload = {}
        row = rows.get(pubkey)
        if row is not None and row["profile_enc"]:
            try:
                ver = crypto.envelope_version(row["profile_enc"])
                payload = json.loads(
                    crypto.decrypt(
                        row["profile_enc"], settings.master_keys[ver],
                        record_id=row["id"], table="counterparty_profiles",
                        column="profile_enc", key_version=ver,
                    ).decode()
                )
            except Exception:  # noqa: BLE001 — display-only cache
                payload = {}
        out[pubkey] = _public_profile(pubkey, payload)
    return out


async def _store_profile(
    merchant_id: str, pubkey_hex: str, payload: dict,
    *, found: bool, now: int, settings
) -> None:
    pubkey_hash = _pubkey_hash(settings, merchant_id, pubkey_hex)
    async with DomainTransaction() as tx:
        existing = await tx.fetch_one(
            f"SELECT id FROM {tx.table('counterparty_profiles')}"
            " WHERE merchant_id = :m AND pubkey_hash = :h",
            {"m": merchant_id, "h": pubkey_hash},
        )
        row_id = existing["id"] if existing else uuid.uuid4().hex
        ver = settings.active_key_version
        key = settings.master_keys[ver]
        pubkey_enc = crypto.encrypt(
            pubkey_hex.encode(), key, record_id=row_id,
            table="counterparty_profiles", column="pubkey_enc",
            key_version=ver,
        )
        profile_enc = crypto.encrypt(
            json.dumps(payload, sort_keys=True,
                       separators=(",", ":")).encode(),
            key, record_id=row_id, table="counterparty_profiles",
            column="profile_enc", key_version=ver,
        )
        expires = now + (PROFILE_TTL_S if found else PROFILE_MISS_TTL_S)
        if existing:
            await tx.execute(
                f"UPDATE {tx.table('counterparty_profiles')} SET"
                " pubkey_enc = :p, profile_enc = :e, fetched_at = :n,"
                " expires_at = :x WHERE id = :i",
                {"p": pubkey_enc, "e": profile_enc, "n": now,
                 "x": expires, "i": row_id},
            )
        else:
            await tx.execute(
                f"INSERT INTO {tx.table('counterparty_profiles')} "
                "(id, merchant_id, pubkey_hash, pubkey_enc, profile_enc,"
                " fetched_at, expires_at) "
                "VALUES (:i, :m, :h, :p, :e, :n, :x)",
                {"i": row_id, "m": merchant_id, "h": pubkey_hash,
                 "p": pubkey_enc, "e": profile_enc, "n": now,
                 "x": expires},
            )


async def refresh_profiles(
    merchant_id: str, pubkeys: list[str], *, settings=None,
    timeout_s: float = PROFILE_FETCH_TIMEOUT_S, force: bool = False,
) -> dict[str, dict]:
    """Fetch latest kind-0 metadata for stale/missing counterparties.

    One bounded query goes to the merchant's public-direction relays; misses are
    cached briefly so an unknown profile does not block every Messages load.
    """
    settings = settings or ext_settings()
    requested = []
    seen = set()
    for pubkey in pubkeys:
        normalized = crypto.normalize(pubkey)
        if normalized and normalized not in seen:
            seen.add(normalized)
            requested.append(normalized)
    rows = await _profile_rows(merchant_id, requested, settings)
    now = _now()
    stale = (
        requested[:PROFILE_REFRESH_MAX]
        if force else [
            p for p in requested
            if not rows.get(p) or int(rows[p]["expires_at"] or 0) <= now
        ][:PROFILE_REFRESH_MAX]
    )
    if stale:
        from nostr_sdk import Filter, Kind, PublicKey

        from . import relay as relay_service
        from .transport import transport

        urls = await relay_service.relay_targets(merchant_id, "public")
        if not urls:
            urls = await relay_service.relay_targets(merchant_id, "inbox")
        events = []
        latest = {}
        if urls:
            authors = []
            valid_stale = []
            for pubkey in stale:
                try:
                    authors.append(PublicKey.parse(pubkey))
                    valid_stale.append(pubkey)
                except Exception:  # noqa: BLE001 — malformed cached/display id
                    continue
            stale = valid_stale
            if stale:
                nostr_filter = (
                    Filter().kinds([Kind(KIND_PROFILE)])
                    .authors(authors).limit(len(stale) * 2)
                )
                try:
                    events = await transport().fetch_from(
                        urls, nostr_filter, timeout_s=timeout_s
                    )
                except Exception:  # noqa: BLE001 — display is best-effort
                    events = []
        for event in events:
            author = event.author().to_hex()
            if author not in stale or event.kind().as_u16() != KIND_PROFILE:
                continue
            try:
                valid = event.verify()
            except Exception:  # noqa: BLE001
                valid = False
            if not valid:
                continue
            prior = latest.get(author)
            if (
                prior is None
                or event.created_at().as_secs()
                > prior.created_at().as_secs()
            ):
                latest[author] = event
        for pubkey in stale:
            payload = {}
            event = latest.get(pubkey)
            if event is not None:
                try:
                    payload = _sanitize_profile(
                        json.loads(event.content() or "{}")
                    )
                except (TypeError, ValueError):
                    payload = {}
            await _store_profile(
                merchant_id, pubkey, payload,
                found=bool(payload), now=now, settings=settings,
            )
    return await profiles_for(merchant_id, requested, settings=settings)
