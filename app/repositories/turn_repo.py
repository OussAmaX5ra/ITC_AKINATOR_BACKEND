"""
app/repositories/turn_repo.py — Data access queries for the Turn model.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from app.extensions import db
from app.models.turn import InputMethod, Turn, TurnAnswer


class TurnRepository:
    """Repository managing Turn records."""

    @staticmethod
    def create(
        session_id: uuid.UUID | str,
        turn_no: int,
        question: str,
        answer: TurnAnswer,
        input_method: InputMethod = InputMethod.BUTTON,
        confidence: Optional[float] = None,
        latency_ms: Optional[int] = None,
    ) -> Turn:
        sess_uuid = uuid.UUID(str(session_id))
        turn = Turn(
            session_id=sess_uuid,
            turn_no=turn_no,
            question=question,
            answer=answer,
            input_method=input_method,
            confidence=confidence,
            latency_ms=latency_ms,
        )
        db.session.add(turn)
        db.session.commit()
        return turn

    @staticmethod
    def get_turns_by_session(session_id: uuid.UUID | str) -> List[Turn]:
        sess_uuid = uuid.UUID(str(session_id))
        query = (
            db.select(Turn)
            .filter_by(session_id=sess_uuid)
            .order_by(Turn.turn_no.asc())
        )
        return list(db.session.scalars(query).all())

    @staticmethod
    def get_turn(session_id: uuid.UUID | str, turn_no: int) -> Optional[Turn]:
        sess_uuid = uuid.UUID(str(session_id))
        query = db.select(Turn).filter_by(session_id=sess_uuid, turn_no=turn_no)
        return db.session.scalar(query)
