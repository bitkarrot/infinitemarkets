"""P0-05: NIP-17 encrypted fixtures — golden + seeded generated (QUAL-05).

Proves the section 6.9/8.5 gift-wrap contract against checked-in golden
fixtures (D-08) produced by the pinned SDK:

- (a) round-trip: every golden wrap unwraps to the exact golden rumor through
  the explicit section 8.5 verification chain (and cross-checks against the
  SDK composite ``UnwrappedGift.from_gift_wrap``);
- (b) tamper matrix: tampered outer content/signature, tampered seal
  content/signature, rumor/seal pubkey mismatch, non-canonical rumor id,
  signed rumor, duplicate common tags, wrong rumor kind, wrong outer kind,
  and wrong-recipient wraps are ALL rejected before trusted processing;
- (c) retry identity: the retry pair preserves the canonical rumor id with
  fresh seal/wrap/outer ids and wrapper keys; receivers dedupe by rumor id;
- (d) party routing: the recipient copy is published only to buyer relays
  and the sender copy only to merchant relays (section 9.3);
- (e) seeded generated edge cases: deterministic mutations of the golden
  wrap (oversized/missing/duplicated/bit-flipped fields) all reject;
- (f) no plaintext logging: decrypted rumor content and key material never
  appear in any log record across wrap/unwrap/reject paths.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path

import pytest
from nostr_sdk import (
    ClientBuilder,
    Event,
    EventBuilder,
    Kind,
    Nip44Version,
    NostrSigner,
    RelayUrl,
    Tag,
    UnsignedEvent,
    UnwrappedGift,
    nip44_encrypt,
)

from harness import relay as relay_module
from harness import sdk

pytestmark = [pytest.mark.protocol, pytest.mark.fast]

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "golden" / "nip17"
GENERATED_SEED = 20260920  # recorded per D-08 (deterministic edge cases)


@pytest.fixture(scope="module")
def golden() -> dict:
    """The checked-in golden NIP-17 chain."""
    keys_doc = json.loads((FIXTURES / "keys.json").read_text())
    return {
        "buyer": sdk.fixed_test_keys("buyer"),
        "merchant": sdk.fixed_test_keys("merchant"),
        "keys_doc": keys_doc,
        "rumor": json.loads((FIXTURES / "rumor.json").read_text()),
        "recipient_seal": json.loads((FIXTURES / "recipient" / "seal.json").read_text()),
        "recipient_wrap": json.loads((FIXTURES / "recipient" / "wrap.json").read_text()),
        "sender_seal": json.loads((FIXTURES / "sender" / "seal.json").read_text()),
        "sender_wrap": json.loads((FIXTURES / "sender" / "wrap.json").read_text()),
        "retry_seal": json.loads((FIXTURES / "retry" / "seal.json").read_text()),
        "retry_wrap": json.loads((FIXTURES / "retry" / "wrap.json").read_text()),
    }


def _wrap(golden: dict, name: str) -> Event:
    return Event.from_json(json.dumps(golden[name]))


def _rumor(golden: dict) -> UnsignedEvent:
    return sdk.rumor_from_json(golden["rumor"])


# --- (a) golden round-trip ---------------------------------------------------


async def test_golden_recipient_copy_unwraps_to_golden_rumor(golden):
    wrap = _wrap(golden, "recipient_wrap")
    seal, rumor = await sdk.unwrap_gift_wrap(golden["buyer"], wrap)
    assert rumor.id().to_hex() == golden["rumor"]["id"]
    assert rumor.id().to_hex() == sdk.canonical_rumor_id(rumor)
    assert seal.id().to_hex() == golden["recipient_seal"]["id"]
    # SDK composite unwrap agrees (cross-check of the explicit chain).
    un = await UnwrappedGift.from_gift_wrap(
        NostrSigner.keys(golden["buyer"]), wrap
    )
    assert un.rumor().id().to_hex() == rumor.id().to_hex()
    assert un.sender().to_hex() == golden["merchant"].public_key().to_hex()


async def test_golden_sender_copy_unwraps_to_golden_rumor(golden):
    """The sender copy's wrap is addressed to the merchant, but the rumor's
    ``p`` tag still names the message recipient (the buyer)."""
    wrap = _wrap(golden, "sender_wrap")
    seal, rumor = await sdk.unwrap_gift_wrap(
        golden["merchant"],
        wrap,
        expected_rumor_recipient=golden["buyer"].public_key(),
    )
    assert rumor.id().to_hex() == golden["rumor"]["id"]
    assert seal.id().to_hex() == golden["sender_seal"]["id"]


async def test_golden_wraps_are_independent_copies(golden):
    """Distinct outer ids + distinct ephemeral wrapper keys (section 6.9)."""
    recipient = _wrap(golden, "recipient_wrap")
    sender = _wrap(golden, "sender_wrap")
    assert recipient.id().to_hex() != sender.id().to_hex()
    assert recipient.author().to_hex() != sender.author().to_hex()
    # Exactly one p tag on each wrap, addressed to its party.
    r_p = [t.as_vec() for t in recipient.tags().to_vec() if t.as_vec()[0] == "p"]
    s_p = [t.as_vec() for t in sender.tags().to_vec() if t.as_vec()[0] == "p"]
    assert r_p == [["p", golden["buyer"].public_key().to_hex()]]
    assert s_p == [["p", golden["merchant"].public_key().to_hex()]]
    # Seal/wrap timestamps are independently randomized (section 6.9) — the
    # three timestamps are pairwise distinct.
    seal_r = Event.from_json(json.dumps(golden["recipient_seal"]))
    assert len({seal_r.created_at().as_secs(), recipient.created_at().as_secs(),
                sender.created_at().as_secs()}) == 3


# --- (b) tamper matrix --------------------------------------------------------


def _tampered(event_json: dict, **changes) -> Event:
    data = dict(event_json)
    data.update(changes)
    return Event.from_json(json.dumps(data))


async def _expect_reject(recipient, wrap: Event, reason: str) -> None:
    with pytest.raises(sdk.WrapRejection, match=reason):
        await sdk.unwrap_gift_wrap(recipient, wrap)


async def test_tampered_outer_content_rejected(golden):
    tampered = _tampered(golden["recipient_wrap"], content="AAAA")
    await _expect_reject(
        golden["buyer"], tampered, "outer-id-or-signature-invalid"
    )


async def test_tampered_outer_signature_rejected(golden):
    tampered = _tampered(golden["recipient_wrap"], sig="00" * 64)
    await _expect_reject(
        golden["buyer"], tampered, "outer-id-or-signature-invalid"
    )


async def test_wrong_outer_kind_rejected(golden):
    keys = sdk.generate_keys()
    other = EventBuilder.text_note("not a wrap").sign_with_keys(keys)
    await _expect_reject(golden["buyer"], other, "outer-kind-not-1059")


async def test_wrap_for_other_recipient_rejected(golden):
    """The sender copy p-tags the merchant — the buyer cannot claim it."""
    wrap = _wrap(golden, "sender_wrap")
    await _expect_reject(golden["buyer"], wrap, "outer-p-tag-not-recipient")


async def test_wrong_recipient_key_decrypt_fails(golden):
    """A wrap p-tagged to the buyer is not the stranger's to open."""
    stranger = sdk.fixed_test_keys("stranger")
    # The stranger's key sees the p tag is not theirs (rejected before decrypt).
    wrap = _wrap(golden, "recipient_wrap")
    await _expect_reject(stranger, wrap, "outer-p-tag-not-recipient")


