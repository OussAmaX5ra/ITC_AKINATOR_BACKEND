"""
app/utils/security.py — Password hashing, token generation, and verification helpers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
import secrets
from typing import Any, Dict, Optional, Union

from flask import current_app, has_app_context
from flask_jwt_extended import create_access_token, create_refresh_token, decode_token
from flask_jwt_extended.exceptions import JWTExtendedException
import jwt
from werkzeug.exceptions import Unauthorized
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
    _ph: Optional[PasswordHasher] = PasswordHasher()
except ImportError:
    _ph = None


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2 if available, else Werkzeug scrypt/pbkdf2."""
    if _ph is not None:
        return _ph.hash(password)
    return generate_password_hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Verify a plaintext password against its hash safely."""
    if not password or not hashed:
        return False
    if _ph is not None and hashed.startswith("$argon2"):
        try:
            return _ph.verify(hashed, password)
        except Exception:
            return False
    try:
        return check_password_hash(hashed, password)
    except Exception:
        return False


def generate_jwt(
    user_id: Union[int, str],
    role: str,
    expires_delta: Optional[timedelta] = None,
    token_type: str = "access",
) -> str:
    """
    Generate a signed JWT token with user identity and role.
    
    Supports access and refresh tokens. Operates within active Flask app context
    when available, or falls back to PyJWT with JWT_SECRET from environment.
    """
    user_id_str = str(user_id)
    claims = {"role": role, "user_id": user_id_str}

    if has_app_context():
        if token_type == "refresh":
            return create_refresh_token(
                identity=user_id_str,
                additional_claims=claims,
                expires_delta=expires_delta,
            )
        return create_access_token(
            identity=user_id_str,
            additional_claims=claims,
            expires_delta=expires_delta,
        )

    # Standalone fallback outside Flask app context
    secret = os.getenv("JWT_SECRET", "jwt-secret-change-me")
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(days=30) if token_type == "refresh" else timedelta(hours=1)

    payload = {
        "sub": user_id_str,
        "role": role,
        "user_id": user_id_str,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt(token: str) -> Dict[str, Any]:
    """
    Decode and validate a signed JWT token.

    Returns:
        dict: The decoded token payload.

    Raises:
        werkzeug.exceptions.Unauthorized: If token is missing, invalid, or expired.
    """
    if not token or not isinstance(token, str):
        raise Unauthorized("Missing or invalid token format.")

    try:
        if has_app_context():
            return decode_token(token)

        secret = os.getenv("JWT_SECRET", "jwt-secret-change-me")
        return jwt.decode(token, secret, algorithms=["HS256"])
    except (jwt.PyJWTError, JWTExtendedException) as exc:
        raise Unauthorized(f"Invalid or expired token: {exc}") from exc
    except Exception as exc:
        raise Unauthorized(f"Could not validate token: {exc}") from exc


def generate_device_token() -> str:
    """Generate a high-entropy secret token for robot authentication."""
    return secrets.token_hex(32)


def hash_device_token(token: str) -> str:
    """Compute a SHA-256 hash of a device token for secure storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_device_token(token: str, stored_hash: str) -> bool:
    """Safely verify a presented device token against the stored SHA-256 hash."""
    if not token or not stored_hash:
        return False
    return secrets.compare_digest(hash_device_token(token), stored_hash)
