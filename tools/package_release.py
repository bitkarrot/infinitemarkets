#!/usr/bin/env python3
"""Build the LNbits remote-install release artifacts for infinitemarkets.

Outputs into ``dist/``:

- ``infinitemarkets-<version>.zip`` — single top-level directory
  ``infinitemarkets/`` containing the extension package, which is the layout
  LNbits' ``extract_archive`` expects (it copies the first top-level dir and
  reads ``config.json`` at its root). Only git-tracked files are packaged, so
  ``__pycache__`` and untracked assets never leak into the release.
- ``manifest.json`` — an LNbits extension-registry manifest whose
  ``extensions[]`` entry is an ExplicitRelease pointing at the zip release
  asset with its real sha256. Operators add this manifest's URL to
  ``lnbits_extensions_manifests`` (or install the zip directly).

The release zip is self-contained: LNbits does not install extension
dependencies, so the pinned ``nostr-sdk`` wheels (PINS.md §3) are
unpacked under ``infinitemarkets/_vendor/<platform tag>/`` and imported
through ``infinitemarkets/_vendored.py`` when the host env lacks them.

The zip is deterministic: fixed entry order (``git ls-files`` order, then
the ``VENDOR_WHEELS`` order and each wheel's own member order), a fixed
mtime, and sha256-pinned wheel bytes, so rebuilds of the same tree
produce the same sha256.
"""

import hashlib
import json
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT_DIR = "infinitemarkets"
REPO = "https://github.com/bitkarrot/infinitemarkets"
# ZipInfo refuses dates before 1980; a fixed timestamp keeps builds reproducible.
FIXED_DATE = (2025, 1, 1, 0, 0, 0)

VENDORED_PACKAGE = "nostr_sdk"
VENDOR_CACHE = ROOT / ".cache" / "vendor-wheels"  # .cache/ is gitignored

# filename -> (files.pythonhosted.org URL, sha256). The set covers the
# platforms LNbits realistically runs on; extend it if a deployment needs
# another wheel — the ABI is cp39-abi3, so every wheel serves Python >=3.9.
VENDOR_WHEELS: dict[str, tuple[str, str]] = {
    "nostr_sdk-0.44.8-cp39-abi3-manylinux_2_17_x86_64.whl": (
        "https://files.pythonhosted.org/packages/7e/28/"
        "64604fd23dfccd68ba76e269f027cf597b083a308666fe46c202ed9f365d/"
        "nostr_sdk-0.44.8-cp39-abi3-manylinux_2_17_x86_64.whl",
        "e6b2f1b44ae95b35712008c2e0335ab833a30545a80c4afa45992b439b20e66b",
    ),
    "nostr_sdk-0.44.8-cp39-abi3-manylinux_2_17_aarch64.whl": (
        "https://files.pythonhosted.org/packages/bb/13/"
        "6233b97a37eb035997d134b46c0f008552a457082a9d2866375e4c098950/"
        "nostr_sdk-0.44.8-cp39-abi3-manylinux_2_17_aarch64.whl",
        "7b7a684afbfc9118aa2dd3adc7f06fa0d0f872e7ccfdf7542d2ba649f4b3689b",
    ),
    "nostr_sdk-0.44.8-cp39-abi3-musllinux_1_2_x86_64.whl": (
        "https://files.pythonhosted.org/packages/9b/82/"
        "28078b60a488efca13e34daaa2bb6e7fdc5c97e33f2ead52feba06179ad6/"
        "nostr_sdk-0.44.8-cp39-abi3-musllinux_1_2_x86_64.whl",
        "7d4b0530005f3ec419c5c9763b0cf121c94fd7aac00268f51d85eed182eeb055",
    ),
    "nostr_sdk-0.44.8-cp39-abi3-musllinux_1_2_aarch64.whl": (
        "https://files.pythonhosted.org/packages/85/e9/"
        "ba457ede5ab84383fbad6d1d62d3bf2ddab7ff00f0f3dedc8476dfed3213/"
        "nostr_sdk-0.44.8-cp39-abi3-musllinux_1_2_aarch64.whl",
        "b142daccbcaf421accf094f33797f2edb7c8b212996412c9ee9dd824dff28bd4",
    ),
    "nostr_sdk-0.44.8-cp39-abi3-macosx_11_0_arm64.whl": (
        "https://files.pythonhosted.org/packages/6b/59/"
        "df089c9ca3f683c3245c6aeb55b76e8933ebb33168b6436c29da24f1040b/"
        "nostr_sdk-0.44.8-cp39-abi3-macosx_11_0_arm64.whl",
        "d781526da09550a8ca7b11abf0ee270bda53fabe191a2abfc8851dd1f3f4235c",
    ),
    "nostr_sdk-0.44.8-cp39-abi3-macosx_11_0_x86_64.whl": (
        "https://files.pythonhosted.org/packages/9a/a8/"
        "3defda5f31dc639d5003c6b96389407637a7a0355e9aa14aceb0feac60db/"
        "nostr_sdk-0.44.8-cp39-abi3-macosx_11_0_x86_64.whl",
        "ef1a69cf54fbc8647d5a7b7a1e77a4d0c81761eefaea1323c53d81523974c488",
    ),
    "nostr_sdk-0.44.8-cp39-abi3-win_amd64.whl": (
        "https://files.pythonhosted.org/packages/da/a0/"
        "d02d8e9057c5c305566fad95f9e3b99f8c1838501a599de7f1c17b59903f/"
        "nostr_sdk-0.44.8-cp39-abi3-win_amd64.whl",
        "0f1e011fdeede5a323907dd138cf8cf8a86cb897a46effb15899490948b15c5e",
    ),
}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", EXT_DIR],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    files = [ln for ln in out.stdout.splitlines() if ln.strip()]
    if not files:
        sys.exit("error: git ls-files returned no files under infinitemarkets/")
    return files


