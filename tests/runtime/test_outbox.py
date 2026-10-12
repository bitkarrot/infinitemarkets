"""OQ6 probes + section 8.6 outbox publisher tests.

Part 1 (OQ6): pin nostr-sdk ``send_event_to`` semantics the §8.6 worker
depends on — connection requirements, unreachable-relay outcomes, and the
exact SendEventOutput shape — against ``harness.relay.LocalRelay`` and a
dead loopback port. Findings are recorded in 02-02-SUMMARY.md.

Part 2: the publisher worker against the real schema (keystore_env tmp DB)
with ``INFINITEMARKETS_ALLOW_INSECURE_RELAYS=1`` admitting ws:// loopback
targets — the production ``validate_relay_url`` remains wss-only.
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import socket
import time
import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.runtime


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _signed_event(keys, text="oq6"):
    from nostr_sdk import EventBuilder

    return EventBuilder.text_note(text).sign_with_keys(keys)


# --- OQ6: raw SDK probes ----------------------------------------------------------


async def test_oq6_send_to_unconnected_client_times_out():
    """Does send_event_to require a prior connect()? Add the relay but never
    call connect() — pin the observed behavior."""
    from nostr_sdk import ClientBuilder, RelayUrl

    from harness import relay as relay_module
    from harness import sdk

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as accepting:
        keys = sdk.generate_keys()
        client = ClientBuilder().build()
        try:
            await client.add_relay(RelayUrl.parse(accepting.url))
            event = _signed_event(keys, "oq6-no-connect")
            # Bound the wait regardless of which behavior the SDK pins.
            output = await asyncio.wait_for(
                client.send_event_to(
                    [RelayUrl.parse(accepting.url)], event
                ),
                timeout=30,
            )
            relay_url = RelayUrl.parse(accepting.url)
            # PINNED: send_event_to does NOT connect on demand — a relay
            # that was added but never connected lands in ``failed`` with
            # 'relay is initialized but not ready', no exception, and the
            # relay sees no EVENT. OQ6 finding A: the transport MUST
            # connect targets before send (RelayTransport.send_to does).
            assert relay_url not in output.success
            assert relay_url in output.failed
            assert "not ready" in str(output.failed[relay_url])
            assert accepting.received_events == []
        finally:
            await client.shutdown()


async def test_oq6_send_to_dead_relay_is_timeout_not_exception():
    """An unreachable target must surface in ``output.failed`` (or timeout),
    never as an exception that kills the batch."""
    from nostr_sdk import ClientBuilder, RelayUrl

    from harness import sdk

    dead_url = f"ws://127.0.0.1:{_free_port()}"
    keys = sdk.generate_keys()
    client = ClientBuilder().build()
    try:
        await client.add_relay(RelayUrl.parse(dead_url))
        # connect() swallows connection-refused — no exception.
        await client.connect()
        event = _signed_event(keys, "oq6-dead")
        output = await asyncio.wait_for(
            client.send_event_to([RelayUrl.parse(dead_url)], event),
            timeout=30,
        )
        relay_url = RelayUrl.parse(dead_url)
        # PINNED: connection-refused lands in ``failed`` with reason
        # 'relay not connected' — never an exception, never in
        # ``success``. OQ6 finding B: transient transport failures share
        # the failed-map with real rejections, so the worker classifies
        # the known transient vocabulary as timeout.
        assert relay_url in output.failed
        reason = str(output.failed[relay_url])
        assert reason in {"relay not connected", "timeout"}
        from infinitemarkets.services.outbox import TRANSIENT_REASONS

        assert reason in TRANSIENT_REASONS
        assert output.success == []
    finally:
        await client.shutdown()


async def test_oq6_send_to_unregistered_relay_is_safe():
    """send_event_to a URL the client never added: pin the outcome — the
    worker must treat every non-accepted classification as evidence."""
    from nostr_sdk import ClientBuilder, RelayUrl

    from harness import relay as relay_module
    from harness import sdk

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as accepting:
        keys = sdk.generate_keys()
        client = ClientBuilder().build()
        try:
            event = _signed_event(keys, "oq6-unregistered")
            # PINNED (OQ6 finding C): an unregistered target raises —
            # 'no relays' — rather than landing in the failed map. The
            # transport therefore add_relay+connect's validated targets
            # inside send_to, and the worker converts any residual
            # exception into timeout evidence rather than crashing.
            with pytest.raises(Exception, match="no relays"):
                await asyncio.wait_for(
                    client.send_event_to(
                        [RelayUrl.parse(accepting.url)], event
                    ),
                    timeout=30,
                )
            assert accepting.received_events == []
        finally:
            await client.shutdown()


# --- worker tests ---------------------------------------------------------------


@pytest_asyncio.fixture
async def worker_env(keystore_env, monkeypatch):
    """Extension modules bound to the tmp DB + insecure-relay allowance."""
    env = {
        "INFINITEMARKETS_MASTER_KEYS": json.dumps(
            {"v1": base64.b64encode(bytes(32)).decode()}
        ),
        "INFINITEMARKETS_ACTIVE_KEY_VERSION": "v1",
        "INFINITEMARKETS_PRIVACY_KEY": base64.b64encode(bytes([9]) * 32).decode(),
        "INFINITEMARKETS_PUBLIC_BASE_URL": "https://x.example",
        "INFINITEMARKETS_ALLOW_INSECURE_RELAYS": "1",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # worker tests DO dial — ensure no leaked kill switch from a host boot
    monkeypatch.delenv("INFINITEMARKETS_RELAY_IO", raising=False)
    gdb = keystore_env["db"]
    outbox = importlib.import_module("infinitemarkets.services.outbox")
    relay_service = importlib.import_module("infinitemarkets.services.relay")
    transport_mod = importlib.import_module(
        "infinitemarkets.services.transport"
    )
    yield {
        "db": gdb,
        "outbox": outbox,
        "relay": relay_service,
        "transport": transport_mod.transport(),
        "keystore": keystore_env["keystore"],
    }
    await transport_mod.transport().close()


async def _merchant(worker_env, merchant_id: str | None = None) -> str:
    """Merchants row + generated key so keystore.sign_event works."""
    mid = merchant_id or uuid.uuid4().hex
    db = worker_env["db"]
    from infinitemarkets.db import table

    async with db.connect() as conn:
        await conn.execute(
            f"INSERT INTO {table('merchants')} "
            "(id, user_id, pubkey, key_ref, display_name, wallet_id_enc,"
            " wallet_id_hash, state, created_at, updated_at) "
            "VALUES (:i, :u, :p, 'v1', 'Test Shop', :w, 'h', 'active',"
            " :t, :t)",
            {
                "i": mid,
                "u": uuid.uuid4().hex,
                "p": uuid.uuid4().hex,  # overwritten by keystore.generate
                "w": b"x",
                "t": int(time.time()),
            },
        )
    pubkey = await worker_env["keystore"].key_store().generate(mid)
    async with db.connect() as conn:
        await conn.execute(
            f"UPDATE {table('merchants')} SET pubkey = :p WHERE id = :i",
            {"p": pubkey, "i": mid},
        )
    return mid


async def _relay_config(db, merchant_id: str, url: str,
                        direction: str = "public", enabled: bool = True):
    from infinitemarkets.db import table

    async with db.connect() as conn:
        await conn.execute(
            f"INSERT INTO {table('relay_configs')} "
            "(id, merchant_id, relay_url, direction, enabled, created_at,"
            " updated_at) VALUES (:i, :m, :u, :d, :e, :t, :t)",
            {
                "i": uuid.uuid4().hex,
                "m": merchant_id,
                "u": url,
                "d": direction,
                "e": enabled,
                "t": int(time.time()),
            },
        )


async def _intent(db, merchant_id: str, kind: int = 0) -> str:
    """merchant_profile intent — renderable from the merchants row alone."""
    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.services.outbox import enqueue_intent

    async with DomainTransaction() as tx:
        return await enqueue_intent(
            tx, merchant_id, "merchant_profile", merchant_id, kind
        )


async def _state(db, intent_id: str) -> dict:
    from infinitemarkets.db import table

    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT * FROM {table('outbox_events')} WHERE id = :i",
            {"i": intent_id},
        )
        pubs = await conn.fetchall(
            f"SELECT * FROM {table('relay_publications')} "
            "WHERE outbox_event_id = :i",
            {"i": intent_id},
        )
    return {"row": dict(row), "pubs": [dict(p) for p in pubs]}


async def test_publish_accepted_marks_published_and_records_evidence(
    worker_env,
):
    """Happy path: claimed -> signed -> sent -> accepted -> published."""
    from harness import relay as relay_module

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as accepting:
        mid = await _merchant(worker_env)
        await _relay_config(worker_env["db"], mid, accepting.url)
        intent = await _intent(worker_env["db"], mid)
        await worker_env["transport"].start([accepting.url])

        result = await worker_env["outbox"].worker_tick("w-test")
        assert result["claimed"] == 1
        state = await _state(worker_env["db"], intent)
        assert state["row"]["state"] == "published"
        assert [p["result"] for p in state["pubs"]] == ["accepted"]
        assert state["pubs"][0]["relay_url"] == accepting.url
        # the relay received exactly one signed EVENT with this id
        assert len(accepting.received_events) == 1
        assert (
            accepting.received_events[0]["event"]["id"]
            == state["pubs"][0]["event_id"]
        )


async def _quiesce_pending(db) -> None:
    """Supersede leftover live intents so claim-count assertions stay
    hermetic — worker ticks claim globally across merchants."""
    from infinitemarkets.db import table

    async with db.connect() as conn:
        await conn.execute(
            f"UPDATE {table('outbox_events')} SET state = 'superseded' "
            "WHERE state IN ('pending', 'claimed', 'partially_published')"
        )


async def test_rejected_and_timeout_relays_leave_intent_pending(worker_env):
    """Zero positive ACKs -> pending + backoff; both evidence rows persist
    verbatim, and the batch itself does not crash."""
    from harness import relay as relay_module

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.REJECTING
    ) as rejecting, relay_module.LocalRelay(
        mode=relay_module.RelayMode.SILENT
    ) as silent:
        mid = await _merchant(worker_env)
        await _relay_config(worker_env["db"], mid, rejecting.url)
        await _relay_config(worker_env["db"], mid, silent.url)
        intent = await _intent(worker_env["db"], mid)
        await worker_env["transport"].start([rejecting.url, silent.url])

        t0 = int(time.time())
        result = await worker_env["outbox"].worker_tick("w-test")
        assert result["claimed"] == 1
        state = await _state(worker_env["db"], intent)
        assert state["row"]["state"] == "pending"
        assert state["row"]["attempts"] == 1
        # backoff is relative to the tick, not assertion time — the silent
        # relay's send timeout can consume most of the first backoff.
        assert state["row"]["next_attempt_at"] > t0
        results = {p["relay_url"]: p["result"] for p in state["pubs"]}
        assert results[rejecting.url] == "rejected"
        assert results[silent.url] == "timeout"
        # the rejecting relay's verbatim message is preserved
        msg = [p["message"] for p in state["pubs"]
               if p["relay_url"] == rejecting.url][0]
        assert "rejecting" in msg


async def test_dead_relay_isolated_one_failure_never_crashes_batch(
    worker_env,
):
    """A dead target yields timeout evidence; a healthy target in the same
    batch still accepts -> published via quorum."""
    from harness import relay as relay_module

    dead = f"ws://127.0.0.1:{_free_port()}"
    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as accepting:
        await _quiesce_pending(worker_env["db"])
        mid = await _merchant(worker_env)
        await _relay_config(worker_env["db"], mid, accepting.url)
        await _relay_config(worker_env["db"], mid, dead)
        intent = await _intent(worker_env["db"], mid)
        await worker_env["transport"].start([accepting.url, dead])

        result = await worker_env["outbox"].worker_tick("w-test")
        assert result["claimed"] == 1
        state = await _state(worker_env["db"], intent)
        # quorum = >=1 positive ACK -> published even with a dead target
        assert state["row"]["state"] == "published"
        results = {p["relay_url"]: p["result"] for p in state["pubs"]}
        assert results[accepting.url] == "accepted"
        assert results[dead] == "timeout"


async def test_accepted_targets_are_never_resent(worker_env):
    """Durable accepted evidence is subtracted before each send — a retry
    after a partial batch sends only to outstanding relays."""
    from harness import relay as relay_module

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as accepting, relay_module.LocalRelay(
        mode=relay_module.RelayMode.SILENT
    ) as silent:
        mid = await _merchant(worker_env)
        await _relay_config(worker_env["db"], mid, accepting.url)
        await _relay_config(worker_env["db"], mid, silent.url)
        intent = await _intent(worker_env["db"], mid)
        await worker_env["transport"].start([accepting.url, silent.url])

        await worker_env["outbox"].worker_tick("w-test")
        assert len(accepting.received_events) == 1

        # Force a second attempt without waiting for backoff.
        from infinitemarkets.db import table

        async with worker_env["db"].connect() as conn:
            await conn.execute(
                f"UPDATE {table('outbox_events')} "
                "SET state = 'pending', next_attempt_at = 0 WHERE id = :i",
                {"i": intent},
            )
        await worker_env["outbox"].worker_tick("w-test")
        state = await _state(worker_env["db"], intent)
        # silent still times out -> pending, but the accepted relay saw no
        # second EVENT frame.
        assert len(accepting.received_events) == 1, (
            "accepted relay target was resent"
        )
        accepted_pubs = [
            p for p in state["pubs"]
            if p["relay_url"] == accepting.url and p["result"] == "accepted"
        ]
        assert len(accepted_pubs) == 1


async def test_newer_live_revision_supersedes_stale_intent(worker_env):
    """A newer live intent for the same aggregate+kind marks the stale one
    superseded — stale content is never published."""
    from harness import relay as relay_module

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as accepting:
        mid = await _merchant(worker_env)
        await _relay_config(worker_env["db"], mid, accepting.url)
        from infinitemarkets.db import DomainTransaction
        from infinitemarkets.services.outbox import enqueue_intent

        async with DomainTransaction() as tx:
            old = await enqueue_intent(
                tx, mid, "merchant_profile", mid, 0, revision=1
            )
            await enqueue_intent(
                tx, mid, "merchant_profile", mid, 0, revision=2
            )
        await worker_env["transport"].start([accepting.url])
        await worker_env["outbox"].worker_tick("w-test")

        state = await _state(worker_env["db"], old)
        assert state["row"]["state"] == "superseded"
        # only the newer intent published an EVENT
        assert len(accepting.received_events) == 1


async def test_dependency_gate_blocks_until_published(worker_env):
    """An intent whose dependency isn't published is requeued, not sent."""
    from harness import relay as relay_module

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as accepting:
        mid = await _merchant(worker_env)
        await _relay_config(worker_env["db"], mid, accepting.url)
        from infinitemarkets.db import DomainTransaction
        from infinitemarkets.services.outbox import enqueue_intent

        async with DomainTransaction() as tx:
            cid = uuid.uuid4().hex
            await enqueue_intent(tx, mid, "collections", cid, 30405)
            child = await enqueue_intent(
                tx, mid, "merchant_profile", mid, 0,
                depends_on=[("collections", cid)],
            )
        # The collection row doesn't exist -> dep intent will be
        # superseded by the worker, leaving the child blocked forever.
        # First tick: child claimed but dependency not published -> requeue.
        await worker_env["transport"].start([accepting.url])
        await worker_env["outbox"].worker_tick("w-test")
        state = await _state(worker_env["db"], child)
        assert state["row"]["state"] == "pending"
        # a dep-blocked wait is not a failure — the attempt budget is
        # untouched (attempts >= OUTBOX_MAX_ATTEMPTS would make the row
        # permanently unclaimable while still 'pending').
        assert state["row"]["attempts"] == 0
        assert state["pubs"] == []
        assert accepting.received_events == []