async def test_valid_wrap_with_undecryptable_content_rejected(golden):
    """A correctly signed kind-1059 with a p tag to the buyer but garbage
    ciphertext is rejected at the outer-decrypt stage."""
    buyer = golden["buyer"]
    ephemeral = sdk.generate_keys()
    wrap = await (
        EventBuilder(Kind(1059), "not-a-nip44-payload")
        .tags([Tag.parse(["p", buyer.public_key().to_hex()])])
        .sign(NostrSigner.keys(ephemeral))
    )
    assert wrap.verify() is True  # valid outer — rejection must come from decrypt
    await _expect_reject(buyer, wrap, "outer-decrypt-failed")


async def test_tampered_seal_content_rejected(golden):
    """A valid wrap carrying a tampered seal is rejected at seal verify."""
    merchant = golden["merchant"]
    buyer = golden["buyer"]
    rumor = _rumor(golden)
    seal = await sdk.seal_rumor(merchant, buyer.public_key(), rumor)
    tampered_seal = _tampered(
        json.loads(seal.as_json()), content=seal.content()[:-4] + "AAAA"
    )
    wrap = sdk.wrap_seal(buyer.public_key(), tampered_seal)
    await _expect_reject(buyer, wrap, "seal-id-or-signature-invalid")


async def test_tampered_seal_signature_rejected(golden):
    merchant = golden["merchant"]
    buyer = golden["buyer"]
    rumor = _rumor(golden)
    seal = await sdk.seal_rumor(merchant, buyer.public_key(), rumor)
    tampered_seal = _tampered(json.loads(seal.as_json()), sig="11" * 64)
    wrap = sdk.wrap_seal(buyer.public_key(), tampered_seal)
    await _expect_reject(buyer, wrap, "seal-id-or-signature-invalid")


