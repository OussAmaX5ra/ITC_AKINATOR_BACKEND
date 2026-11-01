"""
tests/test_health.py — Unit tests for the /api/health endpoint.
"""


def test_health_check_structure(client):
    """Verify that /api/health returns a standardized JSON structure with checks."""
    response = client.get("/api/health")

    # In test mode without live Postgres/Redis, it may return 200 or 503 depending on mocks,
    # but the JSON schema must be strictly valid
    assert response.status_code in (200, 503)
    data = response.get_json()

    assert "status" in data
    assert data["status"] in ("healthy", "degraded")
    assert "checks" in data
    assert "environment" in data

    checks = data["checks"]
    assert "database" in checks
    assert "redis" in checks
    assert "llm" in checks


def test_request_id_header(client):
    """Verify that incoming requests receive an X-Request-ID tracing header."""
    response = client.get("/api/health", headers={"X-Request-ID": "test-req-12345"})
    assert response.headers.get("X-Request-ID") == "test-req-12345"


def test_custom_404_handler(client):
    """Verify that non-existent routes return standardized JSON error format."""
    response = client.get("/api/non-existent-route")
    assert response.status_code == 404
    data = response.get_json()
    assert data["code"] == 404
    assert data["error"] == "Not Found"
