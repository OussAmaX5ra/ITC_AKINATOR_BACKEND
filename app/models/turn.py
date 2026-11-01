"""
app/models/turn.py — Individual question-and-answer exchange within a session.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class TurnAnswer(str, enum.Enum):
    YES = "yes"
    NO = "no"
    DONT_KNOW = "dont_know"
    PROBABLY = "probably"
    PROBABLY_NOT = "probably_not"


class InputMethod(str, enum.Enum):
    VOICE = "voice"
    BUTTON = "button"
    TOUCH = "touch"


class Turn(db.Model):
    __tablename__ = "turns"
    __table_args__ = (
        UniqueConstraint("session_id", "turn_no", name="uq_turns_session_turn"),
    )

    # BigInteger on PostgreSQL (BIGSERIAL), Integer on SQLite (auto-increment rowid)
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[TurnAnswer] = mapped_column(
        Enum(TurnAnswer, native_enum=False, length=20),
        nullable=False,
    )
    input_method: Mapped[InputMethod] = mapped_column(
        Enum(InputMethod, native_enum=False, length=10),
        nullable=False,
        default=InputMethod.BUTTON,
    )
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    session = relationship("Session", back_populates="turns")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": str(self.session_id),
            "turn_no": self.turn_no,
            "question": self.question,
            "answer": self.answer.value if isinstance(self.answer, TurnAnswer) else str(self.answer),
            "input_method": self.input_method.value if isinstance(self.input_method, InputMethod) else str(self.input_method),
            "confidence": self.confidence,
            "latency_ms": self.latency_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
