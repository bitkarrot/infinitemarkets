"""Extension-owned ``INFINITEMARKETS_*`` configuration (spec section 12).

The host has no extension-settings hook, so this module parses and strictly
validates its own environment. Validation failure raises before merchant
services activate: ``infinitemarkets_start`` propagates it and the host marks
the extension inactive.

Keyring format::

    INFINITEMARKETS_MASTER_KEYS={"v1":"<base64 32 bytes>","v2":"..."}
    INFINITEMARKETS_ACTIVE_KEY_VERSION=v2
    INFINITEMARKETS_PRIVACY_KEY=<base64 or 64-hex 32 bytes>
    INFINITEMARKETS_PUBLIC_BASE_URL=https://shop.example

Secret bootstrap: when NEITHER ``INFINITEMARKETS_MASTER_KEYS`` nor
``INFINITEMARKETS_PRIVACY_KEY`` is set, the deployment is unmanaged — a
``v1`` master key and a privacy key are generated once and persisted to
``infinitemarkets-keys.json`` in the host data folder (mode 0600, beside
``database.sqlite3`` and the host's own ``.lnbits_auth_key`` — the same
threat boundary, so a DB-only leak cannot decrypt stored fields). If
EITHER variable is set, the fully explicit contract applies to both.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import secrets
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from lnbits.settings import settings as host_settings
from loguru import logger


class SettingsError(RuntimeError):
    """A required INFINITEMARKETS_* setting is missing or malformed."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SettingsError(f"{name} is required")
    return value


def _decode_32(name: str, value: str) -> bytes:
    """Strictly decode a 32-byte secret (base64 or 64-hex)."""
    raw: bytes | None = None
    try:
        candidate = base64.b64decode(value, validate=True)
        if len(candidate) == 32:
            raw = candidate
    except (binascii.Error, ValueError):
        pass
    if raw is None and len(value) == 64:
        try:
            candidate = bytes.fromhex(value)
            if len(candidate) == 32:
                raw = candidate
        except ValueError:
            pass
    if raw is None:
        raise SettingsError(f"{name} must decode to exactly 32 bytes")
    return raw


def _parse_keyring(raw: str) -> dict[str, bytes]:
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SettingsError(
            "INFINITEMARKETS_MASTER_KEYS must be a JSON object of "
            '{"version": "<base64 32-byte key>"}'
        ) from exc
    if not isinstance(mapping, dict) or not mapping:
        raise SettingsError("INFINITEMARKETS_MASTER_KEYS must be a non-empty map")
    keyring: dict[str, bytes] = {}
    for version, encoded in mapping.items():
        if not isinstance(version, str) or not version:
            raise SettingsError("INFINITEMARKETS_MASTER_KEYS versions must be non-empty strings")
        if not isinstance(encoded, str):
            raise SettingsError(
                f"INFINITEMARKETS_MASTER_KEYS[{version!r}] must be a base64 string"
            )
        try:
            key = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SettingsError(
                f"INFINITEMARKETS_MASTER_KEYS[{version!r}] is not valid base64"
            ) from exc
        if len(key) != 32:
            raise SettingsError(
                f"INFINITEMARKETS_MASTER_KEYS[{version!r}] must decode to 32 bytes"
            )
        keyring[version] = key
    # Duplicate key material under two versions breaks rotation semantics.
    if len(set(keyring.values())) != len(keyring):
        raise SettingsError("INFINITEMARKETS_MASTER_KEYS contains duplicate key material")
    return keyring