async def test_dependency_met_when_aggregate_has_published_revision(worker_env):
    """The edge binds to the intended dep row's OWN revision: a stale
    published revision never satisfies, but a superseded bound intent is
    released by a qualifying published replacement — same merchant /
    aggregate / kind at-or-above the intended revision (the production
    wedge case: products behind superseded collection revs still
    unblock, only through a revision that actually covers the edge)."""
    from harness import relay as relay_module

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as accepting:
        mid = await _merchant(worker_env)
        dep = await _merchant(worker_env)
        await _relay_config(worker_env["db"], mid, accepting.url)
        await _relay_config(worker_env["db"], dep, accepting.url)
        from infinitemarkets.db import DomainTransaction, table
        from infinitemarkets.services.outbox import enqueue_intent

        async with DomainTransaction() as tx:
            rev1 = await enqueue_intent(
                tx, dep, "merchant_profile", dep, 0, revision=1
            )
        await worker_env["transport"].start([accepting.url])
        await worker_env["outbox"].worker_tick("w-test")
        assert (await _state(worker_env["db"], rev1))["row"]["state"] \
            == "published"
        assert len(accepting.received_events) == 1

        async with DomainTransaction() as tx:
            # The dep edge binds to the intended rev2 intent — keep it
            # claim-ineligible so the child is evaluated while NO
            # qualifying publication exists yet.
            rev2 = await enqueue_intent(
                tx, dep, "merchant_profile", dep, 0, revision=2
            )
            child = await enqueue_intent(
                tx, mid, "merchant_profile", mid, 0,
                depends_on=[("merchant_profile", dep)],
            )
        async with worker_env["db"].connect() as conn:
            await conn.execute(
                f"UPDATE {table('outbox_events')} SET next_attempt_at = :n"
                " WHERE id = :i",
                {"n": int(time.time()) + 10000, "i": rev2},
            )
        await worker_env["outbox"].worker_tick("w-test")
        state = await _state(worker_env["db"], child)
        # The published rev1 is STALE — it must not release a rev2 edge.
        assert state["row"]["state"] == "pending"
        assert state["row"]["attempts"] == 0
        assert len(accepting.received_events) == 1

        # A rev3 intent supersedes the bound rev2; once it actually
        # publishes it is a qualifying replacement and the child goes.
        async with DomainTransaction() as tx:
            await enqueue_intent(
                tx, dep, "merchant_profile", dep, 0, revision=3
            )
        await worker_env["outbox"].worker_tick("w-test")
        await worker_env["outbox"].worker_tick("w-test")
        state = await _state(worker_env["db"], child)
        assert state["row"]["state"] == "published"
        assert len(accepting.received_events) == 3


