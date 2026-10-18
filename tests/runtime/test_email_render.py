"""Host-free MIME rendering and transport tests for the transactional email path."""

from __future__ import annotations

import email
import importlib
import inspect
import json
import smtplib
from email import policy
from email.utils import parsedate_to_datetime

import pytest

pytestmark = [pytest.mark.runtime, pytest.mark.fast]


def _email():
    return importlib.import_module("infinitemarkets.services.email")


def _view(**over):
    base = {
        "channel": "customer",
        "event_type": "confirmed",
        "display_name": "Email Shop",
        "state": "confirmed",
        "items": [
            {
                "title": "Printed zine",
                "quantity": 2,
                "unit_price_minor": 500,
                "currency": "USD",
                "currency_decimals": 2,
                "line_total_sat": 1200,
                "backordered_qty": 1,
            }
        ],
        "subtotal_sat": 1200,
        "shipping_sat": 0,
        "total_sat": 1200,
        "delivery": [{"title": "Digital edition", "content": "code-123"}],
        "status_link": "https://shop.example/infinitemarkets/order#sample-token",
        "theme": json.dumps({"preset": "warm-market"}),
    }
    base.update(over)
    return base


def _build(view=None, *, text=None, **over):
    view = view or _view()
    if text is None:
        if view.get("channel") == "account":
            text = (
                f"Use this link to sign in: {view['status_link']}\n"
                "The link expires in 15 minutes and works once.\n"
                "You requested a sign-in link."
            )
        elif view.get("test_send"):
            text = (
                "Sample email preview — not a real order.\n"
                "Sample item x1\nTotal: 1,000 sats\n"
                "This is a transactional order notification."
            )
        elif view.get("channel") == "customer":
            text = "Order confirmed.\nYou opted in to order emails."
            if view.get("status_link"):
                text += f"\nTo opt out: {view['status_link']}"
            else:
                text += "\nTo opt out, use the order page from your order."
        else:
            text = (
                "Order confirmed.\n"
                "This is a transactional order notification."
            )
    builder = getattr(_email(), "_build_message", None)
    assert callable(builder), (
        "email_queue messages need a pure extension-owned _build_message builder"
    )
    return builder(
        subject=f"{view.get('display_name') or 'Infinitemarkets'}: order confirmed",
        text=text,
        view=view,
        from_addr="shop@example.com",
        to_addr="buyer@example.com",
        **over,
    )


def _parts(message):
    plain = message.get_body(preferencelist=("plain",))
    html = message.get_body(preferencelist=("html",))
    return plain.get_content(), html.get_content()


def test_mime_tree_is_alternative_with_optional_related_logo():
    message = _build()
    assert message.get_content_type() == "multipart/alternative"
    assert [part.get_content_type() for part in message.iter_parts()] == [
        "text/plain",
        "text/html",
    ]
    text, html = _parts(message)
    assert "Order confirmed." in text
    assert "Email Shop" in html
    assert message.get_body(preferencelist=("plain",)).get_content_charset() == "utf-8"
    assert message.get_body(preferencelist=("html",)).get_content_charset() == "utf-8"
    assert message.get_body(preferencelist=("plain",))["Content-Transfer-Encoding"] == (
        "quoted-printable"
    )
    assert message.as_string().isascii()
    parsed = email.message_from_string(message.as_string(), policy=policy.default)
    assert parsed.get_content_type() == "multipart/alternative"

    with_logo = _build(logo=(b"\x89PNG\r\n\x1a\nsynthetic-logo", "png"))
    related = with_logo.get_payload()[1]
    assert related.get_content_type() == "multipart/related"
    assert [part.get_content_type() for part in related.iter_parts()] == [
        "text/html",
        "image/png",
    ]
    assert related.get_payload()[1]["Content-ID"] == "<logo@infinitemarkets>"
    assert "cid:logo@infinitemarkets" in related.get_payload()[0].get_content()
    jpeg = _build(logo=(b"\xff\xd8\xffsynthetic-logo", "jpeg"))
    assert jpeg.get_payload()[1].get_content_type() == "multipart/related"
    assert jpeg.get_payload()[1].get_payload()[1].get_content_type() == "image/jpeg"

    unusable = _build(logo=(b"not-an-image", "svg"))
    assert unusable.get_payload()[1].get_content_type() == "text/html"
    assert "cid:logo@infinitemarkets" not in unusable.get_payload()[1].get_content()


