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
from ..security import ProblemError, conflict, is_public_ip, unprocessable
from ..settings import ext_settings
from . import migration_media

_NAME_RE = re.compile(r"[0-9a-f]{64}\.(png|jpg|webp)")

#: Multipart ``usage`` field vocabulary — the field the editor uses to say
#: where an upload is bound.
MEDIA_USAGES = ("catalog", "profile", "appearance")

#: Multipart ``backend`` field vocabulary — which storage receives the
#: bytes. Locked owner decision: exactly one backend per upload; ``local``
#: is the default (and the automatic selection when no Blossom server is
#: configured); ``blossom`` targets the FIRST configured server only —
#: never a dual-write, never a silent failover (06-03).
MEDIA_BACKENDS = ("local", "blossom")


def local_path(merchant_id: str, name: str) -> str:
    """Same-origin path the host ``/library`` mount serves (D-04)."""
    return (
        migration_media.MEDIA_URL_PREFIX
        + f"{migration_media._namespace(merchant_id)}/{name}"
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
            backend="local",
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
    return {
        "uploaded": uploaded,
        "results": results,
        "namespace": namespace,
        "backend": "local",
    }


async def store_upload(
    merchant_id: str, user, files: list[tuple[str, bytes]], *,
    usage: str, backend: str,
) -> dict:
    """Single dispatch point behind ``POST /media/upload`` (06-03).

    ``local`` -> ``store_local``, including the D-05/D-08 profile-origin
    gate (it lives here rather than the route so a profile-bound upload
    to a Blossom server is not blocked by a private ``public_base_url`` —
    the remote descriptor URL is exactly the external-https alternative
    the gate's message recommends). ``blossom`` -> the FIRST configured
    server only.
    """
    if backend == "blossom":
        return await _store_blossom(merchant_id, user, files)
    if usage == "profile" and not origin_is_public(
        ext_settings().public_base_url
    ):
        raise unprocessable(
            "media-origin",
            "Profile image origin is not publicly reachable",
            "Images bound for your Nostr profile must resolve to a "
            "public https URL that relays can fetch. Set "
            "INFINITEMARKETS_PUBLIC_BASE_URL to your shop's public "
            "https origin, or use an external https/Blossom image "
            "instead.",
        )
    return await store_local(merchant_id, user, files)


async def _store_blossom(merchant_id: str, user, files) -> dict:
    """Remote branch of ``store_upload``: BUD-02 PUT to the FIRST
    configured Blossom server (06-02's preserved ordering is the whole
    contract — the loop below iterates FILES, never the server list).

    A remote failure raises through ``problem_boundary`` as a typed
    problem naming the server; NOTHING is written to the local namespace
    and no second server is contacted — the merchant retries to local
    explicitly (locked no-failover decision). Per-file sniff/size gates
    (MEDIA-05) still apply; the 400 MB quota does not (D-06 — remote
    bytes are never tracked)."""
    from .. import keystore as keystore_mod
    from . import blossom, catalog, relay

    await catalog._merchant_owned(merchant_id, user)
    if not files or len(files) > migration_media.MAX_FILES_PER_REQUEST:
        raise unprocessable(
            "invalid-content",
            f"upload 1 to {migration_media.MAX_FILES_PER_REQUEST} "
            "image files per request",
        )
    servers = await relay.get_blossom_servers(merchant_id)
    if not servers:
        raise unprocessable(
            "media-backend",
            "No Blossom media server configured",
            "Uploading with backend=blossom requires a Blossom media "
            "server. Configure one under Settings -> Merchant, or upload "
            "with backend=local to store the image in LNbits instead.",
        )
    server = servers[0]
    keystore = keystore_mod.key_store()
    results: list[dict] = []
    uploaded = 0
    for name, content in files:
        result = {"file": name}
        results.append(result)
        if not content or len(content) > migration_media.MAX_FILE_BYTES:
            result.update(state="rejected", reason="size")
            continue
        ext = migration_media._sniff(content)
        if not ext:
            result.update(state="rejected", reason="not-an-image")
            continue
        try:
            outcome = await blossom.upload_blob(
                merchant_id, keystore, server, content, ext
            )
        except ProblemError as exc:
            raise ProblemError(
                exc.status,
                exc.code,
                exc.title,
                f"Blossom server {server}: {exc.detail or exc.title} "
                "Nothing was stored locally — retry the upload, or "
                "upload with backend=local to use LNbits storage.",
            ) from exc
        result.update(
            state="stored",
            backend="blossom",
            server=outcome["server"],
            sha256=outcome["sha256"],
            bytes=outcome["size"],
            url=outcome["url"],
        )
        uploaded += 1
    return {
        "uploaded": uploaded,
        "results": results,
        "backend": "blossom",
        "server": server,
    }


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
    are never listed (protects pending relinks). Each entry carries
    ``mtime`` (epoch seconds) so the Settings -> Media block can render a
    date column; the top-level ``used_bytes``/``quota_bytes`` pair powers
    its quota bar — ``used_bytes`` is the full namespace total (D-01:
    referenced and unreferenced bytes both count).
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
    files = []
    for n in sorted(names - owned - referenced):
        st = (media_dir / n).stat()
        files.append(
            {
                "name": n,
                "bytes": st.st_size,
                "sha256": n.split(".", 1)[0],
                "mtime": st.st_mtime,
            }
        )
    return {
        "files": files,
        "used_bytes": _dir_bytes(media_dir),
        "quota_bytes": migration_media.MAX_MERCHANT_BYTES,
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
