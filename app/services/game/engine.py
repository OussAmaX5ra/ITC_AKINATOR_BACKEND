"""
app/services/game/engine.py — Core Akinator Game Engine Orchestrator.

Responsibilities
----------------
* Orchestrates the complete game lifecycle: starting sessions, processing answers,
  deciding whether to ask another question or propose a guess, recording verdicts,
  and handling teach submissions upon defeat.
* Coordinates persistence across PostgreSQL (permanent session, turn, guess, and teach records)
  and Redis (ephemeral active game state, candidates, and Q&A history).
* Implements termination criteria:
    1. Confidence >= GUESS_CONFIDENCE (default 0.85) -> Propose guess
    2. question_count == MAX_QUESTIONS (default 20) -> Forced guess
    3. guesses_made >= MAX_GUESSES (default 3) -> Defeat (Lose & prompt teach)
* Emits 'thinking' state immediately upon receiving an answer prior to processing.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from app.models.entity import EntityCategory
from app.models.guess import Guess
from app.models.session import (
    GameCategory,
    GameLanguage,
    GameResult,
    Session,
    SessionSource,
    SessionStatus,
)
from app.models.turn import InputMethod, TurnAnswer
from app.repositories.entity_repo import EntityRepository
from app.repositories.guess_repo import GuessRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.teach_repo import TeachRepository
from app.repositories.turn_repo import TurnRepository
from app.services.events import (
    publish_guess_event,
    publish_state_change,
    publish_turn_event,
    publish_verdict_event,
)
from app.services.game import candidates, fallback, session_store
from app.services.game.session_store import GameState

logger = logging.getLogger(__name__)

# Defaults if not present in Flask config
_DEFAULT_MAX_QUESTIONS = 20
_DEFAULT_GUESS_CONFIDENCE = 0.85
_DEFAULT_MAX_GUESSES = 3


def _get_config_value(key: str, default: Any) -> Any:
    """Safely fetch a configuration value from current_app or return default."""
    try:
        from flask import current_app
        return current_app.config.get(key, default)
    except RuntimeError:
        return default


def start_game(
    category: str,
    language: str = "en",
    source: str = "web",
    device_id: Optional[str] = None,
) -> str:
    """Start a new game session.

    1. Creates a persistent Session record in PostgreSQL.
    2. Loads candidate entities for the requested category from DB.
    3. Initializes the ephemeral session state in Redis with candidate scores.
    4. Computes and sets the initial question.
    5. Returns the session_id UUID string.

    Parameters
    ----------
    category:
        "character", "animal", or "object".
    language:
        "en", "fr", or "ar".
    source:
        "web" or "robot".
    device_id:
        Optional device UUID string if source == "robot".

    Returns
    -------
    str
        UUID string of the created session.
    """
    cat_enum = GameCategory(category.lower())
    lang_enum = GameLanguage(language.lower())
    src_enum = SessionSource(source.lower())

    # 1. Create DB session record
    db_session = SessionRepository.create(
        source=src_enum,
        language=lang_enum,
        category=cat_enum,
        device_id=device_id,
    )
    sess_id = str(db_session.id)

    # 2. Load candidate scores from DB
    candidate_scores = candidates.load_candidates(cat_enum.value)

    # 3. Create Redis session state
    session_store.create_session(
        session_id=sess_id,
        category=cat_enum.value,
        language=lang_enum.value,
        source=src_enum.value,
        device_id=device_id,
        candidate_scores=candidate_scores,
    )

    # 4. Prepare the initial question in session state
    get_next_action(sess_id)

    # 5. Broadcast game started to live stream
    publish_state_change(
        sess_id,
        GameState.ASKING,
        device_id=device_id,
        extra={"category": cat_enum.value, "language": lang_enum.value},
    )

    logger.info(
        "Game started: session_id=%s, category=%s, language=%s, candidates=%d",
        sess_id,
        cat_enum.value,
        lang_enum.value,
        len(candidate_scores),
    )
    return sess_id


def process_answer(
    session_id: str,
    answer: str,
    input_method: str = "button",
    confidence: Optional[float] = None,
    latency_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Process an answer submitted for the current question.

    1. Immediately emits 'thinking' state in Redis.
    2. Updates candidate scores based on the answer and targeted attribute.
    3. Increments turn count, saves the Turn record to DB and session history.
    4. Evaluates termination criteria and returns the next action (question or guess).

    Parameters
    ----------
    session_id:
        UUID string of the session.
    answer:
        One of "yes", "no", "dont_know", "probably", "probably_not".
    input_method:
        One of "voice", "button", "touch".
    confidence:
        Optional confidence of the answer (e.g. from speech recognizer).
    latency_ms:
        Optional response latency in milliseconds.

    Returns
    -------
    dict
        Next action dict:
        {"action": "ask", "question": str, "turn_no": int, ...} or
        {"action": "guess", "guess_name": str, "entity_id": int, ...}
    """
    state = session_store.get_session(session_id)
    if state is None:
        raise KeyError(f"Session '{session_id}' not found in Redis.")

    if state.get("state") == GameState.FINISHED:
        raise ValueError(f"Session '{session_id}' has already finished.")

    # 1. Immediately emit thinking state in Redis and Pub/Sub
    session_store.update_session(session_id, {"state": GameState.THINKING})
    publish_state_change(session_id, GameState.THINKING, device_id=state.get("device_id"))

    # Validate enum strings
    turn_ans = TurnAnswer(answer.lower())
    inp_method = InputMethod(input_method.lower())

    last_question = state.get("last_question") or "Initial Question"
    last_attr_key = state.get("last_attribute_key")
    current_scores = state.get("candidate_scores", {})

    # 2. Update candidate scores if we had a targeted attribute
    if last_attr_key:
        cache = candidates.build_entity_cache(current_scores)
        new_scores = candidates.update_scores(
            candidate_scores=current_scores,
            answer=turn_ans.value,
            attribute_key=last_attr_key,
            entities_cache=cache,
        )
    else:
        new_scores = current_scores

    # 3. Append turn to Redis history (increments question_count)
    updated_state = session_store.append_turn_to_history(
        session_id=session_id,
        question=last_question,
        answer=turn_ans.value,
        attribute_key=last_attr_key,
        confidence=confidence,
    )
    turn_no = updated_state["question_count"]

    # 4. Insert Turn record in PostgreSQL
    TurnRepository.create(
        session_id=session_id,
        turn_no=turn_no,
        question=last_question,
        answer=turn_ans,
        input_method=inp_method,
        confidence=confidence,
        latency_ms=latency_ms,
    )

    # Broadcast turn event to admin live stream
    publish_turn_event(
        session_id=session_id,
        turn_no=turn_no,
        question=last_question,
        answer=turn_ans.value,
        input_method=inp_method.value,
        confidence=confidence,
        latency_ms=latency_ms,
        device_id=state.get("device_id"),
    )

    # 5. Update session in PostgreSQL
    SessionRepository.update_status(
        session_id=session_id,
        status=SessionStatus.ACTIVE,
        question_count=turn_no,
    )

    # 6. Save updated scores to Redis
    session_store.update_session(session_id, {"candidate_scores": new_scores})

    # 7. Compute next action
    return get_next_action(session_id)


