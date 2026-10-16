"""Open Graph product-image fetching stays bounded and SSRF-safe."""

from __future__ import annotations

import io
import ipaddress

import pytest
from PIL import Image

from infinitemarkets.services import og_images

pytestmark = pytest.mark.fast


def _png() -> bytes:
    image = Image.new("RGB", (2, 2), color=(180, 90, 40))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


async def test_remote_image_follows_checked_https_redirect(monkeypatch):
    fetched = []
    resolved = []
    image_bytes = _png()

    async def resolve(host, port):
        resolved.append((host, port))
        return [ipaddress.ip_address("8.8.8.8")]

    def fetch(host, address, path):
        fetched.append((host, address, path))
        if host == "media.example":
            return (
                307,
                "https://cdn.example/assets/product.png?size=large",
                None,
            )
        return 200, None, image_bytes

    monkeypatch.setattr(og_images, "resolve_and_check_egress", resolve)
    monkeypatch.setattr(og_images, "_fetch_image", fetch)

    image = await og_images._remote_image(
        "https://media.example/product.png"
    )

    assert image is not None
    assert image.size == (2, 2)
    assert resolved == [
        ("media.example", 443),
        ("cdn.example", 443),
    ]
    assert fetched == [
        ("media.example", "8.8.8.8", "/product.png"),
        ("cdn.example", "8.8.8.8", "/assets/product.png?size=large"),
    ]


@pytest.mark.parametrize(
    "location",
    [
        "http://media.example/image.png",
        "https://127.0.0.1/image.png",
        "https://user:pass@media.example/image.png",
        "https://media.example:8443/image.png",
        "https://media.example/image.png#fragment",
    ],
)
async def test_remote_image_rejects_unsafe_redirect(monkeypatch, location):
    fetched = []

    async def resolve(host, port):
        if host == "127.0.0.1":
            raise ValueError("non-public redirect target")
        return [ipaddress.ip_address("8.8.8.8")]

    def fetch(host, address, path):
        fetched.append((host, path))
        return 302, location, None

    monkeypatch.setattr(og_images, "resolve_and_check_egress", resolve)
    monkeypatch.setattr(og_images, "_fetch_image", fetch)

    assert await og_images._remote_image(
        "https://media.example/product.png"
    ) is None
    assert len(fetched) == 1


async def test_remote_image_caps_redirect_chain(monkeypatch):
    fetched = []

    async def resolve(host, port):
        return [ipaddress.ip_address("8.8.8.8")]

    def fetch(host, address, path):
        fetched.append((host, path))
        return 302, f"https://cdn{len(fetched)}.example/image.png", None

    monkeypatch.setattr(og_images, "resolve_and_check_egress", resolve)
    monkeypatch.setattr(og_images, "_fetch_image", fetch)

    assert await og_images._remote_image(
        "https://media.example/product.png"
    ) is None
    assert len(fetched) == og_images._MAX_IMAGE_REDIRECTS + 1
