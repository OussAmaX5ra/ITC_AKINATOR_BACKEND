"""
app/services/events.py — Redis Pub/Sub live stream broadcasting utilities.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.extensions import redis_client

logger = logging.getLogger(__name__)

ADMIN_LIVE_STREAM_CHANNEL = "admin:live_stream"


def publish_live_event(event: Dict[str, Any]) -> bool:
    """
    Publish an event dictionary to the Redis 'admin:live_stream' channel.
    Returns True if published successfully, False otherwise.
    """
    try:
        raw_msg = json.dumps(event)
        redis_client.publish(ADMIN_LIVE_STREAM_CHANNEL, raw_msg)
        return True
    except Exception as exc:
        logger.debug("Failed to publish live stream event: %s", exc)
        return False


def publish_turn_event(
    session_id: str,
    turn_no: int,
    question: str,
    answer: str,
    input_method: str = "button",
    confidence: Optional[float] = None,
    latency_ms: Optional[int] = None,
    device_id: Optional[str] = None,
) -> bool:
    """Publish a turn Q&A event to the admin live stream."""
    return publish_live_event(
        {
            "type": "turn",
            "session_id": str(session_id),
            "turn_no": turn_no,
            "question": question,
            "answer": answer,
            "input_method": input_method,
            "confidence": confidence,
            "latency_ms": latency_ms,
            "device_id": str(device_id) if device_id else None,
        }
    )


def publish_guess_event(
    session_id: str,
    guess_name: str,
    entity_id: Optional[int],
    confidence: float,
    guess_no: int,
    turn_no: int,
    device_id: Optional[str] = None,
) -> bool:
    """Publish an Akinator guess event to the admin live stream."""
    return publish_live_event(
        {
            "type": "guess",
            "session_id": str(session_id),
            "guess_name": guess_name,
            "entity_id": entity_id,
            "confidence": confidence,
            "guess_no": guess_no,
            "turn_no": turn_no,
            "device_id": str(device_id) if device_id else None,
        }
    )


def publish_verdict_event(
    session_id: str,
    outcome: str,
    is_correct: bool,
    guess_name: Optional[str] = None,
    device_id: Optional[str] = None,
) -> bool:
    """Publish a player verdict event to the admin live stream."""
    return publish_live_event(
        {
            "type": "verdict",
            "session_id": str(session_id),
            "outcome": outcome,
            "is_correct": is_correct,
            "guess_name": guess_name,
            "device_id": str(device_id) if device_id else None,
        }
    )


def publish_state_change(
    session_id: str,
    state: str,
    device_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> bool:
    """Publish a session state transition to the admin live stream."""
    event: Dict[str, Any] = {
        "type": "session_update",
        "session_id": str(session_id),
        "state": state,
        "device_id": str(device_id) if device_id else None,
    }
    if extra:
        event.update(extra)
    return publish_live_event(event)


def publish_device_heartbeat(
    device_id: str,
    name: str,
    status: str,
    camera_ok: bool,
    mic_ok: bool,
    firmware_version: Optional[str] = None,
    last_heartbeat: Optional[str] = None,
) -> bool:
    """Publish a robot status & heartbeat event to the admin live stream."""
    return publish_live_event(
        {
            "type": "robot_status",
            "device_id": str(device_id),
            "name": name,
            "status": status,
            "camera_ok": camera_ok,
            "mic_ok": mic_ok,
            "firmware_version": firmware_version,
            "last_heartbeat": last_heartbeat,
        }
    )


def publish_face_detection(
    device_id: str,
    faces: List[Dict[str, Any]],
    largest_face: Optional[Dict[str, Any]] = None,
    frame_preview_jpeg_b64: Optional[str] = None,
) -> bool:
    """Publish a face detection / frame preview event to the admin live stream."""
    event: Dict[str, Any] = {
        "type": "frame_preview",
        "device_id": str(device_id),
        "faces": faces,
        "largest_face": largest_face,
        "face_count": len(faces),
    }
    if frame_preview_jpeg_b64:
        event["frame_preview"] = frame_preview_jpeg_b64
    return publish_live_event(event)
