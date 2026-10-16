"""POST /media/upload + unused-upload control — host-boot coverage.

The local-storage slice of Phase 6 (06-01): a merchant with no Blossom
server configured uploads bounded, sniff-verified png/jpg/webp bytes; they
land content-addressed under the host data folder
``images/infinitemarkets/<ns24>/`` and results carry the D-04/D-07 relative
path plus the absolute ``public_base_url`` URL. svg/gif/empty/oversize
bytes, a >16-file request, over-quota uploads, and profile-bound uploads on
a non-public origin are all rejected without storing bytes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.runtime

API = "/infinitemarkets/api/v1"
ORIGIN = "https://shop.example"

_PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"IHDR"
        + b"\x00" * 13 + b"IDAT" + b"x" * 16 + b"IEND")
_JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 30 + b"\xff\xd9"
_WEBP = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBP" + b"VP8 " + b"\x00" * 16
_GIF = b"GIF89a" + b"\x00" * 32
_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'


def _headers(env: dict, csrf: str | None = None,
             origin: str = ORIGIN) -> dict:
    # Real cookie jar semantics: auth + double-submit cookie travel together.
    cookie = f"cookie_access_token={env['token']}"
    if csrf:
        cookie += f"; gm_csrf={csrf}"
    h = {"Cookie": cookie, "Origin": origin}
    if csrf:
        h["X-CSRF-Token"] = csrf
    return h


def _csrf(client) -> str:
    return client.cookies.get("gm_csrf") or ""


async def _merchant_id(env: dict) -> tuple[str, str]:
    """Create a merchant; return (merchant_id, csrf)."""
    client = env["client"]
    # the boundary issues gm_csrf on any authenticated request — seed it;
    # the shared user gets exactly one merchant (user_id UNIQUE).
    existing = await client.get(
        f"{API}/merchants/current", headers=_headers(env)
    )
    if existing.status_code == 200:
        return existing.json()["id"], _csrf(client)
    resp = await client.post(
        f"{API}/merchants",
        json={"wallet_id": env["wallet"].id},
        headers=_headers(env, _csrf(client)),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], _csrf(client)


def _media_dir(merchant_id: str) -> Path:
    from infinitemarkets.services import migration_media

    return migration_media._media_dir(merchant_id)


def _dir_names(merchant_id: str) -> set[str]:
    d = _media_dir(merchant_id)
    if not d.is_dir():
        return set()
    return {p.name for p in d.iterdir() if p.is_file()}


async def _upload(env: dict, csrf: str, files: list[tuple],
                  data: dict | None = None,
                  origin: str = ORIGIN):
    return await env["client"].post(
        f"{API}/media/upload",
        files=files,
        data=data or {},
        headers=_headers(env, csrf, origin),
    )


async def test_media_upload_stores_verified_image(runtime_env):
    """png bytes -> 200; content-addressed file lands in the merchant
    namespace; results carry relative path + absolute public_base_url URL."""
    from lnbits.settings import settings as host_settings

    env = runtime_env
    mid, csrf = await _merchant_id(env)
    payload = _PNG + b"media-01-stores-verified"
    resp = await _upload(
        env, csrf, [("file", ("hero.png", payload, "image/png"))]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["uploaded"] == 1
    sha = hashlib.sha256(payload).hexdigest()
    ns = body["namespace"]
    assert len(ns) == 24 and ns != mid
    result = body["results"][0]
    assert result["file"] == "hero.png"
    assert result["state"] == "stored"
    assert result["sha256"] == sha
    assert result["path"] == f"/images/infinitemarkets/{ns}/{sha}.png"
    assert result["url"] == (
        f"{ORIGIN}/images/infinitemarkets/{ns}/{sha}.png"
    )
    stored = (
        Path(host_settings.lnbits_data_folder)
        / "images" / "infinitemarkets" / ns / f"{sha}.png"
    )
    assert stored.is_file()
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == sha


async def test_media_upload_accepts_webp_jpg_and_is_idempotent(runtime_env):
    """webp/jpg land alongside png; re-uploading identical bytes is a
    content-addressed dedup — reported stored, no second file, no rewrite."""
    env = runtime_env
    mid, csrf = await _merchant_id(env)
    resp = await _upload(env, csrf, [
        ("file", ("a.jpg", _JPG + b"m01a", "image/jpeg")),
        ("file", ("b.webp", _WEBP + b"m01b", "image/webp")),
    ])
    assert resp.status_code == 200, resp.text
    states = {r["file"]: r["state"] for r in resp.json()["results"]}
    assert states == {"a.jpg": "stored", "b.webp": "stored"}
    assert resp.json()["uploaded"] == 2

    # dedup retry: same bytes -> same result, no additional file on disk
    before = _dir_names(mid)
    again = await _upload(
        env, csrf, [("file", ("a.jpg", _JPG + b"m01a", "image/jpeg"))]
    )
    assert again.status_code == 200, again.text
    assert again.json()["results"][0]["state"] == "stored"
    assert again.json()["uploaded"] == 1
    assert _dir_names(mid) == before


async def test_media_upload_rejects_svg_gif_empty_and_nonimage(runtime_env):
    """Magic-byte allowlist: svg, gif, empty, and random bytes never store."""
    env = runtime_env
    mid, csrf = await _merchant_id(env)
    before = _dir_names(mid)
    resp = await _upload(env, csrf, [
        ("file", ("icon.svg", _SVG, "image/svg+xml")),
        ("file", ("anim.gif", _GIF, "image/gif")),
        ("file", ("empty.png", b"", "image/png")),
        ("file", ("blob.png", b"\xde\xad\xbe\xef" * 8, "image/png")),
    ])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["uploaded"] == 0
    reasons = {r["file"]: r["reason"] for r in body["results"]}
    assert reasons["icon.svg"] == "not-an-image"
    assert reasons["anim.gif"] == "not-an-image"
    assert reasons["empty.png"] == "size"
    assert reasons["blob.png"] == "not-an-image"
    assert _dir_names(mid) == before


async def test_media_upload_size_and_file_count_bounds(runtime_env,
                                                       monkeypatch):
    """A part larger than MAX_FILE_BYTES is rejected; a request carrying
    more than 16 file parts is a 422 problem."""
    from infinitemarkets.services import migration_media

    env = runtime_env
    mid, csrf = await _merchant_id(env)
    monkeypatch.setattr(migration_media, "MAX_FILE_BYTES", 64)

    before = _dir_names(mid)
    big = _PNG + b"\x00" * 200
    resp = await _upload(
        env, csrf, [("file", ("big.png", big, "image/png"))]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["uploaded"] == 0
    assert resp.json()["results"][0]["reason"] == "size"
    assert _dir_names(mid) == before

    parts = [
        ("file", (f"f{i:02}.png", _PNG + str(i).encode(), "image/png"))
        for i in range(17)
    ]
    resp = await _upload(env, csrf, parts)
    assert resp.status_code == 422, resp.text


async def test_media_upload_merchant_quota(runtime_env, monkeypatch):
    """400 MB merchant quota (monkeypatched small): exceeding it -> 409
    media-quota and nothing lands on disk (D-01 leftovers count)."""
    from infinitemarkets.services import migration_media

    env = runtime_env
    mid, csrf = await _merchant_id(env)
    monkeypatch.setattr(migration_media, "MAX_MERCHANT_BYTES", 1)

    before = _dir_names(mid)
    resp = await _upload(
        env, csrf, [("file", ("q.png", _PNG + b"quota", "image/png"))]
    )
    assert resp.status_code == 409, resp.text
    assert "media-quota" in resp.json()["type"]
    assert _dir_names(mid) == before


@pytest.mark.parametrize(
    "bad_base",
    ["https://localhost", "https://10.0.0.5", "https://shop.local"],
)
async def test_media_upload_profile_usage_requires_public_origin(
        runtime_env, monkeypatch, bad_base):
    """D-05/D-08: a profile-bound local upload on a loopback/private/.local
    public_base_url -> 422 naming INFINITEMARKETS_PUBLIC_BASE_URL in plain
    language; catalog/appearance usage on the same host stays allowed."""
    env = runtime_env
    mid, csrf = await _merchant_id(env)
    monkeypatch.setenv("INFINITEMARKETS_PUBLIC_BASE_URL", bad_base)

    before = _dir_names(mid)
    resp = await _upload(
        env, csrf,
        [("file", ("avatar.png", _PNG + b"avatar", "image/png"))],
        data={"usage": "profile"},
        origin=bad_base,
    )
    assert resp.status_code == 422, resp.text
    problem = resp.json()
    assert "media-origin" in problem["type"]
    assert "INFINITEMARKETS_PUBLIC_BASE_URL" in problem["detail"]
    assert _dir_names(mid) == before

    # usage omitted / catalog on the same private origin: still allowed —
    # appearance fields may use the safe same-origin relative form (D-04).
    ok = await _upload(
        env, csrf,
        [("file", ("tile.png", _PNG + b"tile", "image/png"))],
        origin=bad_base,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["uploaded"] == 1


async def test_media_upload_rejects_unknown_fields_and_usage(runtime_env):
    """Only file parts + ``usage`` are accepted: a ``backend`` field is
    06-03's expansion and any other non-file part is a 422."""
    env = runtime_env
    mid, csrf = await _merchant_id(env)

    resp = await _upload(
        env, csrf,
        [("file", ("x.png", _PNG + b"x", "image/png"))],
        data={"backend": "blossom"},
    )
    assert resp.status_code == 422, resp.text

    resp = await _upload(
        env, csrf,
        [("file", ("x.png", _PNG + b"x", "image/png"))],
        data={"usage": "bogus"},
    )
    assert resp.status_code == 422, resp.text

    # no files at all -> 422; non-multipart -> 422
    resp = await _upload(
        env, csrf, [], data={"usage": "catalog"},
    )
    assert resp.status_code == 422, resp.text
    resp = await env["client"].post(
        f"{API}/media/upload",
        json={"file": "x"},
        headers=_headers(env, csrf),
    )
    assert resp.status_code == 422, resp.text
