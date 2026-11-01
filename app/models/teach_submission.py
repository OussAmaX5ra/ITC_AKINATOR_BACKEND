"""
app/models/teach_submission.py — Player-submitted answers and Q&A trails when the Akinator loses.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.extensions import db

# Portable JSON type: native JSONB on PostgreSQL, JSON on SQLite
JSONType = JSONB().with_variant(JSON(), "sqlite")


class TeachStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class TeachSubmission(db.Model):
    __tablename__ = "teach_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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
    submitted_name: Mapped[str] = mapped_column(String(150), nullable=False)
    qa_trail: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONType, nullable=False, default=list
    )
    status: Mapped[TeachStatus] = mapped_column(
        Enum(TeachStatus, native_enum=False, length=20),
        nullable=False,
        default=TeachStatus.PENDING,
        index=True,
    )
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    session = relationship("Session", back_populates="teach_submissions")
    entity = relationship("Entity", back_populates="teach_submissions")
    reviewer = relationship("User", back_populates="reviewed_teach_submissions")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": str(self.session_id),
            "entity_id": self.entity_id,
            "submitted_name": self.submitted_name,
            "qa_trail": self.qa_trail or [],
            "status": self.status.value if isinstance(self.status, TeachStatus) else str(self.status),
            "reviewed_by": self.reviewed_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }
