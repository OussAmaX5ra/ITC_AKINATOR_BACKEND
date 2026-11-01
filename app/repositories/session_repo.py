"""
app/repositories/session_repo.py — Data access queries for the Session model.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.extensions import db
from app.models.session import (
    GameCategory,
    GameLanguage,
    GameResult,
    Session,
    SessionSource,
    SessionStatus,
)


class SessionRepository:
    """Repository managing Session records."""

    @staticmethod
    def create(
        source: SessionSource,
        language: GameLanguage,
        category: GameCategory,
        device_id: Optional[uuid.UUID | str] = None,
        prompt_version_id: Optional[int] = None,
        llm_model: Optional[str] = None,
    ) -> Session:
        dev_uuid = None
        if device_id:
            dev_uuid = uuid.UUID(str(device_id))

        session = Session(
            source=source,
            language=language,
            category=category,
            device_id=dev_uuid,
            prompt_version_id=prompt_version_id,
            llm_model=llm_model,
            status=SessionStatus.ACTIVE,
        )
        db.session.add(session)
        db.session.commit()
        return session

    @staticmethod
    def get_by_id(session_id: uuid.UUID | str) -> Optional[Session]:
        if isinstance(session_id, str):
            try:
                session_id = uuid.UUID(session_id)
            except ValueError:
                return None
        return db.session.get(Session, session_id)

    @staticmethod
    def update_status(
        session_id: uuid.UUID | str,
        status: SessionStatus,
        result: Optional[GameResult] = None,
        ended_at: Optional[datetime] = None,
        question_count: Optional[int] = None,
    ) -> Optional[Session]:
        session = SessionRepository.get_by_id(session_id)
        if session:
            session.status = status
            if result is not None:
                session.result = result
            if ended_at is not None:
                session.ended_at = ended_at
            elif status in (SessionStatus.FINISHED, SessionStatus.ABANDONED) and session.ended_at is None:
                session.ended_at = datetime.now(timezone.utc)
            if question_count is not None:
                session.question_count = question_count
            db.session.commit()
        return session

    @staticmethod
    def increment_question_count(session_id: uuid.UUID | str) -> Optional[Session]:
        session = SessionRepository.get_by_id(session_id)
        if session:
            session.question_count += 1
            db.session.commit()
        return session

    @staticmethod
    def list_sessions(
        status: Optional[SessionStatus] = None,
        source: Optional[SessionSource] = None,
        device_id: Optional[uuid.UUID | str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Session]:
        query = db.select(Session)
        if status is not None:
            query = query.filter_by(status=status)
        if source is not None:
            query = query.filter_by(source=source)
        if device_id is not None:
            dev_uuid = uuid.UUID(str(device_id))
            query = query.filter_by(device_id=dev_uuid)

        query = query.order_by(Session.started_at.desc()).limit(limit).offset(offset)
        return list(db.session.scalars(query).all())

    @staticmethod
    def count_sessions(status: Optional[SessionStatus] = None) -> int:
        query = db.select(db.func.count(Session.id))
        if status is not None:
            query = query.filter_by(status=status)
        return db.session.scalar(query) or 0
