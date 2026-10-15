"""P0-04: relay ACK classification + targeted routing (QUAL-04).

Deterministic local relays are authoritative (section 9.1): an accepting
relay produces a positive OK, a rejecting relay a negative OK carrying the
relay's message, and a silent relay a timeout — all surfaced per-relay by
the SDK's ``SendEventOutput`` (verified against nostr-sdk 0.44.8:
``.success`` is a list of RelayUrl, ``.failed`` maps RelayUrl -> reason
string, where a negative OK carries the relay's message verbatim and a
missing OK surfaces as ``'timeout'``).

WebSocket send success alone is NEVER delivery evidence (section 8.6):
publication is proven only by the relay's OK classification. And an explicit
target list must never fan out to unlisted relays (section 9.3).

The optional ``wss://nostr.net`` smoke (``GAMMA_QUAL_SMOKE_RELAY``) is
advisory-only per section 21.27: ephemeral throwaway key, non-sensitive
synthetic event, never a substitute for the local evidence.
"""

from __future__ import annotations

import os

import pytest
from nostr_sdk import ClientBuilder, EventBuilder, NostrSigner, RelayUrl

from harness import evidence, sdk
from harness import relay as relay_module

pytestmark = [pytest.mark.protocol, pytest.mark.fast]

SMOKE_RELAY_ENV = "GAMMA_QUAL_SMOKE_RELAY"


def classify(output, url: str) -> tuple[str, str | None]:
    """Classify one relay's result from a SendEventOutput.

    Returns ``("accepted"|"rejected"|"timeout", message)`` — the
    ``relay_publications.result`` vocabulary of section 4.10.
    """
    relay_url = RelayUrl.parse(url)
    if relay_url in output.success:
        return "accepted", None
    if relay_url in output.failed:
        reason = str(output.failed[relay_url])
        if reason == "timeout":
            return "timeout", None
        return "rejected", reason
    raise AssertionError(f"relay {url} absent from send output")


async def _client(*relays: relay_module.LocalRelay, signer_keys=None) -> "object":
    keys = signer_keys or sdk.generate_keys()
    client = (
        ClientBuilder().signer(NostrSigner.keys(keys)).build()
    )
    for r in relays:
        assert await client.add_relay(RelayUrl.parse(r.url))
    await client.connect()
    return client


async def test_positive_negative_and_timeout_acks_classified_per_relay():
    """One fan-out, three outcomes: positive OK / negative OK / timeout."""
    keys = sdk.generate_keys()
    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as accepting, relay_module.LocalRelay(
        mode=relay_module.RelayMode.REJECTING
    ) as rejecting, relay_module.LocalRelay(
        mode=relay_module.RelayMode.SILENT
    ) as silent:
        client = await _client(accepting, rejecting, silent, signer_keys=keys)
        try:
            event = EventBuilder.text_note("gamma qual ack probe").sign_with_keys(
                keys
            )
            output = await client.send_event(event)

            outcome, _ = classify(output, accepting.url)
            assert outcome == "accepted", f"positive OK expected: {outcome}"
            outcome, message = classify(output, rejecting.url)
            assert outcome == "rejected"
            assert message == rejecting.reject_message, (
                "the relay's negative-OK message must surface verbatim"
            )
            outcome, _ = classify(output, silent.url)
            assert outcome == "timeout", (
                "a relay that never OKs must surface as timeout, never as "
                "send success"
            )

            # Structured per-relay classification recorded into the evidence
            # manifest — the row PINS.md's qualification-results table cites.
            evidence.note_observation(
                "relay_ack_classification",
                {
                    accepting.url: classify(output, accepting.url)[0],
                    rejecting.url: classify(output, rejecting.url)[0],
                    silent.url: classify(output, silent.url)[0],
                },
            )

            # The accepting relay is the only one that recorded a positive
            # result — and all three received the same EVENT bytes.
            for r in (accepting, rejecting, silent):
                assert len(r.received_events) == 1
                assert (
                    r.received_events[0]["event"]["id"]
                    == event.id().to_hex()
                )
        finally:
            await client.disconnect()
            await client.shutdown()


async def test_targeted_send_never_reaches_unlisted_relay():
    """send_event_to an explicit list must not fan out (section 9.3)."""
    keys = sdk.generate_keys()
    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as listed, relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as unlisted:
        client = await _client(listed, unlisted, signer_keys=keys)
        try:
            event = EventBuilder.text_note("targeted").sign_with_keys(keys)
            output = await client.send_event_to(
                [RelayUrl.parse(listed.url)], event
            )
            outcome, _ = classify(output, listed.url)
            assert outcome == "accepted"
            # The unlisted relay is connected to the same client pool but
            # received nothing — WebSocket send never went there.
            assert unlisted.received_events == []
            assert not any(
                '"EVENT"' in m for m in unlisted.received_messages
            ), "no EVENT frame may reach an unlisted relay"

            # Control: an untargeted send_event fans out to the whole pool,
            # proving the unlisted relay was reachable all along.
            event2 = EventBuilder.text_note("fanout").sign_with_keys(keys)
            out2 = await client.send_event(event2)
            assert classify(out2, unlisted.url)[0] == "accepted"
            assert unlisted.received_events != []
        finally:
            await client.disconnect()
            await client.shutdown()


@pytest.mark.skipif(
    not os.environ.get(SMOKE_RELAY_ENV),
    reason=f"advisory external smoke disabled (set {SMOKE_RELAY_ENV}=wss://…)",
)
async def test_external_relay_smoke():
    """Optional wss://nostr.net smoke (section 21.27): advisory only.

    Ephemeral throwaway key, non-sensitive synthetic event. The result is
    recorded in the test output but NEVER substitutes for the deterministic
    local evidence above.
    """
    url = os.environ[SMOKE_RELAY_ENV]
    keys = sdk.generate_keys()
    client = ClientBuilder().signer(NostrSigner.keys(keys)).build()
    try:
        assert await client.add_relay(RelayUrl.parse(url))
        await client.connect()
        event = EventBuilder.text_note(
            "infinitemarkets qualification smoke (ephemeral, non-sensitive)"
        ).sign_with_keys(keys)
        output = await client.send_event_to([RelayUrl.parse(url)], event)
        outcome, message = classify(output, url)
        # Advisory: any classification is a recorded observation, not a gate.
        print(f"SMOKE {url}: {outcome} {message or ''}".strip())
    finally:
        await client.disconnect()
        await client.shutdown()
