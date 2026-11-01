"""
app/repositories/entity_repo.py — Data access queries for the Entity (Knowledge Base) model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.extensions import db
from app.models.entity import Entity, EntityCategory, EntitySource


class EntityRepository:
    """Repository managing Entity knowledge base records."""

    @staticmethod
    def create(
        name: str,
        category: EntityCategory,
        names_i18n: Optional[Dict[str, str]] = None,
        attributes: Optional[Dict[str, float]] = None,
        source: EntitySource = EntitySource.SEED,
        is_approved: bool = True,
    ) -> Entity:
        entity = Entity(
            name=name,
            category=category,
            names_i18n=names_i18n or {},
            attributes=attributes or {},
            source=source,
            is_approved=is_approved,
        )
        db.session.add(entity)
        db.session.commit()
        return entity

    @staticmethod
    def get_by_id(entity_id: int) -> Optional[Entity]:
        return db.session.get(Entity, entity_id)

    @staticmethod
    def get_by_name_and_category(name: str, category: EntityCategory) -> Optional[Entity]:
        query = db.select(Entity).filter_by(name=name, category=category)
        return db.session.scalar(query)

    @staticmethod
    def list_approved_by_category(category: EntityCategory) -> List[Entity]:
        """Fetch all approved entities for a given category (uses composite index)."""
        query = (
            db.select(Entity)
            .filter_by(category=category, is_approved=True)
            .order_by(Entity.name.asc())
        )
        return list(db.session.scalars(query).all())

    @staticmethod
    def list_entities(
        category: Optional[EntityCategory] = None,
        is_approved: Optional[bool] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Entity]:
        query = db.select(Entity)
        if category is not None:
            query = query.filter_by(category=category)
        if is_approved is not None:
            query = query.filter_by(is_approved=is_approved)
        if search:
            query = query.filter(Entity.name.ilike(f"%{search}%"))

        query = query.order_by(Entity.id.asc()).limit(limit).offset(offset)
        return list(db.session.scalars(query).all())

    @staticmethod
    def count_entities(category: Optional[EntityCategory] = None, is_approved: Optional[bool] = None) -> int:
        query = db.select(db.func.count(Entity.id))
        if category is not None:
            query = query.filter_by(category=category)
        if is_approved is not None:
            query = query.filter_by(is_approved=is_approved)
        return db.session.scalar(query) or 0

    @staticmethod
    def update(entity_id: int, **kwargs: Any) -> Optional[Entity]:
        entity = EntityRepository.get_by_id(entity_id)
        if entity:
            for key, val in kwargs.items():
                if hasattr(entity, key):
                    setattr(entity, key, val)
            db.session.commit()
        return entity

    @staticmethod
    def increment_stats(entity_id: int, correct: bool = False) -> Optional[Entity]:
        entity = EntityRepository.get_by_id(entity_id)
        if entity:
            entity.times_guessed += 1
            if correct:
                entity.times_correct += 1
            db.session.commit()
        return entity

    @staticmethod
    def bulk_insert(items: List[Dict[str, Any]]) -> int:
        count = 0
        for item in items:
            name = item.get("name")
            cat_val = item.get("category", "character")
            category = EntityCategory(cat_val) if isinstance(cat_val, str) else cat_val

            existing = EntityRepository.get_by_name_and_category(name, category)
            if existing:
                existing.names_i18n = item.get("names_i18n", existing.names_i18n)
                existing.attributes = item.get("attributes", existing.attributes)
                existing.is_approved = item.get("is_approved", existing.is_approved)
            else:
                entity = Entity(
                    name=name,
                    category=category,
                    names_i18n=item.get("names_i18n", {}),
                    attributes=item.get("attributes", {}),
                    source=item.get("source", EntitySource.SEED),
                    is_approved=item.get("is_approved", True),
                )
                db.session.add(entity)
                count += 1
        db.session.commit()
        return count
