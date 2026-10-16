"""BUD-02 raw ``PUT /upload`` client with server-side BUD-11 auth.

Phase 6 remote-media boundary (MEDIA-04/15/16):

- Authorization is a kind-24242 event signed inside the keystore custody
  boundary (``MerchantKeyStore.sign_event``) — nsec never reaches this
  module, callers, or logs. One event per upload, never reused; the
  header value is replayable until expiration so it is never logged,
  persisted, or returned.
- Egress is resolved and checked at REQUEST time on every call
  (``resolve_and_check_egress``) — config-time ``validate_blossom_url``
  is never trusted as an egress control. TLS connects to a checked IP
  while the hostname is preserved as SNI.
- Upload PUTs NEVER follow redirects: any 3xx is rejected without a
  second request, so body bytes and the Authorization token can never be
  replayed to a different host (locked owner decision — the bounded
  revalidated redirect policy applies to public GETs only).
- The returned descriptor is validated before its URL is exposed:
  sha256/size must match the sent body, type must be an allowed image
  MIME, and ``url`` must be https on the same host as the endpoint (D-11).
- At most ``MAX_IN_FLIGHT_PER_MERCHANT`` simultaneous in-flight PUTs per
  merchant (D-13); blocking ``http.client`` work runs in a thread under
  an overall deadline.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import http.client
import json
import socket
import ssl
import time
from urllib.parse import urlparse

from ..security import resolve_and_check_egress, unprocessable

AUTH_EXPIRATION_S = 300  # D-09 — short-lived BUD-11 token
AUTH_KIND = 24242
CONNECT_TIMEOUT_S = 10.0
UPLOAD_DEADLINE_S = 20.0
MAX_DESCRIPTOR_BYTES = 16 * 1024
MAX_DESCRIPTOR_URL_CHARS = 2048
MAX_IN_FLIGHT_PER_MERCHANT = 4  # D-13
_MAX_ADDRESS_ATTEMPTS = 2

_MIME_BY_EXT = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "webp": "image/webp",
}
_ALLOWED_DESCRIPTOR_TYPES = frozenset(_MIME_BY_EXT.values())

# Process-local cap. A multi-worker PG deployment cannot tighten this
# further in-process — it bounds per-worker egress pressure only.
_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a checked IP while retaining the original TLS hostname
    (adapted from ``og_images._PinnedHTTPSConnection``)."""

    def __init__(self, host: str, address: str, port: int = 443):
        super().__init__(
            host,
            port=port,
            timeout=CONNECT_TIMEOUT_S,
            context=ssl.create_default_context(),
        )
        self._address = address

    def connect(self):
        sock = socket.create_connection(
            (self._address, self.port), timeout=self.timeout
        )
        self.sock = self._context.wrap_socket(
            sock, server_hostname=self.host
        )


def _open_connection(host: str, address: str, port: int = 443):
    """Transport seam — tests substitute a plain loopback connection."""
    return _PinnedHTTPSConnection(host, address, port)


def _semaphore(merchant_id: str) -> asyncio.Semaphore:
    sem = _SEMAPHORES.get(merchant_id)
    if sem is None:
        sem = _SEMAPHORES[merchant_id] = asyncio.Semaphore(
            MAX_IN_FLIGHT_PER_MERCHANT
        )
    return sem


def build_auth_event(pubkey_hex: str, sha256_hex: str,
                     server_domain: str, now: int):
    """Unsigned kind-24242 BUD-11 event: ``t=upload``, ~300s expiration,
    required ``x`` body hash, and ``server`` scoped to the lowercase
    domain only — no scheme, port, or path (current BUD-11 table)."""
    from nostr_sdk import EventBuilder, Kind, PublicKey, Tag

    return (
        EventBuilder(Kind(AUTH_KIND), "Upload Blob")
        .tags(
            [
                Tag.parse(["t", "upload"]),
                Tag.parse(["expiration", str(int(now) + AUTH_EXPIRATION_S)]),
                Tag.parse(["x", sha256_hex]),
                Tag.parse(["server", server_domain.lower()]),
            ]
        )
        .build(PublicKey.parse(pubkey_hex))
    )


def build_auth_header(signed_event_json: bytes) -> str:
    """``Nostr <base64url-NO-PAD>`` — the urlsafe alphabet is required;
    ``base64.b64encode`` emits ``+/``/``=`` which servers reject."""
    return "Nostr " + base64.urlsafe_b64encode(
        signed_event_json
    ).decode().rstrip("=")


