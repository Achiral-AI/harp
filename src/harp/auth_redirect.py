"""Redirect browser-launched URLs back to the real upstream backend.

The patched Warp client constructs browser-facing URLs from
``WARP_SERVER_ROOT_URL`` and shells out via ``ctx.open_url(...)`` for the
sign-up / sign-in / upgrade flows. With Harp pointed at the same URL, those
land on the proxy and have no HTML to render. Forwarding the bytes doesn't
help either — the OAuth callback redirect from upstream targets the
configured server URL, which would loop back at us.

The fix: detect requests that look like *browser navigations* and return a
short ``302`` to the same path on the real upstream. The browser then talks
to ``app.warp.dev`` directly for the OAuth dance; the post-auth deep-link
(`warposs://login?token=...`) opens the local app, which talks to Harp again
for everything else.

This is a conservative filter: only ``GET`` requests to known auth/account
prefixes, or any ``GET`` whose ``Accept`` header asks for HTML, are treated
as browser-bound. Programmatic API calls from the Warp client send
``Accept: application/json`` or ``application/x-protobuf`` and are unaffected.
"""

from __future__ import annotations

from starlette.requests import Request as StarletteRequest

# Path prefixes the Warp client is known to open in a browser.
# Sourced from `app/src/auth/auth_manager.rs` and `app/src/lib.rs`:
#   sign_up_url   -> /signup/remote
#   sign_in_url   -> /login/remote
#   upgrade_url   -> /upgrade
#   login_options -> /login/options (anonymous-user linking)
# Plus a few standard customer-facing pages the client opens via
# `ctx.open_url(server_root_url() + ...)` from settings / billing surfaces.
BROWSER_PATH_PREFIXES: tuple[str, ...] = (
    "/signup/",
    "/login/",
    "/upgrade",
    "/account",
    "/team",
    "/teams",
    "/billing",
    "/onboarding",
    "/profile",
    "/referral",
    "/referrals",
)

# Paths Harp itself owns and must never redirect to upstream.
_OWN_PATHS: frozenset[str] = frozenset(
    {
        "/healthz",
        "/stats",
        "/openapi.json",
        "/docs",
        "/redoc",
        "/docs/oauth2-redirect",
    }
)


def should_redirect_to_browser(request: StarletteRequest) -> bool:
    """Return True if the request should be 302'd back to the upstream host.

    This is a deliberately narrow check; anything that doesn't match falls
    through to the transparent proxy path.
    """

    if request.method != "GET":
        return False

    path = request.url.path
    if path in _OWN_PATHS:
        return False

    if any(path.startswith(p) for p in BROWSER_PATH_PREFIXES):
        return True

    # Heuristic: a top-level HTML navigation from a browser sends an Accept
    # header that includes ``text/html``. The Warp client never asks for HTML
    # — it expects JSON, protobuf, or SSE. So an HTML-accepting GET is almost
    # certainly a browser navigation.
    accept = request.headers.get("accept", "")
    if "text/html" in accept and path != "/":
        return True

    return False


def build_upstream_url(request: StarletteRequest, upstream_base_url: str) -> str:
    """Build the absolute URL on the real upstream the browser should be sent to."""

    base = upstream_base_url.rstrip("/")
    path = request.url.path
    query = request.url.query
    return f"{base}{path}?{query}" if query else f"{base}{path}"
