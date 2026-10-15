"""Keystore NIP-17 wrap/unwrap — the explicit section 8.5 chain against
the checked-in golden fixtures plus the tamper matrix.

The chain mirrors ``harness/sdk.py`` stage-for-stage (the qualified
reference): outer kind 1059 + verify -> exactly one ``p`` == recipient ->
seal kind 13 + empty tags + verify -> rumor unsigned + canonical id +
author match + kind in {14,16,17} + raw-JSON duplicate-tag rejection.
Rejection reasons are the same bounded vocabulary.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.runtime, pytest.mark.fast]

FIXTURES = (
    Path(__file__).resolve().parents[1] / "fixtures" / "golden" / "nip17"
)


def _fixture(*parts) -> dict:
    return json.loads((FIXTURES.joinpath(*parts)).read_text())


KEYS = _fixture("keys.json")
RUMOR = _fixture("rumor.json")


def _settings(keystore_env):
    return keystore_env["settings"].ext_settings()


async def _imported_keystore(keystore_env, monkeypatch):
    """MerchantKeyStore bound to the tmp DB with BOTH golden fixture
    identities imported. The module-scoped env reuses one DB, so merchant
    rows get per-test unique ids — returns ``(ks, {"buyer": mid,
    "merchant": mid})``."""
    import hashlib
    import uuid

    from infinitemarkets.db import table

    monkeypatch.setenv(
        "INFINITEMARKETS_MASTER_KEYS",
        json.dumps({"v1": base64.b64encode(bytes(32)).decode()}),
    )
    monkeypatch.setenv("INFINITEMARKETS_ACTIVE_KEY_VERSION", "v1")
    monkeypatch.setenv(
        "INFINITEMARKETS_PRIVACY_KEY",
        base64.b64encode(bytes([9]) * 32).decode(),
    )
    monkeypatch.setenv(
        "INFINITEMARKETS_PUBLIC_BASE_URL", "https://x.example"
    )
    keystore_mod = keystore_env["keystore"]
    settings = _settings(keystore_env)
    ks = keystore_mod.MerchantKeyStore(settings)
    db = keystore_env["db"]
    mids = {
        "buyer": f"m-buyer-{uuid.uuid4().hex[:10]}",
        "merchant": f"m-merchant-{uuid.uuid4().hex[:10]}",
    }
    for mid, secret_hex in (
        (mids["buyer"], KEYS["buyer_secret_hex"]),
        (mids["merchant"], KEYS["merchant_secret_hex"]),
    ):
        async with db.connect() as conn:
            await conn.execute(
                f"INSERT INTO {table('merchants')} "
                "(id, user_id, pubkey, key_ref, wallet_id_enc,"
                " wallet_id_hash, state, created_at, updated_at) "
                "VALUES (:i, :u, :p, :kr, :w, 'h', 'draft', 0, 0)",
                {
                    "i": mid,
                    "u": uuid.uuid4().hex,
                    "p": hashlib.sha256(mid.encode()).hexdigest(),
                    "kr": f"merchant_keys:{mid}",
                    "w": b"x",
                },
            )
        await ks.import_key(mid, secret_hex)
    return ks, mids


def _rumor_unsigned(data: dict):
    from nostr_sdk import UnsignedEvent

    return UnsignedEvent.from_json(json.dumps(data))


async def _seal_wrap(seal_secret_hex: str, recipient_hex: str,
                     plaintext: str, tags: list | None = None):
    """Build a signed kind-13 seal over arbitrary plaintext, then
    gift-wrap it — used to stage inner-layer tamper cases."""
    from nostr_sdk import (
        EventBuilder,
        Keys,
        Kind,
        Nip44Version,
        NostrSigner,
        PublicKey,
        Tag,
        gift_wrap_from_seal,
        nip44_encrypt,
    )

    keys = Keys.parse(seal_secret_hex)
    recipient = PublicKey.parse(recipient_hex)
    ciphertext = nip44_encrypt(
        keys.secret_key(), recipient, plaintext, Nip44Version.V2
    )
    builder = EventBuilder(Kind(13), ciphertext)
    if tags:
        builder = builder.tags([Tag.parse(t) for t in tags])
    seal = await builder.sign(NostrSigner.keys(keys))
    return gift_wrap_from_seal(recipient, seal)


def _unsigned_rumor(kind: int, author_hex: str, tags: list[list[str]],
                    content: str = "x", created_at: int = 1750000000):
    """A canonically-id'ed unsigned rumor built through the SDK builder."""
    from nostr_sdk import EventBuilder, Kind, PublicKey, Tag, Timestamp

    return (
        EventBuilder(Kind(kind), content)
        .custom_created_at(Timestamp.from_secs(created_at))
        .tags([Tag.parse(t) for t in tags])
        .build(PublicKey.parse(author_hex))
    )


