"""Pin recording and provenance verification for the evidence bundle.

Everything recorded here flows into the evidence manifest pins block via
``harness.evidence``; the raw ``LNBITS_DATABASE_URL`` is never recorded (it
may carry credentials).

Verified facts this module encodes (2026-09-20, against the pinned host
checkout at 4fa70f3 and PyPI):

- nostr-sdk 0.44.8 is WHEELS-ONLY on PyPI (13 wheels, no sdist), and the
  host ``uv.lock`` correspondingly records wheels only. There is no sdist
  artifact to fetch; release-source provenance is pinned from the source
  repository instead (below).
- The source repository (``rust-nostr/nostr-sdk-ffi``, per PyPI metadata)
  has no git tag for 0.44.8 — its tags jump v0.44.2 -> v0.45.0. The
  0.44.x releases are cut from the ``v0.44`` maintenance branch; the
  0.44.8 release commit is pinned below as the release-source revision,
  committed 11 minutes before the PyPI wheel upload.
- Native Cargo dependency revisions are parsed from the ``Cargo.lock`` at
  that revision (cached under ``.cache/nostr-sdk-src/``).
"""

from __future__ import annotations

import hashlib
import importlib.metadata as importlib_metadata
import platform
import sys
import tomllib
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The pinned host revision (spec section 2). tools/checkout_host.py owns the
# checkout; this module only reads it.
LNBITS_COMMIT = "4fa70f338d274e14fc82746a83fba5c2c658211f"
LNBITS_TAG = "v1.7.1"
NOSTR_SDK_VERSION = "0.44.8"

NATIVE_LIBRARY_SUFFIXES = (".so", ".dylib", ".pyd")

# Release-source provenance for nostr-sdk 0.44.8 (see module docstring).
NOSTR_SDK_SOURCE_REPO = "https://github.com/rust-nostr/nostr-sdk-ffi"
NOSTR_SDK_SOURCE_REVISION = "a600c2a7186559b371030fe5fc5585c37b3a0931"
NOSTR_SDK_SOURCE_BRANCH = "v0.44"
NOSTR_SDK_SOURCE_NOTE = (
    "no git tag exists for 0.44.8 (repo tags jump v0.44.2 -> v0.45.0); "
    "revision is the 'Release v0.44.8' commit on the v0.44 maintenance "
    "branch, committed 2026-08-02T11:29:43Z, 11 minutes before the PyPI "
    "wheel upload (2026-08-02T11:40:50Z)"
)

# Native Cargo dependency revisions recorded from the Cargo.lock at
# NOSTR_SDK_SOURCE_REVISION. Keys are Cargo package names; these are the
# recorded pins PINS.md carries and the P0-01 suite verifies against the
# cached release-source Cargo.lock.
NATIVE_CARGO_PINS: dict[str, str] = {
    "secp256k1": "0.29.1",
    "secp256k1-sys": "0.10.1",
    "chacha20poly1305": "0.10.1",
    "chacha20": "0.9.1",
    "aes": "0.8.4",
    "nostr": "0.44.7",
    "nostr-relay-pool": "0.44.3",
    "nostr-sdk": "0.44.1",
    "uniffi": "0.29.4",
}

CARGO_LOCK_CACHE = REPO_ROOT / ".cache" / "nostr-sdk-src" / "Cargo.lock"
CARGO_LOCK_URL = (
    f"https://raw.githubusercontent.com/rust-nostr/nostr-sdk-ffi/"
    f"{NOSTR_SDK_SOURCE_REVISION}/Cargo.lock"
)

HARNESS_LOCK = REPO_ROOT / "uv.lock"

# Pins recorded during the run; ``harness.evidence`` snapshots this at
# session finish. Tests record values here via ``record``/``record_*``.
_RECORD: dict[str, object] = {}


# --- recording ---------------------------------------------------------------


def record(key: str, value: object) -> None:
    """Record a pin value into the evidence manifest pins block."""
    _RECORD[key] = value


def snapshot() -> dict[str, object]:
    """Return the pins recorded so far (defaults merged in)."""
    ensure_defaults()
    return dict(_RECORD)


def nostr_sdk_version() -> str:
    """Installed nostr-sdk version per importlib.metadata."""
    return importlib_metadata.version("nostr-sdk")


def lnbits_checkout_head() -> str | None:
    """HEAD commit of the harness-owned LNbits checkout, or None if absent."""
    from tools.checkout_host import host_checkout_dir, read_head

    return read_head(host_checkout_dir())


# --- native library (tested binary) ----------------------------------------


def installed_native_libraries() -> list[Path]:
    """Compiled library files inside the installed nostr-sdk package."""
    dist = importlib_metadata.distribution("nostr-sdk")
    libs = [
        f.locate()
        for f in (dist.files or [])
        if f.suffix in NATIVE_LIBRARY_SUFFIXES
    ]
    return sorted(p for p in libs if p.is_file())