def fetch_wheel(filename: str, url: str, sha256: str) -> Path:
    """Return the cached wheel, downloading and hash-verifying if needed."""
    VENDOR_CACHE.mkdir(parents=True, exist_ok=True)
    wheel = VENDOR_CACHE / filename
    if wheel.exists() and hashlib.sha256(wheel.read_bytes()).hexdigest() == sha256:
        return wheel
    print(f"fetching {filename}")
    urllib.request.urlretrieve(url, wheel)
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if digest != sha256:
        wheel.unlink()
        sys.exit(f"error: sha256 mismatch for {filename}: got {digest}")
    return wheel


def write_vendored(zf: zipfile.ZipFile) -> int:
    """Write each pinned wheel's package contents under _vendor/<tag>/."""
    count = 0
    for filename, (url, sha256) in VENDOR_WHEELS.items():
        wheel = fetch_wheel(filename, url, sha256)
        platform_tag = filename.removesuffix(".whl").rsplit("-", 1)[-1]
        with zipfile.ZipFile(wheel) as wf:
            for member in sorted(wf.namelist()):
                if not member.startswith(f"{VENDORED_PACKAGE}/"):
                    continue
                info = zipfile.ZipInfo(
                    f"{EXT_DIR}/_vendor/{platform_tag}/{member}",
                    date_time=FIXED_DATE,
                )
                info.external_attr = 0o644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, wf.read(member))
                count += 1
    return count


def build_zip(version: str, files: list[str], out_dir: Path) -> tuple[Path, int]:
    zip_path = out_dir / f"{EXT_DIR}-{version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            info = zipfile.ZipInfo(rel, date_time=FIXED_DATE)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, (ROOT / rel).read_bytes())
        vendored = write_vendored(zf)
    return zip_path, vendored


def icon_url(config: dict, tag: str) -> str | None:
    """Repo raw URL for the extension tile icon (ExplicitRelease.icon)."""
    tile = config.get("tile") or ""
    _, _, *rest = tile.split("/")
    if not rest:
        return None
    return f"{REPO}/raw/{tag}/{EXT_DIR}/{'/'.join(rest)}"


def write_manifest(version: str, zip_name: str, sha256: str,
                   config: dict, out_dir: Path) -> Path:
    tag = f"v{version}"
    manifest = {
        "extensions": [
            {
                "id": EXT_DIR,
                "name": config["name"],
                "version": version,
                "archive": f"{REPO}/releases/download/{tag}/{zip_name}",
                "hash": sha256,
                "repo": REPO,
                "icon": icon_url(config, tag),
                "short_description": config["short_description"],
                "min_lnbits_version": config.get("min_lnbits_version"),
                "max_lnbits_version": config.get("max_lnbits_version"),
                "html_url": f"{REPO}/releases/tag/{tag}",
                "details_link": (
                    "https://raw.githubusercontent.com/bitkarrot/"
                    f"infinitemarkets/{tag}/{EXT_DIR}/config.json"
                ),
                "dependencies": [],
            }
        ],
        "repos": [],
        "featured": [],
        "categories": {},
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def main() -> None:
    config = json.loads((ROOT / EXT_DIR / "config.json").read_text())
    version = config["version"]
    out_dir = ROOT / "dist"
    out_dir.mkdir(exist_ok=True)

    files = tracked_files()
    zip_path, vendored = build_zip(version, files, out_dir)
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    manifest_path = write_manifest(
        version, zip_path.name, digest, config, out_dir
    )

    print(f"zip:      {zip_path.relative_to(ROOT)} "
          f"({len(files)} files + {vendored} vendored, "
          f"{zip_path.stat().st_size} bytes)")
    print(f"sha256:   {digest}")
    print(f"manifest: {manifest_path.relative_to(ROOT)}")
    print("\nRelease commands:")
    print(f"  git tag v{version} && git push origin v{version}")
    print(f"  gh release create v{version} "
          f"dist/{zip_path.name} dist/manifest.json "
          f"--title 'Infinite Markets v{version}'")


if __name__ == "__main__":
    main()
