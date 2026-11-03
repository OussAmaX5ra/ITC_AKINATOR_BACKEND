"""
app/api/games.py — REST API endpoints for the Akinator game loop.

Endpoints
---------
POST /api/games                     — Start a new game session
GET  /api/games/<session_id>         — Retrieve game session details
POST /api/games/<session_id>/answer  — Submit player answer to current question
POST /api/games/<session_id>/verdict — Submit verdict on engine guess
POST /api/games/<session_id>/teach   — Submit correct entity name on defeat
POST /api/games/<session_id>/abandon — Abandon an active game session
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from app.api.schemas import (
    GameStartedResponse,
    StartGameRequest,
    SubmitAnswerRequest,
    SubmitVerdictRequest,
    TeachRequest,
    TeachResponse,
    TurnResponse,
    VerdictResponse,
)
from app.extensions import limiter
from app.repositories.session_repo import SessionRepository
from app.services.game import engine, session_store

logger = logging.getLogger(__name__)

games_bp = Blueprint("games", __name__, url_prefix="/api/games")


@games_bp.route("", methods=["POST"])
@games_bp.route("/", methods=["POST"])
@limiter.limit("10/minute")
def start_game():
    """Start a new game session.

    Request Body:
        { "category": "character", "language": "en" }

    Response (201 Created):
        { "session_id": "...", "first_question": "...", "category": "character", "language": "en", "status": "active" }
    """
    payload = request.get_json(silent=True) or {}
    try:
        req = StartGameRequest.model_validate(payload)
    except ValidationError as err:
        return jsonify({"error": "Bad Request", "code": 400, "detail": err.errors()}), 400

    try:
        session_id = engine.start_game(
            category=req.category.value,
            language=req.language.value,
            source=req.source.value,
            device_id=req.device_id,
        )
    except Exception as exc:
        logger.error("Failed to start game session: %s", exc, exc_info=True)
        return jsonify({"error": "Internal Server Error", "code": 500, "detail": str(exc)}), 500

    state = session_store.get_session(session_id)
    first_question = state.get("last_question") if state else None

    response_data = GameStartedResponse(
        session_id=session_id,
        first_question=first_question,
        category=req.category.value,
        language=req.language.value,
        status="active",
    )
    return jsonify(response_data.model_dump()), 201


@games_bp.route("/<session_id>", methods=["GET"])
def get_game_session(session_id: str):
    """Retrieve details and turn history of a game session."""
    session = SessionRepository.get_by_id(session_id)
    if not session:
        return (
            jsonify({"error": "Not Found", "code": 404, "detail": f"Session '{session_id}' not found."}),
            404,
        )
    return jsonify(session.to_dict(include_turns=True)), 200


@games_bp.route("/<session_id>/answer", methods=["POST"])
@limiter.limit("60/minute")
def submit_answer(session_id: str):
    """Submit an answer to the current question.

    Request Body:
        { "answer": "yes", "input_method": "button" }

    Response (200 OK):
        { "session_id": "...", "action": "ask"|"guess", "question": "...", ... }
    """
    payload = request.get_json(silent=True) or {}
    try:
        req = SubmitAnswerRequest.model_validate(payload)
    except ValidationError as err:
        return jsonify({"error": "Bad Request", "code": 400, "detail": err.errors()}), 400

    try:
        action = engine.process_answer(
            session_id=session_id,
            answer=req.answer.value,
            input_method=req.input_method.value,
            confidence=req.confidence,
            latency_ms=req.latency_ms,
        )
    except KeyError:
        return (
            jsonify({"error": "Not Found", "code": 404, "detail": f"Session '{session_id}' not found."}),
            404,
        )
    except ValueError as exc:
        return (
            jsonify({"error": "Conflict", "code": 409, "detail": str(exc)}),
            409,
        )
    except Exception as exc:
        logger.error("Error processing answer in session %s: %s", session_id, exc, exc_info=True)
        return jsonify({"error": "Internal Server Error", "code": 500, "detail": str(exc)}), 500

    resp = TurnResponse.model_validate(action)
    return jsonify(resp.model_dump()), 200


@games_bp.route("/<session_id>/verdict", methods=["POST"])
def submit_verdict(session_id: str):
    """Submit a verdict on whether the engine's guess was correct.

    Request Body:
        { "is_correct": true }

    Response (200 OK):
        { "session_id": "...", "outcome": "win"|"continue"|"teach", ... }
    """
    payload = request.get_json(silent=True) or {}
    try:
        req = SubmitVerdictRequest.model_validate(payload)
    except ValidationError as err:
        return jsonify({"error": "Bad Request", "code": 400, "detail": err.errors()}), 400

    try:
        result = engine.submit_verdict(session_id=session_id, is_correct=req.is_correct)
    except KeyError:
        return (
            jsonify({"error": "Not Found", "code": 404, "detail": f"Session '{session_id}' not found."}),
            404,
        )
    except Exception as exc:
        logger.error("Error processing verdict in session %s: %s", session_id, exc, exc_info=True)
        return jsonify({"error": "Internal Server Error", "code": 500, "detail": str(exc)}), 500

    resp = VerdictResponse.model_validate(result)
    return jsonify(resp.model_dump()), 200


@games_bp.route("/<session_id>/teach", methods=["POST"])
def submit_teach(session_id: str):
    """Submit the correct entity name on Akinator defeat.

    Request Body:
        { "correct_name": "Alan Turing" }

    Response (200 OK):
        { "session_id": "...", "status": "ok", "message": "...", "submission_id": 1 }
    """
    payload = request.get_json(silent=True) or {}
    try:
        req = TeachRequest.model_validate(payload)
    except ValidationError as err:
        return jsonify({"error": "Bad Request", "code": 400, "detail": err.errors()}), 400

    try:
        result = engine.submit_teach(session_id=session_id, correct_name=req.correct_name)
    except KeyError:
        return (
            jsonify({"error": "Not Found", "code": 404, "detail": f"Session '{session_id}' not found."}),
            404,
        )
    except ValueError as exc:
        return (
            jsonify({"error": "Bad Request", "code": 400, "detail": str(exc)}),
            400,
        )
    except Exception as exc:
        logger.error("Error processing teach submission in session %s: %s", session_id, exc, exc_info=True)
        return jsonify({"error": "Internal Server Error", "code": 500, "detail": str(exc)}), 500

    resp = TeachResponse.model_validate(result)
    return jsonify(resp.model_dump()), 200


@games_bp.route("/<session_id>/abandon", methods=["POST"])
def abandon_game(session_id: str):
    """Abandon an active game session."""
    try:
        result = engine.abandon_session(session_id)
    except Exception as exc:
        logger.error("Error abandoning session %s: %s", session_id, exc, exc_info=True)
        return jsonify({"error": "Internal Server Error", "code": 500, "detail": str(exc)}), 500
    return jsonify(result), 200
