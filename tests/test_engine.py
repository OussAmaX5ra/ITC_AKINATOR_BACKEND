"""
tests/test_engine.py — Unit and integration tests for the Game Engine and Games REST API.

Covers:
  * Game lifecycle: start_game, process_answer, get_next_action
  * Termination criteria: confidence >= GUESS_CONFIDENCE, max questions forced guess, max guesses defeat
  * submit_verdict: win vs continue vs teach
  * submit_teach: Q&A trail saved, DB records updated, Redis cleanup
  * abandon_session: DB status updated, Redis cleaned up
  * Games REST API:
      - POST /api/games
      - GET /api/games/<session_id>
      - POST /api/games/<session_id>/answer
      - POST /api/games/<session_id>/verdict
      - POST /api/games/<session_id>/teach
      - POST /api/games/<session_id>/abandon
      - Validation and error handling (400, 404, 409)
"""

from __future__ import annotations

import json
import pytest

from app.extensions import db
from app.models.entity import Entity, EntityCategory, EntitySource
from app.models.session import GameCategory, GameLanguage, GameResult, Session, SessionStatus
from app.models.teach_submission import TeachStatus, TeachSubmission
from app.models.turn import InputMethod, Turn, TurnAnswer
from app.repositories.session_repo import SessionRepository
from app.services.game import engine, session_store
from app.services.game.session_store import GameState


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def seeded_entities(app):
    """Seed test entities for game engine testing."""
    with app.app_context():
        e1 = Entity(
            name="Alan Turing",
            names_i18n={"en": "Alan Turing", "fr": "Alan Turing", "ar": "ألان تورنغ"},
            category=EntityCategory.CHARACTER,
            attributes={
                "is_real": 1.0,
                "is_alive": 0.0,
                "is_scientist": 1.0,
                "is_computer_scientist": 1.0,
            },
            source=EntitySource.SEED,
            is_approved=True,
        )
        e2 = Entity(
            name="Ada Lovelace",
            names_i18n={"en": "Ada Lovelace", "fr": "Ada Lovelace", "ar": "آدا لوفلايس"},
            category=EntityCategory.CHARACTER,
            attributes={
                "is_real": 1.0,
                "is_alive": 0.0,
                "is_female": 1.0,
                "is_scientist": 1.0,
                "is_computer_scientist": 0.8,
            },
            source=EntitySource.SEED,
            is_approved=True,
        )
        e3 = Entity(
            name="Sherlock Holmes",
            names_i18n={"en": "Sherlock Holmes", "fr": "Sherlock Holmes"},
            category=EntityCategory.CHARACTER,
            attributes={
                "is_real": 0.0,
                "is_alive": 0.0,
                "is_scientist": 0.0,
                "is_computer_scientist": 0.0,
            },
            source=EntitySource.SEED,
            is_approved=True,
        )
        db.session.add_all([e1, e2, e3])
        db.session.commit()

        yield e1, e2, e3

        # Teardown
        for e in [e1, e2, e3]:
            db.session.delete(e)
        db.session.commit()


# ── Engine Core Tests ─────────────────────────────────────────────────────────


