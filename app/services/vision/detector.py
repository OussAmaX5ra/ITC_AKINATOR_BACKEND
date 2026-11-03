"""
app/services/vision/detector.py — Face detection service and live event broadcaster.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.services.events import publish_face_detection

logger = logging.getLogger(__name__)


def broadcast_face_detections(
    device_id: str,
    faces: List[Dict[str, Any]],
    largest_face: Optional[Dict[str, Any]] = None,
    frame_preview_jpeg_b64: Optional[str] = None,
) -> bool:
    """Publish detected face bounding boxes and player preview to the admin live stream."""
    return publish_face_detection(
        device_id=device_id,
        faces=faces,
        largest_face=largest_face,
        frame_preview_jpeg_b64=frame_preview_jpeg_b64,
    )
