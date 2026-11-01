"""
app/utils/logging.py — Structured JSON logging and request tracing.

Provides:
- JSONLogFormatter: Formats all log records into structured JSON lines.
- setup_logging(app): Configures application logging.
- register_request_logging(app): Registers before_request and after_request hooks
  for request ID generation and request-response latency logging.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from flask import Flask, g, has_request_context, request


class JSONLogFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Enrich with request context if currently inside a Flask request
        if has_request_context():
            log_data["request_id"] = getattr(g, "request_id", None)
            log_data["method"] = request.method
            log_data["path"] = request.path
            log_data["remote_addr"] = request.remote_addr
            if hasattr(g, "start_time"):
                duration_ms = round((time.time() - g.start_time) * 1000, 2)
                log_data["duration_ms"] = duration_ms

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def setup_logging(app: Flask) -> None:
    """Configure structured logging on the Flask application."""
    log_level = logging.DEBUG if app.config.get("DEBUG") else logging.INFO

    handler = logging.StreamHandler()
    handler.setFormatter(JSONLogFormatter())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = [handler]

    # Set app logger
    app.logger.handlers = [handler]
    app.logger.setLevel(log_level)


def register_request_logging(app: Flask) -> None:
    """Attach request tracing middleware to the Flask application."""

    @app.before_request
    def start_timer_and_request_id() -> None:
        g.start_time = time.time()
        # Accept incoming X-Request-ID or generate a new UUID4
        incoming_id = request.headers.get("X-Request-ID")
        g.request_id = incoming_id if incoming_id else str(uuid.uuid4())

    @app.after_request
    def log_request_outcome(response):
        duration_ms = round((time.time() - getattr(g, "start_time", time.time())) * 1000, 2)
        request_id = getattr(g, "request_id", "-")

        # Echo request ID in response headers for tracing
        response.headers["X-Request-ID"] = request_id

        # Skip logging noisy asset requests or static endpoints if needed
        if request.path != "/api/health":
            app.logger.info(
                f"{request.method} {request.path} {response.status_code} in {duration_ms}ms"
            )

        return response
