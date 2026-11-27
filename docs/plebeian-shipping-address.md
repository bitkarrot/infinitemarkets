# Plebeian shipping-address alignment — discussion summary

## The issue

Plebeian sends the buyer's shipping address as free-form plain text in the
`address` tag of the kind-16 type-1 order message (a newline-joined
human-readable string). A merchant cannot machine-read the destination, so
the address cannot be validated against the referenced shipping option's
declared coverage.

## What the spec says today

The Open Markets specification
(`OpenMarketsFoundation/specification`, kind-16 type-1 "Order Creation")
defines:

- `shipping`: reference to the shipping option — `"30406:<pubkey>:<d-tag>"`
- `address`: "Shipping address details" — shown as `["address", "<shipping-address>"]`

The spec does **not** constrain the address format — it is an opaque string.
Plebeian's plain-text body is technically spec-conformant, which is exactly
the gap worth raising: the spec models structured coverage on kind-30406
(`country`/`region` ISO code constraints) but leaves the order-side address
unstructured, so coverage validation is impossible.

## What infinitemarkets does with it

`infinitemarkets/services/order_messages.py` already accepts all three
shapes:

1. Separate `country` / `region` tags on the order message.
2. A JSON object in `address` — parsed and merged with the tag fields
   (`{"country": "US", "region": "US-CA", "street": ..., ...}`).
3. Anything else → `{"_opaque": raw}` marker.

For physical products, `_resolve_shipping` (checkout.py) requires
`address.country` (ISO 3166-1 alpha-2) and an in-country `region`
(ISO 3166-2), then checks the destination against the 30406 option's
`country`/`region` lists. An `_opaque` address cannot be validated, so the
physical order takes the documented reject-before-reservation path. Digital
orders are unaffected — Plebeian buyers can only complete digital purchases
today.

## Discussion point: the spec needs the change

Plebeian is not violating the spec — the spec under-specifies `address`.
So the primary ask goes **to the specification repo**: define a normative
address format for kind-16 type-1 orders so clients interoperate instead
of each merchant parsing free text. Once the format is specified, the ask
to Plebeian is simply "align with the updated spec."

Proposed format for the spec update (both shapes worth offering — the
first is richer, the second is the minimal client-side change):

- **Option A (preferred):** `address` carries a JSON object with at minimum
  `country` (ISO 3166-1 alpha-2) and `region` (ISO 3166-2 where required),
  plus free-form `street`/`city`/`postal_code`/`name` fields.

  Example `address` tag value:

  ```json
  {
    "name": "Alice Buyer",
    "street": "123 Maple Avenue, Apt 4",
    "city": "Portland",
    "region": "US-OR",
    "postal_code": "97205",
    "country": "US",
    "phone": "+1-555-0123",
    "instructions": "Leave at side door"
  }
  ```

  Only `country` and `region` are semantically load-bearing for coverage
  validation; the remaining fields are free-form display/delivery text.

- **Option B (minimal):** add `country` and `region` sibling tags alongside
  the existing free-text `address` — keeps the human-readable string for
  display while making the destination machine-readable.

Whatever the spec lands on, infinitemarkets already ingests all three
shapes (JSON object, sibling tags, opaque fallback), so no client-side
change is needed on our end to accept a conformant Plebeian order.

## Compatibility notes

- No regression risk for us either way — all three input shapes are already
  handled; a structured address simply upgrades Plebeian physical orders
  from "rejected" to "validated and accepted".
- If Plebeian prefers display-first, it can keep sending the human-readable
  `address` string *and* add `country`/`region` tags; we merge them.
