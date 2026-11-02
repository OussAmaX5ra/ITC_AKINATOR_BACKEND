"""
tests/test_devices.py — Tests for Device Management Blueprint (Task 4.3).
"""

import uuid
import pytest

from app.extensions import db, redis_client
from app.models.device import Device, DeviceStatus
from app.models.user import User, UserRole
from app.repositories.device_repo import DeviceRepository
from app.repositories.user_repo import UserRepository
from app.utils.security import generate_jwt, hash_password, verify_device_token


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def device_users(app):
    """Seed an admin and an operator for device endpoint access."""
    with app.app_context():
        # Clear existing test users if any
        existing = User.query.filter(User.username.in_(["dev_admin", "dev_operator"])).all()
        for u in existing:
            db.session.delete(u)
        db.session.commit()

        admin = UserRepository.create(
            username="dev_admin",
            email="dev_admin@itc.dz",
            password_hash=hash_password("admin_pass"),
            role=UserRole.ADMIN,
        )
        operator = UserRepository.create(
            username="dev_operator",
            email="dev_operator@itc.dz",
            password_hash=hash_password("op_pass"),
            role=UserRole.OPERATOR,
        )

        admin_token = generate_jwt(user_id=admin.id, role="admin")
        op_token = generate_jwt(user_id=operator.id, role="operator")

        return {
            "admin_token": admin_token,
            "operator_token": op_token,
        }


# ── Register Device Tests ─────────────────────────────────────────────────────


def test_register_device_admin_success(client, device_users):
    resp = client.post(
        "/api/devices/register",
        json={"name": "Akinator-Bot-01", "firmware_version": "1.0.0"},
        headers={"Authorization": f"Bearer {device_users['admin_token']}"},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert "device_id" in data
    assert "device_token" in data
    assert data["name"] == "Akinator-Bot-01"
    assert data["status"] == "offline"

    # Verify device exists in DB and token matches hash
    dev = DeviceRepository.get_by_id(data["device_id"])
    assert dev is not None
    assert dev.name == "Akinator-Bot-01"
    assert verify_device_token(data["device_token"], dev.token_hash) is True


def test_register_device_forbidden_for_operator(client, device_users):
    resp = client.post(
        "/api/devices/register",
        json={"name": "Akinator-Bot-02"},
        headers={"Authorization": f"Bearer {device_users['operator_token']}"},
    )
    assert resp.status_code == 403


def test_register_device_unauthorized_without_jwt(client):
    resp = client.post(
        "/api/devices/register",
        json={"name": "Akinator-Bot-03"},
    )
    assert resp.status_code == 401


def test_register_device_validation_error(client, device_users):
    resp = client.post(
        "/api/devices/register",
        json={"name": ""},
        headers={"Authorization": f"Bearer {device_users['admin_token']}"},
    )
    assert resp.status_code == 400


# ── List Devices Tests ────────────────────────────────────────────────────────


def test_list_devices_reflects_redis_status(client, device_users, fake_redis):
    # Register two devices
    r1 = client.post(
        "/api/devices/register",
        json={"name": "Bot-Alpha"},
        headers={"Authorization": f"Bearer {device_users['admin_token']}"},
    )
    d1_id = r1.get_json()["device_id"]

    r2 = client.post(
        "/api/devices/register",
        json={"name": "Bot-Beta"},
        headers={"Authorization": f"Bearer {device_users['admin_token']}"},
    )
    d2_id = r2.get_json()["device_id"]

    # Simulate Bot-Alpha is online by creating active Redis TTL key
    fake_redis.setex(f"device:{d1_id}:hb", 15, "1")

    resp = client.get(
        "/api/devices",
        headers={"Authorization": f"Bearer {device_users['operator_token']}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "devices" in data
    assert data["total"] >= 2

    dev_map = {d["id"]: d for d in data["devices"]}
    assert dev_map[d1_id]["status"] == "online"
    assert dev_map[d2_id]["status"] == "offline"


def test_list_devices_unauthorized(client):
    resp = client.get("/api/devices")
    assert resp.status_code == 401


# ── Heartbeat Tests ───────────────────────────────────────────────────────────


def test_heartbeat_with_x_device_token(client, device_users, fake_redis):
    # Register device
    reg = client.post(
        "/api/devices/register",
        json={"name": "Bot-Heartbeat"},
        headers={"Authorization": f"Bearer {device_users['admin_token']}"},
    )
    dev_id = reg.get_json()["device_id"]
    token = reg.get_json()["device_token"]

    # Send heartbeat
    resp = client.post(
        f"/api/devices/{dev_id}/heartbeat",
        headers={"X-Device-Token": token},
        json={"camera_ok": True, "mic_ok": True, "firmware_version": "1.2.3"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"

    # Verify Redis TTL key was set
    assert fake_redis.exists(f"device:{dev_id}:hb") == 1
    assert fake_redis.ttl(f"device:{dev_id}:hb") > 0

    # Verify DB was updated
    dev = DeviceRepository.get_by_id(dev_id)
    assert dev.camera_ok is True
    assert dev.mic_ok is True
    assert dev.firmware_version == "1.2.3"
    assert dev.status == DeviceStatus.ONLINE
    assert dev.last_heartbeat is not None


def test_heartbeat_with_bearer_device_token(client, device_users, fake_redis):
    reg = client.post(
        "/api/devices/register",
        json={"name": "Bot-Bearer"},
        headers={"Authorization": f"Bearer {device_users['admin_token']}"},
    )
    dev_id = reg.get_json()["device_id"]
    token = reg.get_json()["device_token"]

    resp = client.post(
        f"/api/devices/{dev_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={"camera_ok": False, "mic_ok": True},
    )
    assert resp.status_code == 200
    assert fake_redis.exists(f"device:{dev_id}:hb") == 1


def test_heartbeat_with_admin_jwt(client, device_users):
    reg = client.post(
        "/api/devices/register",
        json={"name": "Bot-JWT"},
        headers={"Authorization": f"Bearer {device_users['admin_token']}"},
    )
    dev_id = reg.get_json()["device_id"]

    resp = client.post(
        f"/api/devices/{dev_id}/heartbeat",
        headers={"Authorization": f"Bearer {device_users['admin_token']}"},
    )
    assert resp.status_code == 200


def test_heartbeat_invalid_token(client, device_users):
    reg = client.post(
        "/api/devices/register",
        json={"name": "Bot-BadToken"},
        headers={"Authorization": f"Bearer {device_users['admin_token']}"},
    )
    dev_id = reg.get_json()["device_id"]

    resp = client.post(
        f"/api/devices/{dev_id}/heartbeat",
        headers={"X-Device-Token": "completely_wrong_token"},
    )
    assert resp.status_code == 401


def test_heartbeat_missing_token(client, device_users):
    reg = client.post(
        "/api/devices/register",
        json={"name": "Bot-NoToken"},
        headers={"Authorization": f"Bearer {device_users['admin_token']}"},
    )
    dev_id = reg.get_json()["device_id"]

    resp = client.post(f"/api/devices/{dev_id}/heartbeat")
    assert resp.status_code == 401


def test_heartbeat_nonexistent_device(client, device_users):
    fake_id = str(uuid.uuid4())
    resp = client.post(
        f"/api/devices/{fake_id}/heartbeat",
        headers={"Authorization": f"Bearer {device_users['admin_token']}"},
    )
    assert resp.status_code == 404


def test_heartbeat_invalid_uuid(client, device_users):
    resp = client.post(
        "/api/devices/not-a-valid-uuid/heartbeat",
        headers={"Authorization": f"Bearer {device_users['admin_token']}"},
    )
    assert resp.status_code == 400
