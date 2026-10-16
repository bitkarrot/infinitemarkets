"""Route-boundary security — spec section 5.1/5.7/9.5/14.

The host has no CSRF middleware and ships permissive CORS, so the extension
owns origin enforcement at the route boundary:

- Every admin mutation rejects user-id-only authentication (§5.1).
- Bearer ``Authorization`` auth passes without an Origin requirement.
- Cookie auth requires exact ``Origin == INFINITEMARKETS_PUBLIC_BASE_URL``
  (missing/``null`` origins fail) plus a per-session double-submit CSRF
  token (``gm_csrf`` cookie == ``X-CSRF-Token`` header).
- All errors are RFC 9457 problem details (``urn:infinitemarkets:*``).

Also home of the §9.5 relay URL validator and the §5 audit-capture posture
check (OQ3).
"""

from __future__ import annotations

import hmac
import ipaddress
import re
import secrets
import unicodedata
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse
from lnbits.settings import settings as host_settings

from .settings import ext_settings

CSRF_COOKIE = "gm_csrf"
CSRF_HEADER = "x-csrf-token"
IDEMPOTENCY_HEADER = "idempotency-key"

_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9_-]{1,255}$")

PROBLEM_BASE = "urn:infinitemarkets:"


class ProblemError(Exception):
    """RFC 9457 carrier — the route boundary renders problem+json."""

    def __init__(self, status: int, code: str, title: str, detail: str = ""):
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        super().__init__(f"{code}: {title}")


def problem(status: int, code: str, title: str, detail: str = "") -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"{PROBLEM_BASE}{code}",
            "title": title,
            "status": status,
            "detail": detail,
        },
    )


def problem_for(exc: ProblemError) -> JSONResponse:
    return problem(exc.status, exc.code, exc.title, exc.detail)


def config_problem(exc: Exception) -> JSONResponse:
    """Render a host-configuration failure (SettingsError) as problem+json.

    ``SettingsError`` messages name the missing/malformed
    ``INFINITEMARKETS_*`` variable but never echo values, so the detail is
    safe to surface — and surfacing it is the point: without this the
    admin UI only shows a bare 500 and operators cannot tell the
    extension needs host-level env configuration plus a restart.
    """
    return problem(
        500,
        "extension-config",
        "Extension not configured",
        f"{exc} Set the variable in the LNbits host environment "
        "(its .env, systemd unit, or container env) and restart LNbits.",
    )


def unauthorized(detail: str = "authentication required") -> ProblemError:
    return ProblemError(401, "unauthorized", "Unauthorized", detail)


def forbidden(detail: str = "not allowed") -> ProblemError:
    return ProblemError(403, "unauthorized", "Forbidden", detail)


def not_found(detail: str = "resource not found") -> ProblemError:
    return ProblemError(404, "unauthorized", "Not found", detail)


def conflict(code: str, title: str, detail: str = "") -> ProblemError:
    return ProblemError(409, code, title, detail)


def unprocessable(code: str, title: str, detail: str = "") -> ProblemError:
    return ProblemError(422, code, title, detail)


def rate_limited(detail: str = "rate limit exceeded") -> ProblemError:
    return ProblemError(429, "rate-limited", "Rate limited", detail)