def native_library_identity() -> dict[str, object]:
    """Identity (filename, size, sha256) of the installed native SDK library.

    This is the "tested binary" required by P0-02: the artifact whose FFI the
    probes actually exercised.
    """
    libs = installed_native_libraries()
    if not libs:
        raise RuntimeError(
            "no compiled nostr-sdk library found in the installed package"
        )
    lib = libs[0]
    data = lib.read_bytes()
    return {
        "filename": lib.name,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def record_tested_binary() -> dict[str, object]:
    """Record the tested native SDK binary identity into the pins block."""
    identity = native_library_identity()
    record("nostr_sdk_native_library", identity)
    return identity


# --- uv.lock parsing (host parity + full resolution) ------------------------


def _lock_packages(path: Path) -> list[dict]:
    with path.open("rb") as fh:
        lock = tomllib.load(fh)
    return lock.get("package", [])


def _package_wheels(package: dict) -> list[dict]:
    wheels = []
    for wheel in package.get("wheels", []):
        url = wheel.get("url", "")
        wheels.append(
            {
                "filename": url.rsplit("/", 1)[-1],
                "url": url,
                "sha256": (wheel.get("hash") or "").removeprefix("sha256:"),
            }
        )
    return wheels


def _package_sdist(package: dict) -> dict | None:
    sdist = package.get("sdist")
    if not sdist:
        return None
    url = sdist.get("url", "")
    return {
        "filename": url.rsplit("/", 1)[-1],
        "url": url,
        "sha256": (sdist.get("hash") or "").removeprefix("sha256:"),
    }


def _nostr_sdk_package(path: Path) -> dict | None:
    for package in _lock_packages(path):
        if package.get("name") == "nostr-sdk":
            return package
    return None


def host_checkout_dir() -> Path:
    """The harness-owned pinned LNbits checkout directory."""
    from tools.checkout_host import host_checkout_dir as _dir

    return _dir()


def host_lock_path() -> Path:
    return host_checkout_dir() / "uv.lock"


def host_nostr_sdk_wheels() -> list[dict]:
    """Wheel identities recorded for nostr-sdk in the pinned HOST lock."""
    package = _nostr_sdk_package(host_lock_path())
    if package is None:
        raise RuntimeError(f"nostr-sdk missing from host lock {host_lock_path()}")
    return _package_wheels(package)


def host_nostr_sdk_sdist() -> dict | None:
    """Sdist identity for nostr-sdk in the host lock, if present."""
    package = _nostr_sdk_package(host_lock_path())
    if package is None:
        return None
    return _package_sdist(package)


def harness_lock_path() -> Path:
    return HARNESS_LOCK


def harness_lock_sha256() -> str:
    data = harness_lock_path().read_bytes()
    return hashlib.sha256(data).hexdigest()


def harness_nostr_sdk_wheels() -> list[dict]:
    """Wheel identities recorded for nostr-sdk in the HARNESS lock."""
    package = _nostr_sdk_package(harness_lock_path())
    if package is None:
        raise RuntimeError("nostr-sdk missing from harness uv.lock")
    return _package_wheels(package)


def harness_lock_resolution() -> list[dict]:
    """The harness's full lock resolution: every package with name, version,
    and per-artifact hashes — so divergence between the harness's transitives
    and the host checkout's resolution is visible at review instead of
    silently accepted."""
    resolution = []
    for package in _lock_packages(harness_lock_path()):
        entry = {
            "name": package.get("name"),
            "version": package.get("version"),
            "source": package.get("source", {}).get("registry")
            or package.get("source", {}).get("path")
            or package.get("source", {}).get("git"),
            "artifacts": [
                {"filename": w["filename"], "sha256": w["sha256"]}
                for w in _package_wheels(package)
            ],
        }
        sdist = _package_sdist(package)
        if sdist:
            entry["artifacts"].append(
                {"filename": sdist["filename"], "sha256": sdist["sha256"]}
            )
        resolution.append(entry)
    return sorted(resolution, key=lambda e: e["name"])


# --- platform tag mapping ----------------------------------------------------


def installed_wheel_tag() -> str:
    """The full wheel tag of the INSTALLED nostr-sdk wheel (e.g.
    ``cp39-abi3-macosx_11_0_arm64``), read from the installed dist-info."""
    dist = importlib_metadata.distribution("nostr-sdk")
    wheel_text = dist.read_text("WHEEL")
    if not wheel_text:
        raise RuntimeError("no WHEEL metadata found in installed nostr-sdk dist")
    for line in wheel_text.splitlines():
        if line.startswith("Tag:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("no Tag entry in installed nostr-sdk WHEEL metadata")


def installed_platform_tag() -> str:
    """Platform tag of the installed wheel (last dash-separated component)."""
    return installed_wheel_tag().rsplit("-", 1)[-1]


def machine_platform_tags() -> list[str]:
    """Machine-derived platform-tag fragments for the executing machine.

    The installed wheel's platform tag must match these (manylinux/musllinux
    x86_64/aarch64 on Linux, macosx arm64/x86_64 on macOS).
    """
    machine = platform.machine().lower()
    arch = {"arm64": "arm64", "aarch64": "aarch64", "x86_64": "x86_64"}.get(
        machine, machine
    )
    if sys.platform == "darwin":
        if arch in ("arm64", "aarch64"):
            return ["macosx", "arm64"]
        return ["macosx", "x86_64"]
    if sys.platform.startswith("linux"):
        # The libc tag is an either/or: glibc machines use manylinux wheels,
        # musl machines use musllinux — never both.
        libc, _ = platform.libc_ver()
        libc_tag = "musllinux" if libc == "musl" else "manylinux"
        return [libc_tag, arch]
    raise RuntimeError(f"unsupported platform for tag mapping: {sys.platform}")


def wheel_entry_for_tag(entries: list[dict], platform_tag: str) -> dict | None:
    """The lock wheel entry whose filename carries the given platform tag."""
    for entry in entries:
        if entry["filename"].endswith(f"-{platform_tag}.whl"):
            return entry
    return None


def record_nostr_sdk_wheel_parity() -> dict:
    """Record harness-vs-host lock wheel parity for the executing platform.

    Raises AssertionError on parity mismatch (no silent downgrade, D-01).
    """
    platform_tag = installed_platform_tag()
    host_entry = wheel_entry_for_tag(host_nostr_sdk_wheels(), platform_tag)
    harness_entry = wheel_entry_for_tag(harness_nostr_sdk_wheels(), platform_tag)
    if not host_entry:
        raise AssertionError(f"host lock has no nostr-sdk wheel for {platform_tag}")
    if not harness_entry:
        raise AssertionError(
            f"harness lock has no nostr-sdk wheel for {platform_tag}"
        )
    if harness_entry["sha256"] != host_entry["sha256"]:
        raise AssertionError(
            f"harness lock wheel {harness_entry['filename']} sha256 "
            f"{harness_entry['sha256']} != host lock sha256 {host_entry['sha256']}"
        )
    parity = {
        "platform_tag": platform_tag,
        "filename": harness_entry["filename"],
        "sha256": harness_entry["sha256"],
        "host_lock_sha256": host_entry["sha256"],
    }
    record("nostr_sdk_wheel", parity)
    return parity


# --- release-source provenance ------------------------------------------------


def ensure_release_source_cargo_lock() -> Path:
    """The Cargo.lock at the pinned release-source revision (cached).

    Cached under .cache/nostr-sdk-src/; downloaded once from the pinned
    revision when missing. There is no sdist for nostr-sdk 0.44.8 (wheels-only
    release), so the release-source Cargo.lock is the native-provenance
    artifact (see module docstring).
    """
    if CARGO_LOCK_CACHE.exists():
        return CARGO_LOCK_CACHE
    CARGO_LOCK_CACHE.parent.mkdir(parents=True, exist_ok=True)
    data = urllib.request.urlopen(CARGO_LOCK_URL, timeout=30).read()
    CARGO_LOCK_CACHE.write_bytes(data)
    return CARGO_LOCK_CACHE


def cargo_lock_pins() -> dict[str, str]:
    """Native Cargo dependency versions from the release-source Cargo.lock."""
    path = ensure_release_source_cargo_lock()
    with path.open("rb") as fh:
        lock = tomllib.load(fh)
    pins: dict[str, str] = {}
    for package in lock.get("package", []):
        name = package.get("name")
        if name in NATIVE_CARGO_PINS:
            pins[name] = package["version"]
    return pins


def record_lock_evidence() -> None:
    """Record lock identities + full resolution into the evidence pins block."""
    record("harness_lock_path", str(HARNESS_LOCK.relative_to(REPO_ROOT)))
    record("harness_lock_sha256", harness_lock_sha256())
    record("harness_lock_packages", len(harness_lock_resolution()))
    # Full resolution: every direct and transitive package with name,
    # version, and per-artifact hashes (plan 01-01 Task 2) so host-transitive
    # divergence is visible in the durable bundle.
    record("harness_lock_resolution", harness_lock_resolution())
    record(
        "nostr_sdk_source",
        {
            "repository": NOSTR_SDK_SOURCE_REPO,
            "revision": NOSTR_SDK_SOURCE_REVISION,
            "branch": NOSTR_SDK_SOURCE_BRANCH,
            "note": NOSTR_SDK_SOURCE_NOTE,
            "sdist_published": False,
        },
    )
    record("nostr_sdk_native_cargo_pins", cargo_lock_pins())


def ensure_defaults() -> None:
    """Populate default pins (nostr-sdk version, LNbits checkout revision)."""
    from harness.registry import NIP32_NAMESPACE

    _RECORD.setdefault("nostr_sdk", nostr_sdk_version())
    _RECORD.setdefault("lnbits_commit", lnbits_checkout_head())
    _RECORD.setdefault("lnbits_tag", LNBITS_TAG)
    _RECORD.setdefault("nip32_namespace", NIP32_NAMESPACE)
