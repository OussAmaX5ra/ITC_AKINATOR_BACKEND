"""
tests/test_models.py — Unit tests for SQLAlchemy ORM models and relationships.
"""

import uuid
from app.extensions import db
from app.models import (
    Device,
    DeviceStatus,
    Entity,
    EntityCategory,
    EntitySource,
    GameCategory,
    GameLanguage,
    GameResult,
    Guess,
    InputMethod,
    PromptLanguage,
    PromptVersion,
    Session,
    SessionSource,
    SessionStatus,
    TeachStatus,
    TeachSubmission,
    Turn,
    TurnAnswer,
    User,
    UserRole,
)


def test_device_model(app):
    with app.app_context():
        device = Device(
            name="Robot-Beta",
            token_hash="hash_abc_123",
            status=DeviceStatus.ONLINE,
            camera_ok=True,
            mic_ok=True,
            firmware_version="1.0.2",
        )
        db.session.add(device)
        db.session.commit()

        fetched = db.session.get(Device, device.id)
        assert fetched is not None
        assert fetched.name == "Robot-Beta"
        assert fetched.camera_ok is True
        assert fetched.status == DeviceStatus.ONLINE
        d_dict = fetched.to_dict()
        assert d_dict["name"] == "Robot-Beta"
        assert d_dict["status"] == "online"


def test_prompt_version_model(app):
    with app.app_context():
        prompt = PromptVersion(
            name="system_prompt",
            version=1,
            language=PromptLanguage.EN,
            content="Prompt content here",
            is_active=True,
        )
        db.session.add(prompt)
        db.session.commit()

        fetched = db.session.get(PromptVersion, prompt.id)
        assert fetched is not None
        assert fetched.language == PromptLanguage.EN
        assert fetched.is_active is True


def test_entity_model(app):
    with app.app_context():
        entity = Entity(
            name="Marie Curie",
            names_i18n={"en": "Marie Curie", "fr": "Marie Curie", "ar": "ماري كوري"},
            category=EntityCategory.CHARACTER,
            attributes={"is_physicist": 1.0, "won_nobel_prize": 1.0},
            source=EntitySource.SEED,
            is_approved=True,
        )
        db.session.add(entity)
        db.session.commit()

        fetched = db.session.get(Entity, entity.id)
        assert fetched is not None
        assert fetched.name == "Marie Curie"
        assert fetched.attributes["won_nobel_prize"] == 1.0
        assert fetched.names_i18n["ar"] == "ماري كوري"


def test_session_lifecycle_and_relationships(app):
    with app.app_context():
        # Setup foreign dependencies
        device = Device(name="Robot-01", token_hash="tok")
        db.session.add(device)
        db.session.commit()

        session = Session(
            source=SessionSource.ROBOT,
            device_id=device.id,
            language=GameLanguage.EN,
            category=GameCategory.CHARACTER,
            status=SessionStatus.ACTIVE,
        )
        db.session.add(session)
        db.session.commit()

        # Add turn
        turn = Turn(
            session_id=session.id,
            turn_no=1,
            question="Is it alive?",
            answer=TurnAnswer.YES,
            input_method=InputMethod.VOICE,
            confidence=0.88,
        )
        db.session.add(turn)

        # Add entity & guess
        entity = Entity(name="Lion", category=EntityCategory.ANIMAL, attributes={})
        db.session.add(entity)
        db.session.commit()

        guess = Guess(
            session_id=session.id,
            entity_id=entity.id,
            guess_name=entity.name,
            guess_no=1,
            confidence=0.85,
            is_correct=False,
        )
        db.session.add(guess)
        db.session.commit()

        # Add teach submission
        teach = TeachSubmission(
            session_id=session.id,
            submitted_name="Tiger",
            qa_trail=[{"turn": 1, "q": "Is it alive?", "a": "yes"}],
            status=TeachStatus.PENDING,
        )
        db.session.add(teach)
        db.session.commit()

        # Test cascading and relationship collections
        fetched_sess = db.session.get(Session, session.id)
        assert len(fetched_sess.turns) == 1
        assert len(fetched_sess.guesses) == 1
        assert len(fetched_sess.teach_submissions) == 1

        dict_data = fetched_sess.to_dict(include_turns=True)
        assert len(dict_data["turns"]) == 1
        assert len(dict_data["guesses"]) == 1


def test_user_model(app):
    with app.app_context():
        user = User(
            username="itc_operator",
            email="operator@itc.dz",
            password_hash="argon2_hashed_pw",
            role=UserRole.OPERATOR,
        )
        db.session.add(user)
        db.session.commit()

        fetched = db.session.get(User, user.id)
        assert fetched is not None
        assert fetched.role == UserRole.OPERATOR
        assert fetched.is_active is True
