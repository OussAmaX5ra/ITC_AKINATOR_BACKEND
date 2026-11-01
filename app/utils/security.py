"""
app/utils/security.py — Password hashing, token generation, and verification helpers.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Optional

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
    _ph: Optional[PasswordHasher] = PasswordHasher()
except ImportError:
    _ph = None

from werkzeug.security import check_password_hash, generate_password_hash


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2 if available, else Werkzeug scrypt/pbkdf2."""
    if _ph is not None:
        return _ph.hash(password)
    return generate_password_hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Verify a plaintext password against its hash."""
    if _ph is not None and hashed.startswith("$argon2"):
        try:
            return _ph.verify(hashed, password)
        except VerifyMismatchError:
            return False
    return check_password_hash(hashed, password)


def generate_device_token() -> str:
    """Generate a high-entropy secret token for robot authentication."""
    return secrets.token_hex(32)


def hash_device_token(token: str) -> str:
    """Compute a SHA-256 hash of a device token for secure storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_device_token(token: str, stored_hash: str) -> bool:
    """Safely verify a presented device token against the stored SHA-256 hash."""
    return secrets.compare_digest(hash_device_token(token), stored_hash)
