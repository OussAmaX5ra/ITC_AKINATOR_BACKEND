"""
tests/test_session_store.py — Unit tests for app/services/game/session_store.py

All tests use the ``fake_redis`` fixture (from conftest.py) which provides a
fully in-process fakeredis instance.  No real Redis server is required.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest

from app.services.game.session_store import (
    GameState,
    add_excluded_entity,
    append_turn_to_history,
    create_session,
    delete_session,
    get_session,
    get_session_ttl,
    session_exists,
    update_session,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sid() -> str:
    """Generate a fresh random session ID for each test."""
    return str(uuid.uuid4())


# ── create_session ────────────────────────────────────────────────────────────

class TestCreateSession:
    def test_returns_state_dict(self, app, fake_redis):
        sid = _sid()
        state = create_session(sid, "character", "en", "web")

        assert isinstance(state, dict)
        assert state["session_id"] == sid
        assert state["category"] == "character"
        assert state["language"] == "en"
        assert state["source"] == "web"
        assert state["device_id"] is None
        assert state["question_count"] == 0
        assert state["guesses_made"] == 0
        assert state["history"] == []
        assert state["excluded_entity_ids"] == []
        assert state["candidate_scores"] == {}
        assert state["state"] == GameState.ASKING

    def test_key_exists_in_redis(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "animal", "fr", "robot", device_id="dev-uuid-123")

        assert fake_redis.exists(f"session:{sid}")

    def test_key_has_ttl(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "object", "ar", "web")

        ttl = fake_redis.ttl(f"session:{sid}")
        # TTL should be positive and ≤ configured 1800 s
        assert 0 < ttl <= 1800

    def test_persisted_json_is_valid(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "character", "en", "web")

        raw = fake_redis.get(f"session:{sid}")
        loaded = json.loads(raw)
        assert loaded["session_id"] == sid

    def test_with_device_id(self, app, fake_redis):
        sid = _sid()
        state = create_session(sid, "character", "en", "robot", device_id="dev-abc")

        assert state["device_id"] == "dev-abc"

    def test_with_initial_candidate_scores(self, app, fake_redis):
        sid = _sid()
        scores = {"1": 1.0, "2": 0.8, "3": 0.5}
        state = create_session(sid, "character", "en", "web", candidate_scores=scores)

        assert state["candidate_scores"] == scores

    def test_duplicate_session_raises(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "character", "en", "web")

        with pytest.raises(RuntimeError, match="already exists"):
            create_session(sid, "animal", "fr", "robot")


# ── get_session ───────────────────────────────────────────────────────────────

class TestGetSession:
    def test_returns_state_for_existing_session(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "character", "en", "web")

        state = get_session(sid)
        assert state is not None
        assert state["session_id"] == sid

    def test_returns_none_for_missing_session(self, app, fake_redis):
        state = get_session("nonexistent-id")
        assert state is None

    def test_returns_none_after_deletion(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "animal", "fr", "robot")
        delete_session(sid)

        state = get_session(sid)
        assert state is None


# ── update_session ────────────────────────────────────────────────────────────

class TestUpdateSession:
    def test_merges_updates(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "character", "en", "web")

        updated = update_session(sid, {"question_count": 3, "state": GameState.THINKING})

        assert updated["question_count"] == 3
        assert updated["state"] == GameState.THINKING
        # Untouched fields preserved
        assert updated["category"] == "character"

    def test_updated_at_changes(self, app, fake_redis):
        sid = _sid()
        state = create_session(sid, "character", "en", "web")
        original_ts = state["updated_at"]

        # Small sleep so timestamp differs
        time.sleep(0.01)
        updated = update_session(sid, {"state": GameState.ASKING})

        assert updated["updated_at"] != original_ts

    def test_raises_for_missing_session(self, app, fake_redis):
        with pytest.raises(KeyError, match="not found"):
            update_session("ghost-session", {"question_count": 1})

    def test_ttl_refreshed_by_default(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "character", "en", "web")

        # Manually shorten the TTL so we can verify it gets reset
        fake_redis.expire(f"session:{sid}", 10)
        assert fake_redis.ttl(f"session:{sid}") <= 10

        update_session(sid, {"question_count": 1})
        # TTL should be back to full value
        assert fake_redis.ttl(f"session:{sid}") > 100

    def test_candidate_scores_replaced(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "character", "en", "web", candidate_scores={"1": 1.0})

        new_scores = {"1": 0.6, "2": 0.4}
        updated = update_session(sid, {"candidate_scores": new_scores})

        assert updated["candidate_scores"] == new_scores


# ── delete_session ────────────────────────────────────────────────────────────

class TestDeleteSession:
    def test_removes_key(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "animal", "en", "web")
        assert fake_redis.exists(f"session:{sid}")

        result = delete_session(sid)

        assert result is True
        assert not fake_redis.exists(f"session:{sid}")

    def test_idempotent_on_missing_key(self, app, fake_redis):
        result = delete_session("does-not-exist")
        assert result is False


# ── session_exists ────────────────────────────────────────────────────────────

class TestSessionExists:
    def test_true_for_existing(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "character", "en", "web")
        assert session_exists(sid) is True

    def test_false_for_missing(self, app, fake_redis):
        assert session_exists("i-dont-exist") is False

    def test_false_after_delete(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "object", "ar", "robot")
        delete_session(sid)
        assert session_exists(sid) is False


# ── get_session_ttl ───────────────────────────────────────────────────────────

class TestGetSessionTTL:
    def test_returns_positive_ttl(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "character", "en", "web")
        assert get_session_ttl(sid) > 0

    def test_returns_minus_two_for_missing(self, app, fake_redis):
        assert get_session_ttl("missing-session") == -2


# ── append_turn_to_history ────────────────────────────────────────────────────

class TestAppendTurnToHistory:
    def test_first_turn_appended(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "character", "en", "web")

        state = append_turn_to_history(sid, "Is it a person?", "yes", "is_person")

        assert len(state["history"]) == 1
        turn = state["history"][0]
        assert turn["question"] == "Is it a person?"
        assert turn["answer"] == "yes"
        assert turn["attribute_key"] == "is_person"
        assert turn["turn_no"] == 1

    def test_question_count_increments(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "character", "en", "web")

        append_turn_to_history(sid, "Q1?", "yes")
        state = append_turn_to_history(sid, "Q2?", "no")

        assert state["question_count"] == 2
        assert len(state["history"]) == 2

    def test_last_question_updated(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "character", "en", "web")

        state = append_turn_to_history(sid, "Is it real?", "probably", "is_real")

        assert state["last_question"] == "Is it real?"
        assert state["last_attribute_key"] == "is_real"

    def test_raises_for_missing_session(self, app, fake_redis):
        with pytest.raises(KeyError, match="not found"):
            append_turn_to_history("ghost", "Q?", "yes")

    def test_optional_confidence_stored(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "character", "en", "web")

        state = append_turn_to_history(sid, "Q?", "dont_know", confidence=0.73)

        assert state["history"][0]["confidence"] == pytest.approx(0.73)


# ── add_excluded_entity ───────────────────────────────────────────────────────

class TestAddExcludedEntity:
    def test_entity_id_added(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "character", "en", "web")

        state = add_excluded_entity(sid, 42)

        assert 42 in state["excluded_entity_ids"]
        assert state["guesses_made"] == 1

    def test_duplicate_entity_not_added_twice(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "character", "en", "web")

        add_excluded_entity(sid, 7)
        state = add_excluded_entity(sid, 7)

        # Entity ID must appear exactly once
        assert state["excluded_entity_ids"].count(7) == 1
        # But guesses_made is incremented each call regardless
        assert state["guesses_made"] == 2

    def test_multiple_entities_excluded(self, app, fake_redis):
        sid = _sid()
        create_session(sid, "character", "en", "web")

        add_excluded_entity(sid, 1)
        add_excluded_entity(sid, 2)
        state = add_excluded_entity(sid, 3)

        assert set(state["excluded_entity_ids"]) == {1, 2, 3}
        assert state["guesses_made"] == 3

    def test_raises_for_missing_session(self, app, fake_redis):
        with pytest.raises(KeyError, match="not found"):
            add_excluded_entity("ghost", 99)
