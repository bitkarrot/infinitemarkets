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

pytestmark = [pytest.mark.runtime, pytest.mark.fast]

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
