"""
app/__init__.py — Flask App Factory (stub).

Full implementation is completed in Milestone 1.3.
"""


def create_app(config_name: str = "development"):
    """Application factory — returns a configured Flask application instance."""
    from flask import Flask

    app = Flask(__name__)
    return app
