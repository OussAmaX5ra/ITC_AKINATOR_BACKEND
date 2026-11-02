"""
app/services/game/session_store.py — Redis-backed ephemeral game session store.

Responsibilities
----------------
* Persist the in-flight game state for every active session in Redis under
  the key ``session:{session_id}`` as a JSON document.
* Automatically expire keys after 30 minutes of inactivity (TTL is refreshed
  on every update so only truly idle sessions expire).
* Provide a clean, typed interface to the rest of the game engine so callers
  never touch Redis directly.

Session State Schema
--------------------
{
  "session_id":          str   – UUID of the DB session record
  "state":               str   – GameState enum value ("waiting", "asking",
                                  "thinking", "guessing", "finished")
  "category":            str   – "character" | "animal" | "object"
  "language":            str   – "en" | "fr" | "ar"
  "source":              str   – "robot" | "web"
  "device_id":           str | null
  "question_count":      int   – how many Q&A turns have occurred
  "guesses_made":        int   – number of guesses already submitted
  "history":             list  – ordered list of {question, answer, attribute_key}
  "excluded_entity_ids": list  – entity IDs already guessed (excluded from future)
  "candidate_scores":    dict  – {entity_id_str: float} current probability scores
  "last_question":       str | null – the question text sent in the last turn
  "last_attribute_key":  str | null – attribute key the last question targeted
}
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.extensions import redis_client

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

#: Redis key prefix for all active game sessions.
_KEY_PREFIX = "session:"

#: Default TTL in seconds (30 minutes). Can be overridden via Flask app config.
_DEFAULT_TTL_S: int = 1800


# ── Public GameState enum values (kept as plain strings to avoid import loops)

class GameState:
    """String constants for the ``state`` field of the session document."""

    WAITING = "waiting"      # Session created but game not yet started
    ASKING = "asking"        # Waiting for the player's answer
    THINKING = "thinking"    # Processing the answer / querying LLM
    GUESSING = "guessing"    # Engine is about to make a guess
    FINISHED = "finished"    # Game over (win / lose / abandoned)


# ── Internal helpers ─────────────────────────────────────────────────────────

def _redis_key(session_id: str) -> str:
    """Return the Redis key for a given session UUID string."""
    return f"{_KEY_PREFIX}{session_id}"


def _get_ttl() -> int:
    """Return the configured session TTL in seconds.

    Falls back to the module-level default if the Flask app context is not
    available (e.g., during unit tests with fakeredis).
    """
    try:
        from flask import current_app
        return int(current_app.config.get("SESSION_REDIS_TTL_S", _DEFAULT_TTL_S))
    except RuntimeError:
        return _DEFAULT_TTL_S


# ── Public API ───────────────────────────────────────────────────────────────

def create_session(
    session_id: str,
    category: str,
    language: str,
    source: str,
    device_id: Optional[str] = None,
    candidate_scores: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Create and persist a new game session in Redis.

    Parameters
    ----------
    session_id:
        The UUID string of the DB ``Session`` record.  This becomes the Redis
        key suffix.
    category:
        One of ``"character"``, ``"animal"``, ``"object"``.
    language:
        One of ``"en"``, ``"fr"``, ``"ar"``.
    source:
        ``"robot"`` or ``"web"`` — the client that started this session.
    device_id:
        Optional UUID string of the robot device (``None`` for web sessions).
    candidate_scores:
        Optional pre-computed initial scores ``{entity_id_str: float}``.
        When omitted defaults to ``{}``.

    Returns
    -------
    dict
        The freshly created session state document.

    Raises
    ------
    RuntimeError
        If a session with this ID already exists in Redis.
    """
    key = _redis_key(session_id)

    if redis_client.exists(key):
        raise RuntimeError(
            f"Session '{session_id}' already exists in Redis. "
            "Call delete_session() first or use a new session_id."
        )

    state: Dict[str, Any] = {
        "session_id": session_id,
        "state": GameState.ASKING,
        "category": category,
        "language": language,
        "source": source,
        "device_id": device_id,
        "question_count": 0,
        "guesses_made": 0,
        "history": [],
        "excluded_entity_ids": [],
        "candidate_scores": candidate_scores or {},
        "last_question": None,
        "last_attribute_key": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    ttl = _get_ttl()
    redis_client.setex(key, ttl, json.dumps(state, ensure_ascii=False))

    logger.info(
        "Redis session created",
        extra={
            "session_id": session_id,
            "category": category,
            "language": language,
            "source": source,
            "ttl_s": ttl,
        },
    )

    return state


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve and deserialize an active session from Redis.

    Parameters
    ----------
    session_id:
        UUID string of the session.

    Returns
    -------
    dict or None
        The session state document, or ``None`` if the key does not exist
        (session expired or was never created).
    """
    key = _redis_key(session_id)
    raw = redis_client.get(key)

    if raw is None:
        logger.debug("Redis session not found: %s", session_id)
        return None

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error(
            "Failed to deserialize Redis session %s: %s", session_id, exc
        )
        return None


def update_session(
    session_id: str,
    updates: Dict[str, Any],
    *,
    refresh_ttl: bool = True,
) -> Dict[str, Any]:
    """Apply a partial update to an existing session and (by default) refresh its TTL.

    Only the keys present in *updates* are changed; all other fields are
    preserved.  The ``updated_at`` timestamp is always refreshed automatically.

    Parameters
    ----------
    session_id:
        UUID string of the session to update.
    updates:
        A dict of field-name → new-value pairs to merge into the session.
        Supports any top-level key from the session schema including nested
        replacement of ``candidate_scores``, ``history``, and
        ``excluded_entity_ids``.
    refresh_ttl:
        When ``True`` (the default), the Redis TTL is reset to the configured
        value so active sessions never expire while the game is in progress.

    Returns
    -------
    dict
        The updated session state document.

    Raises
    ------
    KeyError
        If the session does not exist in Redis (may have expired).
    """
    state = get_session(session_id)
    if state is None:
        raise KeyError(
            f"Session '{session_id}' not found in Redis. "
            "It may have expired or was never created."
        )

    # Merge the updates into the existing state
    state.update(updates)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()

    key = _redis_key(session_id)
    serialized = json.dumps(state, ensure_ascii=False)

    if refresh_ttl:
        ttl = _get_ttl()
        redis_client.setex(key, ttl, serialized)
    else:
        # Preserve remaining TTL — do a SET that keeps the current expiry
        remaining = redis_client.ttl(key)
        if remaining > 0:
            redis_client.setex(key, remaining, serialized)
        else:
            # Key has no TTL or already expired (race); set the default
            redis_client.setex(key, _get_ttl(), serialized)

    logger.debug(
        "Redis session updated",
        extra={"session_id": session_id, "updated_keys": list(updates.keys())},
    )

    return state


def delete_session(session_id: str) -> bool:
    """Remove a session from Redis.

    Safe to call even if the session no longer exists (idempotent).

    Parameters
    ----------
    session_id:
        UUID string of the session to remove.

    Returns
    -------
    bool
        ``True`` if the key existed and was deleted, ``False`` if it was
        already absent.
    """
    key = _redis_key(session_id)
    deleted = redis_client.delete(key)

    if deleted:
        logger.info("Redis session deleted: %s", session_id)
    else:
        logger.debug(
            "Redis session delete called but key was not present: %s", session_id
        )

    return bool(deleted)


def session_exists(session_id: str) -> bool:
    """Check whether a session key is present in Redis (without deserializing).

    Parameters
    ----------
    session_id:
        UUID string of the session.

    Returns
    -------
    bool
        ``True`` if the key exists, ``False`` otherwise.
    """
    return bool(redis_client.exists(_redis_key(session_id)))


def get_session_ttl(session_id: str) -> int:
    """Return the remaining TTL in seconds for a session key.

    Parameters
    ----------
    session_id:
        UUID string of the session.

    Returns
    -------
    int
        Remaining TTL in seconds.  Returns ``-2`` if the key does not exist,
        ``-1`` if the key exists but has no expiry set.
    """
    return redis_client.ttl(_redis_key(session_id))


# ── Convenience history helpers ───────────────────────────────────────────────

def append_turn_to_history(
    session_id: str,
    question: str,
    answer: str,
    attribute_key: Optional[str] = None,
    confidence: Optional[float] = None,
) -> Dict[str, Any]:
    """Append one Q&A turn to the session's ``history`` list.

    This is a convenience wrapper around :func:`update_session` that handles
    the read-modify-write pattern atomically enough for single-process use.

    Parameters
    ----------
    session_id:
        UUID string of the session.
    question:
        The question text as shown to the player.
    answer:
        One of ``"yes"``, ``"no"``, ``"dont_know"``, ``"probably"``,
        ``"probably_not"``.
    attribute_key:
        Optional entity attribute key that this question targeted.
    confidence:
        Optional float representing the player's answer confidence (from STT).

    Returns
    -------
    dict
        The updated session state.
    """
    state = get_session(session_id)
    if state is None:
        raise KeyError(f"Session '{session_id}' not found in Redis.")

    turn_entry: Dict[str, Any] = {
        "turn_no": state["question_count"] + 1,
        "question": question,
        "answer": answer,
        "attribute_key": attribute_key,
        "confidence": confidence,
    }

    new_history: List[Dict[str, Any]] = state.get("history", []) + [turn_entry]

    return update_session(
        session_id,
        {
            "history": new_history,
            "question_count": state["question_count"] + 1,
            "last_question": question,
            "last_attribute_key": attribute_key,
        },
    )


def add_excluded_entity(session_id: str, entity_id: int) -> Dict[str, Any]:
    """Mark an entity as already guessed so it is excluded from future candidates.

    Parameters
    ----------
    session_id:
        UUID string of the session.
    entity_id:
        Integer primary key of the guessed entity.

    Returns
    -------
    dict
        The updated session state.
    """
    state = get_session(session_id)
    if state is None:
        raise KeyError(f"Session '{session_id}' not found in Redis.")

    excluded: List[int] = state.get("excluded_entity_ids", [])
    if entity_id not in excluded:
        excluded = excluded + [entity_id]

    return update_session(
        session_id,
        {
            "excluded_entity_ids": excluded,
            "guesses_made": state["guesses_made"] + 1,
        },
    )
