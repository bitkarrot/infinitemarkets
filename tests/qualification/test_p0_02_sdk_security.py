"""P0-02: SDK security/FFI/crypto probes (QUAL-02).

SDK-internal probes (blocking under D-13/D-16):

- invalid-event rejection: tampered content (id mismatch), tampered
  signatures, malformed ids, and malformed JSON are rejected by the SDK
  verification path before any trusted processing — clean errors, not
  crashes;
- oversized NIP-44 input: a multi-megabyte crafted ciphertext is rejected
  with bounded wall time and no unbounded memory growth (tracemalloc);
- paused-signing AUTH boundedness: a client with no auth credential
  (signing not performed) connected to an AUTH_FLOOD relay shows bounded
  work, no exception storm, and stays responsive;
- the tested binary identity is recorded (installed native library).

Admission-modeled check (extension-side defense in depth only, D-16):

- known-ID repetition: an id-registry dedupe admits a valid event id
  exactly once.

If nostr-sdk 0.44.8 fails any blocking SDK-internal check, Phase 1 stays
blocked (D-13/D-14) — extension-level input checks cannot waive it (D-16).
"""

from __future__ import annotations

import asyncio
import time
import tracemalloc

import pytest

from harness import evidence, sdk
from harness import pins as pins_module
from harness import relay as relay_module

pytestmark = [pytest.mark.sdk, pytest.mark.fast]

# Oversized-input probe bounds. Measured against the installed 0.44.8:
# ~0.09s/MB wall time, ~1.05x input-size peak Python allocation. The bounds
# are set to catch hangs and amplification, not to be tight.
OVERSIZED_INPUT_BYTES = 4 * 1024 * 1024
OVERSIZED_WALL_BOUND_S = 5.0
ALLOC_PROBE_INPUT_BYTES = 2 * 1024 * 1024
ALLOC_PROBE_PEAK_BOUND_BYTES = 4 * ALLOC_PROBE_INPUT_BYTES

AUTH_FLOOD_CHALLENGES = 200
AUTH_PROBE_WALL_BOUND_S = 30.0


# --- tracer probes (Task 1) ---------------------------------------------------


async def test_ffi_import_and_keypair_generation():
    """The FFI import loads and key generation works through the SDK."""
    keys_a = sdk.generate_keys()
    keys_b = sdk.generate_keys()
    assert keys_a.public_key().to_hex() != keys_b.public_key().to_hex()


async def test_build_sign_and_verify_event():
    keys = sdk.generate_keys()
    event = await sdk.sign_text_note(keys, "gamma qualification tracer")
    assert sdk.verify_event(event) is True
    assert event.verify_id() is True
    assert event.verify_signature() is True


async def test_tampered_event_fails_verification():
    keys = sdk.generate_keys()
    event = await sdk.sign_text_note(keys, "original content")
    assert sdk.verify_event(event) is True

    tampered_content = sdk.tamper_event(event, content="tampered content")
    assert sdk.verify_event(tampered_content) is False

    tampered_sig = sdk.tamper_event(event, sig="00" * 64)
    assert sdk.verify_event(tampered_sig) is False
    assert tampered_sig.verify_signature() is False


async def test_nip44_encrypt_decrypt_roundtrip():
    sender = sdk.generate_keys()
    recipient = sdk.generate_keys()
    plaintext = "gamma nip44 roundtrip"
    assert sdk.nip44_roundtrip(sender, recipient, plaintext) == plaintext


# --- P0-02 (a): invalid-event rejection (SDK-internal) ------------------------


async def test_invalid_events_rejected_before_trusted_processing():
    """Tampered content/sig/malformed ids/malformed JSON: clean rejection."""
    evidence.note_subcheck("invalid-event-rejection", "sdk-internal")
    keys = sdk.generate_keys()
    event = await sdk.sign_text_note(keys, "trusted content")
    assert sdk.verify_event(event) is True

    # Tampered content -> id no longer matches the serialized event.
    tampered = sdk.tamper_event(event, content="attacker content")
    assert sdk.verify_event(tampered) is False
    assert tampered.verify_id() is False

    # Tampered signature.
    bad_sig = sdk.tamper_event(event, sig="ff" * 64)
    assert bad_sig.verify() is False
    assert bad_sig.verify_signature() is False

    # Malformed id: valid JSON event shape, id that matches nothing.
    malformed = sdk.tamper_event(event, id="ab" * 32)
    assert malformed.verify() is False
    assert malformed.verify_id() is False

    # Malformed JSON: a clean error, not a crash.
    with pytest.raises(Exception):  # noqa: B017,PT011 - any clean SDK error
        sdk.Event.from_json("this is not json at all")


# --- P0-02 (b): known-ID repetition (admission-modeled, D-16) ------------------


async def test_known_id_repetition_admitted_exactly_once():
    """Admission-modeled dedupe: the same valid event id processes once."""
    evidence.note_subcheck("known-id-repetition-dedupe", "admission-modeled")
    keys = sdk.generate_keys()
    event = await sdk.sign_text_note(keys, "replayed event")
    assert sdk.verify_event(event) is True

    registry = sdk.IdRegistry()
    eid = sdk.event_id(event)
    # Feed the same valid event id through the admission helper repeatedly.
    admissions = [registry.admit(eid) for _ in range(10)]
    assert admissions == [True] + [False] * 9, "exactly-once admission"
    assert len(registry) == 1


