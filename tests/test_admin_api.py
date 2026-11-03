"""
tests/test_admin_api.py — Comprehensive tests for Admin Dashboard API (Task 4.5).
"""

from datetime import datetime, timedelta, timezone
import uuid
import pytest

from app.extensions import db
from app.models.device import Device, DeviceStatus
from app.models.entity import Entity, EntityCategory, EntitySource
from app.models.guess import Guess
from app.models.prompt_version import PromptLanguage, PromptVersion
from app.models.session import (
    GameCategory,
    GameLanguage,
    GameResult,
    Session,
    SessionSource,
    SessionStatus,
)
from app.models.teach_submission import TeachStatus, TeachSubmission
from app.models.turn import InputMethod, Turn, TurnAnswer
from app.models.user import User, UserRole
from app.repositories.entity_repo import EntityRepository
from app.repositories.prompt_repo import PromptRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.teach_repo import TeachRepository
from app.repositories.user_repo import UserRepository
from app.utils.security import generate_jwt, hash_password


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def admin_auth(app):
    """Seed an admin and an operator user and return their auth headers."""
    with app.app_context():
        # Clear existing test users with these usernames
        existing = User.query.filter(User.username.in_(["adm_admin", "adm_operator"])).all()
        for u in existing:
            db.session.delete(u)
        db.session.commit()

        admin = UserRepository.create(
            username="adm_admin",
            email="adm_admin@itc.dz",
            password_hash=hash_password("admin_secret"),
            role=UserRole.ADMIN,
        )
        operator = UserRepository.create(
            username="adm_operator",
            email="adm_operator@itc.dz",
            password_hash=hash_password("op_secret"),
            role=UserRole.OPERATOR,
        )

        admin_token = generate_jwt(user_id=admin.id, role="admin")
        op_token = generate_jwt(user_id=operator.id, role="operator")

        return {
            "admin_headers": {"Authorization": f"Bearer {admin_token}"},
            "operator_headers": {"Authorization": f"Bearer {op_token}"},
            "admin_id": admin.id,
            "operator_id": operator.id,
        }


