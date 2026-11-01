"""
app/models — SQLAlchemy ORM models package for the ITC Akinator backend.
"""

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

__all__ = [
    "Device",
    "DeviceStatus",
    "Entity",
    "EntityCategory",
    "EntitySource",
    "Guess",
    "PromptVersion",
    "PromptLanguage",
    "Session",
    "SessionSource",
    "GameLanguage",
    "GameCategory",
    "SessionStatus",
    "GameResult",
    "TeachSubmission",
    "TeachStatus",
    "Turn",
    "TurnAnswer",
    "InputMethod",
    "User",
    "UserRole",
]