# --- P0-02 (c): oversized NIP-44 input (SDK-internal) --------------------------


async def test_oversized_nip44_input_rejected_with_bounded_cost():
    """Multi-megabyte crafted ciphertext: clean rejection, bounded time/memory."""
    evidence.note_subcheck("oversized-nip44-input", "sdk-internal")
    recipient = sdk.generate_keys()
    sender = sdk.generate_keys()
    crafted = "A" * OVERSIZED_INPUT_BYTES

    # Wall time without tracing overhead.
    started = time.monotonic()
    with pytest.raises(Exception):  # noqa: B017,PT011 - clean SDK rejection
        sdk.nip44_decrypt(recipient.secret_key(), sender.public_key(), crafted)
    elapsed = time.monotonic() - started
    assert elapsed < OVERSIZED_WALL_BOUND_S, (
        f"oversized NIP-44 input rejection took {elapsed:.2f}s "
        f"(bound {OVERSIZED_WALL_BOUND_S}s) — not bounded before full decode"
    )

    # Python-side allocation growth with tracemalloc: no amplification.
    probe_input = "A" * ALLOC_PROBE_INPUT_BYTES
    tracemalloc.start()
    try:
        started = time.monotonic()
        with pytest.raises(Exception):  # noqa: B017,PT011
            sdk.nip44_decrypt(
                recipient.secret_key(), sender.public_key(), probe_input
            )
        elapsed = time.monotonic() - started
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < ALLOC_PROBE_PEAK_BOUND_BYTES, (
        f"peak Python allocation {peak / 1e6:.1f}MB during oversized-input "
        f"rejection exceeds bound {ALLOC_PROBE_PEAK_BOUND_BYTES / 1e6:.1f}MB "
        "— unbounded memory growth"
    )
    assert elapsed < OVERSIZED_WALL_BOUND_S


# --- P0-02 (d): paused-signing AUTH boundedness (SDK-internal) ----------------


async def test_auth_flood_bounded_with_signing_paused():
    """A large bounded number of AUTH challenges with no auth credential.

    The client is built WITHOUT a signer (no auth credential supplied —
    verified against the installed SDK: ClientBuilder().build() yields a
    client that cannot sign), so relay AUTH challenges are left unanswered.
    """
    evidence.note_subcheck("paused-signing-auth-boundedness", "sdk-internal")
    from nostr_sdk import ClientBuilder, RelayUrl

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.AUTH_FLOOD,
        auth_challenge_count=AUTH_FLOOD_CHALLENGES,
    ) as local:
        client = ClientBuilder().build()  # no signer: signing not performed
        try:
            assert await client.add_relay(RelayUrl.parse(local.url)), (
                "relay must be added"
            )
            started = time.monotonic()
            await asyncio.wait_for(client.connect(), timeout=10)
            # The relay floods AUTH challenges on connect; the client
            # without a credential cannot answer them.
            deadline = time.monotonic() + AUTH_PROBE_WALL_BOUND_S
            while (
                local.auth_challenges_sent < AUTH_FLOOD_CHALLENGES
                and time.monotonic() < deadline
            ):
                await asyncio.sleep(0.05)
            elapsed = time.monotonic() - started

            assert local.auth_challenges_sent >= AUTH_FLOOD_CHALLENGES, (
                "relay must have flooded the configured number of challenges"
            )
            assert elapsed < AUTH_PROBE_WALL_BOUND_S, (
                f"AUTH flood handling took {elapsed:.1f}s — work is not bounded"
            )
            # No exception storm and the client remains responsive.
            relays = await asyncio.wait_for(client.relays(), timeout=10)
            assert local.url.replace("ws://", "") in str(relays) or len(relays) >= 1
            # Client saw the challenges and sent no authenticated response:
            # an unsigned client cannot AUTH, and the fixture recorded no OK.
            assert not any(
                msg.startswith('["OK"')
                for msg in local.received_messages
            )
        finally:
            await client.disconnect()
            await client.shutdown()


# --- P0-02 (e): tested binary identity (SDK-internal provenance) --------------


async def test_tested_binary_identity_recorded_into_evidence_pins():
    """P0-02: record the tested binary (installed native library identity)."""
    evidence.note_subcheck("tested-binary-recorded", "sdk-internal")
    identity = pins_module.record_tested_binary()
    assert identity["filename"], "native library filename must be recorded"
    assert len(identity["sha256"]) == 64, "native library sha256 must be recorded"
    assert identity["size_bytes"] > 0
    assert pins_module.snapshot()["nostr_sdk_native_library"] == identity


# --- P0-02 (f): the D-16 disclosure renders mechanically ----------------------


async def test_d16_subcheck_attribution_recorded():
    """Every P0-02 subcheck above is attributed in the evidence manifest."""
    attribution = evidence._SUBCHECKS  # noqa: SLF001 - probe self-check
    p0_02_subchecks = {
        name
        for subchecks in attribution.values()
        for name in {s["name"] for s in subchecks}
    }
    expected = {
        "invalid-event-rejection",
        "known-id-repetition-dedupe",
        "oversized-nip44-input",
        "paused-signing-auth-boundedness",
        "tested-binary-recorded",
    }
    assert expected <= p0_02_subchecks
    # And the attribution kinds are the D-16 vocabulary.
    kinds = {
        s["kind"]
        for subchecks in attribution.values()
        for s in subchecks
    }
    assert kinds <= {"sdk-internal", "admission-modeled"}
