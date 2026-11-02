"""
app/api/devices.py — Robot device management and heartbeat monitoring endpoints.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
import uuid

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from app.api.auth import jwt_required, role_required
from app.api.schemas import (
    DeviceHeartbeatRequest,
    DeviceHeartbeatResponse,
    DeviceItemResponse,
    DeviceListResponse,
    RegisterDeviceRequest,
    RegisterDeviceResponse,
)
from app.extensions import limiter, redis_client
from app.models.device import Device, DeviceStatus
from app.repositories.device_repo import DeviceRepository
from app.utils.security import (
    decode_jwt,
    generate_device_token,
    hash_device_token,
    verify_device_token,
)

logger = logging.getLogger(__name__)

devices_bp = Blueprint("devices", __name__, url_prefix="/api/devices")


# ── Device Endpoints ──────────────────────────────────────────────────────────


@devices_bp.post("/register")
@role_required("admin")
def register_device() -> Any:
    """
    POST /api/devices/register — Register new robot hardware and generate device token.
    Protected: Admin role required.
    Expects JSON: { "name": "...", "firmware_version": "..." }
    Returns 201 Created: { "device_id": "...", "device_token": "...", ... }
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return (
            jsonify({"error": "Bad Request", "code": 400, "detail": "Invalid or missing JSON body."}),
            400,
        )

    try:
        req = RegisterDeviceRequest(**payload)
    except ValidationError as err:
        return (
            jsonify({"error": "Bad Request", "code": 400, "detail": err.errors()}),
            400,
        )

    raw_token = generate_device_token()
    token_hash = hash_device_token(raw_token)

    device = DeviceRepository.create(
        name=req.name,
        token_hash=token_hash,
        status=DeviceStatus.OFFLINE,
        firmware_version=req.firmware_version,
    )

    logger.info("New device registered: %s (id=%s)", device.name, device.id)

    response_data = RegisterDeviceResponse(
        device_id=str(device.id),
        name=device.name,
        device_token=raw_token,
        status=device.status.value if isinstance(device.status, DeviceStatus) else str(device.status),
        created_at=device.created_at.isoformat() if device.created_at else None,
    )
    return jsonify(response_data.model_dump()), 201


@devices_bp.get("")
@jwt_required
def list_devices() -> Any:
    """
    GET /api/devices — List all registered devices with live online status from Redis.
    Protected: Valid JWT access token required (admin or operator).
    Returns 200 OK: { "devices": [ ... ], "total": N }
    """
    devices = DeviceRepository.list_all()
    device_items = []

    for dev in devices:
        hb_key = f"device:{dev.id}:hb"
        is_alive = False
        try:
            is_alive = bool(redis_client.exists(hb_key))
        except Exception as err:
            logger.warning("Redis error checking heartbeat for device %s: %s", dev.id, err)

        # Status is ONLINE if Redis TTL key is currently active
        if is_alive:
            status_str = DeviceStatus.ONLINE.value
        elif dev.status == DeviceStatus.ERROR:
            status_str = DeviceStatus.ERROR.value
        else:
            status_str = DeviceStatus.OFFLINE.value

        device_items.append(
            DeviceItemResponse(
                id=str(dev.id),
                name=dev.name,
                status=status_str,
                camera_ok=dev.camera_ok,
                mic_ok=dev.mic_ok,
                firmware_version=dev.firmware_version,
                last_heartbeat=dev.last_heartbeat.isoformat() if dev.last_heartbeat else None,
                created_at=dev.created_at.isoformat() if dev.created_at else None,
            )
        )

    response_data = DeviceListResponse(devices=device_items, total=len(device_items))
    return jsonify(response_data.model_dump()), 200


@devices_bp.post("/<device_id>/heartbeat")
@limiter.limit("60/minute")
def device_heartbeat(device_id: str) -> Any:
    """
    POST /api/devices/{id}/heartbeat — HTTP heartbeat fallback.
    Authenticates via X-Device-Token header, Bearer device token, or admin JWT.
    Updates Redis TTL key and database telemetry.
    Returns 200 OK: { "status": "ok", "device_id": "...", "last_heartbeat": "..." }
    """
    # 1. Validate device exists
    try:
        dev_uuid = uuid.UUID(device_id)
    except (ValueError, TypeError):
        return (
            jsonify({"error": "Bad Request", "code": 400, "detail": "Invalid device UUID format."}),
            400,
        )

    device = DeviceRepository.get_by_id(dev_uuid)
    if not device:
        return (
            jsonify({"error": "Not Found", "code": 404, "detail": f"Device '{device_id}' not found."}),
            404,
        )

    # 2. Authenticate device
    # Accepts X-Device-Token header, Bearer device token, or valid JWT
    token: Optional[str] = request.headers.get("X-Device-Token")
    auth_header = request.headers.get("Authorization", "")
    if not token and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()

    is_authenticated = False
    if token:
        # Check if presented token matches stored device token hash
        if verify_device_token(token, device.token_hash):
            is_authenticated = True
        else:
            # Fall back to checking if token is an admin/operator JWT
            try:
                payload = decode_jwt(token)
                if payload.get("type") == "access":
                    is_authenticated = True
            except Exception:
                pass

    if not is_authenticated:
        return (
            jsonify(
                {
                    "error": "Unauthorized",
                    "code": 401,
                    "detail": "Invalid or missing device authentication token.",
                }
            ),
            401,
        )

    # 3. Parse optional telemetry payload
    camera_ok: Optional[bool] = None
    mic_ok: Optional[bool] = None
    firmware_version: Optional[str] = None

    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        try:
            req = DeviceHeartbeatRequest(**payload)
            camera_ok = req.camera_ok
            mic_ok = req.mic_ok
            firmware_version = req.firmware_version
        except ValidationError as err:
            return (
                jsonify({"error": "Bad Request", "code": 400, "detail": err.errors()}),
                400,
            )

    # 4. Update Database record
    updated_device = DeviceRepository.update_heartbeat(
        device_id=dev_uuid,
        camera_ok=camera_ok,
        mic_ok=mic_ok,
        firmware_version=firmware_version,
    )

    # 5. Refresh Redis TTL
    ttl_s = int(current_app.config.get("DEVICE_HB_TTL_S", 15))
    hb_key = f"device:{device.id}:hb"
    try:
        redis_client.setex(hb_key, ttl_s, "1")
    except Exception as err:
        logger.warning("Redis error setting heartbeat for device %s: %s", device.id, err)

    # 6. Publish telemetry to Redis Pub/Sub for admin dashboard live view
    try:
        event = {
            "type": "device_heartbeat",
            "device_id": str(device.id),
            "name": device.name,
            "status": DeviceStatus.ONLINE.value,
            "camera_ok": updated_device.camera_ok if updated_device else device.camera_ok,
            "mic_ok": updated_device.mic_ok if updated_device else device.mic_ok,
            "firmware_version": updated_device.firmware_version if updated_device else device.firmware_version,
            "last_heartbeat": updated_device.last_heartbeat.isoformat() if updated_device and updated_device.last_heartbeat else None,
        }
        redis_client.publish("admin:live_stream", json.dumps(event))
    except Exception as err:
        logger.debug("Redis pub/sub error publishing device heartbeat: %s", err)

    response_data = DeviceHeartbeatResponse(
        status="ok",
        device_id=str(device.id),
        last_heartbeat=updated_device.last_heartbeat.isoformat() if updated_device and updated_device.last_heartbeat else None,
    )
    return jsonify(response_data.model_dump()), 200
