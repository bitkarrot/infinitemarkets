"""Owned-media ingest for migration (plan 04-03 Task 2).

Stage 2 of the Shopify media handoff: the merchant downloads CDN images
locally (no server-side URL fetching is ever performed), then uploads a
JSON manifest mapping source URLs to expected sha256 digests plus the
image bytes themselves. Verified bytes land under the host's data folder
``images/infinitemarkets/<merchant namespace>/`` — outside the
reinstallable extension package — served by the host's ``/images`` mount.
A sidecar ``manifest.json`` in that directory records the URL→file
mapping; ``relink_media`` then swaps owned ``product_images.url``
references to the local paths in one transaction. Anything unverified
keeps its original URL.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from lnbits.settings import settings as host_settings

from ..db import DomainTransaction, db, table
from ..security import conflict, unprocessable

MAX_MANIFEST_ENTRIES = 500
MAX_FILES_PER_REQUEST = 16
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_MERCHANT_BYTES = 400 * 1024 * 1024
_MAX_MANIFEST_BYTES = 512 * 1024

_SIDECAR = "manifest.json"


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return None


def _namespace(merchant_id: str) -> str:
    from .. import crypto
    from ..settings import ext_settings

    return crypto.hmac_index(
        ext_settings().privacy_key, "media-ns", merchant_id, ""
    )[:24]


def _media_dir(merchant_id: str) -> Path:
    return (
        Path(host_settings.lnbits_data_folder)
        / "images" / "infinitemarkets" / _namespace(merchant_id)
    )


def _sidecar_path(merchant_id: str) -> Path:
    return _media_dir(merchant_id) / _SIDECAR


def _load_sidecar(merchant_id: str) -> dict[str, str]:
    path = _sidecar_path(merchant_id)
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        url: name for url, name in raw.items()
        if isinstance(url, str) and isinstance(name, str)
        and re.fullmatch(r"[0-9a-f]{64}\.(png|jpg|webp)", name)
    }


def _save_sidecar(merchant_id: str, mapping: dict[str, str]) -> None:
    tmp = _sidecar_path(merchant_id).with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(mapping, sort_keys=True, separators=(",", ":")),
        "utf-8",
    )
    tmp.replace(_sidecar_path(merchant_id))


def parse_manifest(raw: str | bytes) -> dict[str, str]:
    """``{"<source-url>": "<sha256-hex>", ...}`` — bounded."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "strict")
    if len(raw.encode()) > _MAX_MANIFEST_BYTES:
        raise unprocessable("invalid-content", "manifest too large")
    try:
        manifest = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise unprocessable("invalid-content", "manifest must be JSON") from exc
    if not isinstance(manifest, dict) or not manifest \
            or len(manifest) > MAX_MANIFEST_ENTRIES:
        raise unprocessable("invalid-content", "manifest must map URL to sha256")
    for url, digest in manifest.items():
        if (not isinstance(url, str) or len(url) > 2048
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise unprocessable(
                "invalid-content",
                "manifest entries must map URL to a 64-hex sha256",
            )
    return dict(manifest)


async def _owned_image_urls(conn, merchant_id: str) -> set[str]:
    rows = await conn.fetchall(
        f"SELECT i.url FROM {table('product_images')} i "
        f"JOIN {table('products')} p ON p.id = i.product_id "
        "WHERE p.merchant_id = :m AND p.deleted_at IS NULL",
        {"m": merchant_id},
    )
    return {row["url"] for row in rows}


async def upload_media(
    merchant_id: str, user, manifest: dict[str, str],
    files: list[tuple[str, bytes]],
) -> dict:
    """Verify and stage uploaded image bytes for manifest-listed URLs.

    ``files`` are ``(filename, bytes)`` tuples; the supplied filenames are
    never trusted — stored names are ``<sha256>.<ext>`` derived from
    verified content, so retries and duplicates are idempotent."""
    from . import catalog

    await catalog._merchant_owned(merchant_id, user)
    if not files or len(files) > MAX_FILES_PER_REQUEST:
        raise unprocessable(
            "invalid-content",
            f"upload 1 to {MAX_FILES_PER_REQUEST} image files per request",
        )
    allowed = await _owned_image_urls(db, merchant_id)
    unowned = [url for url in manifest if url not in allowed]
    if unowned:
        raise conflict(
            "media-scope", "manifest references images not in this catalog",
        )
    if len({digest for digest in manifest.values()}) != len(manifest):
        raise conflict("invalid-content", "manifest sha256 values must be unique")
    by_hash = {digest: url for url, digest in manifest.items()}

    verified: list[dict] = []
    results = []
    for name, content in files:
        if not content or len(content) > MAX_FILE_BYTES:
            results.append({"file": name, "state": "rejected", "reason": "size"})
            continue
        digest = hashlib.sha256(content).hexdigest()
        url = by_hash.get(digest)
        if url is None:
            results.append({"file": name, "state": "rejected",
                            "reason": "hash-not-in-manifest"})
            continue
        ext = _sniff(content)
        if not ext:
            results.append({"file": name, "state": "rejected",
                            "reason": "not-an-image"})
            continue
        verified.append({"url": url, "sha256": digest, "ext": ext,
                         "content": content, "name": name})
        results.append({"file": name, "sha256": digest, "url": url,
                        "state": "verified", "bytes": len(content)})
    if not verified:
        return {"uploaded": 0, "results": results,
                "namespace": _namespace(merchant_id)}

    media_dir = _media_dir(merchant_id)
    existing = sum(
        f.stat().st_size for f in media_dir.glob("*") if f.is_file()
    ) if media_dir.is_dir() else 0
    incoming = sum(len(item["content"]) for item in verified)
    if existing + incoming > MAX_MERCHANT_BYTES:
        raise conflict("media-quota", "Merchant media quota exceeded")
    media_dir.mkdir(parents=True, exist_ok=True)

    sidecar = _load_sidecar(merchant_id)
    uploaded = 0
    for item in verified:
        dest = media_dir / f"{item['sha256']}.{item['ext']}"
        if (dest.is_file() and not dest.is_symlink()
                and dest.stat().st_size == len(item["content"])):
            sidecar[item["url"]] = dest.name
            continue  # retry — already stored
        tmp = media_dir / f".{item['sha256']}.{item['ext']}.tmp"
        tmp.write_bytes(item["content"])
        # re-verify what landed before promoting
        if hashlib.sha256(tmp.read_bytes()).hexdigest() != item["sha256"]:
            tmp.unlink(missing_ok=True)
            results.append({"file": item["name"], "state": "rejected",
                            "reason": "write-verify-failed"})
            continue
        tmp.replace(dest)
        sidecar[item["url"]] = dest.name
        uploaded += 1
    _save_sidecar(merchant_id, sidecar)
    return {"uploaded": uploaded, "results": results,
            "namespace": _namespace(merchant_id)}


def _local_url(merchant_id: str, name: str) -> str:
    return f"/images/infinitemarkets/{_namespace(merchant_id)}/{name}"


async def relink_media(merchant_id: str, user) -> dict:
    """Swap owned product-image URLs to verified local files.

    Only URLs recorded in the upload sidecar whose stored file still
    verifies are relinked, in a single transaction. Unmatched or failed
    URLs keep their original CDN reference."""
    from . import catalog

    await catalog._merchant_owned(merchant_id, user)
    sidecar = _load_sidecar(merchant_id)
    if not sidecar:
        return {"relinked": 0, "unmatched": []}
    media_dir = _media_dir(merchant_id)
    replacements: dict[str, str] = {}
    unmatched = []
    for url, name in sidecar.items():
        path = media_dir / name
        if (not path.is_file() or path.is_symlink()
                or hashlib.sha256(path.read_bytes()).hexdigest()
                != name.split(".")[0]):
            unmatched.append(url)
            continue
        replacements[url] = _local_url(merchant_id, name)
    async with DomainTransaction() as tx:
        await tx.fetch_one(
            f"SELECT id FROM {tx.table('merchants')} WHERE id = :m{tx.for_update}",
            {"m": merchant_id},
        )
        rows = await tx.fetch_all(
            f"SELECT i.id, i.url FROM {tx.table('product_images')} i "
            f"JOIN {tx.table('products')} p ON p.id = i.product_id "
            "WHERE p.merchant_id = :m AND p.deleted_at IS NULL "
            "AND i.url NOT LIKE '/images/infinitemarkets/%' LIMIT 5001",
            {"m": merchant_id},
        )
        if len(rows) > 5000:
            raise conflict("media-scope", "too many image rows to relink")
        relinked = 0
        for row in rows:
            local = replacements.get(row["url"])
            if not local:
                continue
            rc = await tx.execute(
                f"UPDATE {tx.table('product_images')} SET url = :u "
                "WHERE id = :i AND url = :old",
                {"u": local, "i": row["id"], "old": row["url"]},
            )
            relinked += rc
        return {"relinked": relinked, "unmatched": unmatched}