def get_next_action(session_id: str) -> Dict[str, Any]:
    """Evaluate current session state and decide whether to ask a question or propose a guess.

    Criteria:
    * guesses_made >= MAX_GUESSES -> Action: 'lose'
    * top_confidence >= GUESS_CONFIDENCE -> Action: 'guess'
    * turn_count >= MAX_QUESTIONS -> Action: 'guess' (forced guess)
    * If best attribute found -> Action: 'ask'
    * If no attributes remain -> Forced guess or lose

    Returns
    -------
    dict
        Structured action payload.
    """
    state = session_store.get_session(session_id)
    if state is None:
        raise KeyError(f"Session '{session_id}' not found in Redis.")

    if state.get("state") == GameState.FINISHED:
        return {
            "session_id": session_id,
            "action": "finished",
            "message": "Session is already finished.",
        }

    candidate_scores = state.get("candidate_scores", {})
    excluded_ids = state.get("excluded_entity_ids", [])
    question_count = state.get("question_count", 0)
    guesses_made = state.get("guesses_made", 0)
    language = state.get("language", "en")

    max_questions = int(_get_config_value("MAX_QUESTIONS", _DEFAULT_MAX_QUESTIONS))
    guess_confidence = float(_get_config_value("GUESS_CONFIDENCE", _DEFAULT_GUESS_CONFIDENCE))
    max_guesses = int(_get_config_value("MAX_GUESSES", _DEFAULT_MAX_GUESSES))

    # Check if max guesses exceeded
    if guesses_made >= max_guesses:
        SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.FINISHED,
            result=GameResult.LOSE,
        )
        session_store.update_session(session_id, {"state": GameState.FINISHED})
        return {
            "session_id": session_id,
            "action": "lose",
            "message": "Max guesses reached without a correct answer.",
            "turn_no": question_count,
            "guesses_made": guesses_made,
            "confidence": 0.0,
        }

    # Identify best candidate and its confidence
    best_candidate = candidates.get_best_guess(
        candidate_scores, excluded_ids=excluded_ids
    )
    best_id, top_conf = best_candidate if best_candidate else (None, 0.0)

    # Determine if we should make a guess
    should_guess = False
    if best_id is not None and guesses_made < max_guesses:
        if top_conf >= guess_confidence:
            should_guess = True
        elif question_count >= max_questions:
            should_guess = True

    if should_guess:
        return _propose_guess(
            session_id=session_id,
            entity_id=int(best_id),
            confidence=top_conf,
            guess_no=guesses_made + 1,
            language=language,
            turn_no=question_count,
        )

    # Otherwise: Ask next best question
    asked_attrs = [
        t.get("attribute_key")
        for t in state.get("history", [])
        if t.get("attribute_key")
    ]
    cache = candidates.build_entity_cache(candidate_scores)
    best_attr = fallback.select_best_question(
        candidate_scores, entities_cache=cache, asked_attributes=asked_attrs
    )

    if best_attr is None:
        # No more attributes can be asked. If we have any candidate left, force a guess.
        if best_id is not None and guesses_made < max_guesses:
            return _propose_guess(
                session_id=session_id,
                entity_id=int(best_id),
                confidence=top_conf,
                guess_no=guesses_made + 1,
                language=language,
                turn_no=question_count,
            )
        # Otherwise, no candidates or guesses remain -> lose
        SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.FINISHED,
            result=GameResult.LOSE,
        )
        session_store.update_session(session_id, {"state": GameState.FINISHED})
        return {
            "session_id": session_id,
            "action": "lose",
            "message": "No remaining questions or candidates.",
            "turn_no": question_count,
            "guesses_made": guesses_made,
            "confidence": 0.0,
        }

    # Generate question text
    q_text = fallback.generate_question_text(best_attr, language)

    # Update session state in Redis
    session_store.update_session(
        session_id,
        {
            "state": GameState.ASKING,
            "last_question": q_text,
            "last_attribute_key": best_attr,
        },
    )

    return {
        "session_id": session_id,
        "action": "ask",
        "question": q_text,
        "attribute_key": best_attr,
        "confidence": top_conf,
        "turn_no": question_count + 1,
        "guesses_made": guesses_made,
    }


