"""
app/repositories — Clean data access layer isolating SQL queries from business logic.
"""

from app.repositories.device_repo import DeviceRepository
from app.repositories.entity_repo import EntityRepository
from app.repositories.guess_repo import GuessRepository
from app.repositories.prompt_repo import PromptRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.teach_repo import TeachRepository
from app.repositories.turn_repo import TurnRepository
from app.repositories.user_repo import UserRepository

__all__ = [
    "DeviceRepository",
    "EntityRepository",
    "GuessRepository",
    "PromptRepository",
    "SessionRepository",
    "TeachRepository",
    "TurnRepository",
    "UserRepository",
]
