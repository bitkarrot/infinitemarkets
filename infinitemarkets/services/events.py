"""Deterministic unsigned event builders — spec section 6.1–6.5 + 6.8.

Every builder renders from CURRENT domain state and returns a plain dict
``{"kind", "content", "tags"}`` — ``created_at`` is assigned at publish
time (02-02), never at build time. Identical domain state produces
byte-identical output: tag order is fixed, content JSON uses
``sort_keys`` + compact separators, and decimals serialize without
scientific notation.

NIP-32 self-describing labels (§6.8) go on the public commerce kinds
(30402/30405/30406) only — kind 0, NIP-89, seals/wraps are excluded.
"""

from __future__ import annotations

import json
from decimal import Decimal

from .fx import default_currency_decimals

NIP32_NAMESPACE = "org.infinitemarkets.protocol"

GAMMA_KIND_PRODUCT = 30402
GAMMA_KIND_COLLECTION = 30405
GAMMA_KIND_SHIPPING = 30406
GAMMA_KIND_TOMBSTONE = 5
GAMMA_KIND_PROFILE = 0
NIP89_KIND_HANDLER_INFO = 31990
NIP89_KIND_RECOMMENDATION = 31989
#: NIP-17 inbox relay advertisement (§9.3). Non-addressable replaceable
#: kind — its protocol_addresses d_tag is the empty string (§4.13).
GAMMA_KIND_INBOX_RELAYS = 10050

GAMMA_FREQ_UNITS = ("D", "W", "Y")  # pinned Gamma units (§6.1 divergence)

NIP15_KIND_STALL = 30017
NIP15_KIND_PRODUCT = 30018
NIP15_ID_MAX = 64
DIGITAL_ZONE_ID = "digital"


class CompatibilityError(Exception):
    """Projection into a compatibility protocol is impossible (e.g. a
    currency mismatch — §6.6 forbids volatile-time conversion). Services
    translate this into a preview/publish error, never a silent fix."""


def _decimal(amount_minor: int, decimals: int) -> str:
    """Fixed-point string — never scientific notation (§6 determinism)."""
    value = Decimal(amount_minor).scaleb(-decimals)
    return format(value, "f")


def _nip32_tags(spec_revision: str) -> list[list[str]]:
    return [
        ["L", NIP32_NAMESPACE],
        ["l", spec_revision, NIP32_NAMESPACE],
    ]


def product_event(
    product: dict,
    *,
    pubkey: str,
    spec_revision: str,
    images: list[dict],
    specs: list[dict],
    categories: list[str],
    member_collection_d_tags: list[str],
    shipping_refs: list[dict],
) -> dict:
    """kind 30402 — section 6.1. Caller guarantees the product is
    publishable (not draft, not deleted)."""
    tags: list[list[str]] = [
        ["d", product["d_tag"]],
        ["title", product["title"] or ""],
    ]
    if product.get("amount_minor") is not None and product.get("currency"):
        price = [
            "price",
            _decimal(
                product["amount_minor"],
                product.get("currency_decimals") or 0,
            ),
            product["currency"],
        ]
        if product.get("recurring_frequency"):
            price.append(product["recurring_frequency"])
        tags.append(price)
    tags.append(["type", product["product_type"], product["format"]])
    tags.append(["visibility", product["visibility"]])
    if product["stock_on_hand"] is not None:
        available = max(
            0, product["stock_on_hand"] - (product["stock_reserved"] or 0)
        )
        tags.append(["stock", str(available)])
    if product.get("summary"):
        tags.append(["summary", product["summary"]])
    if product.get("published_at"):
        tags.append(["published_at", str(product["published_at"])])
    for img in sorted(images, key=lambda i: (i["sort_order"], i["url"])):
        tags.append([
            "image", img["url"], img.get("dimensions") or "",
        ])
    for spec in sorted(specs, key=lambda s: (s["key"], s["value"])):
        tags.append(["spec", spec["key"], spec["value"]])
    if product.get("weight_value") is not None and product.get("weight_unit"):
        tags.append([
            "weight",
            format(Decimal(str(product["weight_value"])).normalize(), "f"),
            product["weight_unit"],
        ])
    if product.get("dim_l") is not None and product.get("dim_unit"):
        dims = "x".join(
            format(Decimal(str(v)).normalize(), "f")
            for v in (product["dim_l"], product["dim_w"], product["dim_h"])
        )
        tags.append(["dim", dims, product["dim_unit"]])
    if product.get("location"):
        tags.append(["location", product["location"]])
    if product.get("geohash"):
        tags.append(["g", product["geohash"]])
    for category in sorted(categories):
        tags.append(["t", category])
    if product["product_type"] == "variation":
        tags.append([
            "a",
            f"30402:{pubkey}:{product['_parent_d_tag']}",
        ])
    for d_tag in sorted(member_collection_d_tags):
        tags.append(["a", f"30405:{pubkey}:{d_tag}"])
    for ref in sorted(
        shipping_refs, key=lambda r: (r["kind"], r["d_tag"])
    ):
        tag = [
            "shipping_option",
            f"{ref['kind']}:{pubkey}:{ref['d_tag']}",
        ]
        if ref.get("extra_cost_minor") is not None:
            tag.append(_decimal(ref["extra_cost_minor"], product.get("currency_decimals") or 0))
        tags.append(tag)
    tags.append(["status", product.get("nip99_status") or "active"])
    tags.extend(_nip32_tags(spec_revision))
    return {
        "kind": GAMMA_KIND_PRODUCT,
        "content": product.get("description_md") or "",
        "tags": tags,
    }