async def _manual_wrap(outer_secret_hex: str, recipient_hex: str,
                       inner_event) -> object:
    """A kind-1059 wrap built without ``gift_wrap_from_seal`` — needed to
    stage inner-seal shapes the SDK's own wrap helper would refuse."""
    from nostr_sdk import (
        EventBuilder,
        Keys,
        Kind,
        Nip44Version,
        NostrSigner,
        PublicKey,
        Tag,
        nip44_encrypt,
    )

    keys = Keys.parse(outer_secret_hex)
    recipient = PublicKey.parse(recipient_hex)
    ciphertext = nip44_encrypt(
        keys.secret_key(), recipient, inner_event.as_json(),
        Nip44Version.V2,
    )
    return await (
        EventBuilder(Kind(1059), ciphertext)
        .tags([Tag.parse(["p", recipient_hex])])
        .sign(NostrSigner.keys(keys))
    )


async def _expect(ks, merchant_id: str, wrap, reason: str,
                  expected_rumor_recipient: str | None = None):
    with pytest.raises(Exception) as caught:
        await ks.nip17_unwrap(
            merchant_id, wrap,
            expected_rumor_recipient=expected_rumor_recipient,
        )
    assert type(caught.value).__name__ == "WrapRejection"
    assert caught.value.reason == reason, (
        f"expected {reason!r}, got {caught.value.reason!r}"
    )


# --- golden unwrap matrix ----------------------------------------------------


async def test_golden_recipient_copy_unwraps(keystore_env, monkeypatch):
    ks, mids = await _imported_keystore(keystore_env, monkeypatch)
    wrap_json = (FIXTURES / "recipient" / "wrap.json").read_text()
    result = await ks.nip17_unwrap(mids["buyer"], wrap_json)
    assert result["rumor_id"] == RUMOR["id"]
    assert result["kind"] == 16
    assert result["author_pubkey"] == KEYS["merchant_pubkey"]
    assert json.loads(result["rumor_json"])["id"] == RUMOR["id"]


async def test_golden_sender_copy_unwraps(keystore_env, monkeypatch):
    """The sender copy is addressed to the merchant but the rumor's ``p``
    still names the buyer — pass the expected rumor recipient."""
    ks, mids = await _imported_keystore(keystore_env, monkeypatch)
    wrap_json = (FIXTURES / "sender" / "wrap.json").read_text()
    result = await ks.nip17_unwrap(
        mids["merchant"], wrap_json,
        expected_rumor_recipient=KEYS["buyer_pubkey"],
    )
    assert result["rumor_id"] == RUMOR["id"]
    assert result["kind"] == 16
    assert result["author_pubkey"] == KEYS["merchant_pubkey"]


async def test_golden_retry_wrap_same_rumor(keystore_env, monkeypatch):
    """The retry copy carries the SAME canonical rumor id under a fresh
    seal/wrap (section 8.6 retry semantics)."""
    ks, mids = await _imported_keystore(keystore_env, monkeypatch)
    first = _fixture("recipient", "wrap.json")
    retry = _fixture("retry", "wrap.json")
    assert first["id"] != retry["id"]
    result = await ks.nip17_unwrap(mids["buyer"], json.dumps(retry))
    assert result["rumor_id"] == RUMOR["id"]