@pytest.fixture
def admin_test_data(app):
    """Seed sessions, turns, guesses, teach submissions, devices, and prompts."""
    with app.app_context():
        # Clean previous test records
        Turn.query.delete()
        Guess.query.delete()
        TeachSubmission.query.delete()
        Session.query.delete()
        PromptVersion.query.delete()
        Entity.query.filter(Entity.name.in_(["Falcon", "Peregrine Falcon", "Eagle"])).delete()
        db.session.commit()

        # 1. Device
        device = Device(
            name="Admin-Test-Bot",
            token_hash="fakehash",
            status=DeviceStatus.ONLINE,
        )
        db.session.add(device)
        db.session.flush()
        device_id = device.id

        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        two_months_ago = now - timedelta(days=60)

        # 2. Sessions
        # Session 1: Finished WIN, Character, EN, Started Today
        s1 = Session(
            source=SessionSource.WEB,
            language=GameLanguage.EN,
            category=GameCategory.CHARACTER,
            status=SessionStatus.FINISHED,
            result=GameResult.WIN,
            question_count=5,
            started_at=now - timedelta(minutes=30),
            ended_at=now,
        )
        db.session.add(s1)
        db.session.flush()

        t1 = Turn(
            session_id=s1.id,
            turn_no=1,
            question="Is your character a scientist?",
            answer=TurnAnswer.YES,
            input_method=InputMethod.VOICE,
            latency_ms=120,
        )
        t2 = Turn(
            session_id=s1.id,
            turn_no=2,
            question="Is your character real?",
            answer=TurnAnswer.YES,
            input_method=InputMethod.BUTTON,
            latency_ms=None,
        )
        g1 = Guess(
            session_id=s1.id,
            guess_name="Marie Curie",
            guess_no=1,
            confidence=0.95,
            is_correct=True,
        )
        db.session.add_all([t1, t2, g1])

        # Session 2: Finished LOSE, Animal, FR, Started Yesterday (this week)
        s2 = Session(
            source=SessionSource.ROBOT,
            device_id=device_id,
            language=GameLanguage.FR,
            category=GameCategory.ANIMAL,
            status=SessionStatus.FINISHED,
            result=GameResult.LOSE,
            question_count=10,
            started_at=yesterday,
            ended_at=yesterday + timedelta(minutes=10),
        )
        db.session.add(s2)
        db.session.flush()

        t3 = Turn(
            session_id=s2.id,
            turn_no=1,
            question="Est-ce un oiseau ?",
            answer=TurnAnswer.YES,
            input_method=InputMethod.VOICE,
            latency_ms=180,
        )
        db.session.add(t3)

        teach_sub = TeachSubmission(
            session_id=s2.id,
            submitted_name="Falcon",
            qa_trail=[
                {"attribute_key": "can_fly", "answer": "yes"},
                {"attribute_key": "is_nocturnal", "answer": "no"},
                {"attribute_key": "has_claws", "answer": "probably"},
                {"attribute_key": "lives_in_water", "answer": "dont_know"},
            ],
            status=TeachStatus.PENDING,
        )
        db.session.add(teach_sub)

        # Session 3: Abandoned, Object, AR, Started 2 months ago
        s3 = Session(
            source=SessionSource.WEB,
            language=GameLanguage.AR,
            category=GameCategory.OBJECT,
            status=SessionStatus.ABANDONED,
            result=None,
            question_count=2,
            started_at=two_months_ago,
            ended_at=two_months_ago + timedelta(minutes=5),
        )
        db.session.add(s3)

        # 3. Prompt Versions
        pv_en1 = PromptVersion(
            name="game_system",
            version=1,
            language=PromptLanguage.EN,
            content="English prompt v1",
            is_active=False,
        )
        pv_en2 = PromptVersion(
            name="game_system",
            version=2,
            language=PromptLanguage.EN,
            content="English prompt v2",
            is_active=True,
        )
        pv_fr1 = PromptVersion(
            name="game_system",
            version=1,
            language=PromptLanguage.FR,
            content="French prompt v1",
            is_active=True,
        )
        db.session.add_all([pv_en1, pv_en2, pv_fr1])
        db.session.commit()

        return {
            "session_1_id": str(s1.id),
            "session_2_id": str(s2.id),
            "session_3_id": str(s3.id),
            "device_id": str(device_id),
            "teach_sub_id": teach_sub.id,
        }


# ── 1. Security & RBAC Tests ──────────────────────────────────────────────────


def test_admin_routes_unauthorized_without_jwt(client):
    """Every admin endpoint must reject unauthenticated requests with 401."""
    routes = [
        ("GET", "/api/admin/stats"),
        ("GET", "/api/admin/sessions"),
        ("GET", f"/api/admin/sessions/{uuid.uuid4()}"),
        ("GET", "/api/admin/teach-submissions"),
        ("POST", "/api/admin/teach-submissions/1/approve"),
        ("POST", "/api/admin/teach-submissions/1/reject"),
        ("GET", "/api/admin/prompt-versions"),
        ("POST", "/api/admin/prompt-versions"),
    ]
    for method, path in routes:
        if method == "GET":
            resp = client.get(path)
        else:
            resp = client.post(path, json={})
        assert resp.status_code == 401, f"{method} {path} should return 401"
        assert resp.get_json()["error"] == "Unauthorized"


def test_admin_routes_forbidden_for_operators(client, admin_auth):
    """Operator role cannot access any admin routes (returns 403 Forbidden)."""
    headers = admin_auth["operator_headers"]
    routes = [
        ("GET", "/api/admin/stats"),
        ("GET", "/api/admin/sessions"),
        ("GET", f"/api/admin/sessions/{uuid.uuid4()}"),
        ("GET", "/api/admin/teach-submissions"),
        ("POST", "/api/admin/teach-submissions/1/approve"),
        ("POST", "/api/admin/teach-submissions/1/reject"),
        ("GET", "/api/admin/prompt-versions"),
        ("POST", "/api/admin/prompt-versions"),
    ]
    for method, path in routes:
        if method == "GET":
            resp = client.get(path, headers=headers)
        else:
            resp = client.post(path, json={}, headers=headers)
        assert resp.status_code == 403, f"{method} {path} should return 403 for operator"
        assert resp.get_json()["error"] == "Forbidden"