def collection_event(
    collection: dict,
    *,
    pubkey: str,
    spec_revision: str,
    member_d_tags: list[str],
    shipping_d_tags: list[str],
) -> dict:
    """kind 30405 — section 6.2. Caller guarantees ≥1 active member."""
    tags: list[list[str]] = [
        ["d", collection["d_tag"]],
        ["title", collection["title"] or ""],
    ]
    for d_tag in sorted(member_d_tags):
        tags.append(["a", f"30402:{pubkey}:{d_tag}"])
    if collection.get("image"):
        tags.append(["image", collection["image"]])
    if collection.get("description"):
        tags.append(["summary", collection["description"][:280]])
    if collection.get("location"):
        tags.append(["location", collection["location"]])
    if collection.get("geohash"):
        tags.append(["g", collection["geohash"]])
    for d_tag in sorted(shipping_d_tags):
        tags.append(["shipping_option", f"30406:{pubkey}:{d_tag}"])
    tags.extend(_nip32_tags(spec_revision))
    return {
        "kind": GAMMA_KIND_COLLECTION,
        "content": collection.get("description") or "",
        "tags": tags,
    }


def shipping_event(
    option: dict,
    *,
    pubkey: str,
    spec_revision: str,
) -> dict:
    """kind 30406 — section 6.3. Caller has run shipping validation."""
    decimals = option.get("currency_decimals")
    if decimals is None:
        decimals = default_currency_decimals(option.get("currency"))
    tags: list[list[str]] = [
        ["d", option["d_tag"]],
        ["title", option["title"] or ""],
    ]
    if option.get("base_price_minor") is not None and option.get("currency"):
        # §3.4 shipping prices use persisted currency precision; fallback
        # supports pre-m003 fixtures and projections.
        tags.append([
            "price",
            _decimal(option["base_price_minor"], decimals),
            option["currency"],
        ])
    countries = json.loads(option["countries"]) if option.get("countries") else []
    for country in sorted(countries):
        tags.append(["country", country])
    regions = json.loads(option["regions"]) if option.get("regions") else []
    for region in sorted(regions):
        tags.append(["region", region])
    tags.append(["service", option["service"]])
    if option.get("carrier"):
        tags.append(["carrier", option["carrier"]])
    if (
        option.get("duration_min") is not None
        and option.get("duration_max") is not None
        and option.get("duration_unit")
    ):
        tags.append([
            "duration",
            str(option["duration_min"]),
            str(option["duration_max"]),
            option["duration_unit"],
        ])
    if option.get("location"):
        tags.append(["location", option["location"]])
    if option.get("geohash"):
        tags.append(["g", option["geohash"]])
    for bound in ("min", "max"):
        weight = option.get(f"weight_{bound}")
        if weight is not None and option.get("weight_unit"):
            tags.append([
                f"weight-{bound}", format(Decimal(str(weight)).normalize(), "f"),
                option["weight_unit"],
            ])
        dimensions = [option.get(f"dim_{bound}_{axis}") for axis in ("l", "w", "h")]
        if all(value is not None for value in dimensions) and option.get("dim_unit"):
            tags.append([
                f"dim-{bound}",
                "x".join(format(Decimal(str(value)).normalize(), "f") for value in dimensions),
                option["dim_unit"],
            ])
    if option.get("price_weight_minor") is not None and option.get(
        "price_weight_unit"
    ):
        tags.append([
            "price-weight",
            _decimal(option["price_weight_minor"], decimals),
            option.get("currency") or "",
            option["price_weight_unit"],
        ])
    if option.get("price_volume_minor") is not None and option.get(
        "price_volume_unit"
    ):
        tags.append([
            "price-volume",
            _decimal(option["price_volume_minor"], decimals),
            option.get("currency") or "",
            option["price_volume_unit"],
        ])
    tags.extend(_nip32_tags(spec_revision))
    return {
        "kind": GAMMA_KIND_SHIPPING,
        "content": option.get("description") or "",
        "tags": tags,
    }


