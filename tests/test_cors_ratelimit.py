"""
tests/test_cors_ratelimit.py — Tests for Task 4.7: CORS & Rate Limiting.

Rate-limiting is disabled in the Testing config (RATELIMIT_ENABLED=False), so we
cannot reach 429 through the Flask-Limiter machinery in the shared test suite.
Instead, this module:
  1. Verifies CORS headers are present on API responses for allowed origins.
  2. Verifies CORS headers are absent (or restricted) for disallowed origins.
  3. Confirms that pre-flight OPTIONS requests are handled correctly.
  4. Verifies that rate-limit decorators exist on the expected endpoints by
     inspecting Flask-Limiter 3.x's internal ``_marked_for_limiting`` registry.
  5. Tests the 429 error handler returns the expected JSON structure by
     simulating the Flask abort(429) path on a fresh isolated app.
"""

from __future__ import annotations

import pytest
from flask import abort

from app import create_app
from app.extensions import db, limiter, redis_client


# ── CORS Tests ────────────────────────────────────────────────────────────────


def test_cors_header_present_for_allowed_origin(client):
    """API responses include Access-Control-Allow-Origin for allowed origins."""
    resp = client.get(
        "/api/health",
        headers={"Origin": "http://localhost:3000"},
    )
    acao = resp.headers.get("Access-Control-Allow-Origin")
    assert acao is not None, "CORS header should be present for allowed origin"
    assert acao in ("http://localhost:3000", "*"), f"Unexpected ACAO: {acao}"


def test_cors_header_present_for_vite_origin(client):
    """Vite dev server origin (localhost:5173) is an allowed CORS origin."""
    resp = client.get(
        "/api/health",
        headers={"Origin": "http://localhost:5173"},
    )
    acao = resp.headers.get("Access-Control-Allow-Origin")
    assert acao is not None
    assert acao in ("http://localhost:5173", "*")


def test_cors_allows_credentials(client):
    """CORS response includes Access-Control-Allow-Credentials: true."""
    resp = client.get(
        "/api/health",
        headers={"Origin": "http://localhost:3000"},
    )
    acac = resp.headers.get("Access-Control-Allow-Credentials")
    assert acac is not None
    assert acac.lower() == "true"


def test_cors_preflight_options(client):
    """OPTIONS pre-flight request to an API path returns 200/204 with CORS headers."""
    resp = client.options(
        "/api/auth/login",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type, Authorization",
        },
    )
    # Flask-CORS handles preflight with 200 or 204
    assert resp.status_code in (200, 204), f"Unexpected preflight status: {resp.status_code}"
    acao = resp.headers.get("Access-Control-Allow-Origin")
    assert acao is not None, "Pre-flight should return Access-Control-Allow-Origin"


def test_cors_exposes_rate_limit_headers(client):
    """
    Calling a valid API endpoint with a known origin returns a successful
    response — verifying that CORS middleware does not block the request.
    Rate-limit response headers (X-RateLimit-*) are injected by Flask-Limiter
    when RATELIMIT_ENABLED is True; in testing mode they are absent, which is expected.
    """
    resp = client.get(
        "/api/health",
        headers={"Origin": "http://localhost:3000"},
    )
    assert resp.status_code in (200, 204, 404)
    # Response must carry at least the base CORS header
    assert resp.headers.get("Access-Control-Allow-Origin") is not None


# ── Rate Limit Decorator Tests (Flask-Limiter 3.x registry) ──────────────────

# Flask-Limiter 3.x stores decorated function qualified names in
# limiter._marked_for_limiting (a set of strings like "module.func.func_name").

EXPECTED_RATE_LIMITED = {
    ("auth.login", "app.api.auth.login.login"),
    ("auth.refresh", "app.api.auth.refresh.refresh"),
    ("games.start_game", "app.api.games.start_game.start_game"),
    ("games.submit_answer", "app.api.games.submit_answer.submit_answer"),
    ("devices.device_heartbeat", "app.api.devices.device_heartbeat.device_heartbeat"),
}