async def test_retry_intent_resets_failed_and_skips_accepted(worker_env):
    """Admin retry: failed/partial -> pending, attempts reset, accepted
    targets still never resent."""
    from harness import relay as relay_module

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as accepting:
        mid = await _merchant(worker_env)
        await _relay_config(worker_env["db"], mid, accepting.url)
        intent = await _intent(worker_env["db"], mid)
        db = worker_env["db"]
        from infinitemarkets.db import table

        async with db.connect() as conn:
            await conn.execute(
                f"UPDATE {table('outbox_events')} SET state = 'failed',"
                " attempts = 20 WHERE id = :i",
                {"i": intent},
            )
        result = await worker_env["relay"].retry_intent(mid, intent)
        assert result["state"] == "pending"
        state = await _state(db, intent)
        assert state["row"]["state"] == "pending"
        assert state["row"]["attempts"] == 0

        # a published intent cannot be retried
        async with db.connect() as conn:
            await conn.execute(
                f"UPDATE {table('outbox_events')} SET state = 'published'"
                " WHERE id = :i",
                {"i": intent},
            )
        from infinitemarkets.security import ProblemError

        with pytest.raises(ProblemError):
            await worker_env["relay"].retry_intent(mid, intent)


async def test_stale_claim_recovery_requeues_with_evidence(worker_env):
    """Lease-expired claims return to the queue — partially_published when
    durable accepted evidence exists, pending otherwise."""
    mid = await _merchant(worker_env)
    db = worker_env["db"]
    intent = await _intent(db, mid)
    from infinitemarkets.db import table

    async with db.connect() as conn:
        await conn.execute(
            f"UPDATE {table('outbox_events')} SET state = 'claimed',"
            " claimed_by = 'dead-worker', claimed_until = 0 WHERE id = :i",
            {"i": intent},
        )
    recovered = await worker_env["outbox"].recover_stale_claims(
        int(time.time())
    )
    assert recovered == 1
    state = await _state(db, intent)
    assert state["row"]["state"] == "pending"