def merchant_profile_event(
    merchant: dict, *, pubkey: str, public_base_url: str = ""
) -> dict:
    """kind 0 — section 6.4. `manual` payment preference only; no
    ecash/lud16 advertising in v1. No NIP-32 labels on identity.

    MEDIA-07 emit side (D-04/D-07): a stored relative
    ``/images/infinitemarkets/`` picture/banner is absolutized with the
    operator-configured ``public_base_url`` at publish time so relays
    receive a fetchable https URL. Already-absolute values pass through
    byte-identical; an empty base never concatenates (defensive —
    ``_validate_profile`` requires https anyway)."""
    profile = json.loads(merchant["profile_json"]) if merchant.get(
        "profile_json"
    ) else {}
    content = {"name": merchant.get("display_name") or ""}
    content.update(profile)
    for key in ("picture", "banner"):
        value = content.get(key)
        if (
            isinstance(value, str)
            and value.startswith("/images/infinitemarkets/")
            and public_base_url
        ):
            content[key] = public_base_url + value
    return {
        "kind": GAMMA_KIND_PROFILE,
        "content": json.dumps(content, sort_keys=True, separators=(",", ":")),
        "tags": [["payment_preference", "manual"]],
    }


def handler_info_event(
    merchant: dict, *, pubkey: str, public_base_url: str
) -> dict:
    """kind 31990 — section 6.5 handler information."""
    content = {
        "name": "Infinitemarkets",
        "about": "Lightning + Nostr storefront checkout",
    }
    return {
        "kind": NIP89_KIND_HANDLER_INFO,
        "content": json.dumps(content, sort_keys=True, separators=(",", ":")),
        "tags": [
            ["d", merchant["recommended_app_d"] or "infinitemarkets"],
            ["k", str(GAMMA_KIND_PRODUCT)],
            ["web", f"{public_base_url}/infinitemarkets/p/<bech32>", "naddr"],
        ],
    }


def handler_recommendation_event(
    merchant: dict, *, pubkey: str, relay_hint: str = ""
) -> dict:
    """kind 31989 — section 6.5 recommendation. `d` is the SUPPORTED KIND
    ("30402"), not the app id — golden fixtures pin this distinction."""
    app_d = merchant["recommended_app_d"] or "infinitemarkets"
    return {
        "kind": NIP89_KIND_RECOMMENDATION,
        "content": "",
        "tags": [
            ["d", str(GAMMA_KIND_PRODUCT)],
            ["a", f"31990:{pubkey}:{app_d}", relay_hint, "web"],
        ],
    }


def _json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def nip15_product_id(product: dict, parent_d_tag: str | None = None) -> str:
    """Section 6.6 id resolution — persisted id wins; otherwise the
    preferred ``<parent_d>-<variation_d>`` composite, falling back to a
    deterministic ``v-<sha256[:32]>`` when the composite is too long."""
    if product.get("nip15_product_id"):
        return product["nip15_product_id"]
    if product["product_type"] == "variation" and parent_d_tag:
        candidate = f"{parent_d_tag}-{product['d_tag']}"
        if len(candidate) <= NIP15_ID_MAX:
            return candidate
        import hashlib

        digest = hashlib.sha256(
            len(parent_d_tag).to_bytes(2, "big")
            + parent_d_tag.encode()
            + product["d_tag"].encode()
        ).hexdigest()
        return f"v-{digest[:32]}"
    return product["d_tag"]


def digital_zone() -> dict:
    """Deterministic zero-cost zone — NIP-15 orders must select a zone even
    for digital products (§6.6)."""
    return {
        "id": DIGITAL_ZONE_ID,
        "name": "Digital delivery",
        "cost_minor": 0,
        "currency_decimals": 0,
        "regions": [],
    }


