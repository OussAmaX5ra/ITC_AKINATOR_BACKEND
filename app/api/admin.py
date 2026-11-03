"""
app/api/admin.py — Administrator dashboard, game analytics, prompt management, and teach moderation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError
from sqlalchemy import func

from app.api.auth import role_required
from app.api.schemas import ApproveTeachRequest, CreatePromptVersionRequest
from app.extensions import db
from app.models.entity import Entity, EntityCategory, EntitySource
from app.models.prompt_version import PromptLanguage, PromptVersion
from app.models.session import (
    GameCategory,
    GameLanguage,
    GameResult,
    Session,
    SessionSource,
    SessionStatus,
)
from app.models.teach_submission import TeachStatus, TeachSubmission
from app.models.turn import InputMethod, Turn
from app.repositories.entity_repo import EntityRepository
from app.repositories.prompt_repo import PromptRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.teach_repo import TeachRepository

logger = logging.getLogger(__name__)

def _parse_iso_datetime(val: str) -> datetime:
    """Parse ISO datetime string, supporting Z and URL-decoded + offsets."""
    cleaned = val.strip().replace("Z", "+00:00")
    if " " in cleaned and cleaned.rfind(" ") > cleaned.rfind("T"):
        idx = cleaned.rfind(" ")
        cleaned = cleaned[:idx] + "+" + cleaned[idx + 1 :]
    return datetime.fromisoformat(cleaned)


admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


# ── 1. Analytics & Dashboard Statistics ──────────────────────────────────────


@admin_bp.get("/stats")
@role_required("admin")
def get_dashboard_stats() -> Any:
    """
    GET /api/admin/stats — Aggregate platform statistics:
      - Total games played, win rate, average question count
      - Distribution per category & language
      - Average STT latency
      - Games today, this week, and this month
    """
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    week_start = today_start - timedelta(days=now.weekday())  # Start of current week (Monday)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    total_games = db.session.scalar(db.select(func.count(Session.id))) or 0
    total_wins = db.session.scalar(db.select(func.count(Session.id)).filter_by(result=GameResult.WIN)) or 0
    total_losses = db.session.scalar(db.select(func.count(Session.id)).filter_by(result=GameResult.LOSE)) or 0
    total_finished = total_wins + total_losses

    win_rate = round((total_wins / total_finished) * 100, 2) if total_finished > 0 else 0.0

    avg_questions_raw = db.session.scalar(db.select(func.avg(Session.question_count)))
    avg_questions = round(float(avg_questions_raw), 2) if avg_questions_raw is not None else 0.0

    # Games per category
    cat_query = db.session.execute(
        db.select(Session.category, func.count(Session.id)).group_by(Session.category)
    ).all()
    games_per_category: Dict[str, int] = {
        (cat.value if hasattr(cat, "value") else str(cat)): count for cat, count in cat_query
    }

    # Games per language
    lang_query = db.session.execute(
        db.select(Session.language, func.count(Session.id)).group_by(Session.language)
    ).all()
    games_per_language: Dict[str, int] = {
        (lang.value if hasattr(lang, "value") else str(lang)): count for lang, count in lang_query
    }

    # Average STT Latency (Voice turns only, with valid latency_ms)
    stt_latency_raw = db.session.scalar(
        db.select(func.avg(Turn.latency_ms)).filter(
            Turn.input_method == InputMethod.VOICE, Turn.latency_ms.is_not(None)
        )
    )
    avg_stt_latency_ms = round(float(stt_latency_raw), 1) if stt_latency_raw is not None else None

    # Temporal counts
    games_today = db.session.scalar(
        db.select(func.count(Session.id)).filter(Session.started_at >= today_start)
    ) or 0
    games_this_week = db.session.scalar(
        db.select(func.count(Session.id)).filter(Session.started_at >= week_start)
    ) or 0
    games_this_month = db.session.scalar(
        db.select(func.count(Session.id)).filter(Session.started_at >= month_start)
    ) or 0

    return (
        jsonify(
            {
                "total_games": total_games,
                "total_wins": total_wins,
                "total_losses": total_losses,
                "win_rate_percent": win_rate,
                "avg_question_count": avg_questions,
                "games_per_category": games_per_category,
                "games_per_language": games_per_language,
                "avg_stt_latency_ms": avg_stt_latency_ms,
                "games_today": games_today,
                "games_this_week": games_this_week,
                "games_this_month": games_this_month,
            }
        ),
        200,
    )


# ── 2. Session Inspection & Filtering ─────────────────────────────────────────


@admin_bp.get("/sessions")
@role_required("admin")
def list_admin_sessions() -> Any:
    """
    GET /api/admin/sessions — List sessions with filters (status, source, device_id, date range).
    Query parameters:
      - status: 'active' | 'finished' | 'abandoned'
      - source: 'web' | 'robot'
      - device_id: UUID
      - date_from: ISO datetime
      - date_to: ISO datetime
      - page: int (default 1)
      - limit: int (default 20, max 100)
    """
    status_param = request.args.get("status")
    status_filter: Optional[SessionStatus] = None
    if status_param:
        try:
            status_filter = SessionStatus(status_param.lower())
        except ValueError:
            return jsonify({"error": "Bad Request", "code": 400, "detail": f"Invalid status '{status_param}'."}), 400

    source_param = request.args.get("source")
    source_filter: Optional[SessionSource] = None
    if source_param:
        try:
            source_filter = SessionSource(source_param.lower())
        except ValueError:
            return jsonify({"error": "Bad Request", "code": 400, "detail": f"Invalid source '{source_param}'."}), 400

    device_param = request.args.get("device_id")
    device_filter: Optional[uuid.UUID] = None
    if device_param:
        try:
            device_filter = uuid.UUID(device_param)
        except ValueError:
            return jsonify({"error": "Bad Request", "code": 400, "detail": "Invalid device_id UUID."}), 400

    date_from: Optional[datetime] = None
    if request.args.get("date_from"):
        try:
            date_from = _parse_iso_datetime(request.args.get("date_from"))
        except ValueError:
            return jsonify({"error": "Bad Request", "code": 400, "detail": "Invalid date_from ISO format."}), 400

    date_to: Optional[datetime] = None
    if request.args.get("date_to"):
        try:
            date_to = _parse_iso_datetime(request.args.get("date_to"))
        except ValueError:
            return jsonify({"error": "Bad Request", "code": 400, "detail": "Invalid date_to ISO format."}), 400

    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(100, max(1, int(request.args.get("limit", 20))))
    except ValueError:
        return jsonify({"error": "Bad Request", "code": 400, "detail": "Page and limit must be positive integers."}), 400

    offset = (page - 1) * limit

    sessions = SessionRepository.list_sessions(
        status=status_filter,
        source=source_filter,
        device_id=device_filter,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    total = SessionRepository.count_sessions(
        status=status_filter,
        source=source_filter,
        device_id=device_filter,
        date_from=date_from,
        date_to=date_to,
    )

    return (
        jsonify(
            {
                "sessions": [s.to_dict(include_turns=False) for s in sessions],
                "total": total,
                "page": page,
                "limit": limit,
            }
        ),
        200,
    )


@admin_bp.get("/sessions/<session_id>")
@role_required("admin")
def get_admin_session_detail(session_id: str) -> Any:
    """
    GET /api/admin/sessions/{id} — Detailed game session audit with all turns, guesses, and teach trails.
    """
    try:
        sess_uuid = uuid.UUID(session_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Bad Request", "code": 400, "detail": "Invalid session UUID format."}), 400

    session = SessionRepository.get_by_id(sess_uuid)
    if not session:
        return jsonify({"error": "Not Found", "code": 404, "detail": f"Session '{session_id}' not found."}), 404

    return jsonify(session.to_dict(include_turns=True)), 200


# ── 3. Teach Submissions Review ───────────────────────────────────────────────


@admin_bp.get("/teach-submissions")
@role_required("admin")
def list_teach_submissions() -> Any:
    """
    GET /api/admin/teach-submissions — List pending or filtered player teach submissions.
    Query parameters:
      - status: 'pending' (default) | 'approved' | 'rejected' | 'all'
      - page: int (default 1)
      - limit: int (default 20, max 100)
    """
    status_param = request.args.get("status", "pending").lower()
    status_filter: Optional[TeachStatus] = None
    if status_param != "all":
        try:
            status_filter = TeachStatus(status_param)
        except ValueError:
            return jsonify({"error": "Bad Request", "code": 400, "detail": f"Invalid status '{status_param}'."}), 400

    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(100, max(1, int(request.args.get("limit", 20))))
    except ValueError:
        return jsonify({"error": "Bad Request", "code": 400, "detail": "Page and limit must be positive integers."}), 400

    offset = (page - 1) * limit

    subs = TeachRepository.list_by_status(status=status_filter, limit=limit, offset=offset)
    total = TeachRepository.count_by_status(status=status_filter)

    return (
        jsonify(
            {
                "teach_submissions": [s.to_dict() for s in subs],
                "total": total,
                "page": page,
                "limit": limit,
            }
        ),
        200,
    )


@admin_bp.post("/teach-submissions/<int:submission_id>/approve")
@role_required("admin")
def approve_teach_submission(submission_id: int) -> Any:
    """
    POST /api/admin/teach-submissions/{id}/approve — Approve teach submission.
    Optionally creates or updates an Entity record in the KB using extracted Q&A attributes.
    """
    sub = TeachRepository.get_by_id(submission_id)
    if not sub:
        return jsonify({"error": "Not Found", "code": 404, "detail": f"Submission #{submission_id} not found."}), 404

    reviewer_id_raw = getattr(g, "current_user_id", None)
    reviewer_id = int(reviewer_id_raw) if reviewer_id_raw else None

    # Parse optional approval payload
    payload = request.get_json(silent=True) or {}
    try:
        req = ApproveTeachRequest(**payload)
    except ValidationError as err:
        return jsonify({"error": "Bad Request", "code": 400, "detail": err.errors()}), 400

    session = SessionRepository.get_by_id(sub.session_id)
    target_category = req.category or (session.category if session else EntityCategory.CHARACTER)

    entity_id = sub.entity_id

    if req.create_entity:
        # Determine attributes: use explicit if provided, else extract from Q&A trail
        attrs = req.attributes
        if attrs is None:
            attrs = {}
            for t in (sub.qa_trail or []):
                attr_key = t.get("attribute_key")
                ans_str = str(t.get("answer", "")).lower()
                if attr_key:
                    if ans_str in ("yes", "probably"):
                        attrs[attr_key] = 1.0 if ans_str == "yes" else 0.5
                    elif ans_str in ("no", "probably_not"):
                        attrs[attr_key] = -1.0 if ans_str == "no" else -0.5
                    elif ans_str == "dont_know":
                        attrs[attr_key] = 0.0

        names_i18n = req.names_i18n or {"en": sub.submitted_name}

        if entity_id:
            # Update existing entity
            existing_ent = EntityRepository.get_by_id(entity_id)
            merged_attrs = dict(existing_ent.attributes or {}) if existing_ent else {}
            merged_attrs.update(attrs)
            merged_names = dict(existing_ent.names_i18n or {}) if existing_ent else {}
            merged_names.update(names_i18n)
            EntityRepository.update(
                entity_id,
                names_i18n=merged_names,
                attributes=merged_attrs,
                is_approved=True,
            )
        else:
            # Check if entity with same name and category already exists
            existing_ent = EntityRepository.get_by_name_and_category(sub.submitted_name, target_category)
            if existing_ent:
                entity_id = existing_ent.id
                merged_attrs = dict(existing_ent.attributes or {})
                merged_attrs.update(attrs)
                merged_names = dict(existing_ent.names_i18n or {})
                merged_names.update(names_i18n)
                EntityRepository.update(
                    entity_id,
                    names_i18n=merged_names,
                    attributes=merged_attrs,
                    is_approved=True,
                )
            else:
                new_ent = EntityRepository.create(
                    name=sub.submitted_name,
                    category=target_category,
                    names_i18n=names_i18n,
                    attributes=attrs,
                    source=EntitySource.LEARNED,
                    is_approved=True,
                )
                entity_id = new_ent.id

    # Update submission record
    TeachRepository.update_status(
        submission_id=submission_id,
        status=TeachStatus.APPROVED,
        reviewed_by=reviewer_id,
        entity_id=entity_id,
    )

    logger.info("Admin approved teach submission #%d -> entity #%s", submission_id, entity_id)
    return (
        jsonify(
            {
                "status": "approved",
                "submission_id": submission_id,
                "entity_id": entity_id,
                "message": f"Teach submission #{submission_id} approved successfully.",
            }
        ),
        200,
    )


@admin_bp.post("/teach-submissions/<int:submission_id>/reject")
@role_required("admin")
def reject_teach_submission(submission_id: int) -> Any:
    """
    POST /api/admin/teach-submissions/{id}/reject — Reject a teach submission.
    """
    sub = TeachRepository.get_by_id(submission_id)
    if not sub:
        return jsonify({"error": "Not Found", "code": 404, "detail": f"Submission #{submission_id} not found."}), 404

    reviewer_id_raw = getattr(g, "current_user_id", None)
    reviewer_id = int(reviewer_id_raw) if reviewer_id_raw else None

    TeachRepository.update_status(
        submission_id=submission_id,
        status=TeachStatus.REJECTED,
        reviewed_by=reviewer_id,
    )

    logger.info("Admin rejected teach submission #%d", submission_id)
    return (
        jsonify(
            {
                "status": "rejected",
                "submission_id": submission_id,
                "message": f"Teach submission #{submission_id} rejected.",
            }
        ),
        200,
    )


# ── 4. Versioned Prompt Management ───────────────────────────────────────────


@admin_bp.get("/prompt-versions")
@role_required("admin")
def list_prompt_versions() -> Any:
    """
    GET /api/admin/prompt-versions — List prompt versions grouped by language.
    Optional query parameter: 'language' (ar, fr, en).
    """
    lang_param = request.args.get("language")
    lang_filter: Optional[PromptLanguage] = None
    if lang_param:
        try:
            lang_filter = PromptLanguage(lang_param.lower())
        except ValueError:
            return jsonify({"error": "Bad Request", "code": 400, "detail": f"Invalid language '{lang_param}'."}), 400

    prompts = PromptRepository.list_versions(language=lang_filter)
    prompts_dicts = [p.to_dict() for p in prompts]

    grouped: Dict[str, List[Dict[str, Any]]] = {"en": [], "fr": [], "ar": []}
    for pd in prompts_dicts:
        l_key = pd.get("language", "en")
        if l_key not in grouped:
            grouped[l_key] = []
        grouped[l_key].append(pd)

    return (
        jsonify(
            {
                "prompt_versions": prompts_dicts,
                "grouped_by_language": grouped,
                "total": len(prompts_dicts),
            }
        ),
        200,
    )


@admin_bp.post("/prompt-versions")
@role_required("admin")
def create_prompt_version() -> Any:
    """
    POST /api/admin/prompt-versions — Create a new prompt version.
    Automatically deactivates prior versions if is_active is True.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Bad Request", "code": 400, "detail": "Invalid or missing JSON body."}), 400

    try:
        req = CreatePromptVersionRequest(**payload)
    except ValidationError as err:
        return jsonify({"error": "Bad Request", "code": 400, "detail": err.errors()}), 400

    # If version not specified, calculate next sequential version
    version_no = req.version
    if version_no is None:
        existing = PromptRepository.list_versions(language=req.language, name=req.name)
        version_no = (max([p.version for p in existing]) + 1) if existing else 1

    prompt = PromptRepository.create(
        name=req.name,
        version=version_no,
        language=req.language,
        content=req.content,
        is_active=req.is_active,
    )

    logger.info("Admin created prompt version: %s v%d [%s]", prompt.name, prompt.version, prompt.language.value)
    return jsonify(prompt.to_dict()), 201