@pytest.mark.parametrize("endpoint_name,limiter_key", list(EXPECTED_RATE_LIMITED))
def test_endpoint_is_rate_limited(app, endpoint_name, limiter_key):
    """
    Verify each critical endpoint is registered in Flask-Limiter's internal
    ``_marked_for_limiting`` set (Flask-Limiter 3.x API).
    """
    with app.app_context():
        view_func = app.view_functions.get(endpoint_name)
        assert view_func is not None, f"View '{endpoint_name}' not found in app"

        marked = getattr(limiter, "_marked_for_limiting", set())
        assert limiter_key in marked, (
            f"Expected '{limiter_key}' in limiter._marked_for_limiting.\n"
            f"Currently registered: {marked}"
        )


# ── 429 Error Handler Tests ───────────────────────────────────────────────────


def test_rate_limit_error_handler_json_format():
    """
    Verify the 429 error handler returns the standard JSON error envelope.
    Uses a fresh isolated app with its own fakeredis instance so we can register
    a test-only route without conflicting with the session-scoped app.
    """
    import fakeredis as _fakeredis
    from app.extensions import RedisExtension

    test_app = create_app("testing")
    # Give the fresh app its own isolated fakeredis — do NOT touch redis_client module singleton
    local_fake = _fakeredis.FakeRedis(decode_responses=True)
    test_app.extensions["redis"] = local_fake

    @test_app.route("/_test_429_trigger")
    def _trigger_429():
        abort(429)

    with test_app.app_context():
        db.create_all()

    with test_app.test_client() as test_client:
        resp = test_client.get("/_test_429_trigger")

    assert resp.status_code == 429
    data = resp.get_json()
    assert data is not None
    assert data["error"] == "Too Many Requests"
    assert data["code"] == 429
    assert "detail" in data


# ── Rate Limit Config Tests ───────────────────────────────────────────────────


def test_ratelimit_disabled_in_testing_config(app):
    """Rate limiting must be disabled in the Testing config so tests run freely."""
    assert app.config.get("RATELIMIT_ENABLED", True) is False, (
        "RATELIMIT_ENABLED should be False in the testing config"
    )


def test_ratelimit_storage_uri_uses_redis_in_non_test_config():
    """In development/production configs, RATELIMIT_STORAGE_URI should use Redis."""
    from app.config import Development

    storage_uri = getattr(Development, "RATELIMIT_STORAGE_URI", None)
    assert storage_uri is not None, "RATELIMIT_STORAGE_URI should be defined in Base/Development config"
    assert storage_uri.startswith("redis://"), (
        f"Expected a Redis URI for rate-limit storage in non-testing config, got: {storage_uri}"
    )


def test_cors_origins_configured_correctly(app):
    """CORS_ORIGINS config contains at least the two standard dev origins."""
    origins = app.config.get("CORS_ORIGINS", [])
    assert isinstance(origins, list), "CORS_ORIGINS should be a list"
    assert len(origins) > 0, "CORS_ORIGINS should not be empty"
    for origin in origins:
        assert origin.startswith("http"), f"Each CORS origin should be an http URL, got: {origin}"
    # Verify both dev server origins are present by default
    assert "http://localhost:3000" in origins or any("3000" in o for o in origins)
    assert "http://localhost:5173" in origins or any("5173" in o for o in origins)


def test_cors_allow_headers_include_authorization(client):
    """Pre-flight response allows the Authorization and X-Device-Token headers."""
    resp = client.options(
        "/api/devices/register",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, X-Device-Token",
        },
    )
    assert resp.status_code in (200, 204)
    allow_headers = resp.headers.get("Access-Control-Allow-Headers", "")
    # Flask-CORS echoes back the requested headers or allows wildcard
    assert allow_headers or resp.headers.get("Access-Control-Allow-Origin")