def test_unicode_parts_round_trip_as_ascii_quoted_printable():
    body = (
        "Order confirmed — café and 🥐.\n"
        "You opted in to order emails.\n"
        "To opt out, use the order page from your order."
    )
    message = _build(text=body)
    assert message.as_string().isascii()
    parsed = email.message_from_string(message.as_string(), policy=policy.default)
    plain = parsed.get_body(preferencelist=("plain",))
    html_part = parsed.get_body(preferencelist=("html",))
    assert plain["Content-Transfer-Encoding"] == "quoted-printable"
    assert html_part["Content-Transfer-Encoding"] == "quoted-printable"
    assert plain.get_content().rstrip("\n") == body
    assert "Email Shop" in html_part.get_content()


async def test_smtp_send_mirrors_host_and_propagates_errors(monkeypatch):
    from lnbits.settings import settings as host_settings

    email_service = _email()
    monkeypatch.setattr(host_settings, "lnbits_email_notifications_server", "smtp.example")
    monkeypatch.setattr(host_settings, "lnbits_email_notifications_port", 587)
    monkeypatch.setattr(host_settings, "lnbits_email_notifications_email", "shop@example.com")
    monkeypatch.setattr(host_settings, "lnbits_email_notifications_username", "")
    monkeypatch.setattr(host_settings, "lnbits_email_notifications_password", "secret")

    calls = []

    class FakeSMTP:
        def __init__(self, server, port, *, timeout):
            calls.append(("connect", server, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            calls.append(("starttls",))

        def login(self, username, password):
            calls.append(("login", username, password))

        def sendmail(self, from_addr, recipients, wire):
            calls.append(("sendmail", from_addr, recipients, wire))

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    message = _build()
    assert await email_service._smtp_send(
        message, to="buyer@example.com", timeout=12.75
    )
    assert calls[:3] == [
        ("connect", "smtp.example", 587, 12.75),
        ("starttls",),
        ("login", "shop@example.com", "secret"),
    ]
    assert calls[3][0:3] == (
        "sendmail",
        "shop@example.com",
        ["buyer@example.com"],
    )
    assert calls[3][3].isascii()

    class FailingSMTP(FakeSMTP):
        def sendmail(self, *_args):
            raise RuntimeError("private transport detail")

    monkeypatch.setattr(smtplib, "SMTP", FailingSMTP)
    with pytest.raises(RuntimeError, match="private transport detail"):
        await email_service._smtp_send(
            message, to="buyer@example.com", timeout=5.5
        )


def test_header_safety_and_deliverability_headers():
    hostile_name = 'Märkét, "shop"\r\n\u202e'
    message = _build(_view(display_name=hostile_name))
    assert "\r" not in str(message["From"])
    assert "\n" not in str(message["From"])
    assert "\u202e" not in str(message["From"])
    assert message["From"].addresses[0].display_name == 'Märkét, "shop"'
    assert parsedate_to_datetime(message["Date"]) is not None
    assert message["Message-ID"].endswith("@example.com>")
    assert message["Auto-Submitted"] == "auto-generated"
    assert "Reply-To" not in message
    assert "List-Unsubscribe" not in message
    assert "To" not in message
    assert message.as_string().isascii()
    empty_name = _build(_view(display_name="\u202e\r\n"))
    assert str(empty_name["From"]) == "shop@example.com"
    assert _email()._subject({"display_name": "\u202e\r\n"}, "confirmed") == (
        "Infinitemarkets: order confirmed"
    )


def test_plain_event_label_does_not_repeat_order():
    email_service = _email()
    body = email_service._render_body(
        {"event_type": "confirmed"},
        {"state": "confirmed", "total_sat": 1200},
        [],
        {},
        None,
        [],
    )
    assert body.startswith("Order confirmed.")
    assert "Order order confirmed." not in body


def test_sections_show_real_order_values_and_live_only_cta():
    view = _view(theme=json.dumps({
        "preset": "warm-market",
        "brand": {"accent": "#777777"},
    }))
    message = _build(view)
    text, rendered = _parts(message)
    assert 'width="600"' in rendered
    assert "Email Shop" in rendered
    assert "Order confirmed" in rendered
    assert "Printed zine" in rendered
    assert "2" in rendered
    assert "5.00 USD" in rendered
    assert "1,200 sats" in rendered
    assert "Subtotal" in rendered and "Shipping" in rendered and "Total" in rendered
    assert "Backordered" in rendered
    assert "code-123" in rendered
    assert 'href="https://shop.example/infinitemarkets/order#sample-token"' in rendered
    assert "color:#000000" in rendered
    assert "<style" not in rendered.lower()
    assert "https://" not in rendered.replace("https://shop.example", "")
    assert "You opted in to order emails." in text
    from infinitemarkets.services.themes import contrast_ratio

    assert contrast_ratio("#000000", "#777777") >= 4.5
    default_html = _parts(_build(_view(theme=None)))[1]
    assert "border-top:3px solid #d69a3a" in default_html

    dead = _build(_view(status_link=None))
    _text, dead_html = _parts(dead)
    assert "<a " not in dead_html
    assert "sample-token" not in dead_html

    merchant = _build(_view(channel="merchant", delivery=[]))
    _merchant_text, merchant_html = _parts(merchant)
    assert "code-123" not in merchant_html
    assert "code-123" not in _merchant_text


def test_sections_keep_adjacent_equal_items_and_render_zero_item_order_totals():
    first = {
        "title": "Equal-priced item",
        "quantity": 2,
        "unit_price_minor": 500,
        "currency": "SAT",
        "currency_decimals": 0,
        "line_total_sat": 1000,
        "backordered_qty": 0,
    }
    second = {**first}
    adjacent = _build(_view(items=[first, second], delivery=[]))
    _text, adjacent_html = _parts(adjacent)
    assert adjacent_html.count("Equal-priced item") == 2
    assert adjacent_html.count("1,000 sats") >= 4

    empty_order = _build(_view(
        items=[],
        subtotal_sat=0,
        shipping_sat=0,
        total_sat=1250,
        delivery=[],
        status_link=None,
    ))
    _text, empty_html = _parts(empty_order)
    assert "No items in this order." in empty_html
    assert "Subtotal" in empty_html and "0 sats" in empty_html
    assert "Shipping" in empty_html and "0 sats" in empty_html
    assert "Total" in empty_html and "1,250 sats" in empty_html
    assert "<a " not in empty_html


def test_sections_show_em_dash_for_nullable_line_and_order_money():
    nullable_item = {
        "title": "Unpriced item",
        "quantity": 1,
        "unit_price_minor": None,
        "currency": "SAT",
        "currency_decimals": 0,
        "line_total_sat": None,
        "backordered_qty": 0,
    }
    message = _build(_view(
        items=[nullable_item],
        subtotal_sat=None,
        shipping_sat=None,
        total_sat=None,
        delivery=[],
        status_link=None,
    ))
    _text, rendered = _parts(message)
    assert "Unpriced item" in rendered
    assert "Subtotal" in rendered
    assert "Shipping" in rendered
    assert "Total" in rendered
    assert rendered.count("—") >= 5


async def test_sections_hide_dead_status_links_and_gate_delivery_exactly():
    from infinitemarkets import crypto
    from infinitemarkets import settings as extension_settings

    service = _email()
    now = 1_800_000_000
    key = bytes([7]) * 32
    settings = extension_settings.ExtSettings(
        master_keys={"v1": key},
        active_key_version="v1",
        privacy_key=bytes([9]) * 32,
        public_base_url="https://shop.example",
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(service, "_now", lambda: now)
    try:
        live_token = "live-fragment-token"
        live_copy = crypto.encrypt(
            live_token.encode(),
            key,
            record_id="order-1",
            table="orders",
            column="public_token_enc",
            key_version="v1",
        )
        live_order = {
            "id": "order-1",
            "public_token_enc": live_copy,
            "public_token_expires_at": now + 60,
        }
        live_link = await service._status_link(live_order, settings)
        assert live_link == (
            "https://shop.example/infinitemarkets/order#live-fragment-token"
        )
        live_html = service._render_html(_view(
            status_link=live_link,
            delivery=[{"title": "Digital edition", "content": "delivery-secret"}],
        ))
        assert 'href="https://shop.example/infinitemarkets/order#live-fragment-token"' in (
            live_html
        )
        assert "delivery-secret" in live_html

        expired_order = {
            **live_order,
            "public_token_expires_at": now,
        }
        corrupt_copy = crypto.encrypt(
            b"wrong-associated-data",
            key,
            record_id="another-order",
            table="orders",
            column="public_token_enc",
            key_version="v1",
        )
        dead_orders = (
            expired_order,
            {**live_order, "public_token_enc": corrupt_copy},
            {**live_order, "public_token_enc": None},
        )
        for order in dead_orders:
            link = await service._status_link(order, settings)
            assert link is None
            dead_html = service._render_html(_view(
                status_link=link,
                delivery=[{"title": "Digital edition", "content": "delivery-secret"}],
            ))
            assert "<a " not in dead_html
            assert "To opt out:" in dead_html
            assert "delivery-secret" in dead_html

        for channel, event_type in (
            ("merchant", "confirmed"),
            ("customer", "processing"),
        ):
            gated_html = service._render_html(_view(
                channel=channel,
                event_type=event_type,
                status_link=None,
                delivery=[{"title": "Digital edition", "content": "delivery-secret"}],
            ))
            assert "delivery-secret" not in gated_html
    finally:
        monkeypatch.undo()


def test_sections_use_fullmatch_accent_and_readable_cta_contrast():
    service = _email()
    from infinitemarkets.services.themes import contrast_ratio

    accepted = ("#777777", "#d69a3a", "#63d2ff", "#fce477", "#000000")
    for accent in accepted:
        resolved_accent, foreground = service._email_colors(
            json.dumps({"preset": "warm-market", "brand": {"accent": accent}})
        )
        assert resolved_accent == accent
        assert contrast_ratio(foreground, accent) >= 4.5
    assert service._email_colors(
        json.dumps({
            "preset": "warm-market",
            "brand": {"accent": "#777777"},
        })
    ) == ("#777777", "#000000")
    assert contrast_ratio("#ffffff", "#777777") < 4.5
    assert contrast_ratio("#111111", "#777777") < 4.5
    assert contrast_ratio("#000000", "#777777") >= 4.5

    for invalid in ("#123456\n", '#fff";background:url(https://evil.invalid)'):
        view = _view(theme=json.dumps({
            "preset": "warm-market",
            "brand": {"accent": invalid},
        }))
        rendered = _parts(_build(view))[1]
        assert "border-top:3px solid #d69a3a" in rendered
        assert "evil.invalid" not in rendered
        assert "background:url" not in rendered


def test_escaping_covers_text_attributes_delivery_and_css():
    hostile = "<script>alert(\"x\")</script> \"'&"
    view = _view(
        display_name=hostile,
        items=[{
            "title": hostile,
            "quantity": 1,
            "unit_price_minor": 1,
            "currency": "USD",
            "currency_decimals": 2,
            "line_total_sat": 1,
            "backordered_qty": 0,
        }],
        delivery=[{"title": hostile, "content": hostile}],
        status_link='https://shop.example/order?x="&y=1#bearer',
        theme=json.dumps({
            "preset": "warm-market",
            "brand": {"accent": '#ffffff";background:url(https://evil.invalid)'},
        }),
    )
    message = _build(
        view,
        text=(
            f"Order confirmed.\n{hostile}\nYou opted in to order emails.\n"
            f"To opt out: {view['status_link']}"
        ),
    )
    text, rendered = _parts(message)
    assert hostile not in rendered
    assert "&lt;script&gt;" in rendered
    assert "&quot;" in rendered
    assert "&#x27;" in rendered or "&#39;" in rendered
    assert "bearer" in rendered
    assert "background:url" not in rendered
    assert "evil.invalid" not in rendered
    assert hostile in text
    source = inspect.getsource(_email()._render_html)
    assert "|safe" not in source
    assert "Markup(" not in source
    assert "{% autoescape false %}" not in source


def test_footers_cover_customer_account_merchant_and_test_in_both_parts():
    customer = _build(_view())
    customer_text, customer_html = _parts(customer)
    for content in (customer_text, customer_html):
        assert "You opted in to order emails." in content
        assert "To opt out" in content
        assert "sample-token" in content

    dead_customer = _build(_view(status_link=None))
    dead_text, dead_html = _parts(dead_customer)
    for content in (dead_text, dead_html):
        assert "You opted in to order emails." in content
        assert "To opt out" in content
        assert "sample-token" not in content
    assert "<a " not in dead_html

    account = _build(_view(
        channel="account",
        event_type="signin_link",
        items=[],
        subtotal_sat=None,
        shipping_sat=None,
        total_sat=None,
        delivery=[],
        status_link="https://shop.example/auth/email?shop=pubkey#signin-token",
    ))
    account_text, account_html = _parts(account)
    for content in (account_text, account_html):
        assert "You requested a sign-in link." in content
        assert "signin-token" in content
    assert "Your sign-in link" in account_html
    assert "Printed zine" not in account_html
    assert "Subtotal" not in account_html

    merchant = _build(_view(channel="merchant", delivery=[]))
    merchant_text, merchant_html = _parts(merchant)
    for content in (merchant_text, merchant_html):
        assert content.count("This is a transactional order notification.") == 1
        assert "To opt out" not in content

    test_send = _build(_view(
        channel="merchant",
        event_type="order_received",
        items=[],
        subtotal_sat=None,
        shipping_sat=None,
        total_sat=None,
        delivery=[],
        status_link=None,
        test_send=True,
    ))
    test_text, test_html = _parts(test_send)
    for content in (test_text, test_html):
        assert "Sample email preview — not a real order." in content
        assert "Sample item" in content
        assert "1,000 sats" in content
        assert "This is a transactional order notification." in content
