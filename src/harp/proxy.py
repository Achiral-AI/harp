"""Transparent reverse proxy to Warp's real backend.

The shim exposes itself as `WARP_SERVER_ROOT_URL` to the patched Warp client.
Anything not handled locally must look indistinguishable from talking directly
to ``app.warp.dev``: same status codes, same headers, same body bytes, same
streaming behaviour for SSE.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response, StreamingResponse

logger = logging.getLogger(__name__)

# Headers that hop-by-hop and must be stripped before forwarding.
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        # Host gets recomputed by httpx for the upstream URL.
        "host",
        # Strip any incoming Content-Length: streaming bodies should re-derive it.
        "content-length",
    }
)


def _scrub(headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(k, v) for k, v in headers if k.lower() not in _HOP_BY_HOP]


class UpstreamProxy:
    """Streams requests/responses between the Warp client and ``app.warp.dev``."""

    def __init__(self, base_url: str, *, timeout_s: float = 600.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_s, connect=15.0),
            follow_redirects=False,
            http2=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def forward(self, request: StarletteRequest, *, body: bytes | None = None) -> Response:
        """Forward ``request`` to upstream and return a Starlette response.

        ``body`` overrides the incoming body. Pass through-bytes when we've already
        consumed the request body for inspection (e.g. in the multi-agent hijack).
        """

        url_path = request.url.path
        query = request.url.query
        upstream_path = f"{url_path}?{query}" if query else url_path

        # If a body wasn't supplied, stream it from the client request to avoid
        # buffering very large uploads in memory.
        if body is None:
            content: bytes | AsyncIterator[bytes] = request.stream()
        else:
            content = body

        upstream_request = self._client.build_request(
            method=request.method,
            url=upstream_path,
            headers=_scrub(list(request.headers.items())),
            content=content,
        )

        upstream_response = await self._client.send(upstream_request, stream=True)

        async def _body_iter() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream_response.aiter_raw():
                    yield chunk
            finally:
                await upstream_response.aclose()

        return StreamingResponse(
            _body_iter(),
            status_code=upstream_response.status_code,
            headers={k: v for k, v in upstream_response.headers.items() if k.lower() not in _HOP_BY_HOP},
            media_type=upstream_response.headers.get("content-type"),
        )
