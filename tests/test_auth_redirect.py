"""auth_redirect predicate coverage."""

from __future__ import annotations

from starlette.requests import Request

from harp.auth_redirect import build_upstream_url, should_redirect_to_browser


def _req(method: str, path: str, query: str = "", accept: str = "") -> Request:
    """Construct a Starlette Request directly from an ASGI scope."""

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [(b"accept", accept.encode())] if accept else [],
        "scheme": "http",
        "server": ("127.0.0.1", 8787),
        "client": ("127.0.0.1", 12345),
        "http_version": "1.1",
    }
    return Request(scope)


def test_signup_remote_is_redirected() -> None:
    r = _req("GET", "/signup/remote", "scheme=warposs&state=abc&public_beta=true")
    assert should_redirect_to_browser(r) is True


def test_login_remote_is_redirected() -> None:
    r = _req("GET", "/login/remote", "scheme=warposs&state=abc")
    assert should_redirect_to_browser(r) is True


def test_upgrade_is_redirected() -> None:
    r = _req("GET", "/upgrade", "scheme=warposs&state=abc")
    assert should_redirect_to_browser(r) is True


def test_billing_account_team_referral_pages_are_redirected() -> None:
    for path in ("/account", "/billing", "/team/x", "/teams", "/referral", "/referrals"):
        r = _req("GET", path)
        assert should_redirect_to_browser(r) is True, path


def test_html_accept_heuristic() -> None:
    """A GET that explicitly asks for HTML is treated as a browser navigation."""
    r = _req("GET", "/some/random/page", accept="text/html,application/xhtml+xml")
    assert should_redirect_to_browser(r) is True


def test_json_get_is_proxied_not_redirected() -> None:
    r = _req("GET", "/current_time", accept="application/json")
    assert should_redirect_to_browser(r) is False


def test_protobuf_get_is_proxied_not_redirected() -> None:
    r = _req("GET", "/api/something", accept="application/x-protobuf")
    assert should_redirect_to_browser(r) is False


def test_post_is_never_redirected() -> None:
    """POST never goes through this path; the catch-all proxy handles it."""
    r = _req("POST", "/signup/remote")
    assert should_redirect_to_browser(r) is False


def test_harp_own_routes_are_never_redirected() -> None:
    for path in ("/healthz", "/stats", "/openapi.json", "/docs", "/redoc"):
        r = _req("GET", path, accept="text/html")
        assert should_redirect_to_browser(r) is False, path


def test_root_html_is_not_redirected() -> None:
    r = _req("GET", "/", accept="text/html")
    assert should_redirect_to_browser(r) is False


def test_build_upstream_url_preserves_query() -> None:
    r = _req("GET", "/signup/remote", "scheme=warposs&state=abc")
    assert (
        build_upstream_url(r, "https://app.warp.dev/")
        == "https://app.warp.dev/signup/remote?scheme=warposs&state=abc"
    )


def test_build_upstream_url_no_query() -> None:
    r = _req("GET", "/account")
    assert build_upstream_url(r, "https://app.warp.dev") == "https://app.warp.dev/account"
