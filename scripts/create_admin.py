"""
scripts/create_admin.py — Bootstrap initial administrator user.

Usage:
    python scripts/create_admin.py [username] [email] [password]
    Defaults: admin admin@itc.dz admin123
"""

import os
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.extensions import db
from app.models.user import User, UserRole
from app.utils.security import hash_password


def create_admin_user(
    username: str = "admin",
    email: str = "admin@itc.dz",
    password: str = "admin123",
) -> None:
    app = create_app(os.getenv("FLASK_ENV", "development"))
    with app.app_context():
        user = User.query.filter((User.username == username) | (User.email == email)).first()

        if user:
            user.password_hash = hash_password(password)
            user.role = UserRole.ADMIN
            user.is_active = True
            db.session.commit()
            print(f"Updated existing user '{user.username}' as active admin.")
        else:
            new_user = User(
                username=username,
                email=email,
                password_hash=hash_password(password),
                role=UserRole.ADMIN,
                is_active=True,
            )
            db.session.add(new_user)
            db.session.commit()
            print(f"Created new admin user '{username}' ({email}).")


if __name__ == "__main__":
    u = sys.argv[1] if len(sys.argv) > 1 else "admin"
    e = sys.argv[2] if len(sys.argv) > 2 else "admin@itc.dz"
    p = sys.argv[3] if len(sys.argv) > 3 else "admin123"
    create_admin_user(u, e, p)
