"""Fallback loader for runtime dependencies vendored into the release archive.

LNbits never installs Python dependencies for extensions — the manifest's
``dependencies`` list is display metadata — so ``nostr_sdk`` must be
importable out of the box on stock hosts. That includes the single-binary
(PyInstaller-style) distribution, which has no environment to pip-install
into at all.

Development checkouts resolve ``nostr-sdk==0.44.8`` through uv.lock.
Remote installs instead get the pinned wheels unpacked under
``infinitemarkets/_vendor/<wheel platform tag>/`` by
``tools/package_release.py``. This shim runs at the top of
``infinitemarkets/__init__.py``, before any module that imports
``nostr_sdk``: when the host environment already provides the module the
shim does nothing, so a provisioned host always wins over the bundled
fallback.
"""

from __future__ import annotations

import importlib
import importlib.util
import platform
import sys
from pathlib import Path

#: Directory populated only inside release archives; absent in git checkouts.
VENDOR_DIR = Path(__file__).resolve().parent / "_vendor"

#: Top-level modules the archive vendors under ``_vendor/<platform tag>/``.
VENDORED_MODULES = ("nostr_sdk",)


def _platform_tags() -> list[str]:
    """Vendored wheel platform tags for this host, in preference order."""
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        return [f"macosx_11_0_{machine}"]
    if sys.platform == "win32":
        arch = {"amd64": "win_amd64", "x86": "win32", "arm64": "win_arm64"}
        return [arch.get(machine, "win_amd64")]
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    # The C library is part of the tag — a glibc host cannot load a musl
    # wheel and vice versa. Only vendored directories are tried, and a
    # wrong candidate simply fails the import probe below.
    return [f"manylinux_2_17_{machine}", f"musllinux_1_2_{machine}"]


def _drop_partial_imports(module: str) -> None:
    """Evict a module (and its submodules) left behind by a failed import."""
    for name in [n for n in sys.modules if n == module or n.startswith(f"{module}.")]:
        sys.modules.pop(name, None)


def ensure_vendored() -> None:
    """Append the platform-matching vendored wheels to ``sys.path``.

    No-op unless the host cannot already resolve a vendored module, and a
    no-op entirely on git checkouts (``_vendor/`` only exists in release
    archives). If no vendored wheel matches this platform the later
    ``import nostr_sdk`` raises the same ``ModuleNotFoundError`` a stock
    host would have produced without this shim.
    """
    if not VENDOR_DIR.is_dir():
        return
    missing = [m for m in VENDORED_MODULES if importlib.util.find_spec(m) is None]
    if not missing:
        return
    for tag in _platform_tags():
        wheel_dir = VENDOR_DIR / tag
        if not wheel_dir.is_dir():
            continue
        sys.path.insert(0, str(wheel_dir))
        try:
            for module in missing:
                importlib.import_module(module)
            return
        except ImportError:
            for module in missing:
                _drop_partial_imports(module)
            sys.path.remove(str(wheel_dir))