async def test_golden_kind14_and_kind17(keystore_env, monkeypatch):
    """kind-14 DM and kind-17 receipt rumors pass the allowlist."""
    ks, mids = await _imported_keystore(keystore_env, monkeypatch)

    # kind 14: merchant -> buyer
    rumor14 = _rumor_unsigned(_fixture("rumor_kind14.json"))
    wrap = await ks.nip17_wrap(
        mids["merchant"], rumor14, KEYS["buyer_pubkey"]
    )
    result = await ks.nip17_unwrap(mids["buyer"], wrap)
    assert result["kind"] == 14

    # kind 17: buyer -> merchant
    rumor17 = _rumor_unsigned(_fixture("rumor_kind17.json"))
    wrap = await ks.nip17_wrap(
        mids["buyer"], rumor17, KEYS["merchant_pubkey"]
    )
    result = await ks.nip17_unwrap(mids["merchant"], wrap)
    assert result["kind"] == 17


async def test_wrap_roundtrip_stable_rumor_fresh_wrap(keystore_env,
                                                      monkeypatch):
    """Two wraps of the same rumor produce DIFFERENT outer ids/seal
    ciphertexts but the identical canonical rumor id."""
    ks, mids = await _imported_keystore(keystore_env, monkeypatch)
    rumor = _rumor_unsigned(RUMOR)
    wrap_a = await ks.nip17_wrap(mids["merchant"], rumor, KEYS["buyer_pubkey"])
    wrap_b = await ks.nip17_wrap(mids["merchant"], rumor, KEYS["buyer_pubkey"])
    assert wrap_a.id().to_hex() != wrap_b.id().to_hex()
    assert wrap_a.content() != wrap_b.content()

    out_a = await ks.nip17_unwrap(mids["buyer"], wrap_a)
    out_b = await ks.nip17_unwrap(mids["buyer"], wrap_b)
    assert out_a["rumor_id"] == RUMOR["id"] == out_b["rumor_id"]
    assert json.loads(out_a["rumor_json"]) == RUMOR


# --- tamper matrix -----------------------------------------------------------


