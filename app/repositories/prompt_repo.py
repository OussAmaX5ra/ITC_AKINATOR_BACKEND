"""
app/repositories/prompt_repo.py — Data access queries for the PromptVersion model.
"""

from __future__ import annotations

from typing import List, Optional

from app.extensions import db
from app.models.prompt_version import PromptLanguage, PromptVersion


class PromptRepository:
    """Repository managing PromptVersion records."""

    @staticmethod
    def get_active_by_language(
        language: PromptLanguage | str,
        name: str = "game_system",
    ) -> Optional[PromptVersion]:
        lang_val = PromptLanguage(language) if isinstance(language, str) else language
        query = (
            db.select(PromptVersion)
            .filter_by(name=name, language=lang_val, is_active=True)
            .order_by(PromptVersion.version.desc())
        )
        return db.session.scalar(query)

    @staticmethod
    def list_versions(
        language: Optional[PromptLanguage | str] = None,
        name: Optional[str] = None,
    ) -> List[PromptVersion]:
        query = db.select(PromptVersion)
        if language is not None:
            lang_val = PromptLanguage(language) if isinstance(language, str) else language
            query = query.filter_by(language=lang_val)
        if name is not None:
            query = query.filter_by(name=name)
        query = query.order_by(PromptVersion.version.desc())
        return list(db.session.scalars(query).all())

    @staticmethod
    def create(
        name: str,
        version: int,
        language: PromptLanguage | str,
        content: str,
        is_active: bool = True,
    ) -> PromptVersion:
        lang_val = PromptLanguage(language) if isinstance(language, str) else language

        # If this new version is active, deactivate existing ones for the same name and language
        if is_active:
            existing_active = db.session.scalars(
                db.select(PromptVersion).filter_by(name=name, language=lang_val, is_active=True)
            ).all()
            for p in existing_active:
                p.is_active = False

        prompt = PromptVersion(
            name=name,
            version=version,
            language=lang_val,
            content=content,
            is_active=is_active,
        )
        db.session.add(prompt)
        db.session.commit()
        return prompt

    @staticmethod
    def set_active_version(prompt_id: int) -> Optional[PromptVersion]:
        target = db.session.get(PromptVersion, prompt_id)
        if target:
            # Deactivate all others with same name and language
            all_same = db.session.scalars(
                db.select(PromptVersion).filter_by(name=target.name, language=target.language)
            ).all()
            for p in all_same:
                p.is_active = (p.id == target.id)
            db.session.commit()
        return target
