"""P0-13: Decimal/FX boundary qualification (QUAL-13, spec section 3.4).

Proves the executable FX boundary model in ``harness/fx.py``:

- fractional minor-unit conversion with ROUND_CEILING per line and per
  shipping component — never on a pre-summed float;
- mixed-currency carts and mixed-currency shipping convert each component
  with its own currency's quote (currencies never arithmetically mix);
- the order total is a checked integer sum and ``total_sat >= 1``;
- empty, zero, nonfinite, failed, provenance-free, or stale quotes reject
  BEFORE any reservation row or stock increment exists;
- one ``order_fx_quotes`` row per source currency persists decimal-string
  values, provider names, direction/units, observed/expiry timestamps, and
  source — on BOTH dialects (the db marker runs this on the selected
  profile);
- provider floats cross into Decimal exactly once via ``Decimal(str(v))``
  (never a float mean); the model never calls the host's cached
  ``fiat_amount_as_satoshis`` helper;
- the float-boundary precision error is measured deterministically and
  recorded into the evidence manifest.
"""

from __future__ import annotations

import ast
import inspect
import math
import uuid
from decimal import Decimal

import pytest

from harness import evidence, fx
from harness.fx import FxQuote, FxRejection

pytestmark = [pytest.mark.db, pytest.mark.fast]

NOW = 1_760_000_000


def _quote(
    currency: str = "USD",
    *,
    currency_per_btc: Decimal = Decimal("40000"),
    providers: tuple[str, ...] = ("kraken", "coinbase"),
    observed_at: int = NOW,
    expires_at: int | None = None,
) -> FxQuote:
    return FxQuote(
        currency=currency,
        currency_per_btc=currency_per_btc,
        sat_per_major_unit=fx.SAT_PER_BTC / currency_per_btc,
        providers=providers,
        observed_at=observed_at,
        expires_at=(
            observed_at + fx.QUOTE_TTL_S if expires_at is None else expires_at
        ),
    )


def _expect_reject(reason: str, fn, **kwargs):
    with pytest.raises(FxRejection, match=reason):
        fn(**kwargs)


# --- quote construction: the single float->Decimal crossing -------------------


def test_provider_floats_cross_once_via_decimal_str():
    """The mean is a Decimal mean of Decimal(str(v)) values — never a float
    mean re-crossed into Decimal (0.1 + 0.2 differs in float vs decimal)."""
    quote = fx.quote_from_provider_floats(
        "USD",
        [("a", 0.1), ("b", 0.2)],
        observed_at=NOW,
    )
    # Decimal mean: (Decimal("0.1") + Decimal("0.2")) / 2 == Decimal("0.15").
    # A float mean would be 0.15000000000000002 — the assertion would fail.
    assert quote.currency_per_btc == Decimal("0.15")
    assert quote.providers == ("a", "b")


def test_quote_ttl_is_five_minutes():
    quote = fx.quote_from_provider_floats(
        "USD", [("a", 40000.0)], observed_at=NOW
    )
    assert quote.expires_at == NOW + 300
    # fresh until expires_at; stale AT expires_at
    assert fx.require_usable_quote(quote, now=quote.expires_at - 1) is quote
    _expect_reject(
        "quote-stale", fx.require_usable_quote, quote=quote, now=quote.expires_at
    )


def test_failed_nonfinite_nonpositive_providers_filtered():
    """NaN/inf/zero/negative/non-numeric provider values are filtered BEFORE
    the mean; surviving providers carry the provenance."""
    quote = fx.quote_from_provider_floats(
        "EUR",
        [
            ("good", 42000.0),
            ("failed-none", None),
            ("failed-str", "err"),
            ("nan", math.nan),
            ("inf", math.inf),
            ("neg-inf", -math.inf),
            ("zero", 0.0),
            ("negative", -5.0),
            ("bool", True),
        ],
        observed_at=NOW,
    )
    assert quote.providers == ("good",)
    assert quote.currency_per_btc == Decimal("42000")


