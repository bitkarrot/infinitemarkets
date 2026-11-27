"""P0-01: pin and provenance verification (QUAL-01).

Asserts the installed SDK identity, the Python 3.12-only claim (D-02), the
pinned host checkout revision (D-01), harness-vs-host lock wheel-hash parity
for the executing platform (no silent downgrade), the tested-binary native
library hash, release-source and native Cargo provenance, the initial
PINS.md pin freeze (platform matrix, advisory profile, D-15 contingency),
and that the evidence manifest pins block matches the recorded values.
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import sys
import tomllib
from pathlib import Path

import pytest

from harness import pins
from tools.checkout_host import LNBITS_COMMIT, host_checkout_dir, read_head

pytestmark = pytest.mark.fast

REPO_ROOT = Path(__file__).resolve().parents[2]
PINS_MD = REPO_ROOT / "PINS.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"

EXPECTED_NOSTR_SDK = "0.44.8"


def test_installed_nostr_sdk_is_exactly_pinned():
    assert importlib_metadata.version("nostr-sdk") == EXPECTED_NOSTR_SDK


def test_requires_python_is_3_12_only():
    with PYPROJECT.open("rb") as fh:
        pyproject = tomllib.load(fh)
    assert pyproject["project"]["requires-python"] == ">=3.12,<3.13"


def test_running_interpreter_is_3_12():
    assert sys.version_info[:2] == (3, 12), (
        "the qualification profile claims Python 3.12 only (D-02)"
    )


def test_host_checkout_head_is_pinned_commit():
    head = read_head(host_checkout_dir())
    assert head == LNBITS_COMMIT, (
        f"host checkout must be exactly {LNBITS_COMMIT}, found {head} "
        "(no silent downgrade, D-01)"
    )


def test_installed_wheel_matches_machine_platform():
    """The installed wheel's platform tag matches the executing machine."""
    platform_tag = pins.installed_platform_tag()
    expected = pins.machine_platform_tags()
    for fragment in expected:
        assert fragment in platform_tag, (
            f"installed wheel platform tag {platform_tag!r} does not match "
            f"the executing machine (expected fragments {expected})"
        )


def test_harness_lock_wheel_parity_with_host_lock():
    """Wheel sha256 parity between harness and HOST lock for this platform.

    Parity failure blocks: the harness must resolve exactly the artifact the
    pinned host resolved (no silent downgrade, D-01).
    """
    parity = pins.record_nostr_sdk_wheel_parity()
    assert parity["sha256"] == parity["host_lock_sha256"]
    assert parity["platform_tag"] == pins.installed_platform_tag()


def test_host_lock_and_pypi_are_wheels_only():
    """nostr-sdk 0.44.8 has no sdist: host lock and PINS.md record that."""
    assert pins.host_nostr_sdk_sdist() is None, (
        "host lock unexpectedly records an sdist for nostr-sdk; "
        "PINS.md provenance section must be updated"
    )


def test_release_source_and_native_cargo_provenance():
    """Release-source revision + native Cargo pins verified and recorded."""
    cargo_pins = pins.cargo_lock_pins()
    assert cargo_pins == pins.NATIVE_CARGO_PINS, (
        f"release-source Cargo.lock native pins diverge from the recorded "
        f"pins: {cargo_pins} != {pins.NATIVE_CARGO_PINS}"
    )
    # At minimum the secp256k1 and chacha20poly1305-family crates are pinned.
    for required in ("secp256k1", "secp256k1-sys", "chacha20poly1305", "chacha20"):
        assert required in cargo_pins
    pins.record_lock_evidence()


def test_native_library_hash_recorded_into_evidence_pins():
    """The tested binary identity is recorded (P0-01 e / P0-02)."""
    identity = pins.record_tested_binary()
    assert len(identity["sha256"]) == 64
    assert identity["size_bytes"] > 0
    assert pins.snapshot()["nostr_sdk_native_library"] == identity


def test_evidence_pins_block_matches_recorded_values():
    """The evidence pins block carries the verified identities.

    Self-sufficient: invokes the recorders directly so this check does not
    depend on test ordering.
    """
    pins.record_nostr_sdk_wheel_parity()
    pins.record_lock_evidence()
    pins.record_tested_binary()
    snapshot = pins.snapshot()
    assert snapshot["nostr_sdk"] == EXPECTED_NOSTR_SDK
    assert snapshot["lnbits_commit"] == LNBITS_COMMIT
    assert snapshot["lnbits_tag"] == pins.LNBITS_TAG
    assert snapshot["nostr_sdk_wheel"]["sha256"] == snapshot["nostr_sdk_wheel"][
        "host_lock_sha256"
    ]
    assert snapshot["nostr_sdk_native_cargo_pins"] == pins.NATIVE_CARGO_PINS
    source = snapshot["nostr_sdk_source"]
    assert source["revision"] == pins.NOSTR_SDK_SOURCE_REVISION
    assert source["sdist_published"] is False
    assert "harness_lock_sha256" in snapshot
    assert snapshot["harness_lock_packages"] == len(
        pins.harness_lock_resolution()
    )
    # Lock resolution records every package with name/version/hash.
    resolution = pins.harness_lock_resolution()
    assert resolution, "harness lock resolution must not be empty"
    for entry in resolution:
        assert entry["name"] and entry["version"]
        assert isinstance(entry["artifacts"], list)


@pytest.mark.parametrize(
    ("needle", "what"),
    [
        ("5dc79c5", "Infinitemarkets market-spec pin"),
        (
            "a2494f4f81d46684e5814a9bf35e2b1df978f955",
            "Nostr NIPs pin",
        ),
        ("v2 payload only", "NIP-44 v2-only pin"),
        (
            "4fa70f338d274e14fc82746a83fba5c2c658211f",
            "LNbits commit pin",
        ),
        ("v1.7.1", "LNbits tag"),
        (EXPECTED_NOSTR_SDK, "nostr-sdk candidate pin"),
        ("Linux x86_64", "blocking platform (x86_64)"),
        ("Linux ARM64", "blocking platform (ARM64)"),
        ("PostgreSQL", "blocking database"),
        ("SQLite", "blocking database"),
        ("macOS ARM64", "advisory smoke profile"),
        ("Python 3.12 only", "Python 3.12-only claim (D-02)"),
        ("APPROVED", "approval section (D-11)"),
        # Task 2 additions (D-15 contingency, provenance, lock identities)
        ("pinned native revision", "D-15 contingency criterion"),
        ("reproducible build", "D-15 contingency criterion"),
        ("hashed artifacts", "D-15 contingency criterion"),
        ("owner approval", "D-15 contingency criterion"),
        (pins.NOSTR_SDK_SOURCE_REVISION, "release-source revision"),
        ("rust-nostr/nostr-sdk-ffi", "release-source repository"),
        ("wheels only", "no-sdist provenance fact"),
        ("secp256k1", "native Cargo dependency pin"),
        ("chacha20poly1305", "native Cargo dependency pin"),
        ("uv.lock", "lockfile identity"),
    ],
)
def test_pins_md_records_the_pinned_identities(needle: str, what: str):
    text = PINS_MD.read_text()
    assert needle in text, f"PINS.md must record the {what}"
