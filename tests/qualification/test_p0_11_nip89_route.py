"""P0-11: NIP-89 local routing + literal NIP-15 DTO fixtures (QUAL-11).

Covers:

- (a) naddr resolution (section 5.4): the golden kind-30402 naddr resolves
  locally to the canonical product page; malformed bech32, wrong-kind,
  foreign-merchant, invalid-d, and unmapped references each fail with a
  distinct bounded rejection;
- (b) zero relay contact: an naddr embedding a relay hint pointing at a
  SILENT local relay resolves without a single connection or request —
  hints are recorded, never fetched (T-03-02);
- (c) NIP-89 pair (section 6.5): the golden 31989/31990 pair validates,
  including the intentionally distinct ``d`` values (``"30402"`` vs the
  handler id) — tampered pairs reject;
- (d) literal NIP-15 DTOs (section 6.6): golden 30017/30018 shapes plus the
  lossy rules — specs pair-arrays, integer-or-null quantity, shipping ids,
  currency-match preview error, hidden/pre-order -> quantity 0, the
  deterministic zero-cost digital zone, and the opaque-address physical
  order shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from nostr_sdk import Coordinate, Kind, Nip19Coordinate, PublicKey, RelayUrl

from harness import nip89, sdk
from harness import relay as relay_module

pytestmark = [pytest.mark.protocol, pytest.mark.fast]

FIXTURES_89 = Path(__file__).resolve().parent.parent / "fixtures" / "golden" / "nip89"
FIXTURES_15 = Path(__file__).resolve().parent.parent / "fixtures" / "golden" / "nip15"

MERCHANT = sdk.fixed_test_keys("merchant")
PRODUCT_D = "gq-prod-0001"


@pytest.fixture(scope="module")
def registry() -> nip89.LocalCatalogRegistry:
    """The local fixture registry: one merchant, one published product."""
    mpk = MERCHANT.public_key().to_hex()
    return nip89.LocalCatalogRegistry(
        merchant_pubkeys=frozenset({mpk}),
        pages={(mpk, PRODUCT_D): f"/infinitemarkets/p/{mpk}/{PRODUCT_D}"},
    )


def _naddr(kind: int, pubkey_hex: str, identifier: str, relays=()) -> str:
    coord = Nip19Coordinate(
        Coordinate(
            Kind(kind), PublicKey.parse(pubkey_hex), identifier=identifier
        ),
        [RelayUrl.parse(r) for r in relays],
    )
    return coord.to_bech32()


# --- (a) naddr resolution -------------------------------------------------------


def test_golden_naddr_resolves_locally(registry):
    naddr = (FIXTURES_89 / "naddr.txt").read_text().strip()
    resolved = nip89.resolve_naddr(naddr, registry)
    mpk = MERCHANT.public_key().to_hex()
    assert resolved.pubkey == mpk
    assert resolved.d == PRODUCT_D
    assert resolved.path == f"/infinitemarkets/p/{mpk}/{PRODUCT_D}"
    # The fixture embeds a hint; it is recorded but never dereferenced.
    assert resolved.relay_hints == ("wss://relay.example.com",)


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-naddr",
        "naddr1!!!invalid",
        "",
        "npub1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq3w4dk",
    ],
    ids=["plain-text", "corrupt-bech32", "empty", "npub-not-naddr"],
)
def test_malformed_naddr_rejected(registry, bad):
    with pytest.raises(nip89.NaddrRejection, match="naddr-malformed"):
        nip89.resolve_naddr(bad, registry)


def test_wrong_kind_naddr_rejected(registry):
    """A kind-30018 naddr is not a 30402 product reference."""
    bad = _naddr(30018, MERCHANT.public_key().to_hex(), PRODUCT_D)
    with pytest.raises(nip89.NaddrRejection, match="naddr-kind-not-30402"):
        nip89.resolve_naddr(bad, registry)


def test_foreign_merchant_naddr_rejected(registry):
    stranger = sdk.fixed_test_keys("stranger")
    bad = _naddr(30402, stranger.public_key().to_hex(), PRODUCT_D)
    with pytest.raises(nip89.NaddrRejection, match="naddr-merchant-not-local"):
        nip89.resolve_naddr(bad, registry)


@pytest.mark.parametrize(
    "d",
    ["short", "UPPERCASE-D", "with space!!", "x" * 65],
    ids=["too-short", "uppercase", "bad-alphabet", "too-long"],
)
def test_invalid_d_naddr_rejected(registry, d):
    bad = _naddr(30402, MERCHANT.public_key().to_hex(), d)
    with pytest.raises(nip89.NaddrRejection, match="naddr-d-invalid"):
        nip89.resolve_naddr(bad, registry)


def test_unmapped_product_naddr_rejected(registry):
    """A valid local-merchant reference to an unpublished d fails."""
    bad = _naddr(30402, MERCHANT.public_key().to_hex(), "gq-prod-9999")
    with pytest.raises(nip89.NaddrRejection, match="naddr-product-not-local"):
        nip89.resolve_naddr(bad, registry)


# --- (b) zero relay contact ------------------------------------------------------


async def test_relay_hint_never_fetched(registry):
    """An naddr whose hint points at a live silent relay still resolves
    locally — the hint relay sees zero connections (section 5.4, T-03-02)."""
    async with relay_module.LocalRelay(
        mode=relay_module.RelayMode.SILENT
    ) as hinted:
        naddr = _naddr(
            30402,
            MERCHANT.public_key().to_hex(),
            PRODUCT_D,
            relays=[hinted.url],
        )
        resolved = nip89.resolve_naddr(naddr, registry)
        assert resolved.relay_hints == (hinted.url,)
        # Resolution is purely local: no connection ever reached the hint.
        assert hinted.connections == []
        assert hinted.received_messages == []


# --- (c) NIP-89 pair validation (section 6.5) -------------------------------------


def _pair() -> tuple[dict, dict]:
    rec = json.loads((FIXTURES_89 / "recommendation_31989.json").read_text())
    handler = json.loads((FIXTURES_89 / "handler_31990.json").read_text())
    return rec, handler


def test_golden_nip89_pair_validates():
    rec, handler = _pair()
    mpk = MERCHANT.public_key().to_hex()
    result = nip89.validate_nip89_pair(rec, handler, mpk)
    assert result == {"handler_d": "gqapp-rec-001", "product_kind": 30402}
    # The intentionally distinct d values (section 6.5).
    rec_d = [t[1] for t in rec["tags"] if t[0] == "d"]
    handler_d = [t[1] for t in handler["tags"] if t[0] == "d"]
    assert rec_d == ["30402"]
    assert handler_d == ["gqapp-rec-001"]


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda r, h: r["tags"][0].__setitem__(1, "gqapp-rec-001"),
         "pair-rec-d-not-30402"),
        (lambda r, h: h.__setitem__("kind", 31989),
         "pair-handler-kind-not-31990"),
        (lambda r, h: h["tags"][0].__setitem__(1, "30402"),
         "pair-d-values-not-distinct"),
        (lambda r, h: r["tags"][1].__setitem__(3, "ios"),
         "pair-rec-a-tag-not-web"),
        (lambda r, h: h["tags"][1].__setitem__(1, "30018"),
         "pair-handler-k-tag-invalid"),
        (lambda r, h: r.__setitem__("pubkey", "00" * 32),
         "pair-rec-author-not-merchant"),
    ],
    ids=[
        "rec-d-equalized-to-app-id",
        "handler-wrong-kind",
        "handler-d-equalized",
        "a-tag-not-web",
        "handler-k-tag-wrong",
        "rec-foreign-author",
    ],
)
def test_tampered_nip89_pair_rejected(mutate, reason):
    rec, handler = _pair()
    mutate(rec, handler)
    with pytest.raises(nip89.NaddrRejection, match=reason):
        nip89.validate_nip89_pair(
            rec, handler, MERCHANT.public_key().to_hex()
        )


# --- (d) literal NIP-15 DTO validation (section 6.6) -------------------------------
#
# The validator is kept in the test module (plan: unless reused elsewhere).


class DtoRejection(Exception):
    """A literal NIP-15 DTO failed shape validation."""


def _req_str(dto: dict, name: str) -> None:
    if not isinstance(dto.get(name), str) or not dto[name]:
        raise DtoRejection(f"missing-or-invalid:{name}")


def validate_stall_dto(dto: dict) -> None:
    """Section 6.6 stall 30017 content shape."""
    for name in ("id", "name", "currency"):
        _req_str(dto, name)
    shipping = dto.get("shipping")
    if not isinstance(shipping, list):
        raise DtoRejection("stall-shipping-not-list")
    for entry in shipping:
        if not isinstance(entry, dict):
            raise DtoRejection("stall-shipping-entry-invalid")
        _req_str(entry, "id")
        _req_str(entry, "name")
        if not isinstance(entry.get("cost"), (int, float)) or isinstance(
            entry.get("cost"), bool
        ):
            raise DtoRejection("stall-shipping-cost-invalid")
        if not isinstance(entry.get("regions"), list):
            raise DtoRejection("stall-shipping-regions-invalid")


def validate_product_dto(dto: dict) -> None:
    """Section 6.6 product 30018 content shape."""
    for name in ("id", "stall_id", "name", "currency"):
        _req_str(dto, name)
    if not isinstance(dto.get("images"), list):
        raise DtoRejection("product-images-not-list")
    if not isinstance(dto.get("price"), (int, float)) or isinstance(
        dto.get("price"), bool
    ):
        raise DtoRejection("product-price-invalid")
    quantity = dto.get("quantity")
    if quantity is not None and (
        not isinstance(quantity, int) or isinstance(quantity, bool)
    ):
        raise DtoRejection("product-quantity-not-int-or-null")
    specs = dto.get("specs")
    if not isinstance(specs, list):
        raise DtoRejection("product-specs-not-pair-array")
    for pair in specs:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(v, str) for v in pair)
        ):
            raise DtoRejection("product-specs-not-pair-array")
    shipping = dto.get("shipping")
    if not isinstance(shipping, list):
        raise DtoRejection("product-shipping-not-list")
    for entry in shipping:
        if not isinstance(entry, dict) or not entry.get("id"):
            raise DtoRejection("product-shipping-missing-id")


def validate_currency_match(stall: dict, product: dict) -> None:
    """Section 6.6: product/projected shipping currency must equal the
    stall currency — mismatches are a compatibility-preview error."""
    if product.get("currency") != stall.get("currency"):
        raise DtoRejection("nip15-currency-mismatch")


def nip15_quantity(visibility: str, quantity: int | None) -> int | None:
    """Section 6.6: hidden / pre-order map to quantity 0."""
    if visibility in ("hidden", "pre-order"):
        return 0
    return quantity


def digital_zone() -> dict:
    """The deterministic zero-cost digital shipping zone (section 6.6)."""
    return {
        "id": "digital",
        "name": "Digital delivery",
        "cost": 0,
        "regions": ["Worldwide"],
    }


def _load15(name: str) -> dict:
    return json.loads((FIXTURES_15 / name).read_text())


def test_valid_stall_and_product_dtos():
    stall = _load15("stall_30017.json")
    product = _load15("product_30018.json")
    validate_stall_dto(stall)
    validate_product_dto(product)
    validate_currency_match(stall, product)
    # The deterministic digital zone is present for digital-capable stalls.
    assert digital_zone() in stall["shipping"]
    # Unlimited stock: quantity null is legal.
    validate_product_dto(_load15("product_30018_unlimited.json"))


@pytest.mark.parametrize(
    "fixture,reason",
    [
        ("invalid_specs_object.json", "product-specs-not-pair-array"),
        ("invalid_quantity_float.json", "product-quantity-not-int-or-null"),
        ("invalid_quantity_string.json", "product-quantity-not-int-or-null"),
        ("invalid_missing_shipping_id.json", "product-shipping-missing-id"),
    ],
)
def test_invalid_product_variants_rejected(fixture, reason):
    with pytest.raises(DtoRejection, match=reason):
        validate_product_dto(_load15(fixture))


def test_mismatched_currencies_rejected():
    stall = _load15("stall_30017.json")
    product = _load15("invalid_mismatched_currency.json")
    validate_product_dto(product)  # shape itself is fine
    with pytest.raises(DtoRejection, match="nip15-currency-mismatch"):
        validate_currency_match(stall, product)


def test_hidden_and_preorder_map_to_quantity_zero():
    hidden = _load15("product_30018_hidden.json")
    assert hidden["quantity"] == 0
    validate_product_dto(hidden)
    assert nip15_quantity("hidden", 5) == 0
    assert nip15_quantity("pre-order", 5) == 0
    assert nip15_quantity("active", 5) == 5
    assert nip15_quantity("active", None) is None


def test_opaque_address_physical_order_shape():
    """Type-2 NIP-15 order: the address is opaque merchant-side payload —
    a string the protocol layer never parses into structured fields."""
    order = _load15("order_physical_opaque_address.json")
    assert order["type"] == 2
    assert isinstance(order["address"], str) and order["address"]
    assert order["shipping_id"] == "gq-ship-dom"
    for item in order["items"]:
        assert isinstance(item["product_id"], str)
        assert isinstance(item["quantity"], int)
