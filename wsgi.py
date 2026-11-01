"""
wsgi.py — Gunicorn production entry point.

Usage:
    gunicorn -w 4 -k gevent -b 0.0.0.0:5000 wsgi:app

The create_app() factory reads FLASK_ENV (development | production | testing)
from the environment; defaults to 'development'.
"""
import os
from app import create_app

app = create_app(os.getenv("FLASK_ENV", "development"))
