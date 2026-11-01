"""
app/models/device.py — Registered robot devices and their telemetry state.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, DateTime, Enum, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class DeviceStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"


class Device(db.Model):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus, native_enum=False, length=20),
        default=DeviceStatus.OFFLINE,
        nullable=False,
    )
    camera_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mic_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    firmware_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    sessions = relationship("Session", back_populates="device", lazy="select")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "status": self.status.value if isinstance(self.status, DeviceStatus) else str(self.status),
            "camera_ok": self.camera_ok,
            "mic_ok": self.mic_ok,
            "firmware_version": self.firmware_version,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