class TestEngineLifecycle:
    def test_start_game(self, app, fake_redis, seeded_entities):
        with app.app_context():
            session_id = engine.start_game(category="character", language="en")

            assert session_id is not None
            # Check DB record
            db_session = SessionRepository.get_by_id(session_id)
            assert db_session is not None
            assert db_session.category == GameCategory.CHARACTER
            assert db_session.language == GameLanguage.EN
            assert db_session.status == SessionStatus.ACTIVE

            # Check Redis record
            state = session_store.get_session(session_id)
            assert state is not None
            assert state["state"] == GameState.ASKING
            assert state["last_question"] is not None
            assert state["last_attribute_key"] is not None
            assert len(state["candidate_scores"]) == 3

    def test_process_answer_updates_scores_and_history(self, app, fake_redis, seeded_entities):
        with app.app_context():
            session_id = engine.start_game(category="character", language="en")
            state = session_store.get_session(session_id)
            first_attr = state["last_attribute_key"]

            action = engine.process_answer(
                session_id=session_id,
                answer="yes",
                input_method="button",
            )

            assert action["session_id"] == session_id
            assert action["action"] in ("ask", "guess")

            # Check DB turn
            turns = Turn.query.filter_by(session_id=db_session_uuid(session_id)).all()
            assert len(turns) == 1
            assert turns[0].turn_no == 1
            assert turns[0].answer == TurnAnswer.YES
            assert turns[0].input_method == InputMethod.BUTTON

            # Check Redis updated
            new_state = session_store.get_session(session_id)
            assert len(new_state["history"]) == 1
            assert new_state["history"][0]["attribute_key"] == first_attr
            assert new_state["question_count"] == 1

    def test_high_confidence_triggers_guess(self, app, fake_redis, seeded_entities):
        e1, e2, e3 = seeded_entities
        with app.app_context():
            session_id = engine.start_game(category="character", language="en")

            # Manually skew candidate scores in Redis to trigger high confidence
            session_store.update_session(
                session_id,
                {"candidate_scores": {str(e1.id): 1.0, str(e2.id): 0.05, str(e3.id): 0.0}},
            )

            action = engine.get_next_action(session_id)
            assert action["action"] == "guess"
            assert action["guess_name"] == "Alan Turing"
            assert action["entity_id"] == e1.id
            assert action["confidence"] >= 0.85

            state = session_store.get_session(session_id)
            assert state["state"] == GameState.GUESSING

    def test_max_questions_forces_guess(self, app, fake_redis, seeded_entities):
        e1, e2, e3 = seeded_entities
        with app.app_context():
            session_id = engine.start_game(category="character", language="en")

            # Set question count to max questions (20) with balanced scores
            session_store.update_session(
                session_id,
                {
                    "question_count": 20,
                    "candidate_scores": {str(e1.id): 0.5, str(e2.id): 0.49, str(e3.id): 0.0},
                },
            )

            action = engine.get_next_action(session_id)
            assert action["action"] == "guess"
            assert action["entity_id"] in (e1.id, e2.id)

    def test_submit_verdict_win(self, app, fake_redis, seeded_entities):
        e1, _, _ = seeded_entities
        with app.app_context():
            session_id = engine.start_game(category="character", language="en")
            # Force guess
            session_store.update_session(
                session_id,
                {"candidate_scores": {str(e1.id): 1.0}},
            )
            engine.get_next_action(session_id)

            result = engine.submit_verdict(session_id, is_correct=True)
            assert result["outcome"] == "win"

            # DB check
            db_sess = SessionRepository.get_by_id(session_id)
            assert db_sess.status == SessionStatus.FINISHED
            assert db_sess.result == GameResult.WIN

            # Entity stats check
            entity = db.session.get(Entity, e1.id)
            assert entity.times_guessed == 1
            assert entity.times_correct == 1

    def test_submit_verdict_wrong_guess_continues(self, app, fake_redis, seeded_entities):
        e1, e2, _ = seeded_entities
        with app.app_context():
            session_id = engine.start_game(category="character", language="en")
            # Skew to e1 with confidence >= 0.85
            session_store.update_session(
                session_id,
                {"candidate_scores": {str(e1.id): 1.0, str(e2.id): 0.05}},
            )
            action = engine.get_next_action(session_id)
            assert action["action"] == "guess"
            assert action["entity_id"] == e1.id

            # Player rejects guess
            result = engine.submit_verdict(session_id, is_correct=False)
            assert result["outcome"] in ("continue", "teach")

            state = session_store.get_session(session_id)
            assert e1.id in state["excluded_entity_ids"]
            assert state["guesses_made"] == 1

    def test_max_guesses_leads_to_defeat(self, app, fake_redis, seeded_entities):
        e1, _, _ = seeded_entities
        with app.app_context():
            session_id = engine.start_game(category="character", language="en")

            # Set guesses_made to 2 (max is 3), so 1 more wrong guess loses
            session_store.update_session(
                session_id,
                {
                    "guesses_made": 2,
                    "candidate_scores": {str(e1.id): 1.0},
                },
            )
            engine.get_next_action(session_id)

            # 3rd wrong guess
            result = engine.submit_verdict(session_id, is_correct=False)
            assert result["outcome"] == "teach"

            db_sess = SessionRepository.get_by_id(session_id)
            assert db_sess.status == SessionStatus.FINISHED
            assert db_sess.result == GameResult.LOSE

    def test_submit_teach(self, app, fake_redis, seeded_entities):
        with app.app_context():
            session_id = engine.start_game(category="character", language="en")
            engine.process_answer(session_id, "yes")

            result = engine.submit_teach(session_id, correct_name="Marie Curie")
            assert result["status"] == "ok"
            assert "submission_id" in result

            # DB check
            sub = db.session.get(TeachSubmission, result["submission_id"])
            assert sub.submitted_name == "Marie Curie"
            assert len(sub.qa_trail) == 1
            assert sub.status == TeachStatus.PENDING

            # Redis cleaned up
            assert session_store.get_session(session_id) is None

    def test_abandon_session(self, app, fake_redis, seeded_entities):
        with app.app_context():
            session_id = engine.start_game(category="character", language="en")
            result = engine.abandon_session(session_id)

            assert result["status"] == "abandoned"
            db_sess = SessionRepository.get_by_id(session_id)
            assert db_sess.status == SessionStatus.ABANDONED
            assert session_store.get_session(session_id) is None


