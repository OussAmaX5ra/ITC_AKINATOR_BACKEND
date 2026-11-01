"""
app/models/entity.py — Knowledge base entities (characters, animals, objects).
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import Boolean, DateTime, Enum, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.extensions import db

# Portable JSON type: native JSONB on PostgreSQL, JSON on SQLite
JSONType = JSONB().with_variant(JSON(), "sqlite")


class EntityCategory(str, enum.Enum):
    CHARACTER = "character"
    ANIMAL = "animal"
    OBJECT = "object"


class EntitySource(str, enum.Enum):
    SEED = "seed"
    LEARNED = "learned"


class Entity(db.Model):
    __tablename__ = "entities"
    __table_args__ = (
        Index("ix_entities_category_is_approved", "category", "is_approved"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    names_i18n: Mapped[Dict[str, str]] = mapped_column(
        JSONType, nullable=False, default=dict
    )
    category: Mapped[EntityCategory] = mapped_column(
        Enum(EntityCategory, native_enum=False, length=20),
        nullable=False,
        default=EntityCategory.CHARACTER,
        index=True,
    )
    attributes: Mapped[Dict[str, float]] = mapped_column(
        JSONType, nullable=False, default=dict
    )
    times_guessed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    times_correct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[EntitySource] = mapped_column(
        Enum(EntitySource, native_enum=False, length=10),
        nullable=False,
        default=EntitySource.SEED,
    )
    is_approved: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    guesses: Mapped[List["Guess"]] = relationship("Guess", back_populates="entity")
    teach_submissions: Mapped[List["TeachSubmission"]] = relationship(
        "TeachSubmission", back_populates="entity"
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "names_i18n": self.names_i18n or {},
            "category": self.category.value if isinstance(self.category, EntityCategory) else str(self.category),
            "attributes": self.attributes or {},
            "times_guessed": self.times_guessed,
            "times_correct": self.times_correct,
            "source": self.source.value if isinstance(self.source, EntitySource) else str(self.source),
            "is_approved": self.is_approved,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
