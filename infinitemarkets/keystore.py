"""MerchantKeyStore — local key backend (spec section 11.1/11.2).

The merchant nsec exists only as an AES-256-GCM envelope in
``merchant_keys``; raw key material is decrypted inside a keystore
operation, used for the single signing/unwrap call, and never cached,
logged, or attached to a long-lived SDK client. Python cannot guarantee
physical memory zeroization — residual risk documented in section 11.2.

NIP-04 methods exist on the interface per section 11.1 but raise
``ReleaseNotAvailable`` — they are Release C scope. NIP-17 wrap/unwrap
run the explicit section 8.5 verification chain inside the operation.
"""

from __future__ import annotations

import time
import uuid

from nostr_sdk import Keys, NostrSigner, UnsignedEvent

from . import crypto
from .db import DomainTransaction, db, table
from .settings import ExtSettings

KEY_ORIGIN_GENERATED = "generated"
KEY_ORIGIN_IMPORTED = "imported"


class KeystoreError(RuntimeError):
    pass


class ReleaseNotAvailable(KeystoreError):
    """Interface member exists per section 11.1 but belongs to Release B/C."""


class WrapRejection(KeystoreError):
    """A gift-wrap chain failed section 8.5 verification.

    ``reason`` is a BOUNDED code from the same vocabulary as
    ``harness/sdk.py``'s reject reasons — it never carries plaintext,
    ciphertext, key material, or untrusted string content.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


#: Rumor kinds the inbox may dispatch (section 8.5 step 8).
ALLOWED_RUMOR_KINDS = frozenset({14, 16, 17})

_KIND_SEAL = 13
_KIND_GIFT_WRAP = 1059


class MerchantKeyStore:
    def __init__(self, settings: ExtSettings) -> None:
        self._settings = settings

    # --- key lifecycle -------------------------------------------------------

    async def generate(
        self, merchant_id: str, *, transaction: DomainTransaction | None = None,
    ) -> str:
        """Generate a fresh keypair, persist the encrypted nsec, return pubkey.

        Refuses when a key row already exists — silent overwrite would
        orphan the old identity. Rotation goes through ``import_key`` (new
        material) or ``rewrap`` (same material, new master version).
        """
        if transaction is None:
            async with DomainTransaction() as tx:
                return await self.generate(merchant_id, transaction=tx)
        existing = await transaction.fetch_one(
            f"SELECT merchant_id FROM {transaction.table('merchant_keys')} "
            "WHERE merchant_id = :m",
            {"m": merchant_id},
        )
        if existing:
            raise KeystoreError(
                "merchant already has a key — use import_key or rewrap"
            )
        keys = Keys.generate()
        nsec = keys.secret_key().to_hex()
        try:
            await self._store(
                merchant_id, bytes.fromhex(nsec), KEY_ORIGIN_GENERATED,
                transaction=transaction, replace_existing=False,
            )
            return keys.public_key().to_hex()
        finally:
            del keys, nsec

    async def import_key(
        self, merchant_id: str, nsec_bech32: str, *,
        transaction: DomainTransaction | None = None,
    ) -> str:
        """Decode a bech32 nsec, validate, encrypt into ``merchant_keys``.

        ``Keys.parse`` validates the nsec1 prefix + secp256k1 range; the raw
        secret lives only inside this call.
        """
        try:
            keys = Keys.parse(nsec_bech32)
        except Exception as exc:
            raise KeystoreError("invalid nsec") from exc
        nsec_hex = keys.secret_key().to_hex()
        try:
            await self._store(
                merchant_id, bytes.fromhex(nsec_hex), KEY_ORIGIN_IMPORTED,
                transaction=transaction,
            )
            return keys.public_key().to_hex()
        finally:
            del keys, nsec_hex

    async def _store(
        self, merchant_id: str, nsec_bytes: bytes, origin: str, *,
        transaction: DomainTransaction | None = None, replace_existing: bool = True,
    ) -> None:
        if transaction is None:
            async with DomainTransaction() as tx:
                await self._store(
                    merchant_id, nsec_bytes, origin, transaction=tx,
                    replace_existing=replace_existing,
                )
            return
        s = self._settings
        envelope = crypto.encrypt(
            nsec_bytes,
            s.master_keys[s.active_key_version],
            record_id=merchant_id,
            table="merchant_keys",
            column="ciphertext",
            key_version=s.active_key_version,
        )
        nonce = envelope[crypto.VERSION_LEN : crypto.VERSION_LEN + crypto.NONCE_LEN]
        body = envelope[crypto.VERSION_LEN + crypto.NONCE_LEN :]
        update = (
            " ON CONFLICT (merchant_id) DO UPDATE SET"
            " key_origin = :o, key_version = :v, nonce = :n,"
            " ciphertext = :c, rotated_at = :t"
        ) if replace_existing else ""
        await transaction.execute(
            f"INSERT INTO {transaction.table('merchant_keys')} "
            "(merchant_id, key_origin, key_version, nonce, ciphertext, created_at) "
            "VALUES (:m, :o, :v, :n, :c, :t)" + update,
            {
                "m": merchant_id,
                "o": origin,
                "v": s.active_key_version,
                "n": nonce,
                "c": body,
                "t": int(time.time()),
            },
        )

    async def _load_nsec(self, merchant_id: str) -> bytes:
        """Decrypt the merchant nsec inside the operation; caller releases."""
        async with db.connect() as conn:
            row = await conn.fetchone(
                f"SELECT key_version, nonce, ciphertext FROM {table('merchant_keys')} "
                "WHERE merchant_id = :m",
                {"m": merchant_id},
            )
        if not row:
            raise KeystoreError("merchant key not found")
        version = row["key_version"]
        key = self._settings.master_keys.get(version)
        if key is None:
            raise KeystoreError("key version absent from keyring")
        envelope = (
            version.encode().ljust(crypto.VERSION_LEN, b"\x00")
            + bytes(row["nonce"])
            + bytes(row["ciphertext"])
        )
        return crypto.decrypt(
            envelope,
            key,
            record_id=merchant_id,
            table="merchant_keys",
            column="ciphertext",
            key_version=version,
        )

    async def _keys(self, merchant_id: str) -> Keys:
        nsec = await self._load_nsec(merchant_id)
        try:
            return Keys.parse(nsec.hex())
        finally:
            del nsec

    async def public_key(self, merchant_id: str) -> str:
        keys = await self._keys(merchant_id)
        try:
            return keys.public_key().to_hex()
        finally:
            del keys

    async def export_key(self, merchant_id: str) -> str:
        """Return the merchant nsec to the owner after an explicit request."""
        nsec = await self._load_nsec(merchant_id)
        try:
            keys = Keys.parse(nsec.hex())
            try:
                return keys.secret_key().to_bech32()
            finally:
                del keys
        finally:
            del nsec

    async def sign_event(self, merchant_id: str, unsigned: UnsignedEvent):
        """Sign ``unsigned`` with the merchant key; key is released on exit."""
        keys = await self._keys(merchant_id)
        try:
            signer = NostrSigner.keys(keys)
            return await signer.sign_event(unsigned)
        finally:
            del keys

    async def delete(self, merchant_id: str) -> None:
        """Erase key material (deactivation final step — see section 6.7)."""
        async with db.connect() as conn:
            await conn.execute(
                f"DELETE FROM {table('merchant_keys')} WHERE merchant_id = :m",
                {"m": merchant_id},
            )

    # --- rotation (resumable, section 11.2) -----------------------------------

    async def rewrap(self, merchant_id: str) -> bool:
        """Re-encrypt one merchant key under the active version.

        Returns True when the row already uses the active version or was
        rewrapped; False when the row's version is absent from the keyring
        (operator must restore the old key before rotation can finish).
        Bounded: one row per call — the rotation job loops over stale rows.
        """
        async with db.connect() as conn:
            row = await conn.fetchone(
                f"SELECT key_version, key_origin FROM {table('merchant_keys')} "
                "WHERE merchant_id = :m",
                {"m": merchant_id},
            )
        if not row:
            raise KeystoreError("merchant key not found")
        active = self._settings.active_key_version
        if row["key_version"] == active:
            return True
        if row["key_version"] not in self._settings.master_keys:
            return False
        nsec = await self._load_nsec(merchant_id)
        try:
            await self._store(merchant_id, nsec, row["key_origin"])
        finally:
            del nsec
        return True

    async def stale_versions(self) -> list[str]:
        """Key versions still present in merchant_keys — for the rotation
        job's 'zero old-version rows' gate."""
        async with db.connect() as conn:
            rows = await conn.fetchall(
                f"SELECT DISTINCT key_version AS v FROM {table('merchant_keys')}"
            )
        return [r["v"] for r in rows]

    async def stale_merchants(self) -> list[str]:
        """merchant_ids whose key rows are NOT on the active version — the
        rotation job's work list."""
        async with db.connect() as conn:
            rows = await conn.fetchall(
                f"SELECT merchant_id AS m FROM {table('merchant_keys')} "
                "WHERE key_version != :v ORDER BY merchant_id",
                {"v": self._settings.active_key_version},
            )
        return [r["m"] for r in rows]

    # --- backup/restore (envelope only — never plaintext) ---------------------

    async def export_encrypted(self, merchant_id: str) -> str:
        """Serialize the encrypted key row to a portable JSON blob.

        The blob stays ciphertext end-to-end — backup safety reduces to
        protecting the master keyring, not the export file.
        """
        import base64
        import json

        async with db.connect() as conn:
            row = await conn.fetchone(
                "SELECT key_origin, key_version, nonce, ciphertext,"
                " created_at FROM " + table("merchant_keys") +
                " WHERE merchant_id = :m",
                {"m": merchant_id},
            )
        if not row:
            raise KeystoreError("merchant key not found")
        return json.dumps(
            {
                "merchant_id": merchant_id,
                "key_origin": row["key_origin"],
                "key_version": row["key_version"],
                "nonce": base64.b64encode(bytes(row["nonce"])).decode(),
                "ciphertext": base64.b64encode(
                    bytes(row["ciphertext"])
                ).decode(),
                "created_at": row["created_at"],
            }
        )

    async def restore_encrypted(self, merchant_id: str, blob: str) -> None:
        """Restore an ``export_encrypted`` blob; refuses to overwrite an
        existing row."""
        import base64
        import json

        try:
            record = json.loads(blob)
            nonce = base64.b64decode(record["nonce"], validate=True)
            ciphertext = base64.b64decode(
                record["ciphertext"], validate=True
            )
            version = record["key_version"]
            origin = record["key_origin"]
        except (KeyError, ValueError, TypeError) as exc:
            raise KeystoreError("malformed key backup") from exc
        async with db.connect() as conn:
            existing = await conn.fetchone(
                f"SELECT merchant_id FROM {table('merchant_keys')} "
                "WHERE merchant_id = :m",
                {"m": merchant_id},
            )
            if existing:
                raise KeystoreError("merchant key already exists")
            await conn.execute(
                f"INSERT INTO {table('merchant_keys')} "
                "(merchant_id, key_origin, key_version, nonce, ciphertext,"
                " created_at) VALUES (:m, :o, :v, :n, :c, :t)",
                {
                    "m": merchant_id,
                    "o": origin,
                    "v": version,
                    "n": nonce,
                    "c": ciphertext,
                    "t": int(time.time()),
                },
            )

    # --- Release B/C interface members (section 11.1) -------------------------

    async def nip17_wrap(self, merchant_id, unsigned_rumor, recipient_pubkey):
        """Seal + gift-wrap ``unsigned_rumor`` for ``recipient_pubkey``.

        The merchant nsec is decrypted inside this operation and released
        in ``finally`` — identical custody discipline to ``sign_event``.
        Each call emits a fresh seal and a fresh ephemeral wrapper key with
        NIP-59-randomized past timestamps (the SDK owns both), so retries
        of the same rumor produce different outer ids/ciphertexts while
        the canonical rumor id stays stable (section 8.6 step 3).
        """
        from nostr_sdk import (
            EventBuilder,
            NostrSigner,
            PublicKey,
            gift_wrap_from_seal,
        )

        keys = await self._keys(merchant_id)
        try:
            recipient = (
                recipient_pubkey
                if isinstance(recipient_pubkey, PublicKey)
                else PublicKey.parse(recipient_pubkey)
            )
            signer = NostrSigner.keys(keys)
            builder = await EventBuilder.seal(
                signer, recipient, unsigned_rumor
            )
            seal = await builder.sign(signer)
            # gift_wrap_from_seal is SYNCHRONOUS in nostr-sdk 0.44.8 —
            # it generates the one-time outer key + randomized timestamp.
            return gift_wrap_from_seal(recipient, seal)
        finally:
            del keys

    async def nip17_unwrap(self, merchant_id, signed_gift_wrap,
                           expected_rumor_recipient=None):
        """The explicit section 8.5 verification chain for one wrap.

        ``signed_gift_wrap`` is a signed kind-1059 ``Event`` or its raw JSON
        string. ``expected_rumor_recipient`` defaults to the merchant's own
        pubkey (buyer -> merchant intake); pass the BUYER pubkey when
        validating a recovered sender copy (the wrap is addressed to the
        merchant but the rumor's ``p`` still names the buyer).

        Returns ``{rumor_json, rumor_id, kind, author_pubkey}`` — no SDK
        event objects leak out (the caller adapts to domain). Rejections
        raise :class:`WrapRejection` with a bounded reason.
        """
        keys = await self._keys(merchant_id)
        try:
            return _unwrap_gift_wrap(
                keys, signed_gift_wrap, expected_rumor_recipient
            )
        finally:
            del keys

    async def nip04_decrypt(self, merchant_id, peer_pubkey, ciphertext):
        raise ReleaseNotAvailable("NIP-04 compat is Release C scope")

    async def nip04_encrypt(self, merchant_id, peer_pubkey, plaintext):
        raise ReleaseNotAvailable("NIP-04 compat is Release C scope")