async def test_relay_targets_direction_and_defaults(worker_env):
    """Target resolution: public set = direction public|both + enabled;
    server-wide defaults (merchant_id NULL) apply to every merchant."""
    mid = await _merchant(worker_env)
    db = worker_env["db"]
    await _relay_config(db, mid, "wss://public.example", "public")
    await _relay_config(db, mid, "wss://inbox.example", "inbox")
    await _relay_config(db, mid, "wss://both.example", "both")
    await _relay_config(db, mid, "wss://off.example", "public",
                        enabled=False)
    targets = await worker_env["relay"].relay_targets(mid, "public")
    assert targets == ["wss://both.example", "wss://public.example"]
    inbox = await worker_env["relay"].relay_targets(mid, "inbox")
    assert inbox == ["wss://both.example", "wss://inbox.example"]

    # server-wide default rows (merchant_id NULL) supplement
    await _relay_config(db, None, "wss://default.example", "public")
    targets = await worker_env["relay"].relay_targets(mid, "public")
    assert "wss://default.example" in targets

    # starter seeding: a merchant with zero configs gets the visible set
    mid2 = uuid.uuid4().hex
    from infinitemarkets.db import table

    async with db.connect() as conn:
        await conn.execute(
            f"INSERT INTO {table('merchants')} "
            "(id, user_id, pubkey, key_ref, display_name, wallet_id_enc,"
            " wallet_id_hash, state, created_at, updated_at) "
            "VALUES (:i, :u, :p, 'v1', 'S2', :w, 'h', 'active', 0, 0)",
            {"i": mid2, "u": uuid.uuid4().hex,
             "p": uuid.uuid4().hex, "w": b"x"},
        )
    await worker_env["relay"].ensure_default_relays(mid2)
    targets = await worker_env["relay"].relay_targets(mid2, "public")
    assert "wss://relay.damus.io" in targets


