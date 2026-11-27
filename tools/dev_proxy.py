"""Dev-only HTTP pass-through proxy -> https://localhost:5099.

Lets plain-HTTP tooling (e.g. the Devin Desktop preview, which cannot
handle the e2e server's self-signed cert) reach the running e2e_server.
Mutations through it need the caller's Origin allow-listed via
INFINITEMARKETS_ADMIN_ORIGINS on the e2e_server env.

Text responses are rewritten upstream-origin -> proxy-origin so absolute
URLs seeded into HTML/JSON (product images, canonical links) resolve
through the proxy instead of the untrusted-cert origin. Request bodies
get the reverse rewrite so values saved back keep canonical https://
URLs (server validation requires https image URLs).

    uv run python tools/dev_proxy.py            # http://127.0.0.1:5080
    GM_PROXY_PORT=5180 GM_UPSTREAM=https://localhost:5099 uv run python tools/dev_proxy.py
"""

from __future__ import annotations

import os

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

UPSTREAM = os.environ.get("GM_UPSTREAM", "https://localhost:5099")
PORT = int(os.environ.get("GM_PROXY_PORT", "5080"))
SELF_ORIGIN = f"http://127.0.0.1:{PORT}"

app = FastAPI()
client = httpx.AsyncClient(verify=False, timeout=None)

DROP_REQ = {b"host", b"content-length", b"connection", b"accept-encoding"}
DROP_RESP = {b"content-length", b"transfer-encoding", b"connection"}

UP_B = UPSTREAM.encode()
SELF_B = SELF_ORIGIN.encode()


def _rewriteable(content_type: str | None) -> bool:
    ct = (content_type or "").split(";")[0].strip().lower()
    return ct.startswith("text/") or ct in {
        "application/json",
        "application/javascript",
        "application/xml",
        "image/svg+xml",
    }


def _relax_img_src_csp(value: bytes) -> bytes:
    """Rewritten URLs are http:// — dev-only CSP needs http: in img-src,
    else the browser blocks them whenever the page isn't served from the
    proxy origin itself (e.g. through an outer preview tunnel)."""
    parts = value.split(b";")
    for i, directive in enumerate(parts):
        if directive.strip().lower().startswith(b"img-src") and b"http:" not in directive:
            parts[i] = directive.rstrip() + b" http:"
    return b";".join(parts)


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def proxy(path: str, request: Request) -> StreamingResponse:
    url = httpx.URL(
        f"{UPSTREAM}/{path}",
        query=request.url.query.encode() if request.url.query else None,
    )
    headers = [
        (k, v) for k, v in request.headers.raw if k.lower() not in DROP_REQ
    ]
    # Identity encoding: bodies must arrive uncompressed to be rewritable.
    headers.append((b"accept-encoding", b"identity"))

    body = await request.body()
    if body and _rewriteable(request.headers.get("content-type")):
        body = body.replace(SELF_B, UP_B)

    req = client.build_request(
        request.method, url, headers=headers, content=body
    )
    resp = await client.send(req, stream=True)

    async def stream():
        try:
            if _rewriteable(resp.headers.get("content-type")):
                data = await resp.aread()
                yield data.replace(UP_B, SELF_B)
            else:
                async for chunk in resp.aiter_raw():
                    yield chunk
        finally:
            await resp.aclose()

    out = StreamingResponse(stream(), status_code=resp.status_code)
    out.raw_headers = [
        (b"location", v.replace(UP_B, SELF_B))
        if k.lower() == b"location"
        else (k, _relax_img_src_csp(v))
        if k.lower() == b"content-security-policy"
        else (k, v)
        for k, v in resp.headers.raw
        if k.lower() not in DROP_RESP
    ]
    return out


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
