"""
app/api/schemas.py — Pydantic request and response schemas for REST endpoints.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.models.entity import EntityCategory
from app.models.session import GameCategory, GameLanguage, SessionSource
from app.models.turn import InputMethod, TurnAnswer


# ── Request Schemas ───────────────────────────────────────────────────────────


class StartGameRequest(BaseModel):
    """Payload for starting a new game session (POST /api/games)."""

    model_config = ConfigDict(extra="forbid")

    category: GameCategory = Field(
        default=GameCategory.CHARACTER,
        description="Category of the entity to guess (character, animal, object).",
    )
    language: GameLanguage = Field(
        default=GameLanguage.EN,
        description="Game language (en, fr, ar).",
    )
    source: SessionSource = Field(
        default=SessionSource.WEB,
        description="Session source client (web or robot).",
    )
    device_id: Optional[str] = Field(
        default=None,
        description="Optional UUID of the physical robot device.",
    )


class SubmitAnswerRequest(BaseModel):
    """Payload for submitting a player answer (POST /api/games/{id}/answer)."""

    model_config = ConfigDict(extra="forbid")

    answer: TurnAnswer = Field(
        description="Answer to the question (yes, no, dont_know, probably, probably_not).",
    )
    input_method: InputMethod = Field(
        default=InputMethod.BUTTON,
        description="Input modality used (button, voice, touch).",
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence of voice input from STT.",
    )
    latency_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional client-side or STT latency in ms.",
    )


class SubmitVerdictRequest(BaseModel):
    """Payload for submitting a guess verdict (POST /api/games/{id}/verdict)."""

    model_config = ConfigDict(extra="forbid")

    is_correct: bool = Field(
        description="Whether the engine's guess was correct.",
    )


class TeachRequest(BaseModel):
    """Payload for teaching the Akinator after defeat (POST /api/games/{id}/teach)."""

    model_config = ConfigDict(extra="forbid")

    correct_name: str = Field(
        min_length=1,
        max_length=150,
        description="The correct entity name the player was thinking of.",
    )


# ── Response Schemas ──────────────────────────────────────────────────────────


class GameStartedResponse(BaseModel):
    """Response returned when a new game session starts."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    first_question: Optional[str] = None
    category: str
    language: str
    status: str = "active"


class TurnResponse(BaseModel):
    """Response returned for an engine action (question, guess, or result)."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    action: str  # 'ask', 'guess', 'lose', 'finished'
    question: Optional[str] = None
    attribute_key: Optional[str] = None
    guess_name: Optional[str] = None
    guess_id: Optional[int] = None
    entity_id: Optional[int] = None
    confidence: float = 0.0
    turn_no: int = 0
    guesses_made: int = 0
    message: Optional[str] = None


class VerdictResponse(BaseModel):
    """Response returned after submitting a verdict."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    outcome: str  # 'win', 'continue', 'teach'
    message: str
    guess_name: Optional[str] = None
    guesses_made: Optional[int] = None
    next_action: Optional[Dict[str, Any]] = None


class TeachResponse(BaseModel):
    """Response returned after submitting a teach entry."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    status: str
    message: str
    submission_id: Optional[int] = None
