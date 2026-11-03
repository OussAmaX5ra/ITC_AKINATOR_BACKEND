"""
tests/test_pubsub_livestream.py — Tests for Redis Pub/Sub Live Stream (Task 4.6).
"""

import json
import uuid
import pytest

from app.extensions import redis_client
from app.models.entity import Entity, EntityCategory
from app.repositories.entity_repo import EntityRepository
from app.services.events import (
    ADMIN_LIVE_STREAM_CHANNEL,
    publish_device_heartbeat,
    publish_face_detection,
    publish_guess_event,
    publish_live_event,
    publish_state_change,
    publish_turn_event,
    publish_verdict_event,
)
from app.services.game import engine
from app.services.vision.detector import broadcast_face_detections
from app.ws.admin import matches_subscription


# ── Direct Event Publishing Tests ─────────────────────────────────────────────


def test_publish_live_event_to_redis(app, fake_redis):
    pubsub = fake_redis.pubsub()
    pubsub.subscribe(ADMIN_LIVE_STREAM_CHANNEL)
    pubsub.get_message()  # consume subscription confirmation message

    event = {"type": "test_event", "foo": "bar"}
    ok = publish_live_event(event)
    assert ok is True

    msg = pubsub.get_message()
    assert msg is not None
    data = json.loads(msg["data"])
    assert data["type"] == "test_event"
    assert data["foo"] == "bar"


def test_publish_turn_event(app, fake_redis):
    pubsub = fake_redis.pubsub()
    pubsub.subscribe(ADMIN_LIVE_STREAM_CHANNEL)
    pubsub.get_message()

    ok = publish_turn_event(
        session_id="sess-123",
        turn_no=1,
        question="Is it human?",
        answer="yes",
        input_method="voice",
        confidence=0.95,
        latency_ms=120,
        device_id=str(uuid.uuid4()),
    )
    assert ok is True

    msg = pubsub.get_message()
    assert msg is not None
    data = json.loads(msg["data"])
    assert data["type"] == "turn"
    assert data["session_id"] == "sess-123"
    assert data["turn_no"] == 1
    assert data["answer"] == "yes"


def test_publish_device_heartbeat(app, fake_redis):
    pubsub = fake_redis.pubsub()
    pubsub.subscribe(ADMIN_LIVE_STREAM_CHANNEL)
    pubsub.get_message()

    dev_id = str(uuid.uuid4())
    ok = publish_device_heartbeat(
        device_id=dev_id,
        name="Akinator-Bot",
        status="online",
        camera_ok=True,
        mic_ok=True,
        firmware_version="1.0.0",
    )
    assert ok is True

    msg = pubsub.get_message()
    assert msg is not None
    data = json.loads(msg["data"])
    assert data["type"] == "robot_status"
    assert data["device_id"] == dev_id
    assert data["status"] == "online"


def test_publish_face_detection(app, fake_redis):
    pubsub = fake_redis.pubsub()
    pubsub.subscribe(ADMIN_LIVE_STREAM_CHANNEL)
    pubsub.get_message()

    faces = [{"bbox": [10, 20, 100, 100], "confidence": 0.98}]
    largest = faces[0]
    dev_id = str(uuid.uuid4())

    ok = broadcast_face_detections(
        device_id=dev_id,
        faces=faces,
        largest_face=largest,
    )
    assert ok is True

    msg = pubsub.get_message()
    assert msg is not None
    data = json.loads(msg["data"])
    assert data["type"] == "frame_preview"
    assert data["device_id"] == dev_id
    assert data["face_count"] == 1
    assert data["largest_face"] == largest


# ── Engine Live Publishing Integration ────────────────────────────────────────


def test_engine_publishes_live_stream_events(app, fake_redis):
    """Verify that Game Engine lifecycle methods broadcast to admin:live_stream."""
    with app.app_context():
        Entity.query.delete()
        EntityRepository.create(
            name="Ada Lovelace",
            category=EntityCategory.CHARACTER,
            attributes={"is_programmer": 1.0, "is_female": 1.0},
        )
        EntityRepository.create(
            name="Alan Turing",
            category=EntityCategory.CHARACTER,
            attributes={"is_programmer": 1.0, "is_male": 1.0},
        )
        EntityRepository.create(
            name="Grace Hopper",
            category=EntityCategory.CHARACTER,
            attributes={"is_programmer": 1.0, "is_female": 1.0, "was_admiral": 1.0},
        )

        pubsub = fake_redis.pubsub()
        pubsub.subscribe(ADMIN_LIVE_STREAM_CHANNEL)
        pubsub.get_message()  # Consume subscription confirmation

        dev_id = str(uuid.uuid4())

        # 1. start_game emits session_update
        sess_id = engine.start_game(category="character", language="en", device_id=dev_id)

        start_msg = pubsub.get_message()
        assert start_msg is not None
        start_data = json.loads(start_msg["data"])
        assert start_data["type"] == "session_update"
        assert start_data["session_id"] == sess_id
        assert start_data["device_id"] == dev_id

        # 2. process_answer emits 'thinking' then 'turn'
        engine.process_answer(session_id=sess_id, answer="yes", input_method="button")

        thinking_msg = pubsub.get_message()
        assert thinking_msg is not None
        assert json.loads(thinking_msg["data"])["state"] == "thinking"

        turn_msg = pubsub.get_message()
        assert turn_msg is not None
        turn_data = json.loads(turn_msg["data"])
        assert turn_data["type"] == "turn"
        assert turn_data["session_id"] == sess_id
        assert turn_data["turn_no"] == 1

        # 3. submit_verdict emits verdict event
        engine.submit_verdict(session_id=sess_id, is_correct=True)
        verdict_msg = pubsub.get_message()
        assert verdict_msg is not None
        verdict_data = json.loads(verdict_msg["data"])
        assert verdict_data["type"] == "verdict"
        assert verdict_data["outcome"] == "win"
        assert verdict_data["is_correct"] is True


# ── Subscription Filtering Logic Tests ────────────────────────────────────────


def test_matches_subscription_all():
    event = {"type": "turn", "session_id": "s1", "device_id": "d1"}
    assert matches_subscription(event, set(), set(), subscribe_all=True) is True


def test_matches_subscription_device_filter():
    event_d1 = {"type": "robot_status", "device_id": "dev-01"}
    event_d2 = {"type": "robot_status", "device_id": "dev-02"}

    subscribed_devices = {"dev-01"}
    subscribed_sessions = set()

    assert matches_subscription(event_d1, subscribed_devices, subscribed_sessions, subscribe_all=False) is True
    assert matches_subscription(event_d2, subscribed_devices, subscribed_sessions, subscribe_all=False) is False


def test_matches_subscription_session_filter():
    event_s1 = {"type": "turn", "session_id": "sess-alpha"}
    event_s2 = {"type": "turn", "session_id": "sess-beta"}

    subscribed_devices = set()
    subscribed_sessions = {"sess-alpha"}

    assert matches_subscription(event_s1, subscribed_devices, subscribed_sessions, subscribe_all=False) is True
    assert matches_subscription(event_s2, subscribed_devices, subscribed_sessions, subscribe_all=False) is False


def test_matches_subscription_default_unfiltered():
    event = {"type": "system_alert", "level": "warning"}
    assert matches_subscription(event, set(), set(), subscribe_all=False) is True