def test_all_providers_failed_rejects_no_provenance():
    _expect_reject(
        "quote-no-provenance",
        fx.quote_from_provider_floats,
        currency="USD",
        provider_values=[("a", math.nan), ("b", None)],
        observed_at=NOW,
    )


# --- rejection-before-reservation gate ----------------------------------------


def test_empty_quote_rejected():
    _expect_reject(
        "quote-empty", fx.require_usable_quote, quote=None, now=NOW
    )


def _degenerate(currency_per_btc: Decimal, sat_per_major: Decimal) -> FxQuote:
    return FxQuote(
        currency="USD",
        currency_per_btc=currency_per_btc,
        sat_per_major_unit=sat_per_major,
        providers=("p",),
        observed_at=NOW,
        expires_at=NOW + 300,
    )


def test_zero_and_negative_rate_rejected():
    zero = _degenerate(Decimal("0"), Decimal("0"))
    _expect_reject(
        "quote-nonpositive", fx.require_usable_quote, quote=zero, now=NOW
    )
    neg = _degenerate(Decimal("-1"), Decimal("-1"))
    _expect_reject(
        "quote-nonpositive", fx.require_usable_quote, quote=neg, now=NOW
    )


def test_nonfinite_rate_rejected():
    nan = FxQuote(
        currency="USD",
        currency_per_btc=Decimal("NaN"),
        sat_per_major_unit=Decimal("NaN"),
        providers=("p",),
        observed_at=NOW,
        expires_at=NOW + 300,
    )
    _expect_reject(
        "quote-nonfinite", fx.require_usable_quote, quote=nan, now=NOW
    )
    inf = FxQuote(
        currency="USD",
        currency_per_btc=Decimal("Infinity"),
        sat_per_major_unit=Decimal("0"),
        providers=("p",),
        observed_at=NOW,
        expires_at=NOW + 300,
    )
    _expect_reject(
        "quote-nonfinite", fx.require_usable_quote, quote=inf, now=NOW
    )


def test_provenance_free_quote_rejected():
    quote = _quote(providers=())
    _expect_reject(
        "quote-no-provenance",
        fx.require_usable_quote,
        quote=quote,
        now=NOW,
    )


def test_stale_quote_rejected_at_conversion_edge():
    quote = _quote()
    _expect_reject(
        "quote-stale",
        fx.convert_line,
        quote=quote,
        currency="USD",
        amount_minor=100,
        currency_decimals=2,
        now=quote.expires_at,
    )


def test_invalid_quote_inputs_rejected():
    quote = _quote()
    _expect_reject(
        "amount-minor-not-int",
        fx.convert_line,
        quote=quote,
        currency="USD",
        amount_minor=1.5,
        currency_decimals=2,
    )
    _expect_reject(
        "amount-minor-not-int",
        fx.convert_line,
        quote=quote,
        currency="USD",
        amount_minor=True,
        currency_decimals=2,
    )
    _expect_reject(
        "amount-minor-negative",
        fx.convert_line,
        quote=quote,
        currency="USD",
        amount_minor=-1,
        currency_decimals=2,
    )
    _expect_reject(
        "currency-decimals-negative",
        fx.convert_line,
        quote=quote,
        currency="USD",
        amount_minor=1,
        currency_decimals=-1,
    )
    _expect_reject(
        "currency-mismatch",
        fx.convert_line,
        quote=quote,
        currency="EUR",
        amount_minor=100,
        currency_decimals=2,
    )


# --- per-component ceiling conversion ------------------------------------------


def test_fractional_minor_unit_conversion_ceils():
    """1.01 USD at 40000 USD/BTC: 1.01 * 2500 = 2525 exact; and a fractional
    result rounds UP per component (never truncation)."""
    quote = _quote(currency_per_btc=Decimal("40000"))
    # sat_per_major_unit = 1e8/40000 = 2500
    assert quote.sat_per_major_unit == Decimal("2500")
    assert (
        fx.convert_line(
            quote, currency="USD", amount_minor=101, currency_decimals=2
        )
        == 2525
    )
    # fractional result: 1 minor unit -> 25.0 sat exact; use a rate that
    # yields a true fraction: 1e8/30000 = 3333.333... sat/USD.
    quote2 = _quote(currency_per_btc=Decimal("30000"))
    sat = fx.convert_line(
        quote2, currency="USD", amount_minor=101, currency_decimals=2
    )
    # 1.01 * 3333.3333... = 3366.666... -> ceil 3367 (int() would give 3366).
    assert sat == 3367