async def test_seal_with_nonempty_tags_rejected(golden):
    merchant = golden["merchant"]
    buyer = golden["buyer"]
    rumor = _rumor(golden)
    seal_builder = await EventBuilder.seal(
        NostrSigner.keys(merchant), buyer.public_key(), rumor
    )
    seal = await seal_builder.tags([Tag.parse(["x", "unexpected"])]).sign(
        NostrSigner.keys(merchant)
    )
    wrap = sdk.wrap_seal(buyer.public_key(), seal)
    await _expect_reject(buyer, wrap, "seal-tags-not-empty")


async def test_rumor_seal_pubkey_mismatch_rejected(golden):
    """Seal signed by a different key than the rumor author (section 8.5/6)."""
    buyer = golden["buyer"]
    impostor = sdk.fixed_test_keys("impostor")
    rumor = _rumor(golden)
    seal = await sdk.seal_rumor(impostor, buyer.public_key(), rumor)
    wrap = sdk.wrap_seal(buyer.public_key(), seal)
    await _expect_reject(buyer, wrap, "rumor-seal-pubkey-mismatch")


async def test_noncanonical_rumor_id_rejected(golden):
    """A rumor whose stored id is not the canonical NIP-01 hash is rejected."""
    merchant = golden["merchant"]
    buyer = golden["buyer"]
    bad_rumor = dict(golden["rumor"])
    bad_rumor["id"] = "ab" * 32
    rumor = UnsignedEvent.from_json(json.dumps(bad_rumor))
    seal = await sdk.seal_rumor(merchant, buyer.public_key(), rumor)
    wrap = sdk.wrap_seal(buyer.public_key(), seal)
    await _expect_reject(buyer, wrap, "rumor-id-not-canonical")


async def test_signed_rumor_rejected(golden):
    """A rumor carrying a ``sig`` field is not a rumor (section 8.5 step 6).

    ``UnsignedEvent.from_json`` silently drops ``sig``, so the signed-rumor
    payload is carried by a hand-sealed (SDK NIP-44) kind-13 whose content is
    the signed JSON verbatim.
    """
    merchant = golden["merchant"]
    buyer = golden["buyer"]
    signed = dict(golden["rumor"])
    signed["sig"] = "22" * 64
    seal = await _hand_seal(merchant, buyer.public_key(), signed)
    wrap = sdk.wrap_seal(buyer.public_key(), seal)
    await _expect_reject(buyer, wrap, "rumor-signed")


async def _hand_seal(author, recipient_pubkey, rumor_data: dict):
    """Seal a raw rumor dict (SDK NIP-44, no custom crypto).

    Used when the payload cannot survive the SDK builders — e.g. signed
    rumors or duplicated tags, both of which ``UnsignedEvent``/``EventBuilder``
    silently normalize away.
    """
    content = nip44_encrypt(
        author.secret_key(),
        recipient_pubkey,
        json.dumps(rumor_data),
        Nip44Version.V2,
    )
    return await EventBuilder(Kind(13), content).sign(NostrSigner.keys(author))


