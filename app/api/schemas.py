"""
app/api/schemas.py — Pydantic request and response schemas for REST endpoints.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.models.entity import EntityCategory
from app.models.prompt_version import PromptLanguage
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


class LoginRequest(BaseModel):
    """Payload for operator/admin login (POST /api/auth/login)."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=1,
        max_length=120,
        description="Username or email address of the account.",
    )
    password: str = Field(
        min_length=1,
        max_length=255,
        description="Plaintext password for authentication.",
    )


class RefreshTokenRequest(BaseModel):
    """Payload for refreshing an expired access token (POST /api/auth/refresh)."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: Optional[str] = Field(
        default=None,
        description="Refresh token (can alternatively be passed via Authorization Bearer header).",
    )


class RegisterDeviceRequest(BaseModel):
    """Payload for registering a new robot device (POST /api/devices/register)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=100,
        description="Display name for robot hardware.",
    )
    firmware_version: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Initial firmware version string.",
    )


class DeviceHeartbeatRequest(BaseModel):
    """Payload for robot heartbeat telemetry (POST /api/devices/{id}/heartbeat)."""

    model_config = ConfigDict(extra="forbid")

    camera_ok: Optional[bool] = Field(
        default=None,
        description="Camera operational status flag.",
    )
    mic_ok: Optional[bool] = Field(
        default=None,
        description="Microphone operational status flag.",
    )
    firmware_version: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Reported firmware version.",
    )


class CreateEntityRequest(BaseModel):
    """Payload for creating a new knowledge base entity (POST /api/entities)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=150,
        description="Entity canonical name.",
    )
    category: EntityCategory = Field(
        default=EntityCategory.CHARACTER,
        description="Entity category (character, animal, object).",
    )
    names_i18n: Dict[str, str] = Field(
        default_factory=dict,
        description="Localized entity names map (e.g. {'en': '...', 'fr': '...', 'ar': '...'}).",
    )
    attributes: Dict[str, float] = Field(
        default_factory=dict,
        description="Attribute probabilities dictionary (attribute_key -> score in [-1.0, 1.0]).",
    )
    is_approved: bool = Field(
        default=True,
        description="Whether the entity is active and approved for gameplay.",
    )


class UpdateEntityRequest(BaseModel):
    """Payload for updating an existing knowledge base entity (PUT /api/entities/{id})."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=150,
        description="Entity canonical name.",
    )
    category: Optional[EntityCategory] = Field(
        default=None,
        description="Entity category.",
    )
    names_i18n: Optional[Dict[str, str]] = Field(
        default=None,
        description="Localized entity names map.",
    )
    attributes: Optional[Dict[str, float]] = Field(
        default=None,
        description="Attribute probabilities dictionary.",
    )
    is_approved: Optional[bool] = Field(
        default=None,
        description="Approval / active status.",
    )


class CreatePromptVersionRequest(BaseModel):
    """Payload for creating a new version of system prompts (POST /api/admin/prompt-versions)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        default="game_system",
        max_length=50,
        description="Prompt identifier name.",
    )
    language: PromptLanguage = Field(
        description="Target language for prompt version (ar, fr, en).",
    )
    content: str = Field(
        min_length=1,
        description="Full system prompt text.",
    )
    version: Optional[int] = Field(
        default=None,
        ge=1,
        description="Explicit version number (autoincrements if omitted).",
    )
    is_active: bool = Field(
        default=True,
        description="Whether to activate this version immediately (deactivates previous active versions).",
    )


class ApproveTeachRequest(BaseModel):
    """Optional payload for approving a teach submission (POST /api/admin/teach-submissions/{id}/approve)."""

    model_config = ConfigDict(extra="forbid")

    category: Optional[EntityCategory] = Field(
        default=None,
        description="Category of the entity to create/update.",
    )
    names_i18n: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional translations dictionary.",
    )
    attributes: Optional[Dict[str, float]] = Field(
        default=None,
        description="Optional explicit attributes (if omitted, extracted from Q&A trail).",
    )
    create_entity: bool = Field(
        default=True,
        description="Whether to insert a new Entity record if not already linked.",
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


class UserResponse(BaseModel):
    """User profile data returned in auth/admin endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: str
    is_active: bool
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None


class LoginResponse(BaseModel):
    """Payload returned upon successful authentication."""

    model_config = ConfigDict(from_attributes=True)

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    user: UserResponse


class RefreshResponse(BaseModel):
    """Payload returned upon successful token refresh."""

    model_config = ConfigDict(from_attributes=True)

    access_token: str
    token_type: str = "Bearer"


class RegisterDeviceResponse(BaseModel):
    """Payload returned when a new device is registered."""

    model_config = ConfigDict(from_attributes=True)

    device_id: str
    name: str
    device_token: str
    status: str
    created_at: Optional[str] = None


class DeviceItemResponse(BaseModel):
    """Device details including live Redis online status."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: str
    camera_ok: bool
    mic_ok: bool
    firmware_version: Optional[str] = None
    last_heartbeat: Optional[str] = None
    created_at: Optional[str] = None


class DeviceListResponse(BaseModel):
    """List of all registered devices with online telemetry."""

    model_config = ConfigDict(from_attributes=True)

    devices: List[DeviceItemResponse]
    total: int


class DeviceHeartbeatResponse(BaseModel):
    """Response payload returned after recording a heartbeat."""

    model_config = ConfigDict(from_attributes=True)

    status: str
    device_id: str
    last_heartbeat: Optional[str] = None


class EntityResponse(BaseModel):
    """Entity representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    names_i18n: Dict[str, str] = Field(default_factory=dict)
    attributes: Dict[str, float] = Field(default_factory=dict)
    times_guessed: int
    times_correct: int
    source: str
    is_approved: bool
    created_at: Optional[str] = None


class EntityListResponse(BaseModel):
    """Paginated list of entities."""

    model_config = ConfigDict(from_attributes=True)

    entities: List[EntityResponse]
    total: int
    page: int
    limit: int


class BulkSeedResponse(BaseModel):
    """Result of bulk seed operation."""

    model_config = ConfigDict(from_attributes=True)

    status: str
    imported_count: int
    message: str
