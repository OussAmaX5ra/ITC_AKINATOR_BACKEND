"""
app/config.py — Environment-driven configuration classes.

Usage inside the app factory:
    from app.config import config_map
    app.config.from_object(config_map[config_name])

The three classes share a common ``Base`` that reads every value from
environment variables (populated from a .env file by python-dotenv).
All type coercions are done here so the rest of the codebase never
has to call os.getenv() or int(os.getenv(...)) directly.
"""

from __future__ import annotations

import os
from datetime import timedelta


def _bool(key: str, default: bool = False) -> bool:
    """Read an env var and coerce it to bool (true/1/yes → True)."""
    val = os.getenv(key, str(default)).strip().lower()
    return val in ("1", "true", "yes", "on")


def _int(key: str, default: int) -> int:
    """Read an env var and coerce it to int."""
    return int(os.getenv(key, str(default)))


def _float(key: str, default: float) -> float:
    """Read an env var and coerce it to float."""
    return float(os.getenv(key, str(default)))


# ─────────────────────────────────────────────────────────────────────────────
# Base — all settings shared across environments
# ─────────────────────────────────────────────────────────────────────────────


class Base:
    """Base configuration.  Never use directly; subclass for each environment."""

    # ── Flask core ────────────────────────────────────────────────────────────
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    TESTING: bool = False
    DEBUG: bool = False

    # ── Database (SQLAlchemy) ─────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://akinator:akinator@localhost:5432/akinator_db",
    )
    # Disable modification tracking (deprecated and wastes memory)
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    # Keep connections alive by issuing a lightweight ping before each use
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
    }

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # ── JWT (Flask-JWT-Extended) ──────────────────────────────────────────────
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET", "jwt-secret-change-me")
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(
        minutes=_int("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", 60)
    )
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(
        days=_int("JWT_REFRESH_TOKEN_EXPIRES_DAYS", 30)
    )
    # Tokens are delivered as Bearer tokens in the Authorization header
    JWT_TOKEN_LOCATION: list[str] = ["headers"]
    JWT_HEADER_NAME: str = "Authorization"
    JWT_HEADER_TYPE: str = "Bearer"

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins (split at runtime in extensions)
    CORS_ORIGINS: list[str] = [
        o.strip()
        for o in os.getenv(
            "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
        ).split(",")
        if o.strip()
    ]

    # ── Rate limiting (Flask-Limiter) ─────────────────────────────────────────
    RATELIMIT_STORAGE_URI: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    RATELIMIT_DEFAULT: str = "200/hour"
    RATELIMIT_HEADERS_ENABLED: bool = True

    # ── LLM Provider ─────────────────────────────────────────────────────────
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "llama3.1:8b")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")

    # ── Speech-to-Text ────────────────────────────────────────────────────────
    STT_MODEL: str = os.getenv("STT_MODEL", "small")
    STT_DEVICE: str = os.getenv("STT_DEVICE", "cpu")

    # ── Text-to-Speech ────────────────────────────────────────────────────────
    TTS_ENABLED: bool = _bool("TTS_ENABLED", True)

    # ── Game Engine ───────────────────────────────────────────────────────────
    MAX_QUESTIONS: int = _int("MAX_QUESTIONS", 20)
    GUESS_CONFIDENCE: float = _float("GUESS_CONFIDENCE", 0.85)
    MAX_GUESSES: int = _int("MAX_GUESSES", 3)
    ANSWER_TIMEOUT_S: int = _int("ANSWER_TIMEOUT_S", 30)
    # Top-K candidates fed into the LLM prompt context window
    TOP_K_CANDIDATES: int = _int("TOP_K_CANDIDATES", 10)
    # Number of LLM retry attempts on malformed JSON output
    LLM_RETRIES: int = _int("LLM_RETRIES", 1)

    # ── Vision / Presence ─────────────────────────────────────────────────────
    PRESENCE_ARRIVE_S: float = _float("PRESENCE_ARRIVE_S", 1.0)
    PRESENCE_LEAVE_S: float = _float("PRESENCE_LEAVE_S", 5.0)
    # Seconds without a face before an active session is auto-abandoned
    SESSION_ABANDON_S: float = _float("SESSION_ABANDON_S", 10.0)

    # ── Device Heartbeat ─────────────────────────────────────────────────────
    DEVICE_HB_TTL_S: int = _int("DEVICE_HB_TTL_S", 15)

    # ── Redis Session TTL ─────────────────────────────────────────────────────
    # How long a live game session key survives in Redis without activity (s)
    SESSION_REDIS_TTL_S: int = _int("SESSION_REDIS_TTL_S", 1800)  # 30 min


