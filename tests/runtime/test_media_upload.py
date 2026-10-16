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
    assert result["path"] == f"/library/infinitemarkets/{ns}/{sha}.png"
    assert result["url"] == (
        f"{ORIGIN}/library/infinitemarkets/{ns}/{sha}.png"
    )
    stored = (
        Path(host_settings.lnbits_data_folder)
        / "images" / "infinitemarkets" / ns / f"{sha}.png"
    )
    assert stored.is_file()
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == sha


async def test_uploaded_path_is_served_over_http(runtime_env):
    """Serveability (the 06-VERIFICATION gap): the emitted relative
    ``path`` must be fetchable on the qualified host — the pinned host
    mounts the data-folder ``images`` dir at ``/library``, so GET on the
    emitted path returns 200 with byte-identical content. This is the
    assertion whose absence let the dead ``/images/`` prefix ship."""
    env = runtime_env
    mid, csrf = await _merchant_id(env)
    payload = _PNG + b"serveable"
    resp = await _upload(
        env, csrf, [("file", ("serve.png", payload, "image/png"))]
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["state"] == "stored"
    assert result["path"].startswith("/library/infinitemarkets/")

    served = await env["client"].get(result["path"])
    assert served.status_code == 200, (result["path"], served.status_code)
    assert served.content == payload


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


async def test_media_upload_backend_dispatch(runtime_env):
    """06-03 dispatch: explicit ``local`` mirrors the absent-field default
    and the response discloses which backend received the bytes;
    ``blossom`` with no configured server -> 422 ``media-backend`` in
    plain language with zero local bytes written (no silent failover to
    local); a ``backend`` outside {local, blossom} -> 422."""
    env = runtime_env
    mid, csrf = await _merchant_id(env)

    resp = await _upload(
        env, csrf,
        [("file", ("loc.png", _PNG + b"backend-local", "image/png"))],
        data={"backend": "local"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["backend"] == "local"
    result = body["results"][0]
    assert result["state"] == "stored"
    assert result["backend"] == "local"
    assert "server" not in result
    sha = hashlib.sha256(_PNG + b"backend-local").hexdigest()
    assert (_media_dir(mid) / f"{sha}.png").is_file()

    before = _dir_names(mid)
    resp = await _upload(
        env, csrf,
        [("file", ("rem.png", _PNG + b"backend-blossom", "image/png"))],
        data={"backend": "blossom"},
    )
    assert resp.status_code == 422, resp.text
    problem = resp.json()
    assert "media-backend" in problem["type"]
    assert "Blossom" in (problem["title"] + problem["detail"])
    assert "local" in problem["detail"]
    assert _dir_names(mid) == before

    resp = await _upload(
        env, csrf,
        [("file", ("bad.png", _PNG + b"backend-bad", "image/png"))],
        data={"backend": "s3"},
    )
    assert resp.status_code == 422, resp.text


async def test_media_upload_rejects_unknown_fields_and_usage(runtime_env):
    """Only file parts + ``usage``/``backend`` are accepted: a ``backend``
    value outside the allowlist and any other non-file part is a 422."""
    env = runtime_env
    mid, csrf = await _merchant_id(env)

    resp = await _upload(
        env, csrf,
        [("file", ("x.png", _PNG + b"x", "image/png"))],
        data={"backend": "bogus"},
    )
    assert resp.status_code == 422, resp.text

    # any other non-file field is rejected
    resp = await _upload(
        env, csrf,
        [("file", ("x.png", _PNG + b"x", "image/png"))],
        data={"note": "hello"},
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


# --- D-02/D-12 unused-upload listing + explicit local deletion ----------------


async def _product(env: dict, csrf: str, title: str):
    """Create a minimal draft product; return the response body."""
    client = env["client"]
    cat = await client.post(
        f"{API}/categories",
        json={"name": f"cat-{title}", "default_currency": "USD"},
        headers=_headers(env, csrf),
    )
    assert cat.status_code == 201, cat.text
    resp = await client.post(
        f"{API}/products",
        json={
            "category_id": cat.json()["id"], "title": title,
            "amount_minor": 100, "currency": "USD",
            "currency_decimals": 2, "visibility": "hidden",
            "format": "digital", "draft": True,
        },
        headers=_headers(env, csrf),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _unused_names(env: dict) -> set[str]:
    resp = await env["client"].get(
        f"{API}/media/unused", headers=_headers(env)
    )
    assert resp.status_code == 200, resp.text
    return {f["name"] for f in resp.json()["files"]}


async def test_unused_listing_and_delete_lifecycle(runtime_env):
    """Upload -> listed; reference via a product image -> unlisted and
    DELETE -> 409; unreferenced DELETE -> gone; repeat -> 200 idempotent."""
    env = runtime_env
    mid, csrf = await _merchant_id(env)

    orphan_payload = _PNG + b"orphan"
    kept_payload = _PNG + b"kept"
    resp = await _upload(env, csrf, [
        ("file", ("orphan.png", orphan_payload, "image/png")),
        ("file", ("kept.png", kept_payload, "image/png")),
    ])
    assert resp.status_code == 200, resp.text
    results = {r["file"]: r for r in resp.json()["results"]}
    orphan_name = results["orphan.png"]["path"].rsplit("/", 1)[1]
    kept_name = results["kept.png"]["path"].rsplit("/", 1)[1]
    kept_url = results["kept.png"]["url"]

    # both unreferenced -> listed with name/bytes/sha256
    unused = await _unused_names(env)
    assert orphan_name in unused and kept_name in unused
    listing = (await env["client"].get(
        f"{API}/media/unused", headers=_headers(env)
    )).json()["files"]
    entry = next(f for f in listing if f["name"] == orphan_name)
    assert entry["bytes"] == len(orphan_payload)
    assert entry["sha256"] == hashlib.sha256(orphan_payload).hexdigest()

    # referencing kept.png as a product image removes it from the list —
    # absolute https form carries the infinitemarkets/<ns>/<name> substring.
    product = await _product(env, csrf, "media-ref")
    patched = await env["client"].patch(
        f"{API}/products/{product['id']}",
        json={"images": [{"url": kept_url}]},
        headers=_headers(env, csrf),
    )
    assert patched.status_code == 200, patched.text
    unused = await _unused_names(env)
    assert kept_name not in unused and orphan_name in unused

    # referenced file is not deletable
    resp = await env["client"].delete(
        f"{API}/media/unused/{kept_name}", headers=_headers(env, csrf)
    )
    assert resp.status_code == 409, resp.text
    assert "media-referenced" in resp.json()["type"]

    # orphan deletes, repeat is idempotent, file is really gone
    resp = await env["client"].delete(
        f"{API}/media/unused/{orphan_name}", headers=_headers(env, csrf)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] is True
    assert not (_media_dir(mid) / orphan_name).exists()
    assert orphan_name not in await _unused_names(env)
    resp = await env["client"].delete(
        f"{API}/media/unused/{orphan_name}", headers=_headers(env, csrf)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] is False


async def test_unused_listing_reports_mtime_and_quota(runtime_env):
    """D-23: every ``files[]`` entry carries ``mtime`` (epoch seconds from
    ``stat().st_mtime``) and the top-level response carries
    ``used_bytes``/``quota_bytes`` so the Settings -> Media block can
    render a date column plus a quota bar. ``quota_bytes`` is the 400 MB
    namespace cap; ``used_bytes`` counts every byte under the namespace —
    REFERENCED files included (D-01 ``_dir_bytes`` semantics), so an
    orphan-only number would be the wrong answer."""
    from infinitemarkets.services import migration_media

    env = runtime_env
    mid, csrf = await _merchant_id(env)

    orphan_payload = _PNG + b"mtime-orphan"
    kept_payload = _PNG + b"mtime-kept"
    resp = await _upload(env, csrf, [
        ("file", ("mtime-orphan.png", orphan_payload, "image/png")),
        ("file", ("mtime-kept.png", kept_payload, "image/png")),
    ])
    assert resp.status_code == 200, resp.text
    results = {r["file"]: r for r in resp.json()["results"]}
    orphan_name = results["mtime-orphan.png"]["path"].rsplit("/", 1)[1]
    kept_url = results["mtime-kept.png"]["url"]

    # referencing kept.png leaves the orphan as the only listing entry
    # while its bytes still sit inside the namespace
    product = await _product(env, csrf, "media-quota")
    patched = await env["client"].patch(
        f"{API}/products/{product['id']}",
        json={"images": [{"url": kept_url}]},
        headers=_headers(env, csrf),
    )
    assert patched.status_code == 200, patched.text

    resp = await env["client"].get(
        f"{API}/media/unused", headers=_headers(env)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # quota summary: the 400 MB cap plus the full namespace total — the
    # referenced kept file still counts toward used_bytes
    assert body["quota_bytes"] == migration_media.MAX_MERCHANT_BYTES
    on_disk = sum(
        p.stat().st_size
        for p in _media_dir(mid).glob("*")
        if p.is_file()
    )
    assert body["used_bytes"] == on_disk
    assert body["used_bytes"] >= len(orphan_payload) + len(kept_payload)

    # every entry carries a renderable mtime (epoch seconds > 0)
    for f in body["files"]:
        assert isinstance(f["mtime"], (int, float))
        assert f["mtime"] > 0
    entry = next(f for f in body["files"] if f["name"] == orphan_name)
    assert entry["mtime"] == (
        _media_dir(mid) / orphan_name
    ).stat().st_mtime


async def test_unused_delete_rejects_traversal_and_bad_names(runtime_env):
    """Names failing [0-9a-f]{64}.(png|jpg|webp) -> 422 before any
    filesystem touch — traversal is impossible by construction."""
    env = runtime_env
    mid, csrf = await _merchant_id(env)
    before = _dir_names(mid)
    for bad in (
        "../escape.png",
        "..%2F..%2Fescape.png",
        "x" * 64 + ".png",          # non-hex
        "a" * 63 + ".png",          # short
        "a" * 64 + ".gif",          # wrong ext
        "a" * 64 + ".png/x",        # path suffix
        "manifest.json",
    ):
        resp = await env["client"].delete(
            f"{API}/media/unused/{bad}", headers=_headers(env, csrf)
        )
        assert resp.status_code in (404, 422), (bad, resp.status_code)
    assert _dir_names(mid) == before


async def test_dual_prefix_references_keep_file_off_unused(runtime_env):
    """D-12 dual-prefix (06-04 gap closure): a ``product_images.url``
    stored under EITHER the legacy ``/images/infinitemarkets/`` prefix or
    the live ``/library/infinitemarkets/`` prefix marks the same on-disk
    file referenced — absent from ``GET /media/unused`` and DELETE -> 409
    for both forms. Rows are seeded via SQL because pre-m019 deployments
    carry the legacy prefix verbatim."""
    import uuid as uuid_mod

    from infinitemarkets.db import db, table
    from infinitemarkets.services import migration_media

    env = runtime_env
    mid, csrf = await _merchant_id(env)
    media_dir = _media_dir(mid)
    media_dir.mkdir(parents=True, exist_ok=True)
    ns = migration_media._namespace(mid)

    legacy_payload = _PNG + b"legacy-prefix-ref"
    legacy_name = f"{hashlib.sha256(legacy_payload).hexdigest()}.png"
    (media_dir / legacy_name).write_bytes(legacy_payload)
    live_payload = _PNG + b"live-prefix-ref"
    live_name = f"{hashlib.sha256(live_payload).hexdigest()}.png"
    (media_dir / live_name).write_bytes(live_payload)

    product = await _product(env, csrf, "dual-prefix-refs")
    async with db.connect() as conn:
        for url in (
            f"/images/infinitemarkets/{ns}/{legacy_name}",
            f"/library/infinitemarkets/{ns}/{live_name}",
        ):
            await conn.execute(
                f"INSERT INTO {table('product_images')} "
                "(id, product_id, url, sort_order) "
                "VALUES (:i, :p, :u, 0)",
                {"i": uuid_mod.uuid4().hex, "p": product["id"], "u": url},
            )

    unused = await _unused_names(env)
    assert legacy_name not in unused and live_name not in unused
    for name in (legacy_name, live_name):
        resp = await env["client"].delete(
            f"{API}/media/unused/{name}", headers=_headers(env, csrf)
        )
        assert resp.status_code == 409, (name, resp.text)
        assert (media_dir / name).is_file()


async def test_sidecar_owned_files_never_listed(runtime_env):
    """Migration-owned filenames (sidecar manifest values) are excluded
    from /media/unused and refuse deletion — pending relinks are safe."""
    from infinitemarkets.services import migration_media

    env = runtime_env
    mid, csrf = await _merchant_id(env)
    media_dir = _media_dir(mid)
    media_dir.mkdir(parents=True, exist_ok=True)

    # seed a file recorded in the migration sidecar + an unrecorded one
    sidecar_payload = _PNG + b"sidecar-owned"
    sidecar_sha = hashlib.sha256(sidecar_payload).hexdigest()
    sidecar_name = f"{sidecar_sha}.png"
    (media_dir / sidecar_name).write_bytes(sidecar_payload)
    migration_media._save_sidecar(
        mid, {"https://cdn.example/migrated.png": sidecar_name}
    )
    free_payload = _PNG + b"free-standing"
    free_sha = hashlib.sha256(free_payload).hexdigest()
    free_name = f"{free_sha}.png"
    (media_dir / free_name).write_bytes(free_payload)

    unused = await _unused_names(env)
    assert sidecar_name not in unused
    assert free_name in unused

    resp = await env["client"].delete(
        f"{API}/media/unused/{sidecar_name}", headers=_headers(env, csrf)
    )
    assert resp.status_code == 409, resp.text
    assert (media_dir / sidecar_name).is_file()

    # restore the sidecar to its prior state for other tests
    migration_media._save_sidecar(mid, {})


# --- D-07 catalog round-trip + migration coexistence ---------------------------


async def test_uploaded_absolute_url_round_trips_through_catalog(runtime_env):
    """D-07: the uploaded absolute https URL satisfies the catalog's
    ``https://`` image validator — PATCH /products/{id} accepts it and the
    stored row carries it verbatim."""
    from infinitemarkets.db import db, table

    env = runtime_env
    mid, csrf = await _merchant_id(env)
    resp = await _upload(
        env, csrf, [("file", ("rt.png", _PNG + b"roundtrip", "image/png"))]
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["url"].startswith("https://")

    product = await _product(env, csrf, "media-roundtrip")
    patched = await env["client"].patch(
        f"{API}/products/{product['id']}",
        json={"images": [{"url": result["url"]}]},
        headers=_headers(env, csrf),
    )
    assert patched.status_code == 200, patched.text
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT url FROM {table('product_images')} "
            "WHERE product_id = :p",
            {"p": product["id"]},
        )
    assert row["url"] == result["url"]


async def test_catalog_accepts_owned_relative_image_prefixes(runtime_env):
    """MEDIA-11 service-side slice (06-04): the catalog image validator
    accepts the two extension-owned relative prefixes — the live
    ``/library/infinitemarkets/`` mount and the legacy
    ``/images/infinitemarkets/`` form (still editable on rows predating
    m019) — while non-owned relative paths and ``http://`` stay 422."""
    from infinitemarkets.services import migration_media

    env = runtime_env
    mid, csrf = await _merchant_id(env)
    ns = migration_media._namespace(mid)
    product = await _product(env, csrf, "prefix-validation")

    for good in (
        f"/library/infinitemarkets/{ns}/{'ab' * 32}.png",
        f"/images/infinitemarkets/{ns}/{'cd' * 32}.png",
    ):
        patched = await env["client"].patch(
            f"{API}/products/{product['id']}",
            json={"images": [{"url": good}]},
            headers=_headers(env, csrf),
        )
        assert patched.status_code == 200, (good, patched.text)

    for bad in (
        "/library/other/file.png",
        "/images/other/file.png",
        "/infinitemarkets/x.png",
        "http://insecure.example/x.png",
        "//protocol-relative.example/x.png",
    ):
        patched = await env["client"].patch(
            f"{API}/products/{product['id']}",
            json={"images": [{"url": bad}]},
            headers=_headers(env, csrf),
        )
        assert patched.status_code == 422, (bad, patched.status_code)


async def test_media_and_migration_share_namespace(runtime_env):
    """D-01: one namespace, one quota — the general media flow resolves the
    same directory and local path the migration flow uses."""
    from infinitemarkets.services import media, migration_media

    env = runtime_env
    mid, _ = await _merchant_id(env)
    assert (
        media.local_path(mid, "probe.png")
        == migration_media._local_url(mid, "probe.png")
    )
    assert media._dir_bytes(migration_media._media_dir(mid)) >= 0
