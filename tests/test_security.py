"""
tests/test_security.py — Unit tests for security utilities (Task 4.1).
"""

from datetime import timedelta
import time
import pytest
from werkzeug.exceptions import Unauthorized

from app.utils.security import (
    decode_jwt,
    generate_device_token,
    generate_jwt,
    hash_device_token,
    hash_password,
    verify_device_token,
    verify_password,
)


class TestPasswordSecurity:
    """Test password hashing and verification."""

    def test_hash_and_verify_success(self):
        pwd = "SecretPassword123!"
        hashed = hash_password(pwd)
        assert hashed != pwd
        assert verify_password(pwd, hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("CorrectPassword")
        assert verify_password("WrongPassword", hashed) is False

    def test_verify_empty_or_none(self):
        assert verify_password("", "some_hash") is False
        assert verify_password("pwd", "") is False
        assert verify_password(None, "some_hash") is False

    def test_verify_corrupted_hash(self):
        assert verify_password("pwd", "not_a_valid_hash") is False
        assert verify_password("pwd", "$argon2id$v=19$m=65536,t=3,p=4$corrupt$corrupt") is False


class TestJwtSecurity:
    """Test JWT generation and decoding."""

    def test_generate_and_decode_access_token_in_app(self, app):
        with app.app_context():
            token = generate_jwt(user_id=42, role="admin")
            assert isinstance(token, str)

            payload = decode_jwt(token)
            assert payload["sub"] == "42"
            assert payload["role"] == "admin"
            assert payload["type"] == "access"

    def test_generate_and_decode_refresh_token_in_app(self, app):
        with app.app_context():
            token = generate_jwt(user_id="user_abc", role="operator", token_type="refresh")
            payload = decode_jwt(token)
            assert payload["sub"] == "user_abc"
            assert payload["role"] == "operator"
            assert payload["type"] == "refresh"

    def test_generate_and_decode_outside_app_context(self):
        token = generate_jwt(user_id=99, role="admin")
        payload = decode_jwt(token)
        assert payload["sub"] == "99"
        assert payload["role"] == "admin"
        assert payload["type"] == "access"

    def test_decode_invalid_token_raises_unauthorized(self, app):
        with app.app_context():
            with pytest.raises(Unauthorized):
                decode_jwt("this.is.not.a.valid.jwt")

        with pytest.raises(Unauthorized):
            decode_jwt("")

    def test_decode_expired_token_raises_unauthorized(self, app):
        with app.app_context():
            token = generate_jwt(user_id=1, role="admin", expires_delta=timedelta(seconds=-10))
            with pytest.raises(Unauthorized):
                decode_jwt(token)


class TestDeviceTokenSecurity:
    """Test device token generation, hashing, and verification."""

    def test_generate_device_token_length(self):
        token1 = generate_device_token()
        token2 = generate_device_token()
        assert len(token1) == 64
        assert len(token2) == 64
        assert token1 != token2

    def test_hash_and_verify_device_token(self):
        token = generate_device_token()
        hashed = hash_device_token(token)
        assert len(hashed) == 64  # SHA-256 hex is 64 chars
        assert verify_device_token(token, hashed) is True

    def test_verify_wrong_device_token(self):
        token = generate_device_token()
        hashed = hash_device_token(token)
        wrong_token = generate_device_token()
        assert verify_device_token(wrong_token, hashed) is False

    def test_verify_empty_or_none(self):
        token = generate_device_token()
        hashed = hash_device_token(token)
        assert verify_device_token("", hashed) is False
        assert verify_device_token(token, "") is False
        assert verify_device_token(None, hashed) is False
