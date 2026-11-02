"""
tests/test_auth.py — Tests for Auth Blueprint and Security Middleware (Task 4.2).
"""

from datetime import timedelta
import pytest
from flask import g, jsonify

from app.api.auth import jwt_required, role_required
from app.extensions import db
from app.models.user import User, UserRole
from app.repositories.user_repo import UserRepository
from app.utils.security import generate_jwt, hash_password


# ── Fixtures & Setup ──────────────────────────────────────────────────────────


@pytest.fixture
def auth_users(app):
    """Seed test users for authentication testing and return their scalar properties."""
    with app.app_context():
        existing = User.query.filter(User.username.in_(["admin_test", "operator_test", "inactive_test"])).all()
        for u in existing:
            db.session.delete(u)
        db.session.commit()

        admin = UserRepository.create(
            username="admin_test",
            email="admin_test@itc.dz",
            password_hash=hash_password("admin_pass_123"),
            role=UserRole.ADMIN,
            is_active=True,
        )

        operator = UserRepository.create(
            username="operator_test",
            email="operator_test@itc.dz",
            password_hash=hash_password("op_pass_123"),
            role=UserRole.OPERATOR,
            is_active=True,
        )

        inactive = UserRepository.create(
            username="inactive_test",
            email="inactive_test@itc.dz",
            password_hash=hash_password("inactive_pass_123"),
            role=UserRole.OPERATOR,
            is_active=False,
        )

        return {
            "admin_id": admin.id,
            "admin_username": admin.username,
            "operator_id": operator.id,
            "operator_username": operator.username,
            "inactive_id": inactive.id,
            "inactive_username": inactive.username,
        }


# ── Login Tests ───────────────────────────────────────────────────────────────


def test_login_success_with_username(client, auth_users):
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin_test", "password": "admin_pass_123"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "Bearer"
    assert data["user"]["username"] == "admin_test"
    assert data["user"]["role"] == "admin"
    assert data["user"]["last_login_at"] is not None


def test_login_success_with_email(client, auth_users):
    resp = client.post(
        "/api/auth/login",
        json={"username": "operator_test@itc.dz", "password": "op_pass_123"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["user"]["username"] == "operator_test"
    assert data["user"]["role"] == "operator"


def test_login_wrong_password(client, auth_users):
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin_test", "password": "wrong_password"},
    )
    assert resp.status_code == 401
    assert resp.get_json()["code"] == 401


def test_login_nonexistent_user(client, auth_users):
    resp = client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "password"},
    )
    assert resp.status_code == 401


def test_login_inactive_user(client, auth_users):
    resp = client.post(
        "/api/auth/login",
        json={"username": "inactive_test", "password": "inactive_pass_123"},
    )
    assert resp.status_code == 401


def test_login_invalid_payload(client):
    resp = client.post("/api/auth/login", json={"username": ""})
    assert resp.status_code == 400


# ── Refresh Token Tests ───────────────────────────────────────────────────────


def test_refresh_token_via_json_body(client, auth_users):
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin_test", "password": "admin_pass_123"},
    )
    refresh_token = login_resp.get_json()["refresh_token"]

    resp = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "access_token" in data
    assert data["token_type"] == "Bearer"


def test_refresh_token_via_auth_header(client, auth_users):
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "operator_test", "password": "op_pass_123"},
    )
    refresh_token = login_resp.get_json()["refresh_token"]

    resp = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.get_json()


def test_refresh_with_access_token_rejected(client, auth_users):
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin_test", "password": "admin_pass_123"},
    )
    access_token = login_resp.get_json()["access_token"]

    resp = client.post("/api/auth/refresh", json={"refresh_token": access_token})
    assert resp.status_code == 401
    assert "refresh token required" in resp.get_json()["detail"].lower()


def test_refresh_missing_token(client):
    resp = client.post("/api/auth/refresh", json={})
    assert resp.status_code == 400


def test_refresh_invalid_token(client):
    resp = client.post("/api/auth/refresh", json={"refresh_token": "garbage.token.here"})
    assert resp.status_code == 401


# ── Middleware Decorator Tests ────────────────────────────────────────────────


def test_jwt_required_success(app, auth_users):
    admin_id = auth_users["admin_id"]
    token = generate_jwt(user_id=admin_id, role="admin")

    @jwt_required
    def protected_view():
        return jsonify({"user_id": g.current_user_id, "role": g.current_user_role}), 200

    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        resp, code = protected_view()
        assert code == 200
        assert resp.get_json()["role"] == "admin"


def test_jwt_required_missing_header(app):
    @jwt_required
    def protected_view():
        return jsonify({"ok": True}), 200

    with app.test_request_context():
        resp, code = protected_view()
        assert code == 401
        assert resp.get_json()["code"] == 401


def test_jwt_required_malformed_header(app):
    @jwt_required
    def protected_view():
        return jsonify({"ok": True}), 200

    with app.test_request_context(headers={"Authorization": "Basic 12345"}):
        resp, code = protected_view()
        assert code == 401


def test_jwt_required_rejects_refresh_token(app, auth_users):
    admin_id = auth_users["admin_id"]
    refresh_token = generate_jwt(user_id=admin_id, role="admin", token_type="refresh")

    @jwt_required
    def protected_view():
        return jsonify({"ok": True}), 200

    with app.test_request_context(headers={"Authorization": f"Bearer {refresh_token}"}):
        resp, code = protected_view()
        assert code == 401
        assert "access token required" in resp.get_json()["detail"].lower()


def test_role_required_admin_success(app, auth_users):
    admin_id = auth_users["admin_id"]
    token = generate_jwt(user_id=admin_id, role="admin")

    @role_required("admin")
    def admin_view():
        return jsonify({"message": "admin area"}), 200

    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        resp, code = admin_view()
        assert code == 200
        assert resp.get_json()["message"] == "admin area"


def test_role_required_operator_forbidden_on_admin_route(app, auth_users):
    operator_id = auth_users["operator_id"]
    token = generate_jwt(user_id=operator_id, role="operator")

    @role_required("admin")
    def admin_view():
        return jsonify({"message": "admin area"}), 200

    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        resp, code = admin_view()
        assert code == 403
        assert resp.get_json()["code"] == 403


def test_role_required_multi_role_allows_operator(app, auth_users):
    operator_id = auth_users["operator_id"]
    token = generate_jwt(user_id=operator_id, role="operator")

    @role_required("admin", "operator")
    def multi_view():
        return jsonify({"message": "multi-role area"}), 200

    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        resp, code = multi_view()
        assert code == 200
        assert resp.get_json()["message"] == "multi-role area"
