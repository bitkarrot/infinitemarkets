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

Frozen hosts additionally lack lazily-loaded **stdlib** modules that
the bundler never saw (observed: ``html.parser``/``_markupbase`` on the
Nuitka single-file build). The archive therefore also carries a small
``_vendor/py/`` dir with the pristine CPython 3.12 files (PSF-licensed,
pinned by sha256 in ``tools/package_release.py``), applied with the same
"only when missing" rule.
"""

from __future__ import annotations

import importlib
import importlib.util
import platform
import sys
from pathlib import Path

#: Directory populated only inside release archives; absent in git checkouts.
VENDOR_DIR = Path(__file__).resolve().parent / "_vendor"

#: Platform-agnostic pure-Python fills under ``_vendor/py/``.
PURE_DIR = VENDOR_DIR / "py"

#: Top-level modules the archive vendors under ``_vendor/<platform tag>/``.
VENDORED_MODULES = ("nostr_sdk",)

#: Stdlib modules the archive vendors under ``_vendor/py/`` — frozen
# hosts can ship a bundled-but-incomplete stdlib.
STDLIB_MODULES = ("_markupbase", "html.parser")


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


def _module_missing(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is None
    except ImportError:  # unimportable/missing parent package
        return True


def _enable_vendored_wheels() -> None:
    missing = [m for m in VENDORED_MODULES if _module_missing(m)]
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


def _enable_vendored_stdlib() -> None:
    """Fill stdlib gaps in frozen builds with ``_vendor/py/`` files."""
    if not PURE_DIR.is_dir():
        return
    if not any(_module_missing(m) for m in STDLIB_MODULES):
        return
    sys.path.append(str(PURE_DIR))
    if _module_missing("html.parser"):
        try:
            import html
        except ImportError:
            return  # vendored html/ package on sys.path covers it wholesale
        # The bundled html package exists but lacks parser — a vendored
        # submodule is invisible unless the package search path is
        # extended, since regular packages only look in their __path__.
        vendored = str(PURE_DIR / "html")
        try:
            if vendored not in html.__path__:
                html.__path__.append(vendored)
        except AttributeError:  # __path__ not list-like on some bundlers
            html.__path__ = [*html.__path__, vendored]


def ensure_vendored() -> None:
    """Append vendored fallbacks to ``sys.path``.

    No-op unless the host cannot already resolve a vendored module, and a
    no-op entirely on git checkouts (``_vendor/`` only exists in release
    archives). If nothing vendored matches this platform the later
    imports raise the same ``ModuleNotFoundError`` a stock host would
    have produced without this shim.
    """
    if not VENDOR_DIR.is_dir():
        return
    _enable_vendored_wheels()
    _enable_vendored_stdlib()