async def test_no_targets_cannot_be_published_or_activate_merchant(worker_env, monkeypatch):
    from infinitemarkets.db import DomainTransaction

    mid = await _merchant(worker_env)
    intent = await _intent(worker_env["db"], mid)

    async def no_targets(merchant_id, direction="public", database=None):
        return []

    monkeypatch.setattr(worker_env["relay"], "relay_targets", no_targets)
    async with DomainTransaction() as tx:
        await tx.execute(
            f"UPDATE {tx.table('merchants')} SET state = 'publication_pending' WHERE id = :m",
            {"m": mid},
        )
    await worker_env["transport"].start([])
    await worker_env["outbox"].worker_tick("no-target-worker")
    state = await _state(worker_env["db"], intent)
    assert state["row"]["state"] == "pending"
    assert state["pubs"] == []
    async with DomainTransaction() as tx:
        merchant = await tx.fetch_one(
            f"SELECT state FROM {tx.table('merchants')} WHERE id = :m", {"m": mid},
        )
    assert merchant["state"] == "publication_pending"


async def test_expired_publication_claim_cannot_write(worker_env):
    from infinitemarkets.db import DomainTransaction

    mid = await _merchant(worker_env)
    intent = await _intent(worker_env["db"], mid)
    claims = await worker_env["outbox"].claim_batch(int(time.time()), "expired-worker")
    claim = next(row for row in claims if row["id"] == intent)
    async with DomainTransaction() as tx:
        await tx.execute(
            f"UPDATE {tx.table('outbox_events')} SET claimed_until = 0 WHERE id = :i",
            {"i": intent},
        )
    result = await worker_env["outbox"].publish_intent(
        claim, transport=worker_env["transport"], keystore=worker_env["keystore"].key_store(),
        relay_targets=[], worker_id="expired-worker", now=int(time.time()),
    )
    assert result == "lost_claim"
    state = await _state(worker_env["db"], intent)
    assert state["row"]["state"] == "claimed"
    assert state["pubs"] == []


async def test_network_send_does_not_hold_database_write_lock(worker_env):
    from types import SimpleNamespace

    from infinitemarkets.db import DomainTransaction

    mid = await _merchant(worker_env)
    intent = await _intent(worker_env["db"], mid)
    claims = await worker_env["outbox"].claim_batch(int(time.time()), "network-worker")
    claim = next(row for row in claims if row["id"] == intent)
    entered, release = asyncio.Event(), asyncio.Event()

    async def send_to(targets, event):
        entered.set()
        await release.wait()
        return SimpleNamespace(success=set(targets), failed={})

    async def unrelated_write():
        async with DomainTransaction() as tx:
            await tx.execute(
                f"UPDATE {tx.table('merchants')} SET display_name = 'updated' WHERE id = :i",
                {"i": mid},
            )

    publishing = asyncio.create_task(worker_env["outbox"].publish_intent(
        claim, transport=SimpleNamespace(send_to=send_to),
        keystore=worker_env["keystore"].key_store(), relay_targets=["wss://relay.example"],
        worker_id="network-worker", now=int(time.time()),
    ))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        await asyncio.wait_for(unrelated_write(), 1)
    finally:
        release.set()
        await publishing
    assert (await _state(worker_env["db"], intent))["row"]["state"] == "published"


async def test_lease_expiry_during_send_cannot_commit_evidence(worker_env):
    from types import SimpleNamespace

    from infinitemarkets.db import DomainTransaction

    mid = await _merchant(worker_env)
    intent = await _intent(worker_env["db"], mid)
    claims = await worker_env["outbox"].claim_batch(int(time.time()), "expiring-worker")
    claim = next(row for row in claims if row["id"] == intent)
    async with DomainTransaction() as tx:
        await tx.execute(
            f"UPDATE {tx.table('outbox_events')} SET claimed_until = :n WHERE id = :i",
            {"i": intent, "n": await tx.now() + 2},
        )

    async def send_to(targets, event):
        await asyncio.sleep(2.1)
        return SimpleNamespace(success=set(targets), failed={})

    result = await worker_env["outbox"].publish_intent(
        claim, transport=SimpleNamespace(send_to=send_to),
        keystore=worker_env["keystore"].key_store(), relay_targets=["wss://relay.example"],
        worker_id="expiring-worker", now=int(time.time()),
    )
    assert result == "lost_claim"
    state = await _state(worker_env["db"], intent)
    assert state["row"]["state"] == "claimed"
    assert state["pubs"] == []


# --- HARD-04: revision-bound dependency satisfaction ---------------------------

async def _catalog_seed(db, mid: str) -> dict:
    """Minimal renderable catalog: category -> product -> collection."""
    from infinitemarkets.db import table

    now = int(time.time())
    ids = {
        "category": uuid.uuid4().hex,
        "product": uuid.uuid4().hex,
        "collection": uuid.uuid4().hex,
    }
    async with db.connect() as conn:
        await conn.execute(
            f"INSERT INTO {table('categories')} "
            "(id, merchant_id, name, publish_gamma, publish_nip15,"
            " created_at, updated_at)"
            " VALUES (:i, :m, 'cat', FALSE, FALSE, :t, :t)",
            {"i": ids["category"], "m": mid, "t": now},
        )
        await conn.execute(
            f"INSERT INTO {table('products')} "
            "(id, merchant_id, category_id, d_tag, product_type, format,"
            " title, visibility, draft, stock_on_hand, stock_reserved,"
            " published_at, revision, created_at, updated_at)"
            " VALUES (:i, :m, :c, 'pa', 'simple', 'physical', 'prod a',"
            " 'on-sale', FALSE, 10, 0, :t, 0, :t, :t)",
            {"i": ids["product"], "m": mid, "c": ids["category"], "t": now},
        )
        await conn.execute(
            f"INSERT INTO {table('collections')} "
            "(id, merchant_id, d_tag, title, revision, created_at,"
            " updated_at) VALUES (:i, :m, 'col1', 'col', 0, :t, :t)",
            {"i": ids["collection"], "m": mid, "t": now},
        )
        await conn.execute(
            f"INSERT INTO {table('product_collections')} "
            "(id, product_id, collection_id) VALUES (:i, :p, :c)",
            {
                "i": uuid.uuid4().hex,
                "p": ids["product"],
                "c": ids["collection"],
            },
        )
    return ids


