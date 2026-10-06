"""Theme token backend — UI-SPEC Tiered Controls (sketch 003-D, LOCKED).

Three progressive tiers, persisted as ONE validated token object on
``merchants.theme`` (plan 02-02 Task 3 decision: a merchant column, not
the settings KV table — it is part of the merchant document):

1. ``preset`` — warm-market | clean-minimal | high-contrast
2. ``brand`` — display name, ≤3-char initials, accent color, preset font
   stack, corner character -> radius set
3. ``advanced`` — explicit opt-in; bounded allowlisted token overrides
   only (no free-form CSS, URLs, scripts, or fonts)

WCAG contrast gates are enforced server-side at write time (≥4.5:1 on
text/bg, text/surface, primary/on-primary); failures name the pair and
the computed ratio. Emission is `.gm-public`-scoped custom properties —
themes NEVER reach admin documents.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urlparse

from ..db import db, table
from ..security import unprocessable

PRESETS = ("warm-market", "clean-minimal", "high-contrast")
LAYOUTS = ("editorial", "guided", "compact", "gallery")
FONT_STACKS = ("system", "serif", "mono")
CORNERS = ("sharp", "rounded", "soft")

# Preset palettes — exact sketch values (sketch-findings theme-system.md);
# high-contrast meets WCAG AAA by design.
PRESET_TOKENS: dict[str, dict[str, str]] = {
    "warm-market": {
        "--color-bg": "#f7f1e8",
        "--color-surface": "#fffaf3",
        "--color-surface-alt": "#f1e4d3",
        "--color-border": "#dfcfbb",
        "--color-text": "#2b241f",
        "--color-text-muted": "#75685c",
        "--color-primary": "#a34f2a",
        "--color-on-primary": "#ffffff",
        "--color-primary-hover": "#843d20",
        "--color-accent": "#d69a3a",
        "--color-focus": "#225bdb",
    },
    "clean-minimal": {
        "--color-bg": "#f4f7f7",
        "--color-surface": "#ffffff",
        "--color-surface-alt": "#e9efef",
        "--color-border": "#d7e0e0",
        "--color-text": "#172223",
        "--color-text-muted": "#647274",
        "--color-primary": "#266760",
        "--color-on-primary": "#ffffff",
        "--color-primary-hover": "#1c514c",
        "--color-accent": "#d69a3a",
        "--color-focus": "#165dff",
    },
    "high-contrast": {
        "--color-bg": "#0b0f14",
        "--color-surface": "#141a21",
        "--color-surface-alt": "#1d2630",
        "--color-border": "#415064",
        "--color-text": "#f7fafc",
        "--color-text-muted": "#bac5d1",
        "--color-primary": "#ffb000",
        "--color-on-primary": "#111111",
        "--color-primary-hover": "#ffd166",
        "--color-accent": "#63d2ff",
        "--color-focus": "#ffffff",
    },
}

# Advanced-tier allowlist (UI-SPEC B6): colors, radius, spacing only —
# semantic/focus keys and anything else are rejected outright.
ALLOWED_ADVANCED_TOKENS = frozenset(
    {
        "--color-bg", "--color-surface", "--color-surface-alt",
        "--color-border", "--color-text", "--color-text-muted",
        "--color-primary", "--color-on-primary", "--color-primary-hover",
        "--color-accent",
        "--radius-sm", "--radius-md", "--radius-lg",
        "--space-sm", "--space-md", "--space-lg", "--space-16",
    }
)
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_RADIUS = re.compile(r"^([0-9]|1[0-9]|2[0-4])px$")  # 0-24px
_SPACE = re.compile(r"^([0-9]|[1-9][0-9])px$")  # 0-99px

_CORNER_RADIUS = {
    "sharp": {"--radius-sm": "0px", "--radius-md": "0px",
              "--radius-lg": "0px"},
    "rounded": {"--radius-sm": "4px", "--radius-md": "8px",
                "--radius-lg": "16px"},
    "soft": {"--radius-sm": "8px", "--radius-md": "16px",
             "--radius-lg": "24px"},
}

_FONT_VALUE = {
    # Sketch font: ui-rounded, "Avenir Next" — warm rounded sans; local
    # stacks only, never remote font loading.
    "system": 'ui-rounded, "Avenir Next", system-ui, sans-serif',
    "serif": 'Georgia, "Times New Roman", serif',
    "mono": 'ui-monospace, "SF Mono", Menlo, monospace',
}

# Contrast-gated pairs (WCAG ≥4.5:1).
_GATED_PAIRS = (
    ("--color-text", "--color-bg"),
    ("--color-text", "--color-surface"),
    ("--color-text", "--color-surface-alt"),
    ("--color-text-muted", "--color-bg"),
    ("--color-text-muted", "--color-surface"),
    ("--color-primary", "--color-on-primary"),
    ("--color-primary-hover", "--color-on-primary"),
    ("--color-primary", "--color-bg"),
    ("--color-primary", "--color-surface"),
    ("--color-focus", "--color-bg"),
    ("--color-focus", "--color-surface"),
)

DEFAULT_THEME = {"preset": "warm-market", "layout": "editorial",
                 "brand": None, "advanced": None, "hero": None}

# Hero (storefront index intro) — bounded content fields, not tokens:
# slogan/subtitle are length-capped; URLs may be #anchors, same-origin
# paths, or https links (javascript:/data:/protocol-relative rejected).
_HERO_ANCHOR = re.compile(r"^#[A-Za-z][\w-]{0,63}$")
_HERO_PATH = re.compile(r"^/(?!/)[\w\-./?=&%#]{0,511}$")
_IP_HOST = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$|^\[?[0-9a-fA-F:]+\]?$")


def _validate_hero_url(value, field: str) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if _HERO_ANCHOR.fullmatch(url) or _HERO_PATH.fullmatch(url):
        return url
    ok = False
    if url.startswith("https://") and len(url) <= 512 \
            and not any(ch.isspace() for ch in url):
        try:
            parsed = urlparse(url)
        except ValueError:
            parsed = None
        ok = bool(
            parsed and parsed.hostname and not parsed.username
            and not _IP_HOST.match(parsed.hostname)
        )
    if not ok:
        raise unprocessable(
            "invalid-content",
            f"hero {field} must be a #anchor, /path or https:// URL",
        )
    return url


def _validate_hero(hero: dict) -> dict:
    if not isinstance(hero, dict):
        raise unprocessable("invalid-content", "hero must be an object")
    unknown = set(hero) - {
        "slogan", "subtitle", "image_url", "primary", "secondary"
    }
    if unknown:
        raise unprocessable(
            "invalid-content", f"unknown hero fields: {sorted(unknown)}"
        )
    out = {}
    for field, limit in (("slogan", 120), ("subtitle", 280)):
        value = str(hero.get(field) or "").strip()
        if value:
            out[field] = value[:limit]
    image_url = _validate_hero_url(hero.get("image_url"), "image_url")
    if image_url:
        out["image_url"] = image_url
    for slot in ("primary", "secondary"):
        raw = hero.get(slot)
        if raw is None:
            continue
        if not isinstance(raw, dict):
            raise unprocessable(
                "invalid-content", f"hero {slot} must be an object"
            )
        unknown = set(raw) - {"label", "url"}
        if unknown:
            raise unprocessable(
                "invalid-content",
                f"unknown hero {slot} fields: {sorted(unknown)}",
            )
        label = str(raw.get("label") or "").strip()[:30]
        url = _validate_hero_url(raw.get("url"), f"{slot}.url") or "#products"
        if not label:
            continue
        out[slot] = {"label": label, "url": url}
    return out


# --- WCAG contrast ---------------------------------------------------------------


def _luminance(hex_color: str) -> float:
    c = hex_color.lstrip("#")
    r, g, b = (int(c[i : i + 2], 16) / 255 for i in (0, 2, 4))
    channels = []
    for ch in (r, g, b):
        channels.append(
            ch / 12.92 if ch <= 0.04045 else ((ch + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(fg: str, bg: str) -> float:
    l1, l2 = _luminance(fg), _luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _enforce_contrast(tokens: dict[str, str]) -> None:
    for fg, bg in _GATED_PAIRS:
        if fg in tokens and bg in tokens:
            ratio = contrast_ratio(tokens[fg], tokens[bg])
            if ratio < 4.5:
                raise unprocessable(
                    "contrast-gate",
                    "Theme contrast gate failed",
                    f"{fg} on {bg} = {ratio:.2f}:1 (needs ≥4.5:1)",
                )


# --- validation + resolution ------------------------------------------------------


def _validate_brand(brand: dict) -> dict:
    out = {}
    if brand.get("name") is not None:
        name = str(brand["name"]).strip()[:200]
        if name:
            out["name"] = name
    if brand.get("initials") is not None:
        initials = str(brand["initials"]).strip()
        if len(initials) > 3:
            raise unprocessable(
                "invalid-content", "logo initials are ≤3 characters"
            )
        if initials:
            out["initials"] = initials
    if brand.get("accent") is not None:
        accent = str(brand["accent"])
        if not _HEX_COLOR.match(accent):
            raise unprocessable(
                "invalid-content", "accent must be a #rrggbb color"
            )
        out["accent"] = accent.lower()
    if brand.get("font") is not None:
        if brand["font"] not in FONT_STACKS:
            raise unprocessable(
                "invalid-content",
                f"font must be one of {FONT_STACKS}",
            )
        out["font"] = brand["font"]
    if brand.get("corners") is not None:
        if brand["corners"] not in CORNERS:
            raise unprocessable(
                "invalid-content",
                f"corners must be one of {CORNERS}",
            )
        out["corners"] = brand["corners"]
    unknown = set(brand) - {"name", "initials", "accent", "font", "corners"}
    if unknown:
        raise unprocessable(
            "invalid-content", f"unknown brand fields: {sorted(unknown)}"
        )
    return out


def _validate_advanced(advanced: dict, opted_in: bool) -> dict:
    if not opted_in:
        raise unprocessable(
            "invalid-content",
            "Advanced tokens are opt-in",
            "advanced tokens require the explicit opt-in flag",
        )
    if not isinstance(advanced, dict):
        raise unprocessable(
            "invalid-content", "advanced tokens must be an object"
        )
    out = {}
    for key, value in advanced.items():
        if key not in ALLOWED_ADVANCED_TOKENS:
            raise unprocessable(
                "invalid-content",
                "Token not allowed",
                f"token {key!r} is not in the advanced allowlist",
            )
        value = str(value).strip()
        if key.startswith("--color-"):
            if not _HEX_COLOR.match(value):
                raise unprocessable(
                    "invalid-content",
                    f"{key} must be a #rrggbb color",
                )
            out[key] = value.lower()
        elif key.startswith("--radius-"):
            if not _RADIUS.match(value):
                raise unprocessable(
                    "invalid-content",
                    f"{key} must be a px radius in 0-24px",
                )
            out[key] = value
        else:  # --space-*
            if not _SPACE.match(value):
                raise unprocessable(
                    "invalid-content",
                    f"{key} must be a px length in 0-99px",
                )
            out[key] = value
    return out


def validate_theme(payload: dict) -> dict:
    """Validate a theme patch into the persisted token object."""
    if not isinstance(payload, dict):
        raise unprocessable("invalid-content", "theme must be an object")
    unknown = set(payload) - {
        "preset", "layout", "brand", "advanced", "advanced_opt_in", "hero"
    }
    if unknown:
        raise unprocessable(
            "invalid-content", f"unknown theme fields: {sorted(unknown)}"
        )
    theme = dict(DEFAULT_THEME)
    theme["preset"] = payload.get("preset", theme["preset"])
    theme["layout"] = payload.get("layout", theme["layout"])
    if theme["preset"] not in PRESETS:
        raise unprocessable(
            "invalid-content", f"preset must be one of {PRESETS}"
        )
    if theme["layout"] not in LAYOUTS:
        raise unprocessable(
            "invalid-content", f"layout must be one of {LAYOUTS}"
        )
    if payload.get("brand") is not None:
        theme["brand"] = _validate_brand(payload["brand"])
    if payload.get("hero") is not None:
        theme["hero"] = _validate_hero(payload["hero"])
    if payload.get("advanced") is not None:
        theme["advanced"] = _validate_advanced(
            payload["advanced"], bool(payload.get("advanced_opt_in"))
        )
        theme["advanced_opt_in"] = True
    # WCAG gates run against the fully resolved token set — a brand accent
    # or advanced override can't silently break contrast.
    _enforce_contrast(resolve_tokens(theme))
    return theme


def resolve_tokens(theme: dict | None) -> dict[str, str]:
    """Flatten preset + brand + advanced into the emitted token set."""
    theme = theme or DEFAULT_THEME
    tokens = dict(PRESET_TOKENS[theme.get("preset", "warm-market")])
    brand = theme.get("brand") or {}
    if brand.get("accent"):
        tokens["--color-accent"] = brand["accent"]
    if brand.get("corners"):
        tokens.update(_CORNER_RADIUS[brand["corners"]])
    if brand.get("font"):
        tokens["--font-body"] = _FONT_VALUE[brand["font"]]
    tokens.update(theme.get("advanced") or {})
    return tokens


# --- viewer dark scheme ------------------------------------------------------------

# Warm dark neutrals — the dark counterpart of the Warm Market palette.
# The merchant brand never picks these; they only color surfaces/text
# when the shopper opts into dark mode (or their system requests it).
_DARK_SURFACES: dict[str, str] = {
    "--color-bg": "#1b1510",
    "--color-surface": "#241c15",
    "--color-surface-alt": "#2e241b",
    "--color-border": "rgba(245, 239, 230, 0.12)",
    "--color-text": "#f5efe6",
    "--color-text-muted": "#b8a996",
    "--color-focus": "#8ab5ff",
    "--shadow-sm": "0 1px 2px rgba(0, 0, 0, 0.45)",
    "--shadow-md": "0 8px 24px rgba(0, 0, 0, 0.45)",
    "--shadow-lg": "0 18px 52px rgba(0, 0, 0, 0.55)",
}


def _mix_hex(a: str, b: str, t: float) -> str:
    """srgb channel mix of ``a`` toward ``b`` by t in [0, 1]."""
    ca, cb = a.lstrip("#"), b.lstrip("#")
    out = []
    for i in (0, 2, 4):
        va, vb = int(ca[i : i + 2], 16), int(cb[i : i + 2], 16)
        out.append(round(va + (vb - va) * t))
    return "#" + "".join(f"{v:02x}" for v in out)


def _lighten_to(color: str, bg: str, target: float) -> str:
    """Mix ``color`` toward white until it clears ``target``:1 on ``bg``.

    Merchant primaries are contrast-gated against their LIGHT surfaces;
    a dark primary would vanish on the dark palette, so the dark scheme
    lightens it — cap at 85% white so the brand hue stays recognizable.
    """
    mixed = color
    t = 0.0
    while contrast_ratio(mixed, bg) < target and t < 0.85:
        t += 0.05
        mixed = _mix_hex(color, "#ffffff", t)
    return mixed


def dark_scheme_tokens(theme: dict | None) -> dict[str, str]:
    """Derive the dark-scheme token set from the resolved light tokens.

    Brand color is preserved: the primary (and hover/accent/focus) are
    lightened just enough to meet the same WCAG pairs on dark surfaces,
    and --color-on-primary flips to the dark surface color because the
    lightened primary now carries dark text.
    """
    tokens = resolve_tokens(theme)
    dark = dict(_DARK_SURFACES)
    bg = dark["--color-bg"]
    dark["--color-primary"] = _lighten_to(tokens["--color-primary"], bg, 4.5)
    dark["--color-primary-hover"] = _lighten_to(
        tokens["--color-primary-hover"], bg, 4.5
    )
    dark["--color-on-primary"] = bg
    accent = tokens["--color-accent"]
    dark["--color-accent"] = (
        accent if contrast_ratio(accent, bg) >= 3.0
        else _lighten_to(accent, bg, 3.0)
    )
    dark["color-scheme"] = "dark"
    return dark


def emit_css(theme: dict | None) -> str:
    """Resolved tokens as `.gm-public`-scoped custom-property blocks —
    the ONLY place theme values become CSS.

    Emits the light base plus a dark-scheme variant: explicit shopper
    choice (`data-scheme="dark"`) always applies, and absent an explicit
    override the viewer's `prefers-color-scheme` picks the dark set.
    The attribute selectors (0,2,0) outrank this inline `.gm-public`
    block so merchant tokens never defeat the shopper's dark choice.
    """
    tokens = resolve_tokens(theme)
    body = ";\n  ".join(f"{k}: {v}" for k, v in sorted(tokens.items()))
    dark_body = ";\n    ".join(
        f"{k}: {v}" for k, v in sorted(dark_scheme_tokens(theme).items())
    )
    dark_sel = ".gm-public[data-scheme=\"dark\"]"
    return (
        f".gm-public {{\n  {body};\n  color-scheme: light;\n}}\n"
        f"{dark_sel} {{\n    {dark_body};\n}}\n"
        "@media (prefers-color-scheme: dark) {\n"
        f"  .gm-public:not([data-scheme=\"light\"]) {{\n    {dark_body};\n  }}\n"
        "}"
    )


def theme_layout(theme: dict | None) -> str:
    return (theme or DEFAULT_THEME).get("layout", "editorial")


# --- persistence ------------------------------------------------------------------


def parse_theme(raw: str | None) -> dict:
    if not raw:
        return dict(DEFAULT_THEME)
    try:
        theme = json.loads(raw)
    except (TypeError, ValueError):
        return dict(DEFAULT_THEME)
    if not isinstance(theme, dict) or theme.get("preset") not in PRESETS:
        return dict(DEFAULT_THEME)
    return theme


async def get_theme(merchant_id: str) -> dict:
    async with db.connect() as conn:
        row = await conn.fetchone(
            f"SELECT theme FROM {table('merchants')} WHERE id = :m",
            {"m": merchant_id},
        )
    return parse_theme(row["theme"] if row else None)


async def save_theme(merchant_id: str, theme: dict) -> dict:
    validated = validate_theme(theme)
    async with db.connect() as conn:
        await conn.execute(
            f"UPDATE {table('merchants')} SET theme = :t, "
            "updated_at = :n WHERE id = :m",
            {"t": json.dumps(validated, sort_keys=True),
             "n": int(time.time()),
             "m": merchant_id},
        )
    return validated