def _reject(reason: str) -> None:
    """Bounded rejection — ids/reasons only, never content (section 8.5)."""
    from loguru import logger

    logger.info(
        "event=infinitemarkets.keystore.wrap_rejected reason={}", reason
    )
    raise WrapRejection(reason)


def _single_tag_values(event_tags, name: str) -> list[str]:
    return [
        tag.as_vec()[1]
        for tag in event_tags.to_vec()
        if tag.as_vec() and tag.as_vec()[0] == name and len(tag.as_vec()) >= 2
    ]


def _canonical_rumor_id(rumor) -> str:
    """Canonical NIP-01 id of a rumor, recomputed through the SDK.

    ``UnsignedEvent.id()`` returns the STORED field — it does not recompute
    the hash — so the canonical id is derived by rebuilding the event with
    the same (pubkey, created_at, kind, tags, content) through the SDK
    builder. Never hand-rolled sha256 (unicode escaping edge cases).
    """
    from nostr_sdk import EventBuilder, Tag

    rebuilt = (
        EventBuilder(rumor.kind(), rumor.content())
        .custom_created_at(rumor.created_at())
        .tags([Tag.parse(tag.as_vec()) for tag in rumor.tags().to_vec()])
        .build(rumor.author())
    )
    return rebuilt.id().to_hex()