async def test_tamper_matrix(keystore_env, monkeypatch):
    """Every staged rejection maps to its bounded reason."""
    from nostr_sdk import (
        Event,
        EventBuilder,
        Keys,
        Kind,
        Nip44Version,
        NostrSigner,
        PublicKey,
        Tag,
        gift_wrap_from_seal,
        nip44_encrypt,
    )

    ks, mids = await _imported_keystore(keystore_env, monkeypatch)
    buyer_pk = KEYS["buyer_pubkey"]
    merchant_pk = KEYS["merchant_pubkey"]
    merchant_secret = KEYS["merchant_secret_hex"]

    # 1. outer kind != 1059 (valid signature, wrong kind).
    evil = Keys.generate()
    wrong_kind = await (
        EventBuilder(Kind(1), "x")
        .tags([Tag.parse(["p", buyer_pk])])
        .sign(NostrSigner.keys(evil))
    )
    await _expect(ks, mids["buyer"], wrong_kind, "outer-kind-not-1059")

    # 2. outer id/signature invalid — content tampered after signing.
    wrap_data = _fixture("recipient", "wrap.json")
    wrap_data["content"] = "QUJD"  # valid base64, wrong bytes
    bad_sig = Event.from_json(json.dumps(wrap_data))
    await _expect(ks, mids["buyer"], bad_sig, "outer-id-or-signature-invalid")

    # 3. two distinct p tags on the outer wrap.
    two_p = await (
        EventBuilder(Kind(1059), "QUJD")
        .tags([Tag.parse(["p", buyer_pk]), Tag.parse(["p", merchant_pk])])
        .sign(NostrSigner.keys(evil))
    )
    await _expect(ks, mids["buyer"], two_p, "outer-p-tag-count")

    # 3b. duplicate IDENTICAL p tags under a valid signature, fed as raw
    # JSON — the strict raw-count path.
    dup_p = await (
        EventBuilder(Kind(1059), "QUJD")
        .tags([Tag.parse(["p", buyer_pk]), Tag.parse(["p", buyer_pk])])
        .sign(NostrSigner.keys(evil))
    )
    await _expect(ks, mids["buyer"], dup_p.as_json(), "outer-p-tag-count")

    # 4. wrap addressed to a different recipient.
    stranger = Keys.generate()
    rumor = _rumor_unsigned(RUMOR)
    other = await _seal_wrap(
        merchant_secret, stranger.public_key().to_hex(), rumor.as_json()
    )
    await _expect(ks, mids["buyer"], other, "outer-p-tag-not-recipient")

    # 5. seal carries non-empty tags.
    tagged = await _seal_wrap(
        merchant_secret, buyer_pk, rumor.as_json(), tags=[["x", "1"]]
    )
    await _expect(ks, mids["buyer"], tagged, "seal-tags-not-empty")

    # 6. seal kind != 13 — a valid kind-14 event carrying ciphertext,
    # wrapped manually (the SDK's own wrap helper enforces kind 13).
    ct = nip44_encrypt(
        Keys.parse(merchant_secret).secret_key(),
        PublicKey.parse(buyer_pk),
        rumor.as_json(), Nip44Version.V2,
    )
    kind14_seal = await EventBuilder(Kind(14), ct).sign(
        NostrSigner.keys(Keys.parse(merchant_secret))
    )
    wrong_seal = await _manual_wrap(
        evil.secret_key().to_hex(), buyer_pk, kind14_seal
    )
    await _expect(ks, mids["buyer"], wrong_seal, "seal-kind-not-13")

    # 7. seal signature/id invalid — tamper the real seal inside a wrap.
    real_seal = Event.from_json(
        (FIXTURES / "recipient" / "seal.json").read_text()
    )
    seal_data = json.loads(real_seal.as_json())
    seal_data["content"] = "QUJD"
    tampered_seal = Event.from_json(json.dumps(seal_data))
    bad_seal = gift_wrap_from_seal(PublicKey.parse(buyer_pk), tampered_seal)
    await _expect(ks, mids["buyer"], bad_seal, "seal-id-or-signature-invalid")

    # 8. seal content does not decrypt (kind-13 shell around junk).
    junk_ct = await (
        EventBuilder(Kind(13), "QUJD")
        .sign(NostrSigner.keys(Keys.parse(merchant_secret)))
    )
    junk_seal = gift_wrap_from_seal(PublicKey.parse(buyer_pk), junk_ct)
    await _expect(ks, mids["buyer"], junk_seal, "seal-decrypt-failed")

    # 9. rumor carries a signature.
    signed_rumor = dict(RUMOR)
    signed_rumor["sig"] = "ab" * 64
    wrap_signed = await _seal_wrap(
        merchant_secret, buyer_pk, json.dumps(signed_rumor)
    )
    await _expect(ks, mids["buyer"], wrap_signed, "rumor-signed")

    # 10. rumor id != canonical NIP-01 hash.
    bad_id = dict(RUMOR)
    bad_id["id"] = "00" * 32
    wrap_bad_id = await _seal_wrap(
        merchant_secret, buyer_pk, json.dumps(bad_id)
    )
    await _expect(ks, mids["buyer"], wrap_bad_id, "rumor-id-not-canonical")

    # 11. rumor author != seal author (outer key is never identity).
    buyer_rumor = _unsigned_rumor(
        16, buyer_pk,
        [["p", buyer_pk], ["subject", "order"], ["type", "1"],
         ["order", "gq-order-01"]],
    )
    mismatch = await _seal_wrap(
        merchant_secret, buyer_pk, buyer_rumor.as_json()
    )
    await _expect(
        ks, mids["buyer"], mismatch, "rumor-seal-pubkey-mismatch"
    )

    # 12. rumor kind outside {14,16,17}.
    kind1_rumor = _unsigned_rumor(
        1, merchant_pk,
        [["p", buyer_pk], ["subject", "order"], ["type", "1"],
         ["order", "gq-order-01"]],
    )
    wrap_kind1 = await _seal_wrap(
        merchant_secret, buyer_pk, kind1_rumor.as_json()
    )
    await _expect(ks, mids["buyer"], wrap_kind1, "rumor-kind-not-allowed")

    # 13. duplicate common tag on the raw rumor JSON.
    dup_rumor = _unsigned_rumor(
        16, merchant_pk,
        [["p", buyer_pk], ["subject", "order"], ["subject", "order"],
         ["type", "1"], ["order", "gq-order-01"]],
    )
    wrap_dup = await _seal_wrap(
        merchant_secret, buyer_pk, dup_rumor.as_json()
    )
    await _expect(ks, mids["buyer"], wrap_dup, "rumor-duplicate-common-tag")

    # 14. rumor p tag does not name the message recipient.
    wrong_p_rumor = _unsigned_rumor(
        16, merchant_pk,
        [["p", merchant_pk], ["subject", "order"], ["type", "1"],
         ["order", "gq-order-01"]],
    )
    wrap_wrong_p = await _seal_wrap(
        merchant_secret, buyer_pk, wrong_p_rumor.as_json()
    )
    await _expect(ks, mids["buyer"], wrap_wrong_p, "rumor-p-tag-invalid")