def validate_descriptor(raw: bytes, *, sha256: str, size: int, ext: str,
                        endpoint_host: str) -> dict:
    """A 200/201 is not trust — the descriptor must agree with the bytes
    we sent and point back at the same host over https (D-11)."""
    try:
        descriptor = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise unprocessable(
            "media-remote", "Upload descriptor is not JSON"
        ) from exc
    if not isinstance(descriptor, dict):
        raise unprocessable(
            "media-remote", "Upload descriptor is not an object"
        )
    if descriptor.get("sha256") != sha256:
        raise unprocessable(
            "media-remote", "Upload descriptor sha256 mismatch"
        )
    if descriptor.get("size") != size:
        raise unprocessable(
            "media-remote", "Upload descriptor size mismatch"
        )
    if descriptor.get("type") not in _ALLOWED_DESCRIPTOR_TYPES:
        raise unprocessable(
            "media-remote", "Upload descriptor type is not an image"
        )
    url = descriptor.get("url")
    if (
        not isinstance(url, str)
        or not url
        or len(url) > MAX_DESCRIPTOR_URL_CHARS
    ):
        raise unprocessable(
            "media-remote", "Upload descriptor url is unusable"
        )
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise unprocessable(
            "media-remote", "Upload descriptor url must be https"
        )
    if (parsed.hostname or "") != endpoint_host:
        raise unprocessable(
            "media-remote",
            "Upload descriptor url is on a different host",
        )
    return descriptor


def _put_once(host: str, address: str, port: int, body: bytes,
              headers: dict) -> tuple[int, bytes]:
    """One PUT through a pinned connection; bounded descriptor read.
    Runs in a worker thread — never awaited inline on the loop."""
    conn = _open_connection(host, address, port)
    try:
        conn.request("PUT", "/upload", body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read(MAX_DESCRIPTOR_BYTES + 1)
        if len(data) > MAX_DESCRIPTOR_BYTES:
            raise unprocessable(
                "media-remote", "Upload descriptor exceeds bounds"
            )
        return resp.status, data
    finally:
        conn.close()


async def _put(host: str, addresses: list, port: int, body: bytes,
               headers: dict) -> bytes:
    """Try the first two resolved addresses; return the raw descriptor
    body on 200/201. Any 3xx rejects WITHOUT a second request — the body
    and Authorization token are never forwarded anywhere (locked rule)."""
    last_error: Exception | None = None
    for address in addresses[:_MAX_ADDRESS_ATTEMPTS]:
        try:
            status, raw = await asyncio.to_thread(
                _put_once, host, str(address), port, body, headers
            )
        except (OSError, http.client.HTTPException) as exc:
            last_error = exc
            continue
        if 300 <= status < 400:
            raise unprocessable(
                "media-remote",
                "Upload endpoint redirected",
                "Blossom PUT /upload answered a redirect status; upload "
                "requests never follow redirects",
            )
        if status not in (200, 201):
            raise unprocessable(
                "media-remote",
                "Blossom upload rejected",
                f"endpoint answered HTTP {status}",
            )
        return raw
    raise unprocessable(
        "media-remote",
        "Blossom upload failed",
        "endpoint unreachable",
    ) from last_error


async def upload_blob(
    merchant_id: str,
    keystore,
    server_url: str,
    content: bytes,
    ext: str,
) -> dict:
    """BUD-02 raw ``PUT {server_url}/upload`` with BUD-11 auth.

    ``ext`` is the caller's magic-byte-sniffed type — never a browser
    filename or Content-Type. Returns ``{url, sha256, size, type,
    server}`` — descriptor fields only; the auth token and key material
    are never exposed.
    """
    parsed = urlparse(server_url or "")
    if parsed.scheme != "https" or not parsed.hostname:
        raise unprocessable(
            "media-remote", "Blossom endpoint must be an https URL"
        )
    mime = _MIME_BY_EXT.get(ext or "")
    if mime is None:
        raise unprocessable(
            "media-remote", "Unsupported media type",
            f"{ext!r} is not png/jpg/webp",
        )
    host = parsed.hostname
    port = parsed.port or 443
    sha256 = hashlib.sha256(content).hexdigest()

    # Request-time egress check on EVERY call — config-time
    # validate_blossom_url is never trusted as an egress control.
    addresses = await resolve_and_check_egress(host, port)

    async with _semaphore(merchant_id):
        # Sign BEFORE dialing; one event per upload, never cached.
        pubkey = await keystore.public_key(merchant_id)
        unsigned = build_auth_event(pubkey, sha256, host, int(time.time()))
        signed = await keystore.sign_event(merchant_id, unsigned)
        # Replayable until expiration — never log, persist, or return it.
        auth = build_auth_header(signed.as_json().encode())
        del signed
        headers = {
            "Content-Type": mime,
            "Content-Length": str(len(content)),
            "X-SHA-256": sha256,
            "Authorization": auth,
        }
        try:
            raw = await asyncio.wait_for(
                _put(host, addresses, port, content, headers),
                timeout=UPLOAD_DEADLINE_S,
            )
        except TimeoutError as exc:
            raise unprocessable(
                "media-remote", "Blossom upload timed out"
            ) from exc
        descriptor = validate_descriptor(
            raw,
            sha256=sha256,
            size=len(content),
            ext=ext,
            endpoint_host=host,
        )
    return {
        "url": descriptor["url"],
        "sha256": sha256,
        "size": len(content),
        "type": descriptor["type"],
        "server": server_url,
    }