async def _pubkey(db, mid: str) -> str:
    from infinitemarkets.db import table

    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT pubkey FROM {table('merchants')} WHERE id = :m",
            {"m": mid},
        )
    return row["pubkey"]


async def _events_of_kind(relay, kind: int) -> list[dict]:
    return [
        e["event"] for e in relay.received_events
        if isinstance(e.get("event"), dict) and e["event"].get("kind") == kind
    ]


async def test_hard04_stale_revision_cannot_publish_dependent(worker_env):
    """HARD-04: published rev1 of the dep aggregate must NOT release a
    child whose edge binds to pending rev2. Only the intended
    publication — or a real published replacement at-or-above the
    intended revision with the same merchant/aggregate/kind — does."""
    from harness import relay as relay_module
    from infinitemarkets.db import DomainTransaction
    from infinitemarkets.services.outbox import enqueue_intent

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as accepting:
        mid = await _merchant(worker_env)
        await _relay_config(worker_env["db"], mid, accepting.url)
        ids = await _catalog_seed(worker_env["db"], mid)
        cid = ids["collection"]
        pubkey = await _pubkey(worker_env["db"], mid)
        addr = f"30405:{pubkey}:col1"

        # Revision 1 of the collection lands for real.
        async with DomainTransaction() as tx:
            rev1 = await enqueue_intent(
                tx, mid, "collections", cid, 30405,
                revision=1, event_address=addr,
            )
        await worker_env["transport"].start([accepting.url])
        await worker_env["outbox"].worker_tick("w-test")
        assert (await _state(worker_env["db"], rev1))["row"]["state"] \
            == "published"
        assert len(await _events_of_kind(accepting, 30405)) == 1

        # Break renderability (zero members -> superseded) and enqueue
        # the intended rev2 + the dependent child.
        async with worker_env["db"].connect() as conn:
            from infinitemarkets.db import table

            await conn.execute(
                f"DELETE FROM {table('product_collections')}"
                " WHERE collection_id = :c",
                {"c": cid},
            )
        async with DomainTransaction() as tx:
            rev2 = await enqueue_intent(
                tx, mid, "collections", cid, 30405,
                revision=2, event_address=addr,
            )
            child = await enqueue_intent(
                tx, mid, "merchant_profile", mid, 0,
                depends_on=[("collections", cid)],
            )
        await worker_env["outbox"].worker_tick("w-test")
        rev2_state = await _state(worker_env["db"], rev2)
        assert rev2_state["row"]["state"] == "superseded"
        state = await _state(worker_env["db"], child)
        # The stale published rev1 must NOT have released the child.
        assert state["row"]["state"] == "pending"
        assert state["row"]["attempts"] == 0
        assert state["pubs"] == []
        assert len(await _events_of_kind(accepting, 0)) == 0

        # Restore renderability; a real rev3 publish is a qualifying
        # replacement for the superseded bound intent.
        async with worker_env["db"].connect() as conn:
            await conn.execute(
                f"INSERT INTO {table('product_collections')} "
                "(id, product_id, collection_id) VALUES (:i, :p, :c)",
                {"i": uuid.uuid4().hex,
                 "p": ids["product"], "c": cid},
            )
        async with DomainTransaction() as tx:
            await enqueue_intent(
                tx, mid, "collections", cid, 30405,
                revision=3, event_address=addr,
            )
        await worker_env["outbox"].worker_tick("w-test")
        await worker_env["outbox"].worker_tick("w-test")
        state = await _state(worker_env["db"], child)
        assert state["row"]["state"] == "published"
        assert len(await _events_of_kind(accepting, 30405)) == 2
        assert len(await _events_of_kind(accepting, 0)) == 1