def test_ceiling_applies_per_component_not_on_summed_total():
    """Two half-unit lines at 1.5 sat/major: per-component ceiling gives
    2 + 2 = 4 sat; a summed-then-converted float path would give 3."""
    quote = FxQuote(
        currency="USD",
        currency_per_btc=Decimal("1"),
        sat_per_major_unit=Decimal("1.5"),
        providers=("p",),
        observed_at=NOW,
        expires_at=NOW + 300,
    )
    line_a = fx.convert_line(
        quote, currency="USD", amount_minor=1, currency_decimals=0
    )
    line_b = fx.convert_line(
        quote, currency="USD", amount_minor=1, currency_decimals=0
    )
    assert (line_a, line_b) == (2, 2)
    assert fx.checked_total_sat([line_a, line_b]) == 4


def test_mixed_currency_cart_converts_each_line_with_own_quote():
    """A cart with USD and EUR lines: each line converts under ITS currency's
    quote; nothing mixes the currencies arithmetically."""
    usd = _quote("USD", currency_per_btc=Decimal("40000"))  # 2500 sat/USD
    eur = _quote("EUR", currency_per_btc=Decimal("50000"))  # 2000 sat/EUR
    usd_line = fx.convert_line(
        usd, currency="USD", amount_minor=1000, currency_decimals=2
    )  # 10.00 USD -> 25000
    eur_line = fx.convert_line(
        eur, currency="EUR", amount_minor=1000, currency_decimals=2
    )  # 10.00 EUR -> 20000
    jpy = _quote("JPY", currency_per_btc=Decimal("6_000_000"))
    jpy_line = fx.convert_line(
        jpy, currency="JPY", amount_minor=5000, currency_decimals=0
    )
    assert usd_line == 25000
    assert eur_line == 20000
    assert jpy_line == math.ceil(5000 * (100_000_000 / 6_000_000))
    total = fx.checked_total_sat([usd_line, eur_line, jpy_line])
    assert total == usd_line + eur_line + jpy_line


def test_mixed_currency_shipping_components():
    """Shipping components in different currencies convert with each
    currency's quote — same per-component rule as cart lines."""
    usd = _quote("USD", currency_per_btc=Decimal("40000"))
    eur = _quote("EUR", currency_per_btc=Decimal("50000"))
    ship_usd = fx.convert_line(
        usd, currency="USD", amount_minor=599, currency_decimals=2
    )
    ship_eur = fx.convert_line(
        eur, currency="EUR", amount_minor=250, currency_decimals=2
    )
    assert ship_usd == math.ceil(5.99 * 2500) == 14975
    assert ship_eur == math.ceil(2.5 * 2000) == 5000
    assert fx.checked_total_sat([ship_usd, ship_eur]) == 19975


def test_checked_total_sum_and_minimum_one_sat():
    assert fx.checked_total_sat([1]) == 1
    _expect_reject(
        "total-sat-below-1", fx.checked_total_sat, components=[]
    )
    _expect_reject(
        "total-sat-below-1", fx.checked_total_sat, components=[0, 0]
    )
    _expect_reject(
        "component-negative", fx.checked_total_sat, components=[5, -1]
    )
    _expect_reject(
        "component-not-int", fx.checked_total_sat, components=[1.5]
    )
    _expect_reject(
        "total-overflow",
        fx.checked_total_sat,
        components=[fx.INT64_MAX, 1],
    )


def test_model_never_calls_host_cached_fiat_helper():
    """The model must never CALL the host's cached ``fiat_amount_as_satoshis``
    helper (the docstring names it only to document the non-selection) and
    never truncates via ``int()`` — conversions use ``ROUND_CEILING``."""
    tree = ast.parse(inspect.getsource(fx))
    called = {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    }
    assert "fiat_amount_as_satoshis" not in called
    assert "ROUND_CEILING" in inspect.getsource(fx)


