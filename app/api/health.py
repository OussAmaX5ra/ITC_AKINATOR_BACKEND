"""
app/api/health.py — Health check and diagnostics endpoint.

GET /api/health
Returns service health status for PostgreSQL, Redis, and LLM configuration.
Status codes:
- 200 OK: All critical dependencies are reachable.
- 503 Service Unavailable: One or more critical dependencies failed.
"""

from __future__ import annotations

import logging
import urllib.request
from typing import Any, Dict

from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from app.extensions import db, redis_client

logger = logging.getLogger(__name__)

health_bp = Blueprint("health", __name__, url_prefix="/api")


@health_bp.route("/health", methods=["GET"])
def health_check():
    """Verify connectivity to PostgreSQL, Redis, and LLM provider."""
    status = "healthy"
    checks: Dict[str, Any] = {}

    # 1. Check PostgreSQL Database
    try:
        db.session.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok", "message": "Connected to database"}
    except Exception as e:
        status = "degraded"
        checks["database"] = {"status": "error", "message": str(e)}
        logger.error("Health check: PostgreSQL error: %s", e)

    # 2. Check Redis
    try:
        if redis_client.ping():
            checks["redis"] = {"status": "ok", "message": "Connected to Redis"}
        else:
            status = "degraded"
            checks["redis"] = {"status": "error", "message": "Ping returned false"}
    except Exception as e:
        status = "degraded"
        checks["redis"] = {"status": "error", "message": str(e)}
        logger.error("Health check: Redis error: %s", e)

    # 3. Check LLM Provider Configuration
    llm_provider = current_app.config.get("LLM_PROVIDER", "ollama")
    llm_model = current_app.config.get("LLM_MODEL", "")

    if llm_provider == "ollama":
        ollama_url = current_app.config.get("OLLAMA_URL", "http://localhost:11434")
        try:
            # Lightweight ping to Ollama base URL
            req = urllib.request.Request(f"{ollama_url.rstrip('/')}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    checks["llm"] = {
                        "status": "ok",
                        "provider": "ollama",
                        "model": llm_model,
                        "url": ollama_url,
                    }
                else:
                    checks["llm"] = {
                        "status": "warning",
                        "provider": "ollama",
                        "message": f"Ollama returned HTTP {resp.status}",
                    }
        except Exception:
            checks["llm"] = {
                "status": "warning",
                "provider": "ollama",
                "message": f"Ollama unreachable at {ollama_url}",
            }
    else:
        # Cloud providers (Gemini, Anthropic, OpenAI)
        api_key = current_app.config.get("LLM_API_KEY", "")
        has_key = bool(api_key and not api_key.startswith("your-"))
        checks["llm"] = {
            "status": "ok" if has_key else "warning",
            "provider": llm_provider,
            "model": llm_model,
            "configured": has_key,
        }

    http_status = 200 if status == "healthy" else 503
    return (
        jsonify(
            {
                "status": status,
                "environment": current_app.config.get("ENV", "development"),
                "checks": checks,
            }
        ),
        http_status,
    )