def _propose_guess(
    session_id: str,
    entity_id: int,
    confidence: float,
    guess_no: int,
    language: str,
    turn_no: int,
) -> Dict[str, Any]:
    """Helper to record and return a guess proposal."""
    entity = EntityRepository.get_by_id(entity_id)
    guess_name = entity.name if entity else f"Entity #{entity_id}"
    if entity and entity.names_i18n and entity.names_i18n.get(language):
        guess_name = entity.names_i18n[language]

    guess_record = GuessRepository.create(
        session_id=session_id,
        guess_name=guess_name,
        guess_no=guess_no,
        confidence=confidence,
        entity_id=entity_id,
    )

    session_store.update_session(
        session_id,
        {
            "state": GameState.GUESSING,
            "current_guess_id": guess_record.id,
            "current_guess_entity_id": entity_id,
            "current_guess_name": guess_name,
        },
    )

    # Broadcast guess event to admin live stream
    curr_state = session_store.get_session(session_id)
    device_id = curr_state.get("device_id") if curr_state else None
    publish_guess_event(
        session_id=session_id,
        guess_name=guess_name,
        entity_id=entity_id,
        confidence=confidence,
        guess_no=guess_no,
        turn_no=turn_no,
        device_id=device_id,
    )

    logger.info(
        "Proposing guess #%d: '%s' (id=%d, confidence=%.3f) for session %s",
        guess_no,
        guess_name,
        entity_id,
        confidence,
        session_id,
    )

    return {
        "session_id": session_id,
        "action": "guess",
        "guess_id": guess_record.id,
        "guess_name": guess_name,
        "entity_id": entity_id,
        "confidence": confidence,
        "turn_no": turn_no,
        "guess_no": guess_no,
        "guesses_made": guess_no - 1,
    }