async def test_hard04_dependency_scope_kind_merchant_and_failed(worker_env):
    """HARD-04 negatives: a published tombstone (wrong kind), a foreign
    merchant's publication of the same aggregate identity, and a failed
    newer replacement never satisfy the bound edge — with only a stale
    published revision to tempt the old check."""
    from harness import relay as relay_module
    from infinitemarkets.db import DomainTransaction, table
    from infinitemarkets.services.outbox import enqueue_intent

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as accepting:
        mid = await _merchant(worker_env)
        dep = await _merchant(worker_env)
        foreign = uuid.uuid4().hex  # merchants row never needed
        await _relay_config(worker_env["db"], mid, accepting.url)
        await _relay_config(worker_env["db"], dep, accepting.url)
        pubkey = await _pubkey(worker_env["db"], dep)
        col_a, col_b, col_c = (uuid.uuid4().hex for _ in range(3))

        # (a) wrong-kind: bound to a kind-30405 rev2 intent; a published
        # kind-5 tombstone rev9 supersedes it but must not satisfy.
        async with DomainTransaction() as tx:
            t_a = await enqueue_intent(
                tx, dep, "collections", col_a, 30405, revision=2,
            )
            child_a = await enqueue_intent(
                tx, mid, "merchant_profile", mid, 0,
                depends_on=[("collections", col_a)],
            )
            await enqueue_intent(
                tx, dep, "collections", col_a, 5, revision=9,
                event_address=f"30405:{pubkey}:tombA",
            )
        # (b) foreign merchant: bound to dep's pending rev2; a DIFFERENT
        # merchant's published rev9 of the same aggregate identity must
        # not satisfy.
        async with DomainTransaction() as tx:
            t_b = await enqueue_intent(
                tx, dep, "collections", col_b, 30405, revision=2,
            )
            child_b = await enqueue_intent(
                tx, mid, "merchant_profile", mid, 31989,
                depends_on=[("collections", col_b)],
            )
            f_b = await enqueue_intent(
                tx, foreign, "collections", col_b, 30405, revision=9,
            )
        # (c) failed replacement: bound to rev2; a FAILED rev3 plus a
        # stale published rev1 must not satisfy.
        async with DomainTransaction() as tx:
            old_c = await enqueue_intent(
                tx, dep, "collections", col_c, 30405, revision=1,
            )
            t_c = await enqueue_intent(
                tx, dep, "collections", col_c, 30405, revision=2,
            )
            child_c = await enqueue_intent(
                tx, mid, "merchant_profile", mid, 31990,
                depends_on=[("collections", col_c)],
            )
            f_c = await enqueue_intent(
                tx, dep, "collections", col_c, 30405, revision=3,
            )
        async with worker_env["db"].connect() as conn:
            await conn.execute(
                f"UPDATE {table('outbox_events')} SET state = 'published'"
                " WHERE id = :i",
                {"i": f_b},
            )
            await conn.execute(
                f"UPDATE {table('outbox_events')} SET state = 'published'"
                " WHERE id = :i",
                {"i": old_c},
            )
            await conn.execute(
                f"UPDATE {table('outbox_events')} SET state = 'failed'"
                " WHERE id = :i",
                {"i": f_c},
            )
        await worker_env["transport"].start([accepting.url])
        await worker_env["outbox"].worker_tick("w-test")
        await worker_env["outbox"].worker_tick("w-test")
        for name, cid_intent in (
            ("a", child_a), ("b", child_b), ("c", child_c),
        ):
            state = await _state(worker_env["db"], cid_intent)
            assert state["row"]["state"] == "pending", name
            assert state["row"]["attempts"] == 0, name
            assert state["pubs"] == [], name
        # Only the tombstone actually landed on the relay.
        assert len(await _events_of_kind(accepting, 5)) == 1
        for bound in (t_a, t_b, t_c):
            bound_state = await _state(worker_env["db"], bound)
            assert bound_state["row"]["state"] == "superseded"


async def test_hard04_reference_removal_republish_before_tombstone(
    worker_env,
):
    """HARD-04 ordering: the actual ``_delete_product_locked`` enqueue
    puts the surviving collection republish BEFORE the product tombstone;
    the worker must hold the tombstone while only a stale published
    revision exists, then emit republish -> tombstone on the wire."""
    from harness import relay as relay_module
    from infinitemarkets.db import DomainTransaction, table
    from infinitemarkets.services import catalog
    from infinitemarkets.services.outbox import enqueue_intent

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as accepting:
        mid = await _merchant(worker_env)
        await _relay_config(worker_env["db"], mid, accepting.url)
        ids = await _catalog_seed(worker_env["db"], mid)
        cid = ids["collection"]
        doomed = uuid.uuid4().hex
        pubkey = await _pubkey(worker_env["db"], mid)
        now = int(time.time())
        async with worker_env["db"].connect() as conn:
            await conn.execute(
                f"INSERT INTO {table('products')} "
                "(id, merchant_id, category_id, d_tag, product_type,"
                " format, title, visibility, draft, stock_on_hand,"
                " stock_reserved, published_at, revision, created_at,"
                " updated_at) VALUES (:i, :m, :c, 'pb', 'simple',"
                " 'physical', 'prod b', 'on-sale', FALSE, 5, 0, :t, 0,"
                " :t, :t)",
                {"i": doomed, "m": mid, "c": ids["category"], "t": now},
            )
            await conn.execute(
                f"INSERT INTO {table('product_collections')} "
                "(id, product_id, collection_id) VALUES (:i, :p, :c)",
                {"i": uuid.uuid4().hex, "p": doomed, "c": cid},
            )

        # Collection rev1 already published before the reference removal.
        async with DomainTransaction() as tx:
            rev1 = await enqueue_intent(
                tx, mid, "collections", cid, 30405,
                revision=1, event_address=f"30405:{pubkey}:col1",
            )
        await worker_env["transport"].start([accepting.url])
        await worker_env["outbox"].worker_tick("w-test")
        assert (await _state(worker_env["db"], rev1))["row"]["state"] \
            == "published"
        assert len(await _events_of_kind(accepting, 30405)) == 1

        # The domain row tracks what is live on relays: rev1.
        async with worker_env["db"].connect() as conn:
            await conn.execute(
                f"UPDATE {table('collections')} SET revision = 1"
                " WHERE id = :c",
                {"c": cid},
            )

        # Actual catalog delete: republish enqueued before the tombstone.
        async with DomainTransaction() as tx:
            await catalog._delete_product_locked(tx, mid, doomed, pubkey)
        async with worker_env["db"].connect() as conn:
            rows = await conn.fetchall(
                f"SELECT id, event_kind, aggregate_revision, state"
                f" FROM {table('outbox_events')}"
                " WHERE aggregate_id IN (:c, :p) ORDER BY created_at, id",
                {"c": cid, "p": doomed},
            )
            edges = await conn.fetchall(
                f"SELECT outbox_event_id AS c,"
                f" depends_on_outbox_event_id AS d"
                f" FROM {table('outbox_dependencies')}",
            )
        republish = next(
            r for r in rows
            if r["event_kind"] == 30405 and r["aggregate_revision"] > 1
        )
        tombstone = next(r for r in rows if r["event_kind"] == 5)
        assert {"c": tombstone["id"], "d": republish["id"]} in [
            {"c": e["c"], "d": e["d"]} for e in edges
        ]

        # Hold the republish claim-ineligible: the tombstone must wait —
        # the stale published rev1 is not a substitute.
        async with worker_env["db"].connect() as conn:
            await conn.execute(
                f"UPDATE {table('outbox_events')} SET next_attempt_at = :n"
                " WHERE id = :i",
                {"n": now + 10000, "i": republish["id"]},
            )
        await worker_env["outbox"].worker_tick("w-test")
        state = await _state(worker_env["db"], tombstone["id"])
        assert state["row"]["state"] == "pending"
        assert state["row"]["attempts"] == 0
        assert len(await _events_of_kind(accepting, 5)) == 0

        # Release the republish: it lands first, the tombstone follows.
        async with worker_env["db"].connect() as conn:
            await conn.execute(
                f"UPDATE {table('outbox_events')} SET next_attempt_at = 0"
                " WHERE id = :i",
                {"i": republish["id"]},
            )
        await worker_env["outbox"].worker_tick("w-test")
        await worker_env["outbox"].worker_tick("w-test")
        assert (await _state(worker_env["db"], republish["id"]))[
            "row"]["state"] == "published"
        assert (await _state(worker_env["db"], tombstone["id"]))[
            "row"]["state"] == "published"
        kinds = [
            e["event"]["kind"] for e in accepting.received_events
            if isinstance(e.get("event"), dict)
        ]
        assert kinds == [30405, 30405, 5]