def stall_event(
    catalog: dict,
    *,
    zones: list[dict],
) -> dict:
    """kind 30017 — one per catalog (§6.6). ``zones`` are pre-validated
    shipping projections: ``{id, name, cost_minor, currency_decimals,
    regions}`` — countries AND regions flatten into the zone's ``regions``
    array."""
    shipping = [
        {
            "id": z["id"],
            "name": z["name"],
            "cost": float(
                _decimal(z["cost_minor"], z.get("currency_decimals") or 0)
            ),
            "regions": sorted(z.get("regions") or []),
        }
        for z in sorted(zones, key=lambda z: z["id"])
    ]
    stall_d = catalog["nip15_stall_d"]
    content = {
        "id": stall_d,
        "name": catalog.get("name") or "",
        "description": catalog.get("description") or "",
        "currency": catalog.get("default_currency") or "",
        "shipping": shipping,
    }
    return {
        "kind": NIP15_KIND_STALL,
        "content": _json(content),
        "tags": [["d", stall_d]],
    }


def nip15_product_event(
    product: dict,
    *,
    stall_d: str,
    stall_currency: str,
    parent_d_tag: str | None = None,
    images: list[dict] | None = None,
    specs: list[dict] | None = None,
    shipping_surcharges: list[dict] | None = None,
) -> dict:
    """kind 30018 — §6.6. Currency mismatches are preview/publish errors,
    never converted. ``hidden``/``pre-order`` project as ``quantity: 0``."""
    currency = product.get("currency") or stall_currency
    if currency != stall_currency:
        raise CompatibilityError(
            f"product currency {currency} != stall currency {stall_currency}"
        )
    product_id = nip15_product_id(product, parent_d_tag)
    decimals = product.get("currency_decimals") or 0

    if product.get("visibility") in ("hidden", "pre-order"):
        quantity: int | None = 0
    elif product.get("stock_on_hand") is None:
        quantity = None
    else:
        quantity = max(
            0, product["stock_on_hand"] - (product.get("stock_reserved") or 0)
        )

    if product.get("format") == "digital":
        shipping = [{"id": DIGITAL_ZONE_ID, "cost": 0}]
    else:
        shipping = [
            {"id": s["d_tag"], "cost": float(
                _decimal(
                    s["extra_cost_minor"] or 0,
                    s.get("currency_decimals") or decimals,
                )
            )}
            for s in sorted(
                shipping_surcharges or [], key=lambda s: s["d_tag"]
            )
        ]

    content = {
        "id": product_id,
        "stall_id": stall_d,
        "name": product.get("title") or "",
        "description": product.get("description_md") or "",
        "images": sorted(i["url"] for i in images or []),
        "currency": currency,
        "price": float(_decimal(product.get("amount_minor") or 0, decimals)),
        "quantity": quantity,
        "specs": sorted(
            [[s["key"], s["value"]] for s in specs or []]
        ),
        "shipping": shipping,
    }
    return {
        "kind": NIP15_KIND_PRODUCT,
        "content": _json(content),
        "tags": [["d", product_id]],
    }


def inbox_profile_address(pubkey: str) -> str:
    """The protocol address of a kind-10050 profile: ``10050:<pk>:`` — the
    empty d-tag marks it non-addressable replaceable (§4.13)."""
    return f"{GAMMA_KIND_INBOX_RELAYS}:{pubkey}:"


def build_kind10050(merchant_pubkey: str, relay_urls: list[str]) -> dict:
    """kind 10050 — NIP-17 inbox relay list (§9.3, D-16).

    Empty content, one ``["relay", <url>]`` tag per advertised inbox relay
    (1–3, normalized through the §9.5 target validator). Identical inputs
    produce byte-identical output — tags keep caller order after
    normalization + dedupe. The advertisement is public: a >3 set or any
    non-``wss://`` target raises instead of emitting a profile other
    clients could not trust.
    """
    from ..security import unprocessable
    from .transport import validate_relay_target

    if not merchant_pubkey:
        raise unprocessable(
            "invalid-relay", "kind 10050 requires the merchant pubkey"
        )
    normalized: list[str] = []
    for raw in relay_urls:
        url = validate_relay_target(raw)
        if url not in normalized:
            normalized.append(url)
    if not 1 <= len(normalized) <= 3:
        raise unprocessable(
            "invalid-relay",
            "kind 10050 advertises between 1 and 3 inbox relays",
        )
    return {
        "kind": GAMMA_KIND_INBOX_RELAYS,
        "content": "",
        "tags": [["relay", url] for url in normalized],
    }


def tombstone_intent(
    *, pubkey: str, kind: int, d_tag: str, reason: str = "deleted"
) -> dict:
    """kind 5 descriptor — section 6.7. The outbox stores this as the
    publish descriptor; the worker builds the signed event."""
    return {
        "kind": GAMMA_KIND_TOMBSTONE,
        "content": reason,
        "tags": [
            ["a", f"{kind}:{pubkey}:{d_tag}"],
            ["k", str(kind)],
        ],
    }