# --- custody + logging ---------------------------------------------------------


async def test_nip04_still_release_gated(keystore_env, monkeypatch):
    ks, mids = await _imported_keystore(keystore_env, monkeypatch)
    keystore_mod = type(ks).__module__
    import importlib

    ks_mod = importlib.import_module(keystore_mod)
    with pytest.raises(ks_mod.ReleaseNotAvailable):
        await ks.nip04_decrypt(mids["buyer"], "pk", "ct")
    with pytest.raises(ks_mod.ReleaseNotAvailable):
        await ks.nip04_encrypt(mids["buyer"], "pk", "pt")


async def test_no_key_plaintext_or_ciphertext_in_logs(keystore_env,
                                                      monkeypatch):
    """Wrap/unwrap and rejection paths must never log key material, rumor
    plaintext, or wrap ciphertext (section 8.5/§16)."""
    from loguru import logger

    ks, mids = await _imported_keystore(keystore_env, monkeypatch)
    captured: list[str] = []
    sink_id = logger.add(lambda m: captured.append(str(m)), level="DEBUG")
    try:
        rumor = _rumor_unsigned(RUMOR)
        wrap = await ks.nip17_wrap(
            mids["merchant"], rumor, KEYS["buyer_pubkey"]
        )
        await ks.nip17_unwrap(mids["buyer"], wrap)
        await ks.nip17_unwrap(mids["buyer"], wrap.as_json())
        from nostr_sdk import Event

        with pytest.raises(Exception):
            await ks.nip17_unwrap(
                mids["buyer"],
                Event.from_json(
                    json.dumps(_fixture("sender", "wrap.json"))
                ),
            )
    finally:
        logger.remove(sink_id)

    blob = "".join(captured)
    for forbidden in (
        KEYS["buyer_secret_hex"],
        KEYS["merchant_secret_hex"],
        "Qualification fixture order message",  # rumor plaintext
        wrap.content(),                          # wrap ciphertext
    ):
        assert forbidden not in blob


async def test_nsec_deleted_in_finally_source():
    """Source assertion: every new crypto entry path releases keys in
    ``finally`` (same discipline as sign_event)."""
    import inspect

    import infinitemarkets.keystore as ks_mod

    wrap_src = inspect.getsource(ks_mod.MerchantKeyStore.nip17_wrap)
    unwrap_src = inspect.getsource(ks_mod.MerchantKeyStore.nip17_unwrap)
    for src in (wrap_src, unwrap_src):
        assert "finally:" in src and "del keys" in src
    # The SDK composite unwrap must never be CALLED — it skips the
    # section-8.5 checks this chain enforces (docstrings may name it).
    file_src = inspect.getsource(ks_mod)
    assert "UnwrappedGift(" not in file_src
    assert "from_gift_wrap(" not in file_src