# ─────────────────────────────────────────────────────────────────────────────
# Development
# ─────────────────────────────────────────────────────────────────────────────


class Development(Base):
    """
    Development configuration.

    - DEBUG and verbose SQLAlchemy logging enabled.
    - Relaxed rate limits so manual testing isn't blocked.
    - LLM defaults to Ollama so no cloud API key is needed.
    """

    DEBUG: bool = True
    SQLALCHEMY_ECHO: bool = True  # Log every SQL statement
    RATELIMIT_DEFAULT: str = "1000/hour"
    # Make JWT tokens short-lived in dev so refresh logic is easy to test
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(hours=24)


# ─────────────────────────────────────────────────────────────────────────────
# Production
# ─────────────────────────────────────────────────────────────────────────────


class Production(Base):
    """
    Production configuration.

    - Debug/echo disabled; secrets must be set in environment.
    - Stricter rate limits.
    - Propagate exceptions is False so Flask's error handler catches them.
    """

    DEBUG: bool = False
    SQLALCHEMY_ECHO: bool = False
    PROPAGATE_EXCEPTIONS: bool = False
    RATELIMIT_DEFAULT: str = "200/hour"

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Prevent accidentally subclassing Production."""


# ─────────────────────────────────────────────────────────────────────────────
# Testing
# ─────────────────────────────────────────────────────────────────────────────


class Testing(Base):
    """
    Testing configuration.

    - Uses an in-process SQLite database so tests are fast and isolated.
    - Disables rate limiting and CSRF so tests can hit endpoints freely.
    - Disables TTS so no real audio model is required.
    - Sets a dummy LLM provider so tests can mock the client.
    - WTF_CSRF_ENABLED kept for reference (not used here but common in Flask).
    """

    TESTING: bool = True
    DEBUG: bool = True

    # Use SQLite in-memory for speed; tests must not touch the real Postgres DB
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS: dict = {}  # SQLite doesn't support pool options

    # Disable Redis rate-limit backend during tests; use in-memory instead
    RATELIMIT_ENABLED: bool = False
    RATELIMIT_STORAGE_URI: str = "memory://"

    # Short-lived tokens to exercise expiry in tests
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(seconds=10)
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(seconds=30)

    # Dummy LLM — tests mock the client, so provider/model don't matter
    LLM_PROVIDER: str = "mock"
    LLM_MODEL: str = "mock-model"

    # Disable heavy services in unit tests
    TTS_ENABLED: bool = False
    STT_DEVICE: str = "cpu"

    # Tiny in-memory Redis substitute (fakeredis) — set in conftest.py
    REDIS_URL: str = "redis://localhost:6379/15"  # db 15 = test isolation


# ─────────────────────────────────────────────────────────────────────────────
# Registry — maps FLASK_ENV strings to config classes
# ─────────────────────────────────────────────────────────────────────────────

config_map: dict[str, type[Base]] = {
    "development": Development,
    "production": Production,
    "testing": Testing,
    # Convenient alias
    "dev": Development,
    "prod": Production,
    "test": Testing,
}


def get_config(name: str | None = None) -> type[Base]:
    """
    Return the config class for *name* (defaults to FLASK_ENV env var).

    Raises ``KeyError`` with a helpful message for unknown names.
    """
    env = (name or os.getenv("FLASK_ENV", "development")).lower()
    try:
        return config_map[env]
    except KeyError:
        valid = ", ".join(config_map)
        raise KeyError(
            f"Unknown config name {env!r}. Valid options are: {valid}"
        ) from None
