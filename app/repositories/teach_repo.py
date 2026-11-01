"""
app/repositories/teach_repo.py — Data access queries for the TeachSubmission model.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.extensions import db
from app.models.teach_submission import TeachStatus, TeachSubmission


class TeachRepository:
    """Repository managing TeachSubmission records."""

    @staticmethod
    def create(
        session_id: uuid.UUID | str,
        submitted_name: str,
        qa_trail: List[Dict[str, Any]],
        entity_id: Optional[int] = None,
    ) -> TeachSubmission:
        sess_uuid = uuid.UUID(str(session_id))
        submission = TeachSubmission(
            session_id=sess_uuid,
            submitted_name=submitted_name,
            qa_trail=qa_trail,
            entity_id=entity_id,
            status=TeachStatus.PENDING,
        )
        db.session.add(submission)
        db.session.commit()
        return submission

    @staticmethod
    def get_by_id(submission_id: int) -> Optional[TeachSubmission]:
        return db.session.get(TeachSubmission, submission_id)

    @staticmethod
    def list_by_status(
        status: Optional[TeachStatus] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[TeachSubmission]:
        query = db.select(TeachSubmission)
        if status is not None:
            query = query.filter_by(status=status)
        query = query.order_by(TeachSubmission.created_at.desc()).limit(limit).offset(offset)
        return list(db.session.scalars(query).all())

    @staticmethod
    def count_by_status(status: Optional[TeachStatus] = None) -> int:
        query = db.select(db.func.count(TeachSubmission.id))
        if status is not None:
            query = query.filter_by(status=status)
        return db.session.scalar(query) or 0

    @staticmethod
    def update_status(
        submission_id: int,
        status: TeachStatus,
        reviewed_by: Optional[int] = None,
        entity_id: Optional[int] = None,
    ) -> Optional[TeachSubmission]:
        submission = TeachRepository.get_by_id(submission_id)
        if submission:
            submission.status = status
            submission.reviewed_at = datetime.now(timezone.utc)
            if reviewed_by is not None:
                submission.reviewed_by = reviewed_by
            if entity_id is not None:
                submission.entity_id = entity_id
            db.session.commit()
        return submission