def _unwrap_gift_wrap(keys, wrap_input,
                      expected_rumor_recipient) -> dict:
    """Section 8.5 verification chain, stage-for-stage identical to
    ``harness/sdk.py`` ``unwrap_gift_wrap`` (the qualified reference).

    ``UnwrappedGift.from_gift_wrap`` is deliberately NOT used: the SDK
    composite skips the p-tag count/recipient, seal-empty-tags, canonical
    rumor-id, and raw-JSON duplicate-tag checks this chain enforces.
    """
    import json

    from nostr_sdk import (
        Event,
        UnsignedEvent,
        nip44_decrypt,
    )

    wrap_raw: dict | None = None
    if isinstance(wrap_input, str):
        try:
            wrap_raw = json.loads(wrap_input)
        except (TypeError, ValueError):
            _reject("outer-unparseable")
        if not isinstance(wrap_raw, dict):
            _reject("outer-unparseable")
        try:
            wrap = Event.from_json(wrap_input)
        except Exception:  # noqa: BLE001 — bounded vocabulary
            _reject("outer-unparseable")
    else:
        wrap = wrap_input

    merchant_pubkey = keys.public_key().to_hex()
    expected_hex = (
        expected_rumor_recipient.to_hex()
        if hasattr(expected_rumor_recipient, "to_hex")
        else expected_rumor_recipient
    ) or merchant_pubkey

    # Stage 1 — outer kind + outer id/signature.
    if wrap.kind().as_u16() != _KIND_GIFT_WRAP:
        _reject("outer-kind-not-1059")
    if not wrap.verify():
        _reject("outer-id-or-signature-invalid")

    # Stage 2 — exactly one p tag equal to the wrap recipient. When the
    # raw JSON is available the count runs on it directly: the SDK parser
    # dedupes duplicate tags, hiding [p,X][p,X] from parsed-level checks.
    if wrap_raw is not None:
        raw_tags = wrap_raw.get("tags") or []
        raw_p = [
            t[1] for t in raw_tags
            if isinstance(t, list) and len(t) >= 2 and t[0] == "p"
        ]
        if len(raw_p) != 1:
            _reject("outer-p-tag-count")
    p_values = _single_tag_values(wrap.tags(), "p")
    if len(p_values) != 1:
        _reject("outer-p-tag-count")
    if p_values[0] != merchant_pubkey:
        _reject("outer-p-tag-not-recipient")

    # Stage 3 — NIP-44-decrypt outer content -> seal JSON.
    try:
        seal_json = nip44_decrypt(
            keys.secret_key(), wrap.author(), wrap.content()
        )
    except Exception:  # noqa: BLE001 — any decrypt failure is a clean reject
        _reject("outer-decrypt-failed")
    try:
        seal = Event.from_json(seal_json)
    except Exception:  # noqa: BLE001
        _reject("seal-unparseable")

    # Stage 4 — seal kind 13, empty tags, id+signature verify.
    if seal.kind().as_u16() != _KIND_SEAL:
        _reject("seal-kind-not-13")
    if not seal.tags().is_empty():
        _reject("seal-tags-not-empty")
    if not seal.verify():
        _reject("seal-id-or-signature-invalid")

    # Stage 5 — NIP-44-decrypt seal content -> rumor.
    try:
        rumor_json = nip44_decrypt(
            keys.secret_key(), seal.author(), seal.content()
        )
    except Exception:  # noqa: BLE001
        _reject("seal-decrypt-failed")

    rumor_data: dict
    try:
        rumor_data = json.loads(rumor_json)
    except (TypeError, ValueError):
        _reject("rumor-unparseable")
    if not isinstance(rumor_data, dict):
        _reject("rumor-unparseable")
    if rumor_data.get("sig"):
        _reject("rumor-signed")
    try:
        rumor = UnsignedEvent.from_json(rumor_json)
    except Exception:  # noqa: BLE001
        _reject("rumor-unparseable")

    # Stage 6 — unsigned rumor, canonical id, author == seal author.
    if rumor.id().to_hex() != _canonical_rumor_id(rumor):
        _reject("rumor-id-not-canonical")
    if rumor.author().to_hex() != seal.author().to_hex():
        _reject("rumor-seal-pubkey-mismatch")

    # Stage 7 — rumor kind allowlist.
    if rumor.kind().as_u16() not in ALLOWED_RUMOR_KINDS:
        _reject("rumor-kind-not-allowed")

    # Stage 8 — duplicate common tags + exactly one rumor p tag equal to
    # the message recipient, counted on the RAW JSON tag list (the SDK
    # parser dedupes duplicate tags, so a parsed-level check could never
    # see them — section 6.9 rejects duplicated common tags).
    raw_tags = rumor_data.get("tags")
    if not isinstance(raw_tags, list):
        _reject("rumor-unparseable")
    raw_names = [
        t[0] for t in raw_tags if isinstance(t, list) and t
    ]
    for name in ("subject", "type", "order"):
        if raw_names.count(name) > 1:
            _reject("rumor-duplicate-common-tag")
    raw_p = [
        t[1]
        for t in raw_tags
        if isinstance(t, list) and len(t) >= 2 and t[0] == "p"
    ]
    # Sender copies: the wrap is addressed to the merchant but the
    # merchant authored the rumor — the rumor's p tag names the message's
    # real recipient (the buyer), not the wrap recipient (section 8.5
    # sender-copy recovery). Inbound buyer wraps still require
    # p == merchant.
    sender_copy = (
        expected_rumor_recipient is None
        and rumor.author().to_hex() == merchant_pubkey
    )
    if len(raw_p) != 1 or (not sender_copy and raw_p[0] != expected_hex):
        _reject("rumor-p-tag-invalid")

    from loguru import logger

    logger.info(
        "event=infinitemarkets.keystore.wrap_accepted rumor_id={} kind={}",
        rumor.id().to_hex(),
        rumor.kind().as_u16(),
    )
    return {
        "rumor_json": rumor_json,
        "rumor_id": rumor.id().to_hex(),
        "kind": rumor.kind().as_u16(),
        "author_pubkey": rumor.author().to_hex(),
    }


def key_store(settings: ExtSettings | None = None) -> MerchantKeyStore:
    from .settings import ext_settings

    return MerchantKeyStore(settings or ext_settings())


def new_id() -> str:
    return uuid.uuid4().hex
