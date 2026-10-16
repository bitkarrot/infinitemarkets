"""Local media storage adapter + unused-upload control (plan 06-01).

Shared local-storage adapter every upload takes when no Blossom backend is
selected (MEDIA-01). Built on the proven ``migration_media`` internals —
HMAC namespace, data-folder media dir, magic-byte sniff allowlist,
size/quota bounds, tmp+rehash+replace write-verify — so the migration flow
and general uploads share ONE namespace and ONE quota (D-01). Stored names
are ``<sha256>.<ext>`` derived from verified bytes, so retries and
duplicates are idempotent (D-03). Absolute URLs are built from
``ext_settings().public_base_url`` — never from request Host headers
(D-04/D-07).
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from urllib.parse import urlparse

from ..db import db, table
from ..security import conflict, is_public_ip, unprocessable
from ..settings import ext_settings
from . import migration_media

_NAME_RE = re.compile(r"[0-9a-f]{64}\.(png|jpg|webp)")

#: Multipart ``usage`` field vocabulary — the field the editor uses to say
#: where an upload is bound. ``backend`` is plan 06-03's expansion and is
#: not accepted here.
MEDIA_USAGES = ("catalog", "profile", "appearance")


def local_path(merchant_id: str, name: str) -> str:
    """Same-origin path the host ``/images`` mount serves (D-04)."""
    return (
        "/images/infinitemarkets/"
        f"{migration_media._namespace(merchant_id)}/{name}"
    )


def absolute_url(merchant_id: str, name: str) -> str:
    """D-07 stored representation: operator-configured origin + path."""
    return ext_settings().public_base_url + local_path(merchant_id, name)


def origin_is_public(base_url: str) -> bool:
    """D-08 gate: can ``base_url`` produce a relay-reachable https URL?

    A name-form check only — DNS is never resolved here. False for an
    empty/single-label host, ``localhost``/``.localhost``/``.local`` names,
    and IP literals that fail ``security.is_public_ip`` (loopback,
    RFC-1918, link-local, CGNAT, ...).
    """
    host = (urlparse(base_url).hostname or "").lower().rstrip(".")
    if not host or "." not in host:
        return False  # empty or single label (e.g. "localhost")
    if host == "localhost" or host.endswith((".localhost", ".local")):
        return False
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return True  # DNS name — form is fine; reachability is operator config
    return is_public_ip(ip)


def _dir_bytes(media_dir) -> int:
    """All bytes in the namespace dir — leftover/unsaved files count
    toward the quota just like referenced ones (D-01)."""
    if not media_dir.is_dir():
        return 0
    return sum(f.stat().st_size for f in media_dir.glob("*") if f.is_file())


def _already_stored(dest, size: int) -> bool:
    return (
        dest.is_file()
        and not dest.is_symlink()
        and dest.stat().st_size == size
    )


async def store_local(
    merchant_id: str, user, files: list[tuple[str, bytes]]
) -> dict:
    """Verify and store uploaded image bytes under the merchant namespace.

    ``files`` are ``(filename, bytes)`` tuples; supplied filenames are
    never trusted. Per-file results carry the relative ``path`` and the
    absolute ``url`` (D-04/D-07). General uploads are NOT recorded in the
    migration sidecar — D-12 unreferenced detection is URL-based and
    sidecar values are treated as migration-owned.
    """
    from . import catalog

    await catalog._merchant_owned(merchant_id, user)
    if not files or len(files) > migration_media.MAX_FILES_PER_REQUEST:
        raise unprocessable(
            "invalid-content",
            f"upload 1 to {migration_media.MAX_FILES_PER_REQUEST} "
            "image files per request",
        )

    results: list[dict] = []
    verified: list[tuple[dict, dict]] = []
    for name, content in files:
        result = {"file": name}
        results.append(result)
        if not content or len(content) > migration_media.MAX_FILE_BYTES:
            result.update(state="rejected", reason="size")
            continue
        digest = hashlib.sha256(content).hexdigest()
        ext = migration_media._sniff(content)
        if not ext:
            result.update(state="rejected", reason="not-an-image")
            continue
        stored_name = f"{digest}.{ext}"
        result.update(
            state="stored",
            sha256=digest,
            bytes=len(content),
            path=local_path(merchant_id, stored_name),
            url=absolute_url(merchant_id, stored_name),
        )
        verified.append(
            (result, {"content": content, "name": stored_name})
        )
    namespace = migration_media._namespace(merchant_id)
    if not verified:
        return {"uploaded": 0, "results": results, "namespace": namespace}

    media_dir = migration_media._media_dir(merchant_id)
    # Dedup retry safety (D-03): bytes already stored add nothing to the
    # quota — they are already part of ``existing``.
    incoming = sum(
        len(item["content"])
        for _, item in verified
        if not _already_stored(
            media_dir / item["name"], len(item["content"])
        )
    )
    if _dir_bytes(media_dir) + incoming > migration_media.MAX_MERCHANT_BYTES:
        raise conflict("media-quota", "Merchant media quota exceeded")
    media_dir.mkdir(parents=True, exist_ok=True)

    uploaded = 0
    for result, item in verified:
        dest = media_dir / item["name"]
        if _already_stored(dest, len(item["content"])):
            uploaded += 1
            continue  # content-addressed dedup — retry is idempotent
        tmp = media_dir / f".{item['name']}.tmp"
        tmp.write_bytes(item["content"])
        # re-verify what landed before promoting (write-verify pattern)
        if hashlib.sha256(tmp.read_bytes()).hexdigest() != item[
                "name"].split(".", 1)[0]:
            tmp.unlink(missing_ok=True)
            result.clear()
            result.update(
                file=item["name"], state="rejected",
                reason="write-verify-failed",
            )
            continue
        tmp.replace(dest)
        uploaded += 1
    return {"uploaded": uploaded, "results": results, "namespace": namespace}


async def _referenced_names(
    merchant_id: str, names: set[str]
) -> set[str]:
    """Names whose ``infinitemarkets/<ns>/<name>`` substring appears in a
    merchant-owned ``product_images.url``, ``merchants.profile_json``, or
    ``merchants.theme`` — D-12 covers relative and absolute stored forms.
    """
    if not names:
        return set()
    needle = (
        f"infinitemarkets/{migration_media._namespace(merchant_id)}/"
    )
    async with db.connect() as conn:
        haystack = set(
            await migration_media._owned_image_urls(conn, merchant_id)
        )
        row = await conn.fetchone(
            f"SELECT profile_json, theme FROM {table('merchants')} "
            "WHERE id = :m",
            {"m": merchant_id},
        )
    if row:
        haystack.add(row["profile_json"] or "")
        haystack.add(row["theme"] or "")
    return {
        n for n in names
        if any(needle + n in text for text in haystack)
    }


async def list_unused(merchant_id: str, user) -> dict:
    """D-02/D-12: local uploads no catalog/profile/theme value references.

    Filenames recorded in the migration sidecar are migration-owned and
    are never listed (protects pending relinks).
    """
    from . import catalog

    await catalog._merchant_owned(merchant_id, user)
    media_dir = migration_media._media_dir(merchant_id)
    names = (
        {
            f.name
            for f in media_dir.iterdir()
            if f.is_file()
            and not f.is_symlink()
            and _NAME_RE.fullmatch(f.name)
        }
        if media_dir.is_dir()
        else set()
    )
    owned = set(migration_media._load_sidecar(merchant_id).values())
    referenced = await _referenced_names(merchant_id, names - owned)
    return {
        "files": [
            {
                "name": n,
                "bytes": (media_dir / n).stat().st_size,
                "sha256": n.split(".", 1)[0],
            }
            for n in sorted(names - owned - referenced)
        ]
    }


async def delete_unused(merchant_id: str, name: str, user) -> dict:
    """Explicit local-only deletion of an unreferenced upload (D-02).

    Referenced or migration-owned files conflict; an absent name is an
    idempotent success. The strict name fullmatch makes traversal
    impossible before any filesystem touch.
    """
    from . import catalog

    await catalog._merchant_owned(merchant_id, user)
    if not _NAME_RE.fullmatch(name):
        raise unprocessable("invalid-content", "invalid media filename")
    media_dir = migration_media._media_dir(merchant_id)
    path = media_dir / name
    if not path.is_file() or path.is_symlink():
        return {"deleted": False}
    if (
        name in migration_media._load_sidecar(merchant_id).values()
        or name in await _referenced_names(merchant_id, {name})
    ):
        raise conflict(
            "media-referenced", "Media file is still referenced"
        )
    try:
        path.unlink()
    except FileNotFoundError:
        return {"deleted": False}
    return {"deleted": True}
