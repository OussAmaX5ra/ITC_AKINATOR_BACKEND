"""
app/api/auth.py — Authentication blueprint and JWT security middleware.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Dict, Optional, Union

from flask import Blueprint, abort, current_app, g, jsonify, request
from pydantic import ValidationError
from werkzeug.exceptions import Unauthorized

from app.api.schemas import LoginRequest, LoginResponse, RefreshResponse, RefreshTokenRequest, UserResponse
from app.extensions import limiter
from app.models.user import User, UserRole
from app.repositories.user_repo import UserRepository
from app.utils.security import decode_jwt, generate_jwt, verify_password

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


# ── Middleware Decorators ─────────────────────────────────────────────────────


def jwt_required(fn: Optional[Callable] = None) -> Callable:
    """
    Decorator protecting endpoints with JWT authentication.
    Validates Authorization: Bearer <access_token> header and populates Flask g.
    Supports usage with or without arguments (@jwt_required or @jwt_required()).
    """

    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Skip re-verification if already authenticated in this request
            if getattr(request, "_jwt_verified", False):
                return f(*args, **kwargs)

            auth_header = request.headers.get("Authorization", "")
            if not auth_header or not auth_header.startswith("Bearer "):
                return (
                    jsonify(
                        {
                            "error": "Unauthorized",
                            "code": 401,
                            "detail": "Missing or invalid Authorization header. Expected 'Bearer <token>'.",
                        }
                    ),
                    401,
                )

            raw_token = auth_header[7:].strip()
            if not raw_token:
                return (
                    jsonify(
                        {
                            "error": "Unauthorized",
                            "code": 401,
                            "detail": "Bearer token must not be empty.",
                        }
                    ),
                    401,
                )

            try:
                payload = decode_jwt(raw_token)
            except Unauthorized as exc:
                return (
                    jsonify(
                        {
                            "error": "Unauthorized",
                            "code": 401,
                            "detail": str(exc.description or exc),
                        }
                    ),
                    401,
                )

            token_type = payload.get("type", "access")
            if token_type != "access":
                return (
                    jsonify(
                        {
                            "error": "Unauthorized",
                            "code": 401,
                            "detail": "Invalid token type: access token required.",
                        }
                    ),
                    401,
                )

            request._jwt_verified = True
            g.jwt_payload = payload
            g.current_user_id = payload.get("sub") or payload.get("user_id")
            g.current_user_role = payload.get("role")
            return f(*args, **kwargs)

        return wrapper

    if fn is not None and callable(fn):
        return decorator(fn)
    return decorator


def role_required(*allowed_roles: Union[str, UserRole]) -> Callable:
    """
    Decorator requiring the authenticated user to hold one of the specified roles.
    Automatically enforces @jwt_required first.
    """
    normalized_roles = {
        r.value if isinstance(r, UserRole) else str(r).lower()
        for r in allowed_roles
    }

    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        @jwt_required
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            user_role = str(getattr(g, "current_user_role", "")).lower()
            if user_role not in normalized_roles:
                return (
                    jsonify(
                        {
                            "error": "Forbidden",
                            "code": 403,
                            "detail": f"Access denied. Required roles: {sorted(list(normalized_roles))}.",
                        }
                    ),
                    403,
                )
            return f(*args, **kwargs)

        return wrapper

    return decorator


def get_current_user() -> Optional[User]:
    """Retrieve the User model instance of the currently authenticated request."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is not None:
        try:
            return UserRepository.get_by_id(int(user_id))
        except (ValueError, TypeError):
            return None
    return None


# ── REST Endpoints ────────────────────────────────────────────────────────────


@auth_bp.post("/login")
@limiter.limit("10/minute")
def login() -> Any:
    """
    POST /api/auth/login — Authenticate an administrator or operator.
    Expects JSON: { "username": "...", "password": "..." }
    Returns JSON: { "access_token": "...", "refresh_token": "...", "token_type": "Bearer", "user": { ... } }
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return (
            jsonify({"error": "Bad Request", "code": 400, "detail": "Invalid or missing JSON body."}),
            400,
        )

    try:
        req = LoginRequest(**payload)
    except ValidationError as err:
        return (
            jsonify({"error": "Bad Request", "code": 400, "detail": err.errors()}),
            400,
        )

    # Allow login with either username or email
    user = UserRepository.get_by_username(req.username) or UserRepository.get_by_email(req.username)

    if not user or not user.is_active or not verify_password(req.password, user.password_hash):
        logger.warning("Failed login attempt for username/email: %s", req.username)
        return (
            jsonify(
                {
                    "error": "Unauthorized",
                    "code": 401,
                    "detail": "Invalid username or password.",
                }
            ),
            401,
        )

    # Update last login timestamp
    UserRepository.update_last_login(user.id)

    role_str = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    access_token = generate_jwt(user_id=user.id, role=role_str, token_type="access")
    refresh_token = generate_jwt(user_id=user.id, role=role_str, token_type="refresh")

    response_data = LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        user=UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            role=role_str,
            is_active=user.is_active,
            created_at=user.created_at.isoformat() if user.created_at else None,
            last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        ),
    )

    logger.info("User logged in successfully: %s (id=%d, role=%s)", user.username, user.id, role_str)
    return jsonify(response_data.model_dump()), 200


@auth_bp.post("/refresh")
@limiter.limit("20/minute")
def refresh() -> Any:
    """
    POST /api/auth/refresh — Exchange a valid refresh token for a new access token.
    Accepts refresh token in JSON body { "refresh_token": "..." } or Authorization Bearer header.
    Returns JSON: { "access_token": "...", "token_type": "Bearer" }
    """
    raw_token: Optional[str] = None

    # Check JSON body first
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        raw_token = payload.get("refresh_token")

    # Fall back to Authorization Bearer header if not provided in JSON body
    if not raw_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            raw_token = auth_header[7:].strip()

    if not raw_token:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "code": 400,
                    "detail": "Refresh token is required via body 'refresh_token' or Authorization Bearer header.",
                }
            ),
            400,
        )

    try:
        token_data = decode_jwt(raw_token)
    except Unauthorized as exc:
        return (
            jsonify(
                {
                    "error": "Unauthorized",
                    "code": 401,
                    "detail": str(exc.description or exc),
                }
            ),
            401,
        )

    token_type = token_data.get("type")
    if token_type != "refresh":
        return (
            jsonify(
                {
                    "error": "Unauthorized",
                    "code": 401,
                    "detail": "Invalid token type: refresh token required.",
                }
            ),
            401,
        )

    user_id_raw = token_data.get("sub") or token_data.get("user_id")
    try:
        user_id = int(user_id_raw)
    except (ValueError, TypeError):
        return (
            jsonify({"error": "Unauthorized", "code": 401, "detail": "Invalid user identity in token."}),
            401,
        )

    user = UserRepository.get_by_id(user_id)
    if not user or not user.is_active:
        return (
            jsonify({"error": "Unauthorized", "code": 401, "detail": "User account inactive or not found."}),
            401,
        )

    role_str = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    new_access_token = generate_jwt(user_id=user.id, role=role_str, token_type="access")

    response_data = RefreshResponse(access_token=new_access_token, token_type="Bearer")
    logger.info("Access token refreshed for user: %s (id=%d)", user.username, user.id)
    return jsonify(response_data.model_dump()), 200