async def test_duplicate_common_tag_rejected(golden):
    """Section 6.9: duplicate common tags are rejected.

    The SDK tag parser dedupes, so the duplicate ``p`` is injected at the raw
    rumor-JSON level where the verification chain must still see it.
    """
    merchant = golden["merchant"]
    buyer = golden["buyer"]
    dup = dict(golden["rumor"])
    dup["tags"] = [list(t) for t in golden["rumor"]["tags"]]
    dup["tags"].append(["p", merchant.public_key().to_hex()])
    # Keep the stored id canonical for the mutated event so the rejection is
    # attributable to the tag rule, not the id check.
    rumor = UnsignedEvent.from_json(json.dumps(dup))
    dup["id"] = sdk.canonical_rumor_id(rumor)
    seal = await _hand_seal(merchant, buyer.public_key(), dup)
    wrap = sdk.wrap_seal(buyer.public_key(), seal)
    await _expect_reject(buyer, wrap, "rumor-p-tag-invalid")


async def test_validate_kind16_tags_counts_on_raw_json(golden):
    """``validate_kind16_tags`` sees duplicates the SDK parser would drop."""
    dup = dict(golden["rumor"])
    dup["tags"] = [list(t) for t in golden["rumor"]["tags"]]
    dup["tags"].append(["subject", "dup"])
    with pytest.raises(sdk.WrapRejection, match="kind16-subject-tag-count"):
        sdk.validate_kind16_tags(dup)
    sdk.validate_kind16_tags(dict(golden["rumor"]))  # clean rumor passes


async def test_wrong_rumor_kind_rejected(golden):
    merchant = golden["merchant"]
    buyer = golden["buyer"]
    rumor = (
        EventBuilder(Kind(9), "not an order message")
        .tags([Tag.parse(["p", buyer.public_key().to_hex()])])
        .build(merchant.public_key())
    )
    seal = await sdk.seal_rumor(merchant, buyer.public_key(), rumor)
    wrap = sdk.wrap_seal(buyer.public_key(), seal)
    await _expect_reject(buyer, wrap, "rumor-kind-not-allowed")


# --- (c) retry identity --------------------------------------------------------


async def test_retry_wrap_preserves_rumor_id(golden):
    buyer = golden["buyer"]
    first = _wrap(golden, "recipient_wrap")
    retry = _wrap(golden, "retry_wrap")

    _seal1, rumor1 = await sdk.unwrap_gift_wrap(buyer, first)
    _seal2, rumor2 = await sdk.unwrap_gift_wrap(buyer, retry)
    assert rumor1.id().to_hex() == rumor2.id().to_hex() == golden["rumor"]["id"]

    # Fresh seals, wrappers, outer ids, and timestamps across the retry.
    assert first.id().to_hex() != retry.id().to_hex()
    assert first.author().to_hex() != retry.author().to_hex()
    assert golden["recipient_seal"]["id"] != golden["retry_seal"]["id"]

    # Receivers dedupe retry wraps by rumor id (section 8.6 step 3).
    registry = sdk.IdRegistry()
    assert registry.admit(rumor1.id().to_hex()) is True
    assert registry.admit(rumor2.id().to_hex()) is False


# --- (d) party routing ---------------------------------------------------------


async def test_copies_route_only_to_their_partys_relays(golden):
    """Section 9.3: recipient copy -> buyer relays; sender copy -> merchant."""
    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as buyer_relay, relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as merchant_relay:
        client = await _client_for(golden["merchant"], buyer_relay, merchant_relay)
        try:
            recipient_wrap = _wrap(golden, "recipient_wrap")
            sender_wrap = _wrap(golden, "sender_wrap")
            out_r = await client.send_event_to(
                [RelayUrl.parse(buyer_relay.url)], recipient_wrap
            )
            out_s = await client.send_event_to(
                [RelayUrl.parse(merchant_relay.url)], sender_wrap
            )
            assert RelayUrl.parse(buyer_relay.url) in out_r.success
            assert RelayUrl.parse(merchant_relay.url) in out_s.success

            # Each relay received exactly its party's copy — no cross-set leak.
            assert [e["event"]["id"] for e in buyer_relay.received_events] == [
                recipient_wrap.id().to_hex()
            ]
            assert [e["event"]["id"] for e in merchant_relay.received_events] == [
                sender_wrap.id().to_hex()
            ]
        finally:
            await client.disconnect()
            await client.shutdown()