# ── 2. Dashboard Statistics Tests ─────────────────────────────────────────────


def test_get_dashboard_stats(client, admin_auth, admin_test_data):
    """GET /api/admin/stats returns aggregate metrics across games, latency, and languages."""
    headers = admin_auth["admin_headers"]
    resp = client.get("/api/admin/stats", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()

    # Total games = 3
    assert data["total_games"] == 3
    assert data["total_wins"] == 1
    assert data["total_losses"] == 1
    # Win rate = 1 win / 2 finished games = 50.0%
    assert data["win_rate_percent"] == 50.0
    # Average questions = (5 + 10 + 2) / 3 = 5.67
    assert data["avg_question_count"] == 5.67

    # Breakdown by category
    assert data["games_per_category"].get("character") == 1
    assert data["games_per_category"].get("animal") == 1
    assert data["games_per_category"].get("object") == 1

    # Breakdown by language
    assert data["games_per_language"].get("en") == 1
    assert data["games_per_language"].get("fr") == 1
    assert data["games_per_language"].get("ar") == 1

    # Average STT latency = (120 + 180) / 2 = 150.0 ms
    assert data["avg_stt_latency_ms"] == 150.0

    # Temporal counts
    assert data["games_today"] >= 1
    assert data["games_this_month"] >= 2  # s1 and s2 were within this month/week


def test_get_dashboard_stats_empty(app, client, admin_auth):
    """When no games exist, stats endpoints return 0s and None without crashing."""
    with app.app_context():
        Turn.query.delete()
        Guess.query.delete()
        TeachSubmission.query.delete()
        Session.query.delete()
        db.session.commit()

    headers = admin_auth["admin_headers"]
    resp = client.get("/api/admin/stats", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["total_games"] == 0
    assert data["total_wins"] == 0
    assert data["total_losses"] == 0
    assert data["win_rate_percent"] == 0.0
    assert data["avg_question_count"] == 0.0
    assert data["avg_stt_latency_ms"] is None


# ── 3. Session Listing & Inspection Tests ──────────────────────────────────────


def test_list_admin_sessions_pagination(client, admin_auth, admin_test_data):
    """GET /api/admin/sessions respects pagination limit and page offset."""
    headers = admin_auth["admin_headers"]
    resp = client.get("/api/admin/sessions?page=1&limit=2", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()

    assert "sessions" in data
    assert len(data["sessions"]) == 2
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["limit"] == 2


def test_list_admin_sessions_filter_by_status(client, admin_auth, admin_test_data):
    """GET /api/admin/sessions filters by status."""
    headers = admin_auth["admin_headers"]

    # Filter by 'finished'
    resp = client.get("/api/admin/sessions?status=finished", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 2
    assert all(s["status"] == "finished" for s in data["sessions"])

    # Filter by 'abandoned'
    resp = client.get("/api/admin/sessions?status=abandoned", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["sessions"][0]["status"] == "abandoned"


def test_list_admin_sessions_filter_by_source_and_device(client, admin_auth, admin_test_data):
    """GET /api/admin/sessions filters by source and device UUID."""
    headers = admin_auth["admin_headers"]
    dev_id = admin_test_data["device_id"]

    # Filter by robot source
    resp = client.get(f"/api/admin/sessions?source=robot&device_id={dev_id}", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["sessions"][0]["source"] == "robot"
    assert data["sessions"][0]["device_id"] == dev_id


def test_list_admin_sessions_filter_by_date_range(client, admin_auth, admin_test_data):
    """GET /api/admin/sessions filters by ISO date_from and date_to."""
    headers = admin_auth["admin_headers"]
    now = datetime.now(timezone.utc)
    two_days_ago = (now - timedelta(days=2)).isoformat()
    future = (now + timedelta(days=1)).isoformat()

    resp = client.get(f"/api/admin/sessions?date_from={two_days_ago}&date_to={future}", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    # Should include s1 (today) and s2 (yesterday), but not s3 (2 months ago)
    assert data["total"] == 2


def test_list_admin_sessions_invalid_filters(client, admin_auth):
    """GET /api/admin/sessions returns 400 Bad Request on invalid parameter formats."""
    headers = admin_auth["admin_headers"]

    # Invalid status
    resp = client.get("/api/admin/sessions?status=unknown_status", headers=headers)
    assert resp.status_code == 400

    # Invalid source
    resp = client.get("/api/admin/sessions?source=satellite", headers=headers)
    assert resp.status_code == 400

    # Invalid device UUID
    resp = client.get("/api/admin/sessions?device_id=not-a-uuid", headers=headers)
    assert resp.status_code == 400

    # Invalid date
    resp = client.get("/api/admin/sessions?date_from=invalid-date", headers=headers)
    assert resp.status_code == 400


def test_get_admin_session_detail_audit_trail(client, admin_auth, admin_test_data):
    """GET /api/admin/sessions/{id} returns full audit trail: turns, guesses, and teach submissions."""
    headers = admin_auth["admin_headers"]
    s1_id = admin_test_data["session_1_id"]

    resp = client.get(f"/api/admin/sessions/{s1_id}", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["id"] == s1_id
    assert "turns" in data
    assert len(data["turns"]) == 2
    assert data["turns"][0]["question"] == "Is your character a scientist?"
    assert data["turns"][0]["latency_ms"] == 120

    assert "guesses" in data
    assert len(data["guesses"]) == 1
    assert data["guesses"][0]["guess_name"] == "Marie Curie"
    assert data["guesses"][0]["is_correct"] is True


def test_get_admin_session_detail_not_found_or_invalid(client, admin_auth):
    """GET /api/admin/sessions/{id} handles 404 and 400 errors properly."""
    headers = admin_auth["admin_headers"]

    # Malformed UUID
    resp = client.get("/api/admin/sessions/not-a-uuid", headers=headers)
    assert resp.status_code == 400

    # Non-existent UUID
    resp = client.get(f"/api/admin/sessions/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


# ── 4. Teach Submissions Review Tests ─────────────────────────────────────────


def test_list_teach_submissions(client, admin_auth, admin_test_data):
    """GET /api/admin/teach-submissions lists pending submissions by default and supports filtering."""
    headers = admin_auth["admin_headers"]

    # Default is pending
    resp = client.get("/api/admin/teach-submissions", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "teach_submissions" in data
    assert len(data["teach_submissions"]) >= 1
    assert data["teach_submissions"][0]["submitted_name"] == "Falcon"
    assert data["teach_submissions"][0]["status"] == "pending"

    # Filter all
    resp_all = client.get("/api/admin/teach-submissions?status=all", headers=headers)
    assert resp_all.status_code == 200
    assert resp_all.get_json()["total"] >= 1

    # Invalid status
    resp_bad = client.get("/api/admin/teach-submissions?status=unknown", headers=headers)
    assert resp_bad.status_code == 400


def test_approve_teach_submission_creates_entity(client, admin_auth, admin_test_data):
    """
    POST /api/admin/teach-submissions/{id}/approve approves submission and extracts
    attributes from Q&A trail into a newly created approved Entity.
    """
    headers = admin_auth["admin_headers"]
    sub_id = admin_test_data["teach_sub_id"]

    resp = client.post(
        f"/api/admin/teach-submissions/{sub_id}/approve",
        json={"create_entity": True},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "approved"
    assert data["submission_id"] == sub_id
    assert data["entity_id"] is not None

    # Verify submission record in DB
    sub = TeachRepository.get_by_id(sub_id)
    assert sub.status == TeachStatus.APPROVED
    assert sub.reviewed_by == admin_auth["admin_id"]
    assert sub.entity_id == data["entity_id"]
    assert sub.reviewed_at is not None

    # Verify created entity
    ent = EntityRepository.get_by_id(data["entity_id"])
    assert ent is not None
    assert ent.name == "Falcon"
    assert ent.category == EntityCategory.ANIMAL
    assert ent.is_approved is True
    assert ent.source == EntitySource.LEARNED
    # Verify attribute conversion from qa_trail:
    # can_fly -> 1.0 (yes), is_nocturnal -> -1.0 (no), has_claws -> 0.5 (probably), lives_in_water -> 0.0 (dont_know)
    assert ent.attributes.get("can_fly") == 1.0
    assert ent.attributes.get("is_nocturnal") == -1.0
    assert ent.attributes.get("has_claws") == 0.5
    assert ent.attributes.get("lives_in_water") == 0.0


def test_approve_teach_submission_with_explicit_attributes(app, client, admin_auth, admin_test_data):
    """POST /api/admin/teach-submissions/{id}/approve with custom attributes and translations."""
    with app.app_context():
        # Create an extra pending teach submission
        sub = TeachRepository.create(
            session_id=admin_test_data["session_1_id"],
            submitted_name="Peregrine Falcon",
            qa_trail=[],
        )
        sub_id = sub.id

    headers = admin_auth["admin_headers"]
    payload = {
        "category": "animal",
        "names_i18n": {"en": "Peregrine Falcon", "fr": "Faucon pèlerin"},
        "attributes": {"can_fly": 1.0, "speed_fast": 1.0},
        "create_entity": True,
    }
    resp = client.post(
        f"/api/admin/teach-submissions/{sub_id}/approve",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 200
    ent_id = resp.get_json()["entity_id"]

    ent = EntityRepository.get_by_id(ent_id)
    assert ent.name == "Peregrine Falcon"
    assert ent.names_i18n.get("fr") == "Faucon pèlerin"
    assert ent.attributes.get("speed_fast") == 1.0


def test_approve_teach_submission_merges_existing_entity(app, client, admin_auth, admin_test_data):
    """POST /api/admin/teach-submissions/{id}/approve merges attributes when entity already exists."""
    with app.app_context():
        existing_ent = EntityRepository.create(
            name="Eagle",
            category=EntityCategory.ANIMAL,
            attributes={"can_fly": 1.0, "is_carnivore": 1.0},
            is_approved=False,
        )
        sub = TeachRepository.create(
            session_id=admin_test_data["session_1_id"],
            submitted_name="Eagle",
            qa_trail=[{"attribute_key": "has_sharp_vision", "answer": "yes"}],
            entity_id=existing_ent.id,
        )
        sub_id = sub.id
        ent_id = existing_ent.id

    headers = admin_auth["admin_headers"]
    resp = client.post(
        f"/api/admin/teach-submissions/{sub_id}/approve",
        json={"create_entity": True},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.get_json()["entity_id"] == ent_id

    ent = EntityRepository.get_by_id(ent_id)
    assert ent.is_approved is True
    assert ent.attributes.get("can_fly") == 1.0
    assert ent.attributes.get("is_carnivore") == 1.0
    assert ent.attributes.get("has_sharp_vision") == 1.0


def test_approve_teach_submission_not_found(client, admin_auth):
    """POST /api/admin/teach-submissions/{id}/approve returns 404 for unknown submission."""
    headers = admin_auth["admin_headers"]
    resp = client.post("/api/admin/teach-submissions/999999/approve", json={}, headers=headers)
    assert resp.status_code == 404


def test_reject_teach_submission(client, admin_auth, admin_test_data):
    """POST /api/admin/teach-submissions/{id}/reject marks submission as rejected with reviewer id."""
    headers = admin_auth["admin_headers"]
    sub_id = admin_test_data["teach_sub_id"]

    resp = client.post(f"/api/admin/teach-submissions/{sub_id}/reject", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "rejected"
    assert data["submission_id"] == sub_id

    sub = TeachRepository.get_by_id(sub_id)
    assert sub.status == TeachStatus.REJECTED
    assert sub.reviewed_by == admin_auth["admin_id"]
    assert sub.reviewed_at is not None


def test_reject_teach_submission_not_found(client, admin_auth):
    """POST /api/admin/teach-submissions/{id}/reject returns 404 for unknown submission."""
    headers = admin_auth["admin_headers"]
    resp = client.post("/api/admin/teach-submissions/999999/reject", headers=headers)
    assert resp.status_code == 404


# ── 5. Versioned Prompt Management Tests ──────────────────────────────────────


def test_list_prompt_versions_grouped(client, admin_auth, admin_test_data):
    """GET /api/admin/prompt-versions returns versions grouped by language."""
    headers = admin_auth["admin_headers"]
    resp = client.get("/api/admin/prompt-versions", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()

    assert "prompt_versions" in data
    assert "grouped_by_language" in data
    grouped = data["grouped_by_language"]

    assert "en" in grouped
    assert "fr" in grouped
    assert "ar" in grouped

    # English has v1 and v2
    en_versions = [p["version"] for p in grouped["en"]]
    assert 1 in en_versions
    assert 2 in en_versions


def test_list_prompt_versions_filter_language(client, admin_auth, admin_test_data):
    """GET /api/admin/prompt-versions?language=en filters properly and validates language param."""
    headers = admin_auth["admin_headers"]

    resp = client.get("/api/admin/prompt-versions?language=en", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert all(p["language"] == "en" for p in data["prompt_versions"])

    resp_bad = client.get("/api/admin/prompt-versions?language=es", headers=headers)
    assert resp_bad.status_code == 400


def test_create_prompt_version_success_and_deactivates_prior(client, admin_auth, admin_test_data):
    """
    POST /api/admin/prompt-versions creates new prompt version and deactivates
    the previously active version of the same language.
    """
    headers = admin_auth["admin_headers"]
    payload = {
        "name": "game_system",
        "language": "en",
        "content": "English prompt v3 with advanced rules.",
        "version": 3,
        "is_active": True,
    }

    resp = client.post("/api/admin/prompt-versions", json=payload, headers=headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["name"] == "game_system"
    assert data["version"] == 3
    assert data["language"] == "en"
    assert data["is_active"] is True

    # Verify previous v2 is now inactive in DB
    en_prompts = PromptRepository.list_versions(language=PromptLanguage.EN, name="game_system")
    v2 = next((p for p in en_prompts if p.version == 2), None)
    assert v2 is not None
    assert v2.is_active is False

    # Active version should now be v3
    active_prompt = PromptRepository.get_active_by_language(PromptLanguage.EN, name="game_system")
    assert active_prompt is not None
    assert active_prompt.version == 3


def test_create_prompt_version_auto_increment(client, admin_auth, admin_test_data):
    """POST /api/admin/prompt-versions auto-increments version number when omitted."""
    headers = admin_auth["admin_headers"]
    payload = {
        "name": "game_system",
        "language": "fr",
        "content": "French prompt v2 auto incremented.",
        "is_active": True,
    }

    resp = client.post("/api/admin/prompt-versions", json=payload, headers=headers)
    assert resp.status_code == 201
    data = resp.get_json()
    # French had v1, so next is v2
    assert data["version"] == 2


def test_create_prompt_version_validation_errors(client, admin_auth):
    """POST /api/admin/prompt-versions returns 400 on malformed payloads."""
    headers = admin_auth["admin_headers"]

    # Missing content
    resp = client.post(
        "/api/admin/prompt-versions",
        json={"name": "game_system", "language": "en"},
        headers=headers,
    )
    assert resp.status_code == 400

    # Invalid language
    resp = client.post(
        "/api/admin/prompt-versions",
        json={"name": "game_system", "language": "german", "content": "hello"},
        headers=headers,
    )
    assert resp.status_code == 400

    # Non-json payload
    resp = client.post(
        "/api/admin/prompt-versions",
        data="not a json",
        content_type="text/plain",
        headers=headers,
    )
    assert resp.status_code == 400