# ── REST API Tests ───────────────────────────────────────────────────────────


class TestGamesAPI:
    def test_start_game_api(self, client, fake_redis, seeded_entities):
        resp = client.post(
            "/api/games",
            json={"category": "character", "language": "en"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert "session_id" in data
        assert "first_question" in data
        assert data["category"] == "character"
        assert data["language"] == "en"
        assert data["status"] == "active"

    def test_start_game_invalid_category(self, client):
        resp = client.post(
            "/api/games",
            json={"category": "alien", "language": "en"},
        )
        assert resp.status_code == 400

    def test_get_session_details(self, client, fake_redis, seeded_entities):
        create_resp = client.post("/api/games", json={"category": "character", "language": "en"})
        sid = create_resp.get_json()["session_id"]

        resp = client.get(f"/api/games/{sid}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == sid
        assert data["category"] == "character"

    def test_submit_answer_api(self, client, fake_redis, seeded_entities):
        create_resp = client.post("/api/games", json={"category": "character", "language": "en"})
        sid = create_resp.get_json()["session_id"]

        resp = client.post(
            f"/api/games/{sid}/answer",
            json={"answer": "yes", "input_method": "button"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["session_id"] == sid
        assert data["action"] in ("ask", "guess")

    def test_submit_answer_not_found(self, client):
        resp = client.post(
            "/api/games/00000000-0000-0000-0000-000000000000/answer",
            json={"answer": "yes"},
        )
        assert resp.status_code == 404

    def test_submit_verdict_api(self, client, fake_redis, seeded_entities):
        e1, _, _ = seeded_entities
        create_resp = client.post("/api/games", json={"category": "character", "language": "en"})
        sid = create_resp.get_json()["session_id"]

        # Force a guess state
        session_store.update_session(
            sid,
            {"candidate_scores": {str(e1.id): 1.0}},
        )
        engine.get_next_action(sid)

        resp = client.post(
            f"/api/games/{sid}/verdict",
            json={"is_correct": True},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["outcome"] == "win"

    def test_submit_teach_api(self, client, fake_redis, seeded_entities):
        create_resp = client.post("/api/games", json={"category": "character", "language": "en"})
        sid = create_resp.get_json()["session_id"]

        resp = client.post(
            f"/api/games/{sid}/teach",
            json={"correct_name": "Isaac Newton"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "submission_id" in data

    def test_abandon_api(self, client, fake_redis, seeded_entities):
        create_resp = client.post("/api/games", json={"category": "character", "language": "en"})
        sid = create_resp.get_json()["session_id"]

        resp = client.post(f"/api/games/{sid}/abandon")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "abandoned"

    def test_full_game_flow_to_defeat_and_teach(self, client, fake_redis, seeded_entities):
        """End-to-end game flow: start -> answer until guess -> wrong verdict -> teach."""
        # 1. Start game
        resp = client.post("/api/games", json={"category": "character", "language": "en"})
        assert resp.status_code == 201
        sid = resp.get_json()["session_id"]

        # 2. Answer question
        ans_resp = client.post(f"/api/games/{sid}/answer", json={"answer": "yes"})
        assert ans_resp.status_code == 200

        # 3. Simulate multiple wrong guesses to reach defeat
        e1, e2, e3 = seeded_entities
        session_store.update_session(sid, {"guesses_made": 2, "candidate_scores": {str(e1.id): 1.0}})
        engine.get_next_action(sid)

        verdict_resp = client.post(f"/api/games/{sid}/verdict", json={"is_correct": False})
        assert verdict_resp.status_code == 200
        assert verdict_resp.get_json()["outcome"] == "teach"

        # 4. Teach correct entity
        teach_resp = client.post(f"/api/games/{sid}/teach", json={"correct_name": "Katherine Johnson"})
        assert teach_resp.status_code == 200
        assert teach_resp.get_json()["status"] == "ok"


def db_session_uuid(sid_str: str):
    import uuid
    return uuid.UUID(sid_str)
