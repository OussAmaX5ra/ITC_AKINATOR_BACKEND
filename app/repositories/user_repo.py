"""
app/repositories/user_repo.py — Data access queries for the User model.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from app.extensions import db
from app.models.user import User, UserRole


class UserRepository:
    """Repository managing User records."""

    @staticmethod
    def create(
        username: str,
        email: str,
        password_hash: str,
        role: UserRole = UserRole.OPERATOR,
        is_active: bool = True,
    ) -> User:
        user = User(
            username=username,
            email=email,
            password_hash=password_hash,
            role=role,
            is_active=is_active,
        )
        db.session.add(user)
        db.session.commit()
        return user

    @staticmethod
    def get_by_id(user_id: int) -> Optional[User]:
        return db.session.get(User, user_id)

    @staticmethod
    def get_by_username(username: str) -> Optional[User]:
        query = db.select(User).filter_by(username=username)
        return db.session.scalar(query)

    @staticmethod
    def get_by_email(email: str) -> Optional[User]:
        query = db.select(User).filter_by(email=email)
        return db.session.scalar(query)

    @staticmethod
    def update_last_login(user_id: int) -> Optional[User]:
        user = UserRepository.get_by_id(user_id)
        if user:
            user.last_login_at = datetime.now(timezone.utc)
            db.session.commit()
        return user

    @staticmethod
    def list_users() -> List[User]:
        query = db.select(User).order_by(User.id.asc())
        return list(db.session.scalars(query).all())
