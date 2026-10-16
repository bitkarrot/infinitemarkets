"""Bounded 1200x630 Open Graph card rendering for public storefront pages."""

from __future__ import annotations

import asyncio
import hashlib
import http.client
import io
import re
import socket
import ssl
import time
from collections import OrderedDict
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageDraw, ImageFont, ImageOps

from ..security import resolve_and_check_egress

WIDTH = 1200
HEIGHT = 630
_MAX_SOURCE_BYTES = 3 * 1024 * 1024
_MAX_SOURCE_PIXELS = 16_000_000
_MAX_IMAGE_REDIRECTS = 3
_IMAGE_FETCH_TIMEOUT_S = 12
_CACHE_TTL_S = 12 * 60 * 60
_CACHE_SIZE = 64
_CACHE_MAX_BYTES = 32 * 1024 * 1024
_IMAGE_CACHE: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
_IMAGE_CACHE_BYTES = 0
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a checked IP while retaining the original TLS hostname."""

    def __init__(self, host: str, address: str):
        super().__init__(host, port=443, timeout=3.0,
                         context=ssl.create_default_context())
        self._address = address

    def connect(self):
        sock = socket.create_connection(
            (self._address, 443), timeout=self.timeout
        )
        self.sock = self._context.wrap_socket(
            sock, server_hostname=self.host
        )


def _fetch_image(
    host: str, address: str, path: str,
) -> tuple[int, str | None, bytes | None] | None:
    conn = _PinnedHTTPSConnection(host, address)
    try:
        conn.request(
            "GET",
            path,
            headers={
                "Accept": "image/png,image/jpeg,image/webp,image/gif",
                "User-Agent": "InfiniteMarkets-OG/1.0",
            },
        )
        response = conn.getresponse()
        if response.status in {301, 302, 303, 307, 308}:
            return response.status, response.getheader("Location"), None
        content_type = (response.getheader("Content-Type") or "").split(";")[0]
        if response.status != 200 or content_type not in {
            "image/png", "image/jpeg", "image/webp", "image/gif",
        }:
            return None
        length = response.getheader("Content-Length")
        if length and int(length) > _MAX_SOURCE_BYTES:
            return None
        data = bytearray()
        deadline = time.monotonic() + 4
        while len(data) <= _MAX_SOURCE_BYTES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            if conn.sock:
                conn.sock.settimeout(min(3.0, remaining))
            chunk = response.read(min(64 * 1024, _MAX_SOURCE_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > _MAX_SOURCE_BYTES:
            return None
        return response.status, None, bytes(data)
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        conn.close()


async def _remote_image(url: str) -> Image.Image | None:
    try:
        current_url = (url or "").strip()
        deadline = time.monotonic() + _IMAGE_FETCH_TIMEOUT_S
        for redirect_count in range(_MAX_IMAGE_REDIRECTS + 1):
            parsed = urlparse(current_url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.fragment
                or parsed.port not in (None, 443)
            ):
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            addresses = await asyncio.wait_for(
                resolve_and_check_egress(parsed.hostname, 443),
                timeout=min(3.0, remaining),
            )
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            result = None
            for address in addresses[:2]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        _fetch_image, parsed.hostname, str(address), path
                    ),
                    timeout=min(4.5, remaining),
                )
                if result is not None:
                    break
            if result is None:
                return None
            status, location, data = result
            if status in {301, 302, 303, 307, 308}:
                if (
                    redirect_count >= _MAX_IMAGE_REDIRECTS
                    or not location
                    or len(location) > 2048
                ):
                    return None
                current_url = urljoin(current_url, location)
                continue
            if status != 200 or not data:
                return None
            break
        else:
            return None
        with Image.open(io.BytesIO(data)) as source:
            if (
                source.format not in {"PNG", "JPEG", "WEBP", "GIF"}
                or source.width * source.height > _MAX_SOURCE_PIXELS
            ):
                return None
            source.seek(0)
            source.load()
            return source.convert("RGBA")
    except Exception:
        # A missing, unsafe, or unsupported merchant image must not break
        # the generated card; the brand initials remain as the fallback.
        return None


def _color(value: str | None, fallback: str) -> str:
    return value if isinstance(value, str) and _HEX.fullmatch(value) else fallback


def _wrapped_lines(draw, text: str, font, max_width: int,
                   max_lines: int) -> list[str]:
    words = re.sub(r"\s+", " ", text or "").strip().split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and " ".join(lines).replace(" ", "") \
            != " ".join(words).replace(" ", ""):
        line = lines[-1]
        while line and draw.textbbox(
            (0, 0), line + "...", font=font
        )[2] > max_width:
            line = line[:-1]
        lines[-1] = line.rstrip() + "..."
    return lines


def _paste_contained(canvas: Image.Image, source: Image.Image,
                     box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    image = ImageOps.contain(source, (x2 - x1, y2 - y1))
    x = x1 + (x2 - x1 - image.width) // 2
    y = y1 + (y2 - y1 - image.height) // 2
    canvas.paste(image, (x, y), image)


def _render_card(
    brand_name: str,
    title: str,
    subtitle: str,
    price: str,
    eyebrow: str,
    accent: str,
    background: str,
    surface: str,
    text_color: str,
    logo: Image.Image | None,
    product_image: Image.Image | None,
) -> bytes:
    accent = _color(accent, "#a34f2a")
    background = _color(background, "#f7f1e8")
    surface = _color(surface, "#fffaf3")
    text_color = _color(text_color, "#2b241f")
    image = Image.new("RGB", (WIDTH, HEIGHT), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 28, 1172, 602), radius=28, fill=surface)
    draw.rounded_rectangle((28, 28, 48, 602), radius=10, fill=accent)

    brand_font = ImageFont.load_default(size=34)
    title_font = ImageFont.load_default(size=64)
    body_font = ImageFont.load_default(size=27)
    price_font = ImageFont.load_default(size=30)
    mark_font = ImageFont.load_default(size=34)

    draw.rounded_rectangle((84, 76, 166, 158), radius=20, fill=accent)
    if logo is not None:
        _paste_contained(image, logo, (92, 84, 158, 150))
    else:
        initials = (brand_name.strip()[:2] or "S").upper()
        bounds = draw.textbbox((0, 0), initials, font=mark_font)
        draw.text(
            (125 - (bounds[2] - bounds[0]) / 2,
             117 - (bounds[3] - bounds[1]) / 2),
            initials, fill="#ffffff", font=mark_font,
        )
    draw.text((188, 97), brand_name[:70] or "Independent shop",
              fill=text_color, font=brand_font)
    draw.text((84, 210), eyebrow[:40],
              fill=accent, font=ImageFont.load_default(size=20))

    lines = _wrapped_lines(draw, title or "Product", title_font, 550, 3)
    y = 250
    for line in lines:
        draw.text((84, y), line, fill=text_color, font=title_font)
        y += 74
    if subtitle and y <= 410:
        y += 10
        for line in _wrapped_lines(draw, subtitle, body_font, 535, 2):
            draw.text((84, y), line, fill=text_color, font=body_font)
            y += 38
    if price:
        draw.text((84, 520), price[:50], fill=accent, font=price_font)

    photo_box = (704, 76, 1116, 552)
    draw.rounded_rectangle(photo_box, radius=24, fill=background)
    if product_image is not None:
        _paste_contained(image, product_image, (
            photo_box[0] + 18, photo_box[1] + 18,
            photo_box[2] - 18, photo_box[3] - 18,
        ))
    else:
        # A quiet geometric placeholder keeps text-only cards intentional.
        draw.ellipse((830, 166, 1064, 400), fill=surface)
        draw.rounded_rectangle((868, 238, 1028, 396), radius=28, fill=accent)
        draw.polygon(
            [(868, 270), (948, 206), (1028, 270)],
            fill=accent,
        )
        draw.line((948, 238, 948, 396), fill=surface, width=6)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _cached(cache_key: str) -> bytes | None:
    global _IMAGE_CACHE_BYTES
    record = _IMAGE_CACHE.get(cache_key)
    if not record:
        return None
    expires, data = record
    if expires <= time.monotonic():
        _IMAGE_CACHE.pop(cache_key, None)
        _IMAGE_CACHE_BYTES -= len(data)
        return None
    _IMAGE_CACHE.move_to_end(cache_key)
    return data


def _cache_image(cache_key: str, data: bytes) -> None:
    global _IMAGE_CACHE_BYTES
    old = _IMAGE_CACHE.pop(cache_key, None)
    if old:
        _IMAGE_CACHE_BYTES -= len(old[1])
    _IMAGE_CACHE[cache_key] = (time.monotonic() + _CACHE_TTL_S, data)
    _IMAGE_CACHE_BYTES += len(data)
    while (
        len(_IMAGE_CACHE) > _CACHE_SIZE
        or _IMAGE_CACHE_BYTES > _CACHE_MAX_BYTES
    ):
        _, (_, removed) = _IMAGE_CACHE.popitem(last=False)
        _IMAGE_CACHE_BYTES -= len(removed)


async def render_branded_card(
    cache_key: str,
    *,
    brand_name: str,
    title: str,
    subtitle: str = "",
    price: str = "",
    eyebrow: str = "FEATURED PRODUCT",
    accent: str = "#a34f2a",
    background: str = "#f7f1e8",
    surface: str = "#fffaf3",
    text_color: str = "#2b241f",
    logo_url: str = "",
    product_image_url: str = "",
) -> tuple[bytes, str]:
    key = hashlib.sha256(cache_key.encode()).hexdigest()
    cached = _cached(key)
    if cached is not None:
        return cached, key
    urls = [url for url in (logo_url, product_image_url) if url]
    loaded = await asyncio.gather(*(_remote_image(url) for url in urls))
    images = dict(zip(urls, loaded, strict=False))
    png = _render_card(
        brand_name,
        title,
        subtitle,
        price,
        eyebrow,
        accent,
        background,
        surface,
        text_color,
        images.get(logo_url),
        images.get(product_image_url),
    )
    _cache_image(key, png)
    return png, key