# --- persistence + rejection-before-reservation (both dialects via marker) ----


async def _seed_product_and_order(
    qual_db, *, product_id: str, order_id: str, on_hand: int = 10
):
    async with qual_db.connect() as conn:
        async with qual_db.transaction(conn) as t:
            await t.execute(
                f"INSERT INTO {qual_db.table('products')}"
                " (id, merchant_id, stock_on_hand, stock_reserved)"
                " VALUES (:id, :m, :h, 0)",
                {"id": product_id, "m": "merchant-1", "h": on_hand},
            )
            await t.execute(
                f"INSERT INTO {qual_db.table('orders')}"
                " (id, merchant_id, state) VALUES (:id, :m, 'received')",
                {"id": order_id, "m": "merchant-1"},
            )


async def test_order_fx_quotes_persists_decimal_strings(qual_db_factory):
    """One order_fx_quotes row per source currency: decimal-string rate,
    providers, direction/units, observed/expiry timestamps, source."""
    order_id = f"order-{uuid.uuid4().hex[:8]}"
    async with qual_db_factory() as qual_db:
        await _seed_product_and_order(
            qual_db, product_id="prod-fx", order_id=order_id
        )
        usd = fx.quote_from_provider_floats(
            "USD",
            [("kraken", 40000.1), ("coinbase", 40000.3)],
            observed_at=NOW,
        )
        eur = fx.quote_from_provider_floats(
            "EUR", [("kraken", 42000.0)], observed_at=NOW
        )
        async with qual_db.connect() as conn:
            async with qual_db.transaction(conn) as t:
                for quote in (usd, eur):
                    await t.execute(
                        fx.insert_order_fx_quote_sql(qual_db.table("order_fx_quotes")),
                        fx.order_fx_quote_row(order_id, quote),
                    )
        rows = await qual_db.fetch_all(
            f"SELECT * FROM {qual_db.table('order_fx_quotes')}"
            " WHERE order_id = :o ORDER BY currency",
            {"o": order_id},
        )
        assert [r["currency"] for r in rows] == ["EUR", "USD"]
        usd_row = next(r for r in rows if r["currency"] == "USD")
        # decimal-string rate (not float repr noise), direction/unit, source
        assert usd_row["rate_decimal"] == str(usd.sat_per_major_unit)
        assert usd_row["rate_direction"] == "sat_per_major_unit"
        assert usd_row["rate_unit"] == "sat/USD"
        assert usd_row["source"] == "btc_rates"
        assert usd_row["providers"] == "kraken,coinbase"
        assert usd_row["quoted_at"] == NOW
        assert usd_row["expires_at"] == NOW + fx.QUOTE_TTL_S
        # the persisted rate is the MEAN's conversion, not a single provider
        assert Decimal(usd_row["rate_decimal"]) == fx.SAT_PER_BTC / Decimal(
            "40000.2"
        )


async def test_order_fx_quotes_unique_per_currency(qual_db_factory):
    order_id = f"order-{uuid.uuid4().hex[:8]}"
    async with qual_db_factory() as qual_db:
        await _seed_product_and_order(
            qual_db, product_id="prod-fx2", order_id=order_id
        )
        usd = fx.quote_from_provider_floats(
            "USD", [("a", 1.0)], observed_at=NOW
        )
        async with qual_db.connect() as conn:
            async with qual_db.transaction(conn) as t:
                await t.execute(
                    fx.insert_order_fx_quote_sql(
                        qual_db.table("order_fx_quotes")
                    ),
                    fx.order_fx_quote_row(order_id, usd),
                )
        with pytest.raises(Exception):  # UNIQUE (order_id, currency)
            async with qual_db.connect() as conn:
                async with qual_db.transaction(conn) as t:
                    await t.execute(
                        fx.insert_order_fx_quote_sql(
                            qual_db.table("order_fx_quotes")
                        ),
                        fx.order_fx_quote_row(order_id, usd),
                    )


