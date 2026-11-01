"""
app/models/prompt_version.py — Versioned LLM system prompts by language.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class PromptLanguage(str, enum.Enum):
    AR = "ar"
    FR = "fr"
    EN = "en"


class PromptVersion(db.Model):
    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, default="game_system")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    language: Mapped[PromptLanguage] = mapped_column(
        Enum(PromptLanguage, native_enum=False, length=10),
        nullable=False,
        default=PromptLanguage.EN,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    sessions = relationship("Session", back_populates="prompt_version", lazy="select")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "language": self.language.value if isinstance(self.language, PromptLanguage) else str(self.language),
            "content": self.content,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