async def _client_for(keys, *relays):
    client = ClientBuilder().signer(NostrSigner.keys(keys)).build()
    for r in relays:
        assert await client.add_relay(RelayUrl.parse(r.url))
    await client.connect()
    return client


# --- (e) seeded generated edge cases (D-08) ------------------------------------

_GENERATED_CASES: list[tuple[str, dict]] = []


def _build_generated_cases() -> list[tuple[str, dict]]:
    """Deterministic mutations of the golden wrap, seeded per D-08."""
    rng = random.Random(GENERATED_SEED)
    base = json.loads((FIXTURES / "recipient" / "wrap.json").read_text())
    cases: list[tuple[str, dict]] = []

    oversized = dict(base)
    oversized["content"] = base["content"] + "A" * rng.choice([1024, 8192])
    cases.append(("oversized-content", oversized))

    missing_p = dict(base)
    missing_p["tags"] = []
    cases.append(("missing-p-tag", missing_p))

    dup_p = dict(base)
    dup_p["tags"] = [list(t) for t in base["tags"]] + [list(base["tags"][0])]
    cases.append(("duplicate-p-tag", dup_p))

    flipped = dict(base)
    sig = base["sig"]
    pos = rng.randrange(len(sig))
    flipped["sig"] = sig[:pos] + ("0" if sig[pos] != "0" else "1") + sig[pos + 1 :]
    cases.append(("bit-flipped-signature", flipped))

    truncated = dict(base)
    truncated["content"] = base["content"][: rng.randrange(1, 32)]
    cases.append(("truncated-content", truncated))

    wrong_kind = dict(base)
    wrong_kind["kind"] = rng.choice([13, 16, 4])
    cases.append(("wrong-outer-kind", wrong_kind))

    bad_id = dict(base)
    bad_id["id"] = "ff" * 32
    cases.append(("noncanonical-outer-id", bad_id))
    return cases


_GENERATED_CASES = _build_generated_cases()


@pytest.mark.parametrize(
    "name,tampered",
    _GENERATED_CASES,
    ids=[name for name, _ in _GENERATED_CASES],
)
async def test_seeded_generated_mutations_rejected(name, tampered, golden):
    """Every seeded mutation of a golden wrap must reject (D-08).

    Rejection is a clean error — a ``WrapRejection`` from the verification
    chain or a parse error from ``Event.from_json`` — never a silent accept.
    """
    with pytest.raises(Exception) as excinfo:
        await sdk.unwrap_gift_wrap(
            golden["buyer"], Event.from_json(json.dumps(tampered))
        )
    assert excinfo.value is not None


# --- (f) no plaintext logging --------------------------------------------------


async def test_no_plaintext_or_key_material_in_logs(golden, caplog):
    """PITFALLS NIP-17 privacy leak: decrypted rumor content and conversation
    keys must never appear in any log record across wrap/unwrap/reject."""
    rumor_content = golden["rumor"]["content"]
    secrets = [
        golden["keys_doc"]["buyer_secret_hex"],
        golden["keys_doc"]["merchant_secret_hex"],
        golden["recipient_wrap"]["content"],  # ciphertext is not logged either
        golden["recipient_seal"]["content"],
    ]
    with caplog.at_level(logging.DEBUG, logger="harness.sdk"):
        # accept path
        await sdk.unwrap_gift_wrap(
            golden["buyer"], _wrap(golden, "recipient_wrap")
        )
        # reject paths
        for name, tampered in _GENERATED_CASES:
            try:
                await sdk.unwrap_gift_wrap(
                    golden["buyer"],
                    Event.from_json(json.dumps(tampered)),
                )
            except Exception:  # noqa: BLE001 — rejections expected
                pass
        try:
            await sdk.unwrap_gift_wrap(
                golden["buyer"],
                _tampered(golden["recipient_wrap"], sig="00" * 64),
            )
        except Exception:  # noqa: BLE001
            pass

    rendered = "\n".join(
        record.getMessage() for record in caplog.records
    )
    for secret in secrets:
        assert secret not in rendered, "secret/ciphertext leaked into logs"
    if rumor_content:
        assert rumor_content not in rendered, (
            "decrypted rumor plaintext leaked into logs"
        )