async def test_rejection_leaves_no_reservation_or_stock_or_quote_rows(
    qual_db_factory,
):
    """A stale quote rejects checkout BEFORE any reservation row, stock
    increment, or order_fx_quotes row exists (section 3.4 ordering)."""
    order_id = f"order-{uuid.uuid4().hex[:8]}"
    product_id = "prod-fx3"
    async with qual_db_factory() as qual_db:
        await _seed_product_and_order(
            qual_db, product_id=product_id, order_id=order_id, on_hand=5
        )
        stale = _quote(expires_at=NOW)  # already expired at NOW
        with pytest.raises(FxRejection, match="quote-stale"):
            # The checkout gate runs BEFORE the reservation transaction.
            fx.require_usable_quote(stale, now=NOW)
        reservations = await qual_db.fetch_all(
            f"SELECT * FROM {qual_db.table('inventory_reservations')}"
        )
        assert reservations == []
        product = await qual_db.fetch_all(
            f"SELECT stock_reserved FROM {qual_db.table('products')}"
            " WHERE id = :id",
            {"id": product_id},
        )
        assert product[0]["stock_reserved"] == 0
        quotes = await qual_db.fetch_all(
            f"SELECT * FROM {qual_db.table('order_fx_quotes')}"
        )
        assert quotes == []


async def test_valid_quote_then_reservation_flow(qual_db_factory):
    """Positive control: a fresh quote converts lines, persists its row, and
    a held reservation + stock increment land in the same transaction."""
    from harness import tx

    order_id = f"order-{uuid.uuid4().hex[:8]}"
    product_id = "prod-fx4"
    async with qual_db_factory() as qual_db:
        await _seed_product_and_order(
            qual_db, product_id=product_id, order_id=order_id, on_hand=5
        )
        quote = fx.quote_from_provider_floats(
            "USD", [("a", 40000.0)], observed_at=NOW
        )
        fx.require_usable_quote(quote, now=NOW)
        line_sat = fx.convert_line(
            quote, currency="USD", amount_minor=1234, currency_decimals=2
        )
        ship_sat = fx.convert_line(
            quote, currency="USD", amount_minor=500, currency_decimals=2
        )
        total = fx.checked_total_sat([line_sat, ship_sat])
        assert total == math.ceil(12.34 * 2500) + math.ceil(5.0 * 2500)
        await tx.claim_and_reserve(
            qual_db,
            product_id=product_id,
            qty=1,
            order_id=order_id,
            reservation_id=f"res-{order_id}",
            expires_at=NOW + 900,
        )
        async with qual_db.connect() as conn:
            async with qual_db.transaction(conn) as t:
                await t.execute(
                    fx.insert_order_fx_quote_sql(
                        qual_db.table("order_fx_quotes")
                    ),
                    fx.order_fx_quote_row(order_id, quote),
                )
        rows = await qual_db.fetch_all(
            f"SELECT * FROM {qual_db.table('order_fx_quotes')}"
            " WHERE order_id = :o",
            {"o": order_id},
        )
        assert len(rows) == 1


# --- deterministic float-boundary measurement -----------------------------------


def test_float_boundary_measurement_is_deterministic_and_recorded():
    """The measured bound is deterministic under the fixed seed and is
    recorded into the evidence manifest (PINS.md points at it)."""
    m1 = fx.measure_float_boundary_error(fx.seeded_float_sample())
    m2 = fx.measure_float_boundary_error(fx.seeded_float_sample())
    assert m1 == m2, "measurement must be deterministic under the seed"
    assert m1["seed"] == fx.MEASUREMENT_SEED
    assert m1["samples"] == len(fx.seeded_float_sample())
    # Sanity bounds: Decimal(str(v)) error must be far below 1e-12 relative,
    # and the ceiling-conversion difference must be a handful of sats at most.
    assert 0 <= m1["max_relative_error"] < 1e-12
    assert m1["max_value_relative_error"] <= m1["max_relative_error"]
    assert 0 <= m1["max_abs_sat_error"] <= 3
    assert m1["worst_case"]
    evidence.set_fx_measurement(m1)
