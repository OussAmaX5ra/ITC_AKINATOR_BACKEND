"""
app/extensions.py — Flask extensions initialization.

All extensions are instantiated unattached to any specific app instance.
They are bound to the Flask application instance inside the create_app() factory
via their respective init_app() methods (Application Factory Pattern).
"""

from __future__ import annotations

import logging
from typing import Optional

from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sock import Sock
from flask_sqlalchemy import SQLAlchemy
import redis

logger = logging.getLogger(__name__)

# ── SQLAlchemy & Migrations ──────────────────────────────────────────────────
db: SQLAlchemy = SQLAlchemy()
migrate: Migrate = Migrate()

# ── WebSockets ───────────────────────────────────────────────────────────────
sock: Sock = Sock()

# ── CORS & Security ──────────────────────────────────────────────────────────
cors: CORS = CORS()
jwt: JWTManager = JWTManager()

# ── Rate Limiter ─────────────────────────────────────────────────────────────
limiter: Limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/hour"],
    storage_uri="memory://",  # overridden in init_app with app.config["RATELIMIT_STORAGE_URI"]
)


# ── Redis Client Wrapper ─────────────────────────────────────────────────────
class RedisExtension:
    """Wrapper around redis.Redis supporting lazy initialization via init_app()."""

    def __init__(self) -> None:
        self._client: Optional[redis.Redis] = None

    def init_app(self, app: Flask) -> None:
        """Initialize Redis connection from app configuration."""
        redis_url = app.config.get("REDIS_URL", "redis://localhost:6379/0")
        try:
            self._client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
            )
            # Expose the client on app extensions
            app.extensions["redis"] = self._client
        except Exception as e:
            logger.warning("Could not initialize Redis client on startup: %s", e)
            self._client = None

    @property
    def client(self) -> redis.Redis:
        """Return the active Redis client."""
        if self._client is None:
            raise RuntimeError(
                "Redis client has not been initialized. Ensure create_app() has run."
            )
        return self._client

    def __getattr__(self, name: str):
        """Proxy attribute access directly to underlying redis.Redis instance."""
        if self._client is not None:
            return getattr(self._client, name)
        raise RuntimeError("Redis client is not initialized.")


redis_client: RedisExtension = RedisExtension()
