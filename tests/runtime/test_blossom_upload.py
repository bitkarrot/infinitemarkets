"""Fake-Blossom BUD-02/BUD-11 protocol suite (MEDIA-04/15/16).

Loopback-only: a ``http.server.ThreadingHTTPServer`` fake records the
wire exchange and replies per a per-test script. The egress resolver and
the pinned-TLS connection are monkeypatched module seams so no test ever
dials a public Blossom server — URL validation, the ``server`` tag
domain, and D-11 descriptor-host checks still exercise the real
``https://media.example.com`` code path.

Signing runs through the REAL ``MerchantKeyStore.sign_event`` custody
path against a migrated tmp DB (``keystore_env``); the decoded auth
event is verified with ``nostr_sdk.Event.verify``.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import http.server
import importlib
import ipaddress
import json
import threading
import time
import uuid

import pytest

# ``fast`` lives on the service-level tests individually: the route-level
# dispatch tests at the bottom boot the real host (runtime_env) and can
# never belong to the seconds-scale quick gate.
pytestmark = pytest.mark.runtime

SERVER_URL = "https://media.example.com"
SERVER_HOST = "media.example.com"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _blossom():
    """Lazy import so collection stays clean pre-implementation; the RED
    failure names ``upload_blob`` rather than a module import error."""
    try:
        module = importlib.import_module("infinitemarkets.services.blossom")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "infinitemarkets.services.blossom.upload_blob is not implemented"
        ) from exc
    if not hasattr(module, "upload_blob"):
        raise AssertionError(
            "infinitemarkets.services.blossom.upload_blob is not implemented"
        )
    return module


class _FakeBlossom:
    """Loopback BUD-02 endpoint: records every request, replies per the
    per-test ``script`` callable ``record -> (status, headers, body)``."""

    def __init__(self):
        self.records: list[tuple[str, str, dict, bytes]] = []
        self.script = None
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()
        self.httpd = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), self._handler_class()
        )
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(
            target=self.httpd.serve_forever, daemon=True
        )
        self._thread.start()

    def _handler_class(self):
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep test output quiet
                pass

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                record = (
                    self.command,
                    self.path,
                    dict(self.headers.items()),
                    body,
                )
                with fake._lock:
                    fake.in_flight += 1
                    fake.max_in_flight = max(
                        fake.max_in_flight, fake.in_flight
                    )
                    fake.records.append(record)
                try:
                    status, headers, payload = fake.script(record)
                finally:
                    with fake._lock:
                        fake.in_flight -= 1
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if payload:
                    self.wfile.write(payload)

            do_PUT = _handle
            do_GET = _handle
            do_POST = _handle

        return Handler

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def fake_blossom():
    fake = _FakeBlossom()
    try:
        yield fake
    finally:
        fake.close()


def _wire_egress(blossom_mod, monkeypatch, fake, resolver=None):
    """Point the egress/connection seams at the loopback fake."""
    if resolver is None:

        async def resolver(host, port=443):
            return [ipaddress.ip_address("127.0.0.1")]

    monkeypatch.setattr(
        blossom_mod, "resolve_and_check_egress", resolver
    )
    monkeypatch.setattr(
        blossom_mod,
        "_open_connection",
        lambda host, address, port=443: http.client.HTTPConnection(
            "127.0.0.1", fake.port
        ),
    )


def _ext_settings(keystore_env):
    gsettings = keystore_env["settings"]
    return gsettings.ExtSettings(
        master_keys={"v1": bytes(32)},
        active_key_version="v1",
        privacy_key=bytes([9]) * 32,
        public_base_url="https://x.example",
    )


async def _merchant_keystore(keystore_env, monkeypatch):
    """Real custody path: merchant row + generated key in the tmp DB."""
    _set_env(monkeypatch)
    keystore_mod = keystore_env["keystore"]
    ks = keystore_mod.MerchantKeyStore(_ext_settings(keystore_env))
    mid = f"m-blossom-{uuid.uuid4().hex[:10]}"
    async with keystore_env["db"].connect() as conn:
        await conn.execute(
            "INSERT INTO infinitemarkets.merchants "
            "(id, user_id, pubkey, key_ref, wallet_id_enc, wallet_id_hash,"
            " state, created_at, updated_at) "
            "VALUES (:i, :u, :p, :kr, :w, 'h', 'draft', 0, 0)",
            {
                "i": mid,
                "u": uuid.uuid4().hex,
                "p": hashlib.sha256(mid.encode()).hexdigest(),
                "kr": f"merchant_keys:{mid}",
                "w": b"x",
            },
        )
    pubkey = await ks.generate(mid)
    return ks, mid, pubkey


def _set_env(monkeypatch):
    monkeypatch.setenv(
        "INFINITEMARKETS_MASTER_KEYS",
        json.dumps({"v1": base64.b64encode(bytes(32)).decode()}),
    )
    monkeypatch.setenv("INFINITEMARKETS_ACTIVE_KEY_VERSION", "v1")
    monkeypatch.setenv(
        "INFINITEMARKETS_PRIVACY_KEY",
        base64.b64encode(bytes([9]) * 32).decode(),
    )
    monkeypatch.setenv("INFINITEMARKETS_PUBLIC_BASE_URL", "https://x.example")


def _descriptor(sha: str, size: int, *, url=None, type="image/png") -> bytes:
    return json.dumps(
        {
            "url": url if url is not None else f"{SERVER_URL}/{sha}.png",
            "sha256": sha,
            "size": size,
            "type": type,
        }
    ).encode()


def _ok(payload: bytes):
    return lambda record: (
        200,
        {"Content-Type": "application/json"},
        payload,
    )


def _decode_auth(record) -> "object":
    """Decode the ``Nostr <base64url-no-pad>`` Authorization token into a
    verified ``nostr_sdk.Event``."""
    from nostr_sdk import Event

    auth = record[2].get("Authorization", "")
    assert auth.startswith("Nostr "), f"bad auth scheme: {auth!r}"
    token = auth[len("Nostr "):]
    assert "=" not in token, "BUD-11 token must be unpadded base64url"
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    event = Event.from_json(raw.decode())
    assert event.verify(), "auth event signature/id does not verify"
    return event


def _tag_map(event) -> dict:
    return {
        vec[0]: vec[1]
        for vec in (t.as_vec() for t in event.tags().to_vec())
        if len(vec) > 1
    }


# --- wire format + BUD-11 auth event (MEDIA-15) -------------------------------


@pytest.mark.fast
async def test_upload_put_wire_format_and_bud11_auth_event(
    keystore_env, monkeypatch, fake_blossom
):
    blossom = _blossom()
    ks, mid, pubkey = await _merchant_keystore(keystore_env, monkeypatch)
    sha = hashlib.sha256(PNG).hexdigest()
    fake_blossom.script = _ok(_descriptor(sha, len(PNG)))
    _wire_egress(blossom, monkeypatch, fake_blossom)

    result = await blossom.upload_blob(mid, ks, SERVER_URL, PNG, "png")

    assert len(fake_blossom.records) == 1
    method, path, headers, body = fake_blossom.records[0]
    assert method == "PUT"
    assert path == "/upload"
    assert body == PNG
    assert headers.get("X-SHA-256") == sha
    assert headers.get("Content-Type") == "image/png"
    assert int(headers.get("Content-Length") or -1) == len(PNG)

    event = _decode_auth(fake_blossom.records[0])
    assert event.kind().as_u16() == 24242
    assert event.author().to_hex() == pubkey
    assert event.content()  # human-readable authorization text
    tags = _tag_map(event)
    assert tags["t"] == "upload"
    assert tags["x"] == sha
    assert tags["server"] == SERVER_HOST  # lowercase domain only
    exp = int(tags["expiration"])
    assert 250 <= exp - int(time.time()) <= 350

    assert result == {
        "url": f"{SERVER_URL}/{sha}.png",
        "sha256": sha,
        "size": len(PNG),
        "type": "image/png",
        "server": SERVER_URL,
    }


@pytest.mark.fast
async def test_upload_signs_fresh_event_per_call(
    keystore_env, monkeypatch, fake_blossom
):
    """One event per upload — tokens are replayable until expiration and
    must never be cached across calls. A spy on the real sign_event
    proves the custody path runs for every call; distinct bodies also
    produce distinct event ids (x tag binds the token to the blob)."""
    blossom = _blossom()
    ks, mid, _ = await _merchant_keystore(keystore_env, monkeypatch)
    calls = 0
    real_sign = ks.sign_event

    async def _sign_spy(m, unsigned, conn=None):
        nonlocal calls
        calls += 1
        return await real_sign(m, unsigned, conn)

    monkeypatch.setattr(ks, "sign_event", _sign_spy)
    blobs = [PNG, b"\x89PNG\r\n\x1a\n" + b"\x01" * 32]
    shas = [hashlib.sha256(b).hexdigest() for b in blobs]
    lookup = {s: _descriptor(s, len(b)) for s, b in zip(shas, blobs)}
    fake_blossom.script = lambda record: (
        200,
        {"Content-Type": "application/json"},
        lookup[hashlib.sha256(record[3]).hexdigest()],
    )
    _wire_egress(blossom, monkeypatch, fake_blossom)

    for blob in blobs:
        await blossom.upload_blob(mid, ks, SERVER_URL, blob, "png")

    assert calls == 2, "keystore.sign_event must run once per upload"
    assert len(fake_blossom.records) == 2
    ids = {
        _decode_auth(r).id().to_hex() for r in fake_blossom.records
    }
    assert len(ids) == 2
    xs = {_tag_map(_decode_auth(r))["x"] for r in fake_blossom.records}
    assert xs == set(shas)


@pytest.mark.fast
async def test_upload_rejects_non_https_and_bad_ext(
    keystore_env, monkeypatch, fake_blossom
):
    from infinitemarkets.security import ProblemError

    blossom = _blossom()
    ks, mid, _ = await _merchant_keystore(keystore_env, monkeypatch)
    _wire_egress(blossom, monkeypatch, fake_blossom)
    fake_blossom.script = _ok(b"{}")

    for url in ("http://media.example.com", "https://", "notaurl"):
        with pytest.raises(ProblemError):
            await blossom.upload_blob(mid, ks, url, PNG, "png")
    with pytest.raises(ProblemError):
        await blossom.upload_blob(mid, ks, SERVER_URL, PNG, "gif")
    assert fake_blossom.records == []


# --- descriptor validation (D-11, MEDIA-05) -----------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        "wrong-sha256",
        "wrong-size",
        "gif-type",
        "http-url",
        "off-host-url",
        "oversized-url",
        "not-json",
        "not-object",
    ],
)
@pytest.mark.fast
async def test_descriptor_poison_rejected(
    keystore_env, monkeypatch, fake_blossom, mutate
):
    from infinitemarkets.security import ProblemError

    blossom = _blossom()
    ks, mid, _ = await _merchant_keystore(keystore_env, monkeypatch)
    sha = hashlib.sha256(PNG).hexdigest()
    payload = {
        "wrong-sha256": _descriptor(
            hashlib.sha256(b"other").hexdigest(), len(PNG)
        ),
        "wrong-size": _descriptor(sha, len(PNG) + 1),
        "gif-type": _descriptor(sha, len(PNG), type="image/gif"),
        "http-url": _descriptor(
            sha, len(PNG), url=f"http://{SERVER_HOST}/{sha}.png"
        ),
        "off-host-url": _descriptor(
            sha, len(PNG), url=f"https://cdn.evil.example/{sha}.png"
        ),
        "oversized-url": _descriptor(
            sha, len(PNG), url=f"{SERVER_URL}/{'a' * 2100}.png"
        ),
        "not-json": b"{not json",
        "not-object": b"[1,2]",
    }[mutate]
    fake_blossom.script = _ok(payload)
    _wire_egress(blossom, monkeypatch, fake_blossom)

    with pytest.raises(ProblemError) as excinfo:
        await blossom.upload_blob(mid, ks, SERVER_URL, PNG, "png")
    assert excinfo.value.status == 422
    assert excinfo.value.code == "media-remote"
    # the descriptor was received — the upload itself succeeded on the wire
    assert len(fake_blossom.records) == 1


@pytest.mark.fast
async def test_descriptor_201_accepted(
    keystore_env, monkeypatch, fake_blossom
):
    blossom = _blossom()
    ks, mid, _ = await _merchant_keystore(keystore_env, monkeypatch)
    sha = hashlib.sha256(PNG).hexdigest()
    fake_blossom.script = lambda record: (
        201,
        {"Content-Type": "application/json"},
        _descriptor(sha, len(PNG)),
    )
    _wire_egress(blossom, monkeypatch, fake_blossom)

    result = await blossom.upload_blob(mid, ks, SERVER_URL, PNG, "png")
    assert result["sha256"] == sha
    assert result["url"] == f"{SERVER_URL}/{sha}.png"


@pytest.mark.fast
async def test_descriptor_body_bound_rejected(
    keystore_env, monkeypatch, fake_blossom
):
    """A valid-JSON descriptor larger than the read bound is refused —
    the bound fires before parsing."""
    from infinitemarkets.security import ProblemError

    blossom = _blossom()
    ks, mid, _ = await _merchant_keystore(keystore_env, monkeypatch)
    sha = hashlib.sha256(PNG).hexdigest()
    payload = json.dumps(
        {
            "url": f"{SERVER_URL}/{sha}.png",
            "sha256": sha,
            "size": len(PNG),
            "type": "image/png",
            "pad": "x" * (20 * 1024),
        }
    ).encode()
    assert len(payload) > 16 * 1024
    fake_blossom.script = _ok(payload)
    _wire_egress(blossom, monkeypatch, fake_blossom)

    with pytest.raises(ProblemError) as excinfo:
        await blossom.upload_blob(mid, ks, SERVER_URL, PNG, "png")
    assert excinfo.value.code == "media-remote"


# --- egress + redirect discipline (MEDIA-16) ----------------------------------


@pytest.mark.fast
@pytest.mark.parametrize("status", [307, 308, 302])
async def test_redirect_rejected_single_request(
    keystore_env, monkeypatch, fake_blossom, status
):
    """Upload PUTs never follow redirects: exactly ONE request reaches
    the fake, no bytes/auth are replayed to the Location target."""
    from infinitemarkets.security import ProblemError

    blossom = _blossom()
    ks, mid, _ = await _merchant_keystore(keystore_env, monkeypatch)
    fake_blossom.script = lambda record: (
        status,
        {"Location": "https://evil.example/upload"},
        b"",
    )
    _wire_egress(blossom, monkeypatch, fake_blossom)

    with pytest.raises(ProblemError) as excinfo:
        await blossom.upload_blob(mid, ks, SERVER_URL, PNG, "png")
    assert excinfo.value.status == 422
    assert excinfo.value.code == "media-remote"
    assert "redirect" in excinfo.value.title.lower()
    assert len(fake_blossom.records) == 1


@pytest.mark.fast
async def test_egress_resolver_consulted_every_call(
    keystore_env, monkeypatch, fake_blossom
):
    """The resolver runs at REQUEST time — a spy proves every call
    re-resolves instead of trusting a cached config-time check."""
    blossom = _blossom()
    ks, mid, _ = await _merchant_keystore(keystore_env, monkeypatch)
    sha = hashlib.sha256(PNG).hexdigest()
    fake_blossom.script = _ok(_descriptor(sha, len(PNG)))
    calls = []

    async def _spy(host, port=443):
        calls.append((host, port))
        return [ipaddress.ip_address("127.0.0.1")]

    _wire_egress(blossom, monkeypatch, fake_blossom, resolver=_spy)

    await blossom.upload_blob(mid, ks, SERVER_URL, PNG, "png")
    await blossom.upload_blob(mid, ks, SERVER_URL, PNG, "png")
    assert calls == [(SERVER_HOST, 443), (SERVER_HOST, 443)]


@pytest.mark.fast
async def test_egress_rejection_precedes_any_connection(
    keystore_env, monkeypatch, fake_blossom
):
    """A resolver that refuses non-public space (the real
    resolve_and_check_egress contract) aborts the upload before a single
    connection is opened or a request emitted."""
    from infinitemarkets.security import ProblemError, unprocessable

    blossom = _blossom()
    ks, mid, _ = await _merchant_keystore(keystore_env, monkeypatch)
    dialed = []

    async def _private(host, port=443):
        raise unprocessable(
            "invalid-relay",
            "Relay host does not resolve to public routable space",
        )

    def _conn_spy(host, address, port=443):
        dialed.append(address)
        return http.client.HTTPConnection("127.0.0.1", fake_blossom.port)

    monkeypatch.setattr(blossom, "resolve_and_check_egress", _private)
    monkeypatch.setattr(blossom, "_open_connection", _conn_spy)

    with pytest.raises(ProblemError):
        await blossom.upload_blob(mid, ks, SERVER_URL, PNG, "png")
    assert dialed == []
    assert fake_blossom.records == []


# --- D-13 concurrency cap + result shape (MEDIA-04) ---------------------------


@pytest.mark.fast
async def test_in_flight_put_cap_per_merchant(
    keystore_env, monkeypatch, fake_blossom
):
    """D-13: at most 4 simultaneous in-flight PUTs per merchant — five
    parallel uploads through a slow handler never exceed the cap."""
    import asyncio

    blossom = _blossom()
    ks, mid, _ = await _merchant_keystore(keystore_env, monkeypatch)
    sha = hashlib.sha256(PNG).hexdigest()

    def _slow(record):
        time.sleep(0.4)
        return (
            200,
            {"Content-Type": "application/json"},
            _descriptor(sha, len(record[3])),
        )

    fake_blossom.script = _slow
    _wire_egress(blossom, monkeypatch, fake_blossom)

    results = await asyncio.gather(
        *(
            blossom.upload_blob(mid, ks, SERVER_URL, PNG, "png")
            for _ in range(5)
        )
    )
    assert len(results) == 5
    assert all(r["sha256"] == sha for r in results)
    assert fake_blossom.max_in_flight <= 4, (
        f"observed {fake_blossom.max_in_flight} in-flight PUTs"
    )
    # the cap actually serialized something — 5 uploads could not all
    # overlap through the 0.4s handler
    assert fake_blossom.max_in_flight >= 2


@pytest.mark.fast
async def test_result_dict_carries_no_key_or_token(
    keystore_env, monkeypatch, fake_blossom
):
    """MEDIA-04, structurally: the result exposes descriptor fields only
    — no Authorization token, no event JSON, no key material."""
    blossom = _blossom()
    ks, mid, _ = await _merchant_keystore(keystore_env, monkeypatch)
    sha = hashlib.sha256(PNG).hexdigest()
    fake_blossom.script = _ok(_descriptor(sha, len(PNG)))
    _wire_egress(blossom, monkeypatch, fake_blossom)

    result = await blossom.upload_blob(mid, ks, SERVER_URL, PNG, "png")

    assert set(result) == {"url", "sha256", "size", "type", "server"}
    blob = json.dumps(result)
    token = fake_blossom.records[0][2]["Authorization"]
    assert token not in blob
    assert "Nostr " not in blob
    assert "nsec" not in blob


# --- route-level dispatch: POST /media/upload backend=blossom (06-03) --------
# These tests exercise the real HTTP route inside a host boot (runtime_env)
# and therefore deliberately carry NO fast mark — the module's keystore-level
# tests above remain the fast-gate coverage.
#
# Locked dispatch contract under test:
#   - backend=blossom PUTs each file ONLY to get_blossom_servers()[0]
#   - a remote failure is a typed problem naming the server — zero local
#     bytes, and servers[1] is never contacted (no failover, no dual-write)
#   - blossom bytes never count toward the 400 MB local quota (D-06)
#   - the response discloses backend+server and carries no signing
#     material or token (MEDIA-04)

ROUTE_API = "/infinitemarkets/api/v1"
SECOND_URL = "https://second.example.com"
SECOND_HOST = "second.example.com"


@pytest.fixture
def fake_blossom_factory():
    made: list[_FakeBlossom] = []

    def _make() -> _FakeBlossom:
        fake = _FakeBlossom()
        made.append(fake)
        return fake

    try:
        yield _make
    finally:
        for fake in made:
            fake.close()


def _route_headers(env: dict, csrf: str | None = None) -> dict:
    cookie = f"cookie_access_token={env['token']}"
    if csrf:
        cookie += f"; gm_csrf={csrf}"
    h = {"Cookie": cookie, "Origin": "https://shop.example"}
    if csrf:
        h["X-CSRF-Token"] = csrf
    return h


async def _route_merchant(env: dict) -> tuple[str, str]:
    client = env["client"]
    existing = await client.get(
        f"{ROUTE_API}/merchants/current", headers=_route_headers(env)
    )
    if existing.status_code == 200:
        return existing.json()["id"], client.cookies.get("gm_csrf") or ""
    resp = await client.post(
        f"{ROUTE_API}/merchants",
        json={"wallet_id": env["wallet"].id},
        headers=_route_headers(env, client.cookies.get("gm_csrf") or ""),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], client.cookies.get("gm_csrf") or ""


async def _set_route_servers(env: dict, mid: str, csrf: str,
                             servers: list[str]):
    resp = await env["client"].patch(
        f"{ROUTE_API}/merchants/{mid}",
        json={"blossom_servers": servers},
        headers=_route_headers(env, csrf),
    )
    assert resp.status_code == 200, resp.text


def _route_media_names(merchant_id: str) -> set:
    from infinitemarkets.services import migration_media

    media_dir = migration_media._media_dir(merchant_id)
    if not media_dir.is_dir():
        return set()
    return {p.name for p in media_dir.iterdir() if p.is_file()}


def _wire_route_fakes(blossom_mod, monkeypatch, fakes_by_host: dict):
    """Point the egress/connection seams at per-host loopback fakes —
    recording which configured host the upload actually dialed."""

    async def resolver(host, port=443):
        assert host in fakes_by_host, f"unexpected egress target {host}"
        return [ipaddress.ip_address("127.0.0.1")]

    monkeypatch.setattr(
        blossom_mod, "resolve_and_check_egress", resolver
    )
    monkeypatch.setattr(
        blossom_mod,
        "_open_connection",
        lambda host, address, port=443: http.client.HTTPConnection(
            "127.0.0.1", fakes_by_host[host].port
        ),
    )


async def _route_upload(env: dict, csrf: str, data: dict | None = None):
    return await env["client"].post(
        f"{ROUTE_API}/media/upload",
        files=[("file", ("hero.png", PNG, "image/png"))],
        data=data or {},
        headers=_route_headers(env, csrf),
    )


async def test_route_upload_blossom_targets_first_configured_server(
    runtime_env, monkeypatch, fake_blossom, fake_blossom_factory
):
    """backend=blossom PUTs each file ONLY to get_blossom_servers()[0]:
    bytes + a verifiable BUD-11 event arrive at the first server, the
    second configured server records zero requests, nothing lands in the
    local namespace, and the response names the backend/server plus the
    validated descriptor url."""
    blossom = _blossom()
    env = runtime_env
    mid, csrf = await _route_merchant(env)
    second = fake_blossom_factory()
    await _set_route_servers(env, mid, csrf, [SERVER_URL, SECOND_URL])

    sha = hashlib.sha256(PNG).hexdigest()
    fake_blossom.script = _ok(_descriptor(sha, len(PNG)))
    _wire_route_fakes(
        blossom, monkeypatch,
        {SERVER_HOST: fake_blossom, SECOND_HOST: second},
    )

    before = _route_media_names(mid)
    resp = await _route_upload(env, csrf, data={"backend": "blossom"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["backend"] == "blossom"
    assert body["server"] == SERVER_URL
    assert body["uploaded"] == 1
    result = body["results"][0]
    assert result["state"] == "stored"
    assert result["backend"] == "blossom"
    assert result["server"] == SERVER_URL
    assert result["url"] == f"{SERVER_URL}/{sha}.png"
    assert result["sha256"] == sha
    assert "path" not in result

    # servers[0] saw exactly one PUT with the real wire format; the second
    # configured server was never contacted (no failover, no dual-write)
    assert len(fake_blossom.records) == 1
    method, path, headers, sent = fake_blossom.records[0]
    assert (method, path, sent) == ("PUT", "/upload", PNG)
    assert headers.get("X-SHA-256") == sha
    event = _decode_auth(fake_blossom.records[0])
    assert event.kind().as_u16() == 24242
    assert _tag_map(event)["server"] == SERVER_HOST
    assert second.records == []
    assert _route_media_names(mid) == before


@pytest.mark.parametrize("failure", ["http-500", "bad-descriptor"])
async def test_route_upload_blossom_failure_is_explicit(
    runtime_env, monkeypatch, fake_blossom, fake_blossom_factory, failure
):
    """A remote failure returns a typed problem NAMING the failed server,
    writes zero bytes to the local namespace, and never touches
    servers[1] — the merchant retries to local explicitly (locked)."""
    blossom = _blossom()
    env = runtime_env
    mid, csrf = await _route_merchant(env)
    second = fake_blossom_factory()
    await _set_route_servers(env, mid, csrf, [SERVER_URL, SECOND_URL])

    if failure == "http-500":
        fake_blossom.script = lambda record: (500, {}, b"boom")
    else:
        fake_blossom.script = _ok(
            _descriptor(hashlib.sha256(b"other").hexdigest(), len(PNG))
        )
    _wire_route_fakes(
        blossom, monkeypatch,
        {SERVER_HOST: fake_blossom, SECOND_HOST: second},
    )

    before = _route_media_names(mid)
    resp = await _route_upload(env, csrf, data={"backend": "blossom"})
    assert resp.status_code == 422, resp.text
    problem = resp.json()
    assert "media-remote" in problem["type"]
    assert SERVER_URL in problem["detail"]  # names the failed server
    assert _route_media_names(mid) == before
    assert second.records == []


async def test_route_upload_blossom_response_carries_no_signing_material(
    runtime_env, monkeypatch, fake_blossom
):
    """MEDIA-04 at the route boundary: the response discloses backend +
    server for editor copy but carries no BUD-11 token, no event JSON,
    and no key material."""
    blossom = _blossom()
    env = runtime_env
    mid, csrf = await _route_merchant(env)
    await _set_route_servers(env, mid, csrf, [SERVER_URL])
    sha = hashlib.sha256(PNG).hexdigest()
    fake_blossom.script = _ok(_descriptor(sha, len(PNG)))
    _wire_route_fakes(blossom, monkeypatch, {SERVER_HOST: fake_blossom})

    resp = await _route_upload(env, csrf, data={"backend": "blossom"})
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert set(result) <= {
        "file", "state", "backend", "server",
        "url", "sha256", "bytes", "type",
    }
    blob = resp.text
    token = fake_blossom.records[0][2]["Authorization"]
    assert token not in blob
    assert "Nostr " not in blob
    assert "nsec" not in blob


async def test_route_upload_blossom_bytes_never_count_toward_local_quota(
    runtime_env, monkeypatch, fake_blossom
):
    """D-06: the 400 MB quota gates the local branch only — a merchant
    over quota still uploads via blossom; remote storage limits are the
    Blossom operator's concern."""
    from infinitemarkets.services import migration_media

    blossom = _blossom()
    env = runtime_env
    mid, csrf = await _route_merchant(env)
    await _set_route_servers(env, mid, csrf, [SERVER_URL])
    sha = hashlib.sha256(PNG).hexdigest()
    fake_blossom.script = _ok(_descriptor(sha, len(PNG)))
    _wire_route_fakes(blossom, monkeypatch, {SERVER_HOST: fake_blossom})
    monkeypatch.setattr(migration_media, "MAX_MERCHANT_BYTES", 1)

    # the same bytes over the local branch hit the quota
    local = await _route_upload(env, csrf)
    assert local.status_code == 409, local.text
    assert "media-quota" in local.json()["type"]

    resp = await _route_upload(env, csrf, data={"backend": "blossom"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["backend"] == "blossom"