def _parse_base_url(raw: str) -> str:
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SettingsError(
            "INFINITEMARKETS_PUBLIC_BASE_URL must be an https:// origin "
            "(never derived from Host/Forwarded headers)"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SettingsError(
            "INFINITEMARKETS_PUBLIC_BASE_URL must not carry userinfo, query, or fragment"
        )
    if parsed.path not in ("", "/"):
        raise SettingsError(
            "INFINITEMARKETS_PUBLIC_BASE_URL must be an origin (no path)"
        )
    return f"https://{parsed.netloc}"


GENERATED_KEYS_FILE = "infinitemarkets-keys.json"


def generated_keys_path() -> Path:
    """Keyfile lives beside the host database — same threat boundary."""
    return Path(host_settings.lnbits_data_folder, GENERATED_KEYS_FILE)


def _load_keyfile(path: Path) -> tuple[dict[str, bytes], bytes]:
    try:
        data = json.loads(path.read_text())
        return (
            _parse_keyring(json.dumps(data["master_keys"])),
            _decode_32(GENERATED_KEYS_FILE, data["privacy_key"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SettingsError(
            f"{path} exists but is malformed: {exc}. Fix the file or "
            "set INFINITEMARKETS_MASTER_KEYS + INFINITEMARKETS_PRIVACY_KEY."
        ) from exc


def _write_json_synced(fh, payload: dict) -> None:
    json.dump(payload, fh)
    fh.flush()
    os.fsync(fh.fileno())


def _publish_keyfile(path: Path, payload: dict) -> bool:
    """Exclusively create ``path`` holding ``payload`` (mode 0600).

    Returns False when another process already published it. An existing
    keyfile is never replaced: the fully written temp file is hard-linked
    into place, which fails atomically if ``path`` exists, so readers
    never observe a partial file. Filesystems without hard links fall
    back to ``O_EXCL`` creation of ``path`` itself.
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".imkeys-")  # 0600
    try:
        with os.fdopen(fd, "w") as fh:
            _write_json_synced(fh, payload)
        try:
            os.link(tmp, path)
            return True
        except FileExistsError:
            return False
        except OSError:
            pass  # no hard-link support on this filesystem
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w") as fh:
            _write_json_synced(fh, payload)
        return True
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _load_published_keyfile(path: Path) -> tuple[dict[str, bytes], bytes]:
    """Read the keyfile a concurrent winner just published. On the
    ``O_EXCL`` fallback the winner may still be writing, so a malformed
    read is retried briefly before it is reported."""
    deadline = time.monotonic() + 5
    while True:
        try:
            return _load_keyfile(path)
        except SettingsError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.05)


def _generated_keys_ack_path() -> Path:
    return generated_keys_path().with_name(GENERATED_KEYS_FILE + ".ack")


def _keyfile_fingerprint() -> str:
    """sha256 over the keyfile's key material (raises if absent/malformed)."""
    data = json.loads(generated_keys_path().read_text())
    material = json.dumps(
        {"master_keys": data["master_keys"],
         "privacy_key": data["privacy_key"]},
        sort_keys=True,
    )
    return hashlib.sha256(material.encode()).hexdigest()


def generated_keys_acknowledged() -> bool:
    """True once the operator dismisses the auto-generated-keys warning.

    The dismissal is a sidecar holding the fingerprint of the key material
    it acknowledged — the keyfile itself is never rewritten, and a
    regenerated keyfile (fresh material) re-surfaces the warning."""
    try:
        ack = _generated_keys_ack_path().read_text().strip()
        return bool(ack) and ack == _keyfile_fingerprint()
    except Exception:  # noqa: BLE001 — absent/malformed file warns
        return False


def acknowledge_generated_keys() -> None:
    """Record the dismissal in the sidecar (atomic replace, mode 0600)."""
    fingerprint = _keyfile_fingerprint()
    ack_path = _generated_keys_ack_path()
    fd, tmp = tempfile.mkstemp(dir=ack_path.parent, prefix=".imkeys-")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(fingerprint)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, ack_path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _generated_keys() -> tuple[dict[str, bytes], bytes]:
    """Load the persisted generated keyring, or publish a fresh one.

    Multi-process first boot: two workers must never use different
    keyrings — the loser would orphan ciphertexts written under its
    in-memory keys. Workers race to exclusively create the keyfile;
    exactly one wins and every other worker discards its candidate and
    returns the winner's keys. No lockfile exists, so there is nothing to
    go stale, reclaim, or tamper with.
    """
    path = generated_keys_path()
    if path.is_file():
        return _load_keyfile(path)

    keyring_raw = {"v1": base64.b64encode(secrets.token_bytes(32)).decode()}
    privacy_raw = base64.b64encode(secrets.token_bytes(32)).decode()
    payload = {
        "master_keys": keyring_raw,
        "privacy_key": privacy_raw,
        "warning": (
            "Auto-generated by infinitemarkets. Set "
            "INFINITEMARKETS_MASTER_KEYS and "
            "INFINITEMARKETS_PRIVACY_KEY in the host environment to "
            "manage keys explicitly."
        ),
    }
    try:
        published = _publish_keyfile(path, payload)
    except OSError as exc:
        raise SettingsError(
            "no INFINITEMARKETS_* keys configured and generated keys "
            f"could not be persisted to {path}: {exc}"
        ) from exc
    if not published:
        return _load_published_keyfile(path)
    logger.warning(
        "infinitemarkets: no master/privacy keys configured — "
        f"generated and persisted to {path} (mode 0600). To manage "
        "keys explicitly, copy THIS file's master_keys/privacy_key "
        "values into INFINITEMARKETS_MASTER_KEYS + "
        "INFINITEMARKETS_PRIVACY_KEY — fresh material orphans every "
        "encrypted record."
    )
    return (
        _parse_keyring(json.dumps(keyring_raw)),
        base64.b64decode(privacy_raw),
    )


def generated_keyfile_diverged(settings: "ExtSettings") -> str | None:
    """Generated keyfile exists but env-managed keys don't cover its
    material — everything encrypted under the generated pair is
    unreadable. Returns a warning for admin surfaces, else None."""
    path = generated_keys_path()
    if settings.keys_autogenerated or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
        gen_items = {
            label: base64.b64decode(b64)
            for label, b64 in data.get("master_keys", {}).items()
        }
        gen_privacy = _decode_32(
            GENERATED_KEYS_FILE, data.get("privacy_key", "")
        )
    except Exception:
        return None
    # Rows reference keys by version label — coverage requires the label
    # AND material, not just the bytes somewhere in the ring.
    covered = gen_items and all(
        settings.master_keys.get(label) == key
        for label, key in gen_items.items()
    ) and gen_privacy == settings.privacy_key
    if covered:
        return None
    return (
        f"{path} holds the auto-generated keys this data was encrypted "
        "under, but the configured INFINITEMARKETS_* secrets no longer "
        "include them — affected records are undecryptable. Add the "
        "file's master_keys entries as inactive versions and copy its "
        "privacy_key, or restore generated mode."
    )


def _origins_env(name: str) -> tuple[str, ...]:
    """Comma-separated list of bare ``scheme://host[:port]`` origins.

    Trust is origin-wide, so an entry carrying a path, query, fragment or
    userinfo is rejected rather than silently widened to its origin."""
    raw = os.environ.get(name, "").strip()
    origins = []
    for piece in (p.strip() for p in raw.split(",") if p.strip()):
        p = urlparse(piece)
        if p.scheme not in {"http", "https"} or not p.hostname:
            raise SettingsError(
                f"{name} entry {piece!r} must be an http(s) origin"
            )
        if (p.path not in ("", "/") or p.params or p.query or p.fragment
                or p.username is not None or p.password is not None):
            raise SettingsError(
                f"{name} entry {piece!r} must be a bare origin "
                "(scheme://host[:port]) — origin trust cannot be path-scoped"
            )
        origins.append(f"{p.scheme}://{p.netloc}")
    return tuple(origins)


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer") from exc
    if value < minimum:
        raise SettingsError(f"{name} must be >= {minimum}")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise SettingsError(f"{name} must be a boolean")


@dataclass(frozen=True)
class ExtSettings:
    master_keys: dict[str, bytes]
    active_key_version: str
    privacy_key: bytes
    public_base_url: str
    reservation_ttl: int = 900
    outbox_max_attempts: int = 20
    outbox_batch: int = 32
    peer_relay_ttl: int = 86400
    inbox_max_event_bytes: int = 32768
    inbox_author_cap: int = 60  # per-author wraps/minute pre-validation (D-24)
    checkout_rate_limit: int = 10  # per minute per IP (section 15)
    checkout_rate_limit_hourly: int = 100  # per hour per IP (section 15)
    email_enabled: bool = True
    email_max_attempts: int = 5
    nsec_signin: bool = False
    admin_origins: tuple[str, ...] = ()
    spec_revision: str = "5dc79c5"
    # True when the keyring/privacy key were auto-generated because no
    # secret env vars were set — the admin UI warns on this.
    keys_autogenerated: bool = False
    extra: dict = field(default_factory=dict)


def ext_settings() -> ExtSettings:
    """Parse + strictly validate the extension environment (section 12)."""
    master_env = os.environ.get("INFINITEMARKETS_MASTER_KEYS", "").strip()
    privacy_env = os.environ.get("INFINITEMARKETS_PRIVACY_KEY", "").strip()
    keys_generated = not master_env and not privacy_env
    if keys_generated:
        keyring, privacy = _generated_keys()
    else:
        keyring = _parse_keyring(_require("INFINITEMARKETS_MASTER_KEYS"))
        privacy = _decode_32(
            "INFINITEMARKETS_PRIVACY_KEY",
            _require("INFINITEMARKETS_PRIVACY_KEY"),
        )
    active = os.environ.get("INFINITEMARKETS_ACTIVE_KEY_VERSION", "").strip()
    if not active:
        if len(keyring) == 1:
            active = next(iter(keyring))
        else:
            raise SettingsError(
                "INFINITEMARKETS_ACTIVE_KEY_VERSION is required when "
                "INFINITEMARKETS_MASTER_KEYS holds more than one version"
            )
    if active not in keyring:
        raise SettingsError(
            "INFINITEMARKETS_ACTIVE_KEY_VERSION must name a key present in "
            "INFINITEMARKETS_MASTER_KEYS"
        )
    if privacy in keyring.values():
        raise SettingsError(
            "INFINITEMARKETS_PRIVACY_KEY must be distinct from master keys"
        )
    # The host's own declared origin is operator configuration — not a
    # request-derived header — so it is a safe default. It must still
    # satisfy the canonical-https rules (http://127.0.0.1 hosts still
    # need the explicit variable).
    base_url = _parse_base_url(
        os.environ.get("INFINITEMARKETS_PUBLIC_BASE_URL", "").strip()
        or host_settings.lnbits_baseurl.strip()
    )
    return ExtSettings(
        master_keys=keyring,
        active_key_version=active,
        privacy_key=privacy,
        public_base_url=base_url,
        reservation_ttl=_int_env("INFINITEMARKETS_RESERVATION_TTL", 900),
        outbox_max_attempts=_int_env("INFINITEMARKETS_OUTBOX_MAX_ATTEMPTS", 20),
        outbox_batch=_int_env("INFINITEMARKETS_OUTBOX_BATCH", 32),
        peer_relay_ttl=_int_env("INFINITEMARKETS_PEER_RELAY_TTL", 86400),
        inbox_max_event_bytes=_int_env("INFINITEMARKETS_INBOX_MAX_EVENT_BYTES", 32768),
        inbox_author_cap=_int_env("INFINITEMARKETS_INBOX_AUTHOR_CAP", 60),
        checkout_rate_limit=_int_env("INFINITEMARKETS_CHECKOUT_RATE_LIMIT", 10),
        checkout_rate_limit_hourly=_int_env(
            "INFINITEMARKETS_CHECKOUT_RATE_LIMIT_HOURLY", 100
        ),
        email_enabled=_bool_env("INFINITEMARKETS_EMAIL_ENABLED", True),
        email_max_attempts=_int_env("INFINITEMARKETS_EMAIL_MAX_ATTEMPTS", 5),
        # Dev/e2e affordance: POST /nostr/verify accepts a raw nsec and
        # mints the same session a signed challenge would. OFF by
        # default — a public nsec field trains users to hand keys to
        # storefronts, so only enable on test/self-hosted deploys.
        nsec_signin=_bool_env("INFINITEMARKETS_NSEC_SIGNIN", False),
        admin_origins=_origins_env("INFINITEMARKETS_ADMIN_ORIGINS"),
        spec_revision=os.environ.get(
            "INFINITEMARKETS_SPEC_REVISION", "5dc79c5"
        ).strip()
        or "5dc79c5",
        keys_autogenerated=keys_generated,
    )