def submit_verdict(session_id: str, is_correct: bool) -> Dict[str, Any]:
    """Submit a verdict on whether the engine's last proposed guess was correct.

    Parameters
    ----------
    session_id:
        UUID string of the session.
    is_correct:
        True if the guess was correct, False otherwise.

    Returns
    -------
    dict
        Outcome payload:
        {"outcome": "win"|"continue"|"teach", ...}
    """
    state = session_store.get_session(session_id)
    if state is None:
        raise KeyError(f"Session '{session_id}' not found in Redis.")

    current_guess_id = state.get("current_guess_id")
    current_guess_eid = state.get("current_guess_entity_id")
    guess_name = state.get("current_guess_name", "")

    # Update Guess record in DB
    if current_guess_id:
        GuessRepository.update_verdict(current_guess_id, is_correct)

    # Update Entity statistics
    if current_guess_eid:
        EntityRepository.increment_stats(current_guess_eid, correct=is_correct)

    if is_correct:
        # Akinator Wins!
        SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.FINISHED,
            result=GameResult.WIN,
        )
        session_store.update_session(session_id, {"state": GameState.FINISHED})

        logger.info("Session %s ended with WIN (guess: '%s')", session_id, guess_name)
        publish_verdict_event(
            session_id=session_id,
            outcome="win",
            is_correct=True,
            guess_name=guess_name,
            device_id=state.get("device_id"),
        )
        return {
            "session_id": session_id,
            "outcome": "win",
            "message": f"I guessed it! It's {guess_name}.",
            "guess_name": guess_name,
        }

    # Wrong guess: add to excluded candidates and increment guesses_made
    if current_guess_eid:
        session_store.add_excluded_entity(session_id, current_guess_eid)
    else:
        current_guesses = state.get("guesses_made", 0) + 1
        session_store.update_session(session_id, {"guesses_made": current_guesses})

    refreshed_state = session_store.get_session(session_id)
    guesses_made = refreshed_state.get("guesses_made", 0) if refreshed_state else 0
    max_guesses = int(_get_config_value("MAX_GUESSES", _DEFAULT_MAX_GUESSES))

    if guesses_made >= max_guesses:
        # Defeat: Prompt player to teach the correct entity
        SessionRepository.update_status(
            session_id=session_id,
            status=SessionStatus.FINISHED,
            result=GameResult.LOSE,
        )
        session_store.update_session(session_id, {"state": GameState.FINISHED})

        logger.info("Session %s ended with DEFEAT (max guesses reached)", session_id)
        return {
            "session_id": session_id,
            "outcome": "teach",
            "message": "I give up! You defeated me. Please teach me who you were thinking of.",
            "guesses_made": guesses_made,
        }

    # Continue game with next action
    session_store.update_session(session_id, {"state": GameState.ASKING})
    next_action = get_next_action(session_id)

    if next_action.get("action") == "lose":
        return {
            "session_id": session_id,
            "outcome": "teach",
            "message": "I have no more guesses. Please teach me!",
            "guesses_made": guesses_made,
            "next_action": next_action,
        }

    return {
        "session_id": session_id,
        "outcome": "continue",
        "message": "Wrong guess. Let me think more...",
        "guesses_made": guesses_made,
        "next_action": next_action,
    }


