"""
app/ws/admin.py — Admin WebSocket route (/ws/admin) for real-time live monitoring.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Set

from flask import request
from simple_websocket import ConnectionClosed, ConnectionError
from werkzeug.exceptions import Unauthorized

from app.extensions import redis_client
from app.services.events import ADMIN_LIVE_STREAM_CHANNEL
from app.utils.security import decode_jwt

logger = logging.getLogger(__name__)


def matches_subscription(
    event: Dict[str, Any],
    subscribed_devices: Set[str],
    subscribed_sessions: Set[str],
    subscribe_all: bool,
) -> bool:
    """Check if a live stream event matches the admin's subscription filters."""
    if subscribe_all:
        return True

    dev_id = event.get("device_id")
    if dev_id and str(dev_id) in subscribed_devices:
        return True

    sess_id = event.get("session_id")
    if sess_id and str(sess_id) in subscribed_sessions:
        return True

    # If no filters set at all, default to forwarding
    if not subscribed_devices and not subscribed_sessions:
        return True

    return False


def register_admin_ws(sock) -> None:
    """Register the /ws/admin WebSocket route on the flask-sock instance."""

    @sock.route("/ws/admin")
    def admin_endpoint(ws) -> None:
        token = request.args.get("token")

        # 1. Authenticate connection
        if not token:
            try:
                initial_raw = ws.receive(timeout=3.0)
                if initial_raw:
                    msg = json.loads(initial_raw)
                    if isinstance(msg, dict) and msg.get("type") == "auth":
                        token = msg.get("token")
            except Exception:
                pass

        if not token:
            try:
                ws.send(json.dumps({"type": "error", "code": 401, "message": "Authentication token required."}))
                ws.close(4001, "Unauthorized")
            except Exception:
                pass
            return

        try:
            payload = decode_jwt(token)
        except Unauthorized as exc:
            try:
                ws.send(json.dumps({"type": "error", "code": 401, "message": str(exc.description or exc)}))
                ws.close(4001, "Unauthorized")
            except Exception:
                pass
            return

        user_role = str(payload.get("role", "")).lower()
        if user_role not in ("admin", "operator"):
            try:
                ws.send(json.dumps({"type": "error", "code": 403, "message": "Admin or operator role required."}))
                ws.close(4003, "Forbidden")
            except Exception:
                pass
            return

        user_id = payload.get("sub") or payload.get("user_id")
        logger.info("Admin WebSocket connected: user_id=%s, role=%s", user_id, user_role)

        # Notify successful connection
        ws.send(json.dumps({"type": "connected", "user_id": user_id, "role": user_role}))

        # 2. Setup Subscriptions & Redis Pub/Sub
        subscribed_devices: Set[str] = set()
        subscribed_sessions: Set[str] = set()
        subscribe_all: bool = True

        pubsub = redis_client.pubsub()
        pubsub.subscribe(ADMIN_LIVE_STREAM_CHANNEL)

        try:
            while ws.connected:
                # 3a. Read from client (non-blocking with short timeout)
                try:
                    client_msg = ws.receive(timeout=0.05)
                except (ConnectionClosed, ConnectionError):
                    break

                if client_msg is not None:
                    try:
                        cmd = json.loads(client_msg) if isinstance(client_msg, str) else {}
                    except Exception:
                        cmd = {}

                    cmd_type = cmd.get("type")
                    if cmd_type == "subscribe":
                        if cmd.get("all") is True:
                            subscribe_all = True
                        if cmd.get("device_id"):
                            subscribed_devices.add(str(cmd["device_id"]))
                            subscribe_all = False
                        if cmd.get("session_id"):
                            subscribed_sessions.add(str(cmd["session_id"]))
                            subscribe_all = False

                        ws.send(
                            json.dumps(
                                {
                                    "type": "subscribed",
                                    "all": subscribe_all,
                                    "devices": list(subscribed_devices),
                                    "sessions": list(subscribed_sessions),
                                }
                            )
                        )
                    elif cmd_type == "unsubscribe":
                        if cmd.get("device_id"):
                            subscribed_devices.discard(str(cmd["device_id"]))
                        if cmd.get("session_id"):
                            subscribed_sessions.discard(str(cmd["session_id"]))
                        if not subscribed_devices and not subscribed_sessions:
                            subscribe_all = True

                        ws.send(
                            json.dumps(
                                {
                                    "type": "unsubscribed",
                                    "all": subscribe_all,
                                    "devices": list(subscribed_devices),
                                    "sessions": list(subscribed_sessions),
                                }
                            )
                        )
                    elif cmd_type == "ping":
                        ws.send(json.dumps({"type": "pong"}))

                # 3b. Read incoming events from Redis channel
                try:
                    redis_msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
                    if redis_msg and redis_msg.get("type") == "message":
                        data_str = redis_msg.get("data")
                        if isinstance(data_str, (str, bytes)):
                            try:
                                event = json.loads(data_str)
                                if isinstance(event, dict) and matches_subscription(
                                    event, subscribed_devices, subscribed_sessions, subscribe_all
                                ):
                                    ws.send(json.dumps(event) if not isinstance(data_str, str) else data_str)
                            except Exception as err:
                                logger.debug("Error processing live stream event: %s", err)
                except Exception as err:
                    logger.debug("Redis pubsub get_message error: %s", err)

        except Exception as exc:
            logger.info("Admin WebSocket connection closed: %s", exc)
        finally:
            try:
                pubsub.unsubscribe(ADMIN_LIVE_STREAM_CHANNEL)
                pubsub.close()
            except Exception:
                pass
            logger.info("Admin WebSocket disconnected: user_id=%s", user_id)