async def test_hard04_prune_preserves_retained_dependencies(worker_env):
    """HARD-04 prune: manual history flush must not delete prerequisites
    a retained intent still needs — the bound dep row, transitive
    prerequisites, and the published replacement rows that prove an
    edge. A blocked child must never come back dependency-free."""
    from harness import relay as relay_module
    from infinitemarkets.db import DomainTransaction, table
    from infinitemarkets.services.outbox import enqueue_intent

    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.ACCEPTING
    ) as accepting:
        mid = await _merchant(worker_env)
        foreign = uuid.uuid4().hex
        await _relay_config(worker_env["db"], mid, accepting.url)
        now = int(time.time())
        old = now - 100 * 86400

        async with DomainTransaction() as tx:
            # Chain: A -> B -> D. B is old+superseded, D is old+published;
            # A is a live retained child that still needs both.
            d_row = await enqueue_intent(
                tx, mid, "collections", "dep-d", 30405, revision=1,
            )
            b_row = await enqueue_intent(
                tx, mid, "merchant_profile", "dep-b", 0, revision=2,
                depends_on=[("collections", "dep-d")],
            )
            a_row = await enqueue_intent(
                tx, mid, "merchant_profile", mid, 0,
                depends_on=[("merchant_profile", "dep-b")],
            )
            # Proof chain: A2 -> B2(superseded rev2); P2 published rev3
            # is the qualifying replacement that will release A2.
            b2_row = await enqueue_intent(
                tx, mid, "merchant_profile", "dep-b2", 31989, revision=2,
            )
            a2_row = await enqueue_intent(
                tx, mid, "merchant_profile", mid, 31989,
                depends_on=[("merchant_profile", "dep-b2")],
            )
            p2_row = await enqueue_intent(
                tx, mid, "merchant_profile", "dep-b2", 31989, revision=3,
            )
            # Genuinely prunable + a foreign row outside merchant scope.
            u_row = await enqueue_intent(
                tx, mid, "merchant_profile", "dep-u", 31990, revision=1,
            )
            f_row = await enqueue_intent(
                tx, foreign, "merchant_profile", "dep-f", 31990,
                revision=1,
            )
        async with worker_env["db"].connect() as conn:
            for i, s in (
                (d_row, "published"), (b_row, "superseded"),
                (b2_row, "superseded"), (p2_row, "published"),
                (u_row, "failed"), (f_row, "published"),
            ):
                await conn.execute(
                    f"UPDATE {table('outbox_events')} SET state = :s,"
                    " updated_at = :o WHERE id = :i",
                    {"s": s, "o": old, "i": i},
                )

        report = await worker_env["relay"].prune_outbox(mid, 30)
        assert report["pruned"] == 1
        async with worker_env["db"].connect() as conn:
            surviving = {
                r["id"]
                for r in await conn.fetchall(
                    f"SELECT id FROM {table('outbox_events')}"
                    " WHERE id IN (:a, :b, :c, :d, :e, :f, :g)",
                    {
                        "a": a_row, "b": b_row, "c": a2_row, "d": d_row,
                        "e": b2_row, "f": p2_row, "g": f_row,
                    },
                )
            }
            u_gone = await conn.fetchone(
                f"SELECT COUNT(*) AS n FROM {table('outbox_events')}"
                " WHERE id = :i",
                {"i": u_row},
            )
            edges = {
                (e["outbox_event_id"], e["depends_on_outbox_event_id"])
                for e in await conn.fetchall(
                    f"SELECT * FROM {table('outbox_dependencies')}"
                )
            }
        # Every prerequisite of a retained intent survived — bound rows,
        # the transitive D, and the P2 replacement proof.
        assert surviving == {
            a_row, b_row, a2_row, d_row, b2_row, p2_row, f_row,
        }
        assert u_gone["n"] == 0
        assert (a_row, b_row) in edges
        assert (b_row, d_row) in edges
        assert (a2_row, b2_row) in edges

        # Worker truth: A still blocked (no published rev>=2 for dep-b),
        # A2 released by the retained P2 replacement proof.
        await worker_env["transport"].start([accepting.url])
        await worker_env["outbox"].worker_tick("w-test")
        await worker_env["outbox"].worker_tick("w-test")
        a_state = await _state(worker_env["db"], a_row)
        assert a_state["row"]["state"] == "pending"
        assert a_state["row"]["attempts"] == 0
        a2_state = await _state(worker_env["db"], a2_row)
        assert a2_state["row"]["state"] == "published"
