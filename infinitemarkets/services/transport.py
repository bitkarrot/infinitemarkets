"""Extension-owned nostr-sdk transport — spec section 9.1/9.5/10.

One ``Client`` per worker process, created with bounded connection
parameters, connected only to validated configured relays, shared by the
outbox publisher, and closed inside ``infinitemarkets_stop``. No signer is ever
attached — signing happens per event through ``keystore.sign_event`` so raw
nsecs never reach the transport.

``INFINITEMARKETS_ALLOW_INSECURE_RELAYS=1`` is a TEST-ONLY escape hatch:
it permits ``ws://`` loopback targets so runtime tests can point the
transport at ``harness.relay.LocalRelay``. It is rejected (startup failure)
when the host is not in test mode… documented residual: qualified
deployments never set it.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from nostr_sdk import Client, ClientBuilder, ClientOptions, RelayUrl

from ..security import (
    resolve_and_check_egress,
    unprocessable,
    validate_relay_url,
)
from ..settings import ext_settings

# §9.5 bounds
CONNECT_TIMEOUT_S = 10
MAX_RELAYS = 32


def insecure_relays_allowed() -> bool:
    return os.environ.get("INFINITEMARKETS_ALLOW_INSECURE_RELAYS") == "1"


def relay_io_enabled() -> bool:
    """TEST-ONLY kill switch: ``INFINITEMARKETS_RELAY_IO=off`` builds the
    client but never dials — runtime host boots must not publish test
    events to real public relays."""
    return os.environ.get("INFINITEMARKETS_RELAY_IO", "on") != "off"


def validate_relay_target(raw: str) -> str:
    """§9.5 relay target validation; the test-only insecure allowance admits
    ``ws://`` loopback targets (LocalRelay fixtures) and nothing else."""
    if insecure_relays_allowed():
        url = raw.strip()
        if url.startswith("ws://"):
            try:
                parsed = RelayUrl.parse(url)
            except Exception as exc:
                raise unprocessable(
                    "invalid-relay", "Invalid relay URL"
                ) from exc
            if parsed.is_local_addr():
                return url
            raise unprocessable(
                "invalid-relay",
                "ws:// relay targets are test-only and must be loopback",
            )
    return validate_relay_url(raw)


async def validate_peer_relay_target(raw: str) -> str:
    """Strict wss:// target whose hostname DNS-resolves ONLY to public
    space — the D-30 peer-relay/discovery-time SSRF gate. Re-applied on
    every reconnect (call sites re-run it), so DNS rebinding flips an
    accepted target back out of service.

    The test-only insecure hatch admits ws:// loopback (LocalRelay)
    exactly like ``validate_relay_target`` — nothing else.
    """
    if insecure_relays_allowed() and raw.strip().startswith("ws://"):
        # The hatch admits ONLY genuine loopback ws:// targets
        # (LocalRelay). ``RelayUrl.is_local_addr`` also matches private
        # ranges — re-check the literal host so ws:// non-loopback can
        # never piggyback on the hatch.
        import ipaddress as _ip

        url = validate_relay_target(raw)  # raises unless is_local_addr
        host = urlparse(url).hostname or ""
        try:
            loopback = _ip.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if not loopback:
            raise unprocessable(
                "invalid-relay",
                "ws:// egress targets must be loopback",
            )
        return url
    parsed_url = urlparse(raw.strip())
    url = validate_relay_url(raw)  # wss-only + literal/TLD rejections
    host = parsed_url.hostname
    if not host:
        raise unprocessable("invalid-relay", "Relay URL has no host")
    await resolve_and_check_egress(host, parsed_url.port or 443)
    return url


# Backward-compatible alias kept for the earlier task-3 naming.
validate_egress_target = validate_peer_relay_target