def submit_teach(session_id: str, correct_name: str) -> Dict[str, Any]:
    """Record a user submission teaching the system the correct entity after a loss.

    Parameters
    ----------
    session_id:
        UUID string of the session.
    correct_name:
        The name of the entity the user was thinking of.

    Returns
    -------
    dict
        Confirmation payload with submission ID.
    """
    clean_name = correct_name.strip()
    if not clean_name:
        raise ValueError("Submitted entity name cannot be empty.")

    db_session = SessionRepository.get_by_id(session_id)
    if not db_session:
        raise KeyError(f"Session '{session_id}' not found in database.")

    # Retrieve Q&A trail from Redis (or reconstruct from DB turns)
    state = session_store.get_session(session_id)
    if state and state.get("history"):
        qa_trail = state["history"]
    else:
        turns = TurnRepository.get_turns_by_session(session_id)
        qa_trail = [
            {
                "turn_no": t.turn_no,
                "question": t.question,
                "answer": t.answer.value if hasattr(t.answer, "value") else str(t.answer),
                "input_method": t.input_method.value if hasattr(t.input_method, "value") else str(t.input_method),
            }
            for t in turns
        ]

    # Check if this entity already exists in the KB
    existing_entity = EntityRepository.get_by_name_and_category(
        clean_name, db_session.category
    )
    entity_id = existing_entity.id if existing_entity else None

    # Insert TeachSubmission
    submission = TeachRepository.create(
        session_id=session_id,
        submitted_name=clean_name,
        qa_trail=qa_trail,
        entity_id=entity_id,
    )

    # Ensure DB session is marked finished with LOSE
    SessionRepository.update_status(
        session_id=session_id,
        status=SessionStatus.FINISHED,
        result=GameResult.LOSE,
    )

    # Clean up ephemeral Redis session state
    session_store.delete_session(session_id)

    logger.info(
        "Teach submission recorded: session=%s, entity='%s', submission_id=%d",
        session_id,
        clean_name,
        submission.id,
    )
    publish_state_change(
        session_id,
        "teach_submitted",
        device_id=state.get("device_id") if state else None,
        extra={"submitted_name": clean_name, "submission_id": submission.id},
    )

    return {
        "session_id": session_id,
        "status": "ok",
        "message": f"Thank you! I learned about '{clean_name}'.",
        "submission_id": submission.id,
    }


def abandon_session(session_id: str) -> Dict[str, Any]:
    """Mark an active session as abandoned and delete its Redis state.

    Parameters
    ----------
    session_id:
        UUID string of the session.

    Returns
    -------
    dict
        Status payload.
    """
    SessionRepository.update_status(
        session_id=session_id,
        status=SessionStatus.ABANDONED,
    )
    session_store.delete_session(session_id)

    logger.info("Session %s abandoned", session_id)
    publish_state_change(session_id, SessionStatus.ABANDONED.value)
    return {
        "session_id": session_id,
        "status": "abandoned",
        "message": "Session marked as abandoned.",
    }
