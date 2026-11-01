"""
app/repositories/guess_repo.py — Data access queries for the Guess model.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from app.extensions import db
from app.models.guess import Guess


class GuessRepository:
    """Repository managing Guess records."""

    @staticmethod
    def create(
        session_id: uuid.UUID | str,
        guess_name: str,
        guess_no: int,
        confidence: float,
        entity_id: Optional[int] = None,
        is_correct: Optional[bool] = None,
    ) -> Guess:
        sess_uuid = uuid.UUID(str(session_id))
        guess = Guess(
            session_id=sess_uuid,
            guess_name=guess_name,
            guess_no=guess_no,
            confidence=confidence,
            entity_id=entity_id,
            is_correct=is_correct,
        )
        db.session.add(guess)
        db.session.commit()
        return guess

    @staticmethod
    def get_by_id(guess_id: int) -> Optional[Guess]:
        return db.session.get(Guess, guess_id)

    @staticmethod
    def update_verdict(guess_id: int, is_correct: bool) -> Optional[Guess]:
        guess = GuessRepository.get_by_id(guess_id)
        if guess:
            guess.is_correct = is_correct
            db.session.commit()
        return guess

    @staticmethod
    def get_guesses_by_session(session_id: uuid.UUID | str) -> List[Guess]:
        sess_uuid = uuid.UUID(str(session_id))
        query = (
            db.select(Guess)
            .filter_by(session_id=sess_uuid)
            .order_by(Guess.guess_no.asc())
        )
        return list(db.session.scalars(query).all())
