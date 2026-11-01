"""
app/__init__.py — Application factory for the ITC Akinator backend.

Initializes extensions, logging, REST blueprints, WebSocket endpoints,
and standardized JSON error handlers.
"""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from flask import Flask, jsonify

from app.config import get_config
from app.extensions import cors, db, jwt, limiter, migrate, redis_client, sock
from app.utils.logging import register_request_logging, setup_logging


def create_app(config_name: Optional[str] = None) -> Flask:
    """Create and configure the Flask application instance."""
    # Load environment variables from .env file
    load_dotenv()

    app = Flask(__name__)

    # Load configuration
    cfg = get_config(config_name or os.getenv("FLASK_ENV", "development"))
    app.config.from_object(cfg)

    # 1. Setup Structured JSON Logging & Request Tracing
    setup_logging(app)
    register_request_logging(app)

    # 2. Initialize Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    redis_client.init_app(app)
    sock.init_app(app)
    jwt.init_app(app)

    # Ensure all ORM models are registered with SQLAlchemy metadata
    from app import models  # noqa: F401

    cors_origins = app.config.get("CORS_ORIGINS", ["http://localhost:3000", "http://localhost:5173"])
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": cors_origins}},
        supports_credentials=True,
    )

    if app.config.get("RATELIMIT_ENABLED", True):
        limiter.init_app(app)

    # 3. Register Blueprints
    from app.api.admin import admin_bp
    from app.api.auth import auth_bp
    from app.api.devices import devices_bp
    from app.api.entities import entities_bp
    from app.api.games import games_bp
    from app.api.health import health_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(games_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(entities_bp)
    app.register_blueprint(admin_bp)

    # 4. Register WebSockets
    from app.ws import register_websockets

    register_websockets(sock)

    # 5. Global Standardized JSON Error Handlers
    @app.errorhandler(400)
    def bad_request(error):
        return (
            jsonify({"error": "Bad Request", "code": 400, "detail": str(error.description)}),
            400,
        )

    @app.errorhandler(404)
    def not_found(error):
        return (
            jsonify({"error": "Not Found", "code": 404, "detail": str(error.description)}),
            404,
        )

    @app.errorhandler(429)
    def ratelimit_handler(error):
        return (
            jsonify(
                {
                    "error": "Too Many Requests",
                    "code": 429,
                    "detail": "Rate limit exceeded. Try again later.",
                }
            ),
            429,
        )

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error("Internal Server Error: %s", error)
        return (
            jsonify(
                {
                    "error": "Internal Server Error",
                    "code": 500,
                    "detail": "An unexpected error occurred.",
                }
            ),
            500,
        )

    return app