# --- admin guard --------------------------------------------------------------

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _bearer_present(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    return auth.lower().startswith("bearer ") and len(auth) > 7


def _allowed_cookie_origins() -> set[str]:
    """Operator-declared origins allowed to submit cookie-authed
    mutations — never derived from the request's Host header:

    - ``INFINITEMARKETS_PUBLIC_BASE_URL`` (canonical storefront)
    - the host's ``nostr_absolute_request_urls`` — LNbits already treats
      this as the operator's trusted origin set for absolute requests;
      admins working on any of those hostnames are legitimate
    - ``INFINITEMARKETS_ADMIN_ORIGINS`` (explicit extra origins, e.g. an
      internal admin hostname)
    """
    allowed = {ext_settings().public_base_url}
    urls = getattr(host_settings, "nostr_absolute_request_urls", None) or []
    for u in urls:
        p = urlparse(str(u).strip().rstrip("/"))
        if p.scheme in {"http", "https"} and p.netloc:
            allowed.add(f"{p.scheme}://{p.netloc}")
    allowed.update(ext_settings().admin_origins)
    return allowed


def _user_id_only_auth(request: Request) -> bool:
    """True when the request carries no credential but relies on the host's
    optional ``usr``-only auth path (which we refuse for mutations)."""
    return not _bearer_present(request) and not request.cookies.get(
        "cookie_access_token"
    )


def enforce_mutation_security(request: Request) -> None:
    """Section-5.1 mutation rules — invoked INSIDE the route boundary so
    rejections render as problem+json (dependency-raised errors would
    bypass it).

    Bearer auth is sufficient; cookie auth additionally requires exact
    canonical Origin and the double-submit CSRF token; user-id-only auth
    is rejected outright.
    """
    if request.method in _SAFE_METHODS:
        return

    # §14: admin mutations accept an Idempotency-Key header (clients SHOULD
    # send one). Shape-validate only — the idempotency_records claim path
    # lands with m002 in plan 02-03.
    key = request.headers.get(IDEMPOTENCY_HEADER)
    if key is not None and not _IDEMPOTENCY_RE.match(key):
        raise unprocessable(
            "invalid-idempotency-key", "Invalid Idempotency-Key header"
        )

    # A cookie credential present at all means the browser-cookie rules
    # apply — even if an Authorization header is also set (an attacker page
    # could otherwise smuggle a forged bearer to skip the Origin check).
    if request.cookies.get("cookie_access_token"):
        origin = request.headers.get("origin")
        if (
            not origin
            or origin.lower() == "null"
            or origin not in _allowed_cookie_origins()
        ):
            raise forbidden("cross-origin cookie mutation rejected")

        # Double-submit CSRF: per-session cookie == header.
        cookie = request.cookies.get(CSRF_COOKIE)
        header = request.headers.get(CSRF_HEADER)
        if (
            not cookie
            or not header
            or len(cookie) < 32
            or not hmac.compare_digest(cookie, header)
        ):
            raise forbidden("missing or invalid CSRF token")
        return

    if _bearer_present(request):
        return

    # Neither bearer nor cookie: only the host's optional usr-only path
    # remains — refused for mutations (§5.1).
    raise forbidden("user-id-only authentication is not accepted")


def issue_csrf_cookie(response, request: Request) -> None:
    """Set the per-session double-submit cookie if absent.

    Called by the admin index route; ``SameSite=Strict`` + ``Secure`` keep
    it inside the canonical origin. Not HttpOnly — the admin JS must echo it
    in ``X-CSRF-Token`` (double-submit contract).
    """
    if request.cookies.get(CSRF_COOKIE):
        return
    response.set_cookie(
        CSRF_COOKIE,
        secrets.token_urlsafe(32),
        samesite="strict",
        secure=True,
        httponly=False,
        path="/infinitemarkets",
    )


# --- relay URL validation (section 9.5) ----------------------------------------

_CONFUSABLE_SCRIPT_RUN = re.compile(r"^[a-z0-9.-]+$")


def validate_relay_url(raw: str) -> str:
    """Validate + normalize a relay URL per section 9.5.

    Rejects: non-wss schemes, raw-IP hosts, userinfo, fragments,
    loopback/private/link-local/multicast/reserved/metadata ranges
    (IPv4 + IPv6 literals — also via numeric-embed hostnames), and
    Unicode-confusable hostnames. Returns the normalized URL.
    """
    if not raw or len(raw) > 512 or raw != raw.strip():
        raise unprocessable("invalid-relay", "Invalid relay URL")
    parsed = urlparse(raw)
    if parsed.scheme != "wss":
        raise unprocessable(
            "invalid-relay", "Relay URLs must use the wss:// scheme"
        )
    if parsed.username or parsed.password:
        raise unprocessable(
            "invalid-relay", "Relay URLs must not carry userinfo"
        )
    if parsed.fragment:
        raise unprocessable(
            "invalid-relay", "Relay URLs must not carry fragments"
        )
    host = parsed.hostname
    if not host:
        raise unprocessable("invalid-relay", "Relay URL has no host")

    # Raw IP literal hosts are rejected outright (section 9.5).
    try:
        ipaddress.ip_address(host.strip("[]"))
        raise unprocessable(
            "invalid-relay",
            "Raw IP relay hosts are not accepted",
        ) from None
    except ValueError:
        pass

    # Unicode-confusable hostnames: require pure ASCII after IDNA
    # normalization; reject mixed-script lookalikes by construction.
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError) as exc:
        raise unprocessable(
            "invalid-relay", "Relay hostname is not valid IDNA"
        ) from exc
    if not _CONFUSABLE_SCRIPT_RUN.match(ascii_host):
        raise unprocessable(
            "invalid-relay", "Relay hostname contains disallowed characters"
        )
    if unicodedata.normalize("NFC", host) != host:
        raise unprocessable(
            "invalid-relay", "Relay hostname is not in NFC form"
        )
    # Reject obvious lookalikes where IDNA produced an xn-- punycode label
    # for a host that also parses as plain ASCII — a confusable vector.
    if "xn--" in ascii_host:
        raise unprocessable(
            "invalid-relay",
            "Punycode (confusable) relay hostnames are not accepted",
        )

    # Internal-surface hostnames: single-label names and well-known private
    # suffixes can resolve to loopback/link-local at connect time — rejected
    # here; the relay worker re-validates resolution in 02-02.
    labels = ascii_host.rstrip(".").split(".")
    _INTERNAL_TLDS = {
        "localhost", "local", "internal", "lan", "home", "corp",
        "localdomain", "intranet",
    }
    if len(labels) < 2 or labels[-1] in _INTERNAL_TLDS:
        raise unprocessable(
            "invalid-relay",
            "Internal or single-label relay hostnames are not accepted",
        )

    normalized = f"wss://{ascii_host}"
    if parsed.port:
        normalized += f":{parsed.port}"
    if parsed.path and parsed.path != "/":
        normalized += parsed.path
    return normalized


