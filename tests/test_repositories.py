"""
tests/test_repositories.py — Comprehensive unit tests for repository query operations.
"""

from app.models.device import DeviceStatus
from app.models.entity import EntityCategory
from app.models.prompt_version import PromptLanguage
from app.models.session import GameCategory, GameLanguage, GameResult, SessionSource, SessionStatus
from app.models.teach_submission import TeachStatus
from app.models.turn import InputMethod, TurnAnswer
from app.models.user import UserRole
from app.repositories import (
    DeviceRepository,
    EntityRepository,
    GuessRepository,
    PromptRepository,
    SessionRepository,
    TeachRepository,
    TurnRepository,
    UserRepository,
)


def test_device_repository(app):
    with app.app_context():
        device = DeviceRepository.create("Test-Robot-Repo", "hash_repo_123")
        assert device.id is not None
        assert device.status == DeviceStatus.OFFLINE

        updated = DeviceRepository.update_heartbeat(device.id, camera_ok=True, mic_ok=True, firmware_version="2.0")
        assert updated is not None
        assert updated.status == DeviceStatus.ONLINE
        assert updated.camera_ok is True
        assert updated.firmware_version == "2.0"

        fetched = DeviceRepository.get_by_id(device.id)
        assert fetched.name == "Test-Robot-Repo"


def test_session_and_turn_repositories(app):
    with app.app_context():
        session = SessionRepository.create(
            source=SessionSource.WEB,
            language=GameLanguage.EN,
            category=GameCategory.CHARACTER,
        )
        assert session.id is not None
        assert session.status == SessionStatus.ACTIVE
        assert session.question_count == 0

        # Increment question count
        SessionRepository.increment_question_count(session.id)
        refreshed = SessionRepository.get_by_id(session.id)
        assert refreshed.question_count == 1

        # Turn repository
        turn = TurnRepository.create(
            session_id=session.id,
            turn_no=1,
            question="Is it alive?",
            answer=TurnAnswer.YES,
            input_method=InputMethod.BUTTON,
            confidence=0.95,
        )
        assert turn.id is not None

        turns = TurnRepository.get_turns_by_session(session.id)
        assert len(turns) == 1
        assert turns[0].question == "Is it alive?"

        # Guess repository
        guess = GuessRepository.create(
            session_id=session.id,
            guess_name="Sample Character",
            guess_no=1,
            confidence=0.91,
        )
        assert guess.id is not None
        GuessRepository.update_verdict(guess.id, True)
        assert GuessRepository.get_by_id(guess.id).is_correct is True

        # Finish session
        finished = SessionRepository.update_status(
            session.id,
            status=SessionStatus.FINISHED,
            result=GameResult.WIN,
        )
        assert finished.status == SessionStatus.FINISHED
        assert finished.result == GameResult.WIN


def test_entity_repository(app):
    with app.app_context():
        entity = EntityRepository.create(
            name="Repo Albert Einstein",
            category=EntityCategory.CHARACTER,
            names_i18n={"en": "Albert Einstein"},
            attributes={"is_physicist": 1.0},
        )
        assert entity.id is not None

        by_cat = EntityRepository.list_approved_by_category(EntityCategory.CHARACTER)
        assert any(e.name == "Repo Albert Einstein" for e in by_cat)

        EntityRepository.increment_stats(entity.id, correct=True)
        refreshed = EntityRepository.get_by_id(entity.id)
        assert refreshed.times_guessed == 1
        assert refreshed.times_correct == 1


def test_teach_repository(app):
    with app.app_context():
        session = SessionRepository.create(
            source=SessionSource.WEB,
            language=GameLanguage.FR,
            category=GameCategory.OBJECT,
        )
        submission = TeachRepository.create(
            session_id=session.id,
            submitted_name="Laptop",
            qa_trail=[{"q": "Is it electronic?", "a": "yes"}],
        )
        assert submission.status == TeachStatus.PENDING

        TeachRepository.update_status(submission.id, TeachStatus.APPROVED)
        assert TeachRepository.get_by_id(submission.id).status == TeachStatus.APPROVED


def test_user_and_prompt_repositories(app):
    with app.app_context():
        user = UserRepository.create(
            username="repo_admin",
            email="repo_admin@itc.dz",
            password_hash="pw_hash",
            role=UserRole.ADMIN,
        )
        assert user.id is not None
        assert UserRepository.get_by_username("repo_admin") is not None
        assert UserRepository.get_by_email("repo_admin@itc.dz") is not None

        # Prompt repository
        p1 = PromptRepository.create("game_system", 1, PromptLanguage.EN, "v1 prompt", is_active=True)
        assert PromptRepository.get_active_by_language(PromptLanguage.EN).version == 1

        p2 = PromptRepository.create("game_system", 2, PromptLanguage.EN, "v2 prompt", is_active=True)
        assert PromptRepository.get_active_by_language(PromptLanguage.EN).version == 2
        # Verify p1 was deactivated
        assert PromptRepository.get_active_by_language(PromptLanguage.EN).id == p2.id
