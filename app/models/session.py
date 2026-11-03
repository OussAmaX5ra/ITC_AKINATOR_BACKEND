"""
app/models/session.py — Akinator game sessions across robot and web clients.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, SmallInteger, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class SessionSource(str, enum.Enum):
    ROBOT = "robot"
    WEB = "web"


class GameLanguage(str, enum.Enum):
    AR = "ar"
    FR = "fr"
    EN = "en"


class GameCategory(str, enum.Enum):
    CHARACTER = "character"
    ANIMAL = "animal"
    OBJECT = "object"


class SessionStatus(str, enum.Enum):
    ACTIVE = "active"
    FINISHED = "finished"
    ABANDONED = "abandoned"


class GameResult(str, enum.Enum):
    WIN = "win"
    LOSE = "lose"


class Session(db.Model):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source: Mapped[SessionSource] = mapped_column(
        Enum(SessionSource, native_enum=False, length=10),
        nullable=False,
        default=SessionSource.WEB,
    )
    device_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    prompt_version_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    language: Mapped[GameLanguage] = mapped_column(
        Enum(GameLanguage, native_enum=False, length=10),
        nullable=False,
        default=GameLanguage.EN,
    )
    category: Mapped[GameCategory] = mapped_column(
        Enum(GameCategory, native_enum=False, length=20),
        nullable=False,
        default=GameCategory.CHARACTER,
    )
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, native_enum=False, length=20),
        nullable=False,
        default=SessionStatus.ACTIVE,
        index=True,
    )
    result: Mapped[Optional[GameResult]] = mapped_column(
        Enum(GameResult, native_enum=False, length=10),
        nullable=True,
    )
    question_count: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    llm_model: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    device = relationship("Device", back_populates="sessions")
    prompt_version = relationship("PromptVersion", back_populates="sessions")
    turns: Mapped[List["Turn"]] = relationship(
        "Turn", back_populates="session", cascade="all, delete-orphan", order_by="Turn.turn_no"
    )
    guesses: Mapped[List["Guess"]] = relationship(
        "Guess", back_populates="session", cascade="all, delete-orphan", order_by="Guess.guess_no"
    )
    teach_submissions: Mapped[List["TeachSubmission"]] = relationship(
        "TeachSubmission", back_populates="session", cascade="all, delete-orphan"
    )

    def to_dict(self, include_turns: bool = False) -> Dict[str, Any]:
        data = {
            "id": str(self.id),
            "source": self.source.value if isinstance(self.source, SessionSource) else str(self.source),
            "device_id": str(self.device_id) if self.device_id else None,
            "prompt_version_id": self.prompt_version_id,
            "language": self.language.value if isinstance(self.language, GameLanguage) else str(self.language),
            "category": self.category.value if isinstance(self.category, GameCategory) else str(self.category),
            "status": self.status.value if isinstance(self.status, SessionStatus) else str(self.status),
            "result": self.result.value if isinstance(self.result, GameResult) else (str(self.result) if self.result else None),
            "question_count": self.question_count,
            "llm_model": self.llm_model,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }
        if include_turns:
            data["turns"] = [turn.to_dict() for turn in self.turns]
            data["guesses"] = [guess.to_dict() for guess in self.guesses]
            data["teach_submissions"] = [sub.to_dict() for sub in self.teach_submissions]
        return data
