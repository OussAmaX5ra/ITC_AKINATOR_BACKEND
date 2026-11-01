"""
app/repositories/device_repo.py — Data access queries for the Device model.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.extensions import db
from app.models.device import Device, DeviceStatus


class DeviceRepository:
    """Repository managing Device records."""

    @staticmethod
    def create(
        name: str,
        token_hash: str,
        status: DeviceStatus = DeviceStatus.OFFLINE,
        firmware_version: Optional[str] = None,
    ) -> Device:
        device = Device(
            name=name,
            token_hash=token_hash,
            status=status,
            firmware_version=firmware_version,
        )
        db.session.add(device)
        db.session.commit()
        return device

    @staticmethod
    def get_by_id(device_id: uuid.UUID | str) -> Optional[Device]:
        if isinstance(device_id, str):
            try:
                device_id = uuid.UUID(device_id)
            except ValueError:
                return None
        return db.session.get(Device, device_id)

    @staticmethod
    def list_all(status: Optional[DeviceStatus] = None) -> List[Device]:
        query = db.select(Device)
        if status is not None:
            query = query.filter_by(status=status)
        query = query.order_by(Device.created_at.desc())
        return list(db.session.scalars(query).all())

    @staticmethod
    def update_status(device_id: uuid.UUID | str, status: DeviceStatus) -> Optional[Device]:
        device = DeviceRepository.get_by_id(device_id)
        if device:
            device.status = status
            db.session.commit()
        return device

    @staticmethod
    def update_heartbeat(
        device_id: uuid.UUID | str,
        camera_ok: Optional[bool] = None,
        mic_ok: Optional[bool] = None,
        firmware_version: Optional[str] = None,
    ) -> Optional[Device]:
        device = DeviceRepository.get_by_id(device_id)
        if device:
            device.last_heartbeat = datetime.now(timezone.utc)
            device.status = DeviceStatus.ONLINE
            if camera_ok is not None:
                device.camera_ok = camera_ok
            if mic_ok is not None:
                device.mic_ok = mic_ok
            if firmware_version is not None:
                device.firmware_version = firmware_version
            db.session.commit()
        return device

    @staticmethod
    def delete(device_id: uuid.UUID | str) -> bool:
        device = DeviceRepository.get_by_id(device_id)
        if device:
            db.session.delete(device)
            db.session.commit()
            return True
        return False