class RelayTransport:
    """Owned client lifecycle — no signer, bounded options, validated set."""

    def __init__(self) -> None:
        self._client: Client | None = None
        self._targets: set[str] = set()

    @property
    def client(self) -> Client | None:
        return self._client

    async def start(self, relay_urls: list[str]) -> None:
        """Create the client and connect to the validated relay set."""
        if self._client is not None:
            return
        opts = (
            ClientOptions()
            # Bound message/event sizes the relay will accept from us.
            .relay_limits(_relay_limits())
            # Do not auto-retry forever on unreachable relays — the
            # relay_manager tick owns reconnection cadence.
            .autoconnect(False)
            # NIP-42 is handled MANUALLY through keystore.sign_event —
            # the SDK's automatic AUTH would need key material here.
            .automatic_authentication(False)
        )
        self._client = ClientBuilder().opts(opts).build()
        if not relay_io_enabled():
            return
        await self.sync_relays(relay_urls)
        await self._client.connect()

    async def sync_relays(self, relay_urls: list[str]) -> None:
        """Converge the client's relay set to the validated target list."""
        if self._client is None or not relay_io_enabled():
            return
        validated = {validate_relay_target(u) for u in relay_urls}
        for url in validated - self._targets:
            if await self._client.add_relay(RelayUrl.parse(url)):
                await self._client.connect_relay(RelayUrl.parse(url))
        for url in self._targets - validated:
            await self._client.remove_relay(RelayUrl.parse(url))
        self._targets = validated

    async def _connect_target(self, target) -> bool:
        """Pool-add + connect one validated target; returns True when the
        relay was newly pooled by this call (caller may release it).
        Ad-hoc additions beyond ``MAX_RELAYS`` are refused — the pool must
        stay bounded (§9.5)."""
        known = await self._client.relays()
        if target in known:
            await self._client.connect_relay(target)
            return False
        if len(known) >= MAX_RELAYS:
            return False
        await self._client.add_relay(target)
        await self._client.connect_relay(target)
        return True

    async def _release_adhoc(self, added: list) -> None:
        """Drop relays a single op pooled ad-hoc. A relay carrying live
        subscriptions (an inbox session converged onto it mid-op) is
        left in place — its owner tears it down."""
        for target in added:
            try:
                if await (await self._client.relay(target)).subscriptions():
                    continue
            except Exception:  # noqa: BLE001 — already gone
                continue
            try:
                await self._client.remove_relay(target)
            except Exception:  # noqa: BLE001 — best-effort teardown
                pass

    async def send_to(self, urls: list[str], event):
        """Send an already-signed event to an explicit validated subset.

        OQ6 finding: ``send_event_to`` does not connect on demand — a
        target the client never connected lands in ``failed`` as 'relay is
        initialized but not ready'. Ensure every target is connected first.
        Ad-hoc targets (peer relays) are released after the send — pooling
        them permanently grew the connection set without bound.
        """
        if self._client is None:
            raise RuntimeError("transport not started")
        if not relay_io_enabled():
            raise RuntimeError("relay io disabled")
        targets = [RelayUrl.parse(validate_relay_target(u)) for u in urls]
        added = [t for t in targets if await self._connect_target(t)]
        try:
            return await self._client.send_event_to(targets, event)
        finally:
            await self._release_adhoc(added)

    async def connected_urls(self) -> list[str]:
        if self._client is None:
            return []
        return [str(u) for u in (await self._client.relays()).keys()]

    async def fetch_from(self, urls: list[str], nostr_filter,
                        timeout_s: float = 10) -> list:
        """Auto-closing fetch against explicit validated targets (peer
        kind-10050 discovery). Returns [] when relay IO is disabled."""
        import datetime

        if self._client is None:
            await self.start([])
        if self._client is None or not relay_io_enabled():
            return []
        targets = [RelayUrl.parse(validate_relay_target(u)) for u in urls]
        added = [t for t in targets if await self._connect_target(t)]
        try:
            events = await self._client.fetch_events_from(
                targets, nostr_filter, datetime.timedelta(seconds=timeout_s)
            )
            return events.to_vec()
        finally:
            await self._release_adhoc(added)

    async def subscribe_to(self, urls: list[str], nostr_filter):
        """Long-lived subscription on explicit validated targets (§9.2
        inbox sessions). Returns the SDK SubscribeOutput; caller tracks
        ``output.id`` → session."""
        if self._client is None:
            raise RuntimeError("transport not started")
        if not relay_io_enabled():
            raise RuntimeError("relay io disabled")
        targets = [RelayUrl.parse(validate_relay_target(u)) for u in urls]
        for target in targets:
            await self._connect_target(target)
        return await self._client.subscribe_to(targets, nostr_filter)

    async def handle_notifications(self, handler) -> None:
        """Run the client's notification pump with ``handler`` — the
        Python ``HandleNotification`` impl dispatches event deliveries to
        admission and relay messages (EOSE/AUTH/CLOSED) to callbacks."""
        if self._client is None:
            raise RuntimeError("transport not started")
        await self._client.handle_notifications(handler)

    async def send_msg_to(self, urls: list[str], msg):
        """Send an arbitrary ClientMessage (e.g. the manual NIP-42 AUTH
        answer) on explicit validated connections."""
        if self._client is None:
            raise RuntimeError("transport not started")
        if not relay_io_enabled():
            raise RuntimeError("relay io disabled")
        targets = [RelayUrl.parse(validate_relay_target(u)) for u in urls]
        return await self._client.send_msg_to(targets, msg)

    async def unsubscribe(self, subscription_id: str) -> None:
        if self._client is not None:
            await self._client.unsubscribe(subscription_id)

    async def disconnect_relay(self, url: str) -> None:
        if self._client is not None:
            await self._client.disconnect_relay(RelayUrl.parse(url))

    async def remove_relay(self, url: str) -> None:
        """Full teardown — nostr-sdk keeps a disconnected relay in the
        pool where reconnecting silently never serves REQs; removing it
        makes the next add+connect+subscribe land on the wire."""
        if self._client is not None:
            target = RelayUrl.parse(url)
            try:
                await self._client.disconnect_relay(target)
            except Exception:  # noqa: BLE001 — best-effort
                pass
            await self._client.remove_relay(target)

    async def close(self) -> None:
        client, self._client = self._client, None
        self._targets = set()
        if client is not None:
            try:
                await client.disconnect()
            finally:
                await client.shutdown()


def _relay_limits():
    from nostr_sdk import RelayLimits

    limits = RelayLimits.disable()
    # keep generous-but-bounded message size (catalog events are small)
    limits.message_max_size = 256 * 1024
    limits.event_max_size = 128 * 1024
    return limits


_transport: RelayTransport | None = None


def transport() -> RelayTransport:
    """Process-wide owned transport (per-worker on multi-worker hosts)."""
    global _transport
    if _transport is None:
        _transport = RelayTransport()
    return _transport


async def start_transport() -> None:
    """infinitemarkets_start hook step — connect to the server-wide default +
    all configured public relay targets."""
    from . import relay as relay_service

    ext_settings()
    urls = await relay_service.all_public_targets()
    await transport().start(urls)