# --- DNS egress checks (section 9.5, D-30) ------------------------------------

#: The link-local cloud-metadata address is blocked explicitly even where
#: a stub resolver would still route it.
_METADATA_IP = ipaddress.ip_address("169.254.169.254")

_DNS_CACHE_TTL_S = 60
_dns_cache: dict[str, tuple[float, list]] = {}


def is_public_ip(ip) -> bool:
    """Routable public space only — loopback/private/link-local/multicast/
    reserved/unspecified, the cloud-metadata literal, and every other
    non-global special-registry range (CGNAT 100.64/10, documentation
    prefixes, IETF assignments — ``is_global`` is the positive check) are
    egress-banned for IPv4 AND IPv6 answers alike."""
    if ip == _METADATA_IP:
        return False
    return ip.is_global and not (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def resolve_and_check_egress(host: str, port: int = 443) -> list:
    """Resolve ``host`` and reject when ANY answer is non-public space.

    Shared by ``validate_peer_relay_target`` (peer kind-10050 routes),
    inbox-target ``relay_configs`` writes, and reconnect revalidation —
    DNS rebinding flips an accepted target back out of service on the
    next check. Results carry a bounded TTL cache so per-reconnect cost
    stays flat. Raises ``unprocessable`` on resolution failure or any
    non-public answer; returns the address list on success.
    """
    import asyncio
    import socket
    import time

    cached = _dns_cache.get(host)
    if cached and cached[0] > time.monotonic():
        ips = cached[1]
    else:
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(
                host, port, type=socket.SOCK_STREAM
            )
        except socket.gaierror as exc:
            raise unprocessable(
                "invalid-relay", "Relay host does not resolve"
            ) from exc
        ips = [ipaddress.ip_address(info[4][0]) for info in infos]
        _dns_cache[host] = (time.monotonic() + _DNS_CACHE_TTL_S, ips)
    if not ips or not all(is_public_ip(ip) for ip in ips):
        raise unprocessable(
            "invalid-relay",
            "Relay host does not resolve to public routable space",
        )
    return ips


def audit_capture_enabled() -> list[str]:
    """Host audit-capture flags that are unsafe for infinitemarkets (OQ3).

    Qualified deployments keep request-body/query/path capture disabled —
    the host records them verbatim with no redaction hook, so secrets in
    request bodies (nsec import) would persist to the audit log.
    """
    flags = []
    for name in (
        "lnbits_audit_log_request_body",
        "lnbits_audit_log_query_params",
        "lnbits_audit_log_path_params",
    ):
        if getattr(host_settings, name, False):
            flags.append(name)
    return flags


def audit_capture_warnings() -> list[str]:
    """Startup-readiness warnings for unsafe audit capture (OQ3)."""
    flags = audit_capture_enabled()
    if not flags:
        return []
    return [
        "infinitemarkets: host audit capture is enabled for "
        + ", ".join(flags)
        + " — qualified deployments MUST disable request body/query/path "
          "audit capture (secrets and order PII would persist verbatim)."
    ]
