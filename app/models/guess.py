"""
app/models/guess.py — Guesses proposed by the engine during a session.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class Guess(db.Model):
    __tablename__ = "guesses"

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
    entity_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("entities.id", ondelete="SET NULL"),
        nullable=True,
    )
    guess_name: Mapped[str] = mapped_column(String(150), nullable=False)
    guess_no: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    session = relationship("Session", back_populates="guesses")
    entity = relationship("Entity", back_populates="guesses")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": str(self.session_id),
            "entity_id": self.entity_id,
            "guess_name": self.guess_name,
            "guess_no": self.guess_no,
            "confidence": self.confidence,
            "is_correct": self.is_correct,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
