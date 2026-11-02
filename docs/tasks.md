# ITC Akinator Backend — Implementation Task List

> **Purpose:** Step-by-step checklist for the AI agent to follow when building the backend.
> Mark each task `[x]` when completed. Every task maps to the
> [Project_Specification.md](./Project_Specification.md) and the
> [akinator_backend_schemas.drawio](./akinator_backend_schemas.drawio) diagrams.
>
> **Scope:** Backend only — no frontend, no ESP32 firmware, no React UI.

---

## Milestone 1 — Project Skeleton & Foundation

### 1.1 Repository Bootstrap
- [x] Create top-level files: `wsgi.py`, `requirements.txt`, `.env.example`, `.gitignore`
- [x] Create the `app/` package with `__init__.py` (empty Flask app factory stub)
- [x] Create empty directory scaffolding: `app/api/`, `app/ws/`, `app/services/`, `app/models/`, `app/repositories/`, `app/utils/`, `prompts/`, `data/`, `migrations/`, `scripts/`, `tests/`
- [x] Add `__init__.py` files to all Python packages

### 1.2 Configuration & Environment
- [x] Implement `app/config.py` with `Dev`, `Prod`, and `Test` configuration classes loading from environment variables
- [x] Populate `.env.example` with all required keys: `FLASK_ENV`, `SECRET_KEY`, `JWT_SECRET`, `DATABASE_URL`, `REDIS_URL`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `OLLAMA_URL`, `STT_MODEL`, `STT_DEVICE`, `TTS_ENABLED`, `MAX_QUESTIONS`, `GUESS_CONFIDENCE`, `MAX_GUESSES`, `ANSWER_TIMEOUT_S`, `PRESENCE_ARRIVE_S`, `PRESENCE_LEAVE_S`, `DEVICE_HB_TTL_S`

### 1.3 Flask App Factory
- [x] Implement `app/__init__.py` → `create_app(config_name)` factory function
- [x] Register configuration loading from `.env` (python-dotenv)
- [x] Initialize all extensions inside `create_app`
- [x] Register all REST blueprints and WebSocket routes

### 1.4 Extensions Module
- [x] Create `app/extensions.py` and initialize: `SQLAlchemy (db)`, `Flask-Migrate (migrate)`, `Redis client (redis_client)`, `flask-sock (sock)`, `Flask-CORS (cors)`, `Flask-Limiter (limiter)`

### 1.5 Docker & Deployment Setup
- [x] Write `Dockerfile` (multi-stage Python 3.11 build with Gunicorn + gevent)
- [x] Write `docker-compose.yml` with services: `api`, `postgres` (PostgreSQL 16), `redis` (Redis 7), `nginx` (reverse proxy)
- [x] Write `wsgi.py` as the Gunicorn entry point calling `create_app()`

### 1.6 Health Check Endpoint
- [x] Create `app/api/health.py` blueprint
- [x] Implement `GET /api/health` that checks: PostgreSQL connection, Redis connectivity, and basic LLM provider reachability
- [x] Register the health blueprint in the app factory

### 1.7 Logging Setup
- [x] Implement `app/utils/logging.py` with structured JSON logging (request ID, timestamps, log levels)
- [x] Add request logging middleware to the Flask app

### 1.8 Milestone 1 Verification
- [x] `docker-compose up` starts all 4 services without errors
- [x] `GET /api/health` returns `200 OK` with dependency status JSON
- [x] Write `tests/test_health.py` — health endpoint returns correct statuses

---

## Milestone 2 — Database Models & Persistence Layer

### 2.1 SQLAlchemy Models
- [x] `app/models/device.py` — `Device` model: `id` UUID PK, `name` VARCHAR(100), `token_hash` VARCHAR(255), `status` ENUM(`online`, `offline`, `error`), `camera_ok` BOOL, `mic_ok` BOOL, `firmware_version` VARCHAR(50), `last_heartbeat` TIMESTAMPTZ, `created_at` TIMESTAMPTZ
- [x] `app/models/prompt_version.py` — `PromptVersion` model: `id` SERIAL PK, `name` VARCHAR(50), `version` INT, `language` ENUM(`ar`, `fr`, `en`), `content` TEXT, `is_active` BOOL, `created_at` TIMESTAMPTZ
- [x] `app/models/session.py` — `Session` model: `id` UUID PK, `source` ENUM(`robot`, `web`), `device_id` UUID FK→devices (nullable), `prompt_version_id` INT FK→prompt_versions, `language` ENUM(`ar`, `fr`, `en`), `category` ENUM(`character`, `animal`, `object`), `status` ENUM(`active`, `finished`, `abandoned`), `result` ENUM(`win`, `lose`) nullable, `question_count` SMALLINT, `llm_model` VARCHAR(50), `started_at` TIMESTAMPTZ, `ended_at` TIMESTAMPTZ nullable
- [x] `app/models/turn.py` — `Turn` model: `id` BIGSERIAL PK, `session_id` UUID FK→sessions, `turn_no` SMALLINT, `question` TEXT, `answer` ENUM(`yes`, `no`, `dont_know`, `probably`, `probably_not`), `input_method` ENUM(`voice`, `button`, `touch`), `confidence` FLOAT, `latency_ms` INT, `created_at` TIMESTAMPTZ. Constraint: `UNIQUE(session_id, turn_no)`
- [x] `app/models/guess.py` — `Guess` model: `id` BIGSERIAL PK, `session_id` UUID FK→sessions, `entity_id` INT FK→entities (nullable), `guess_name` VARCHAR(150), `guess_no` SMALLINT, `confidence` FLOAT, `is_correct` BOOL nullable, `created_at` TIMESTAMPTZ
- [x] `app/models/entity.py` — `Entity` model: `id` SERIAL PK, `name` VARCHAR(150), `names_i18n` JSONB, `category` ENUM(`character`, `animal`, `object`), `attributes` JSONB, `times_guessed` INT default 0, `times_correct` INT default 0, `source` ENUM(`seed`, `learned`), `is_approved` BOOL default TRUE, `created_at` TIMESTAMPTZ
- [x] `app/models/teach_submission.py` — `TeachSubmission` model: `id` SERIAL PK, `session_id` UUID FK→sessions, `entity_id` INT FK→entities (nullable), `submitted_name` VARCHAR(150), `qa_trail` JSONB, `status` ENUM(`pending`, `approved`, `rejected`), `reviewed_by` INT FK→users (nullable), `created_at` TIMESTAMPTZ, `reviewed_at` TIMESTAMPTZ nullable
- [x] `app/models/user.py` — `User` model: `id` SERIAL PK, `username` VARCHAR(50) UNIQUE, `email` VARCHAR(120) UNIQUE, `password_hash` VARCHAR(255), `role` ENUM(`admin`, `operator`), `is_active` BOOL, `created_at` TIMESTAMPTZ, `last_login_at` TIMESTAMPTZ nullable

### 2.2 Database Indexes & Constraints
- [x] Add `UNIQUE` constraint on `(turns.session_id, turns.turn_no)`
- [x] Add indexes on `sessions(started_at)`, `sessions(device_id)`, `sessions(status)`
- [x] Add index on `entities(category, is_approved)` for fast KB loading
- [x] Add index on `teach_submissions(status)` for pending review queries

### 2.3 Alembic Migrations
- [x] Initialize Flask-Migrate / Alembic: `flask db init`
- [x] Generate initial migration from all models: `flask db migrate`
- [x] Apply migration to the database: `flask db upgrade`
- [x] Verify all 8 tables exist with correct columns and constraints

### 2.4 Seed Data & Scripts
- [x] Create `data/seed_entities.json` minimal mock fixture (3-5 sample entries for developer testing of the loader)
- [x] Implement `scripts/seed_kb.py` CLI script to bulk-insert seed entities from any provided JSON into the `entities` table (idempotent — skip existing)
- [x] Implement `scripts/create_admin.py` CLI script to create initial admin user with hashed password (argon2/bcrypt)

### 2.5 Repositories (Data Access Layer)
- [x] `app/repositories/device_repo.py` — CRUD for devices (create, get by id, list all, update status, update heartbeat)
- [x] `app/repositories/session_repo.py` — Create session, get by id, update status/result/ended_at, list sessions with filtering & pagination
- [x] `app/repositories/turn_repo.py` — Insert turn, get turns by session_id
- [x] `app/repositories/guess_repo.py` — Insert guess, update is_correct, get guesses by session_id
- [x] `app/repositories/entity_repo.py` — CRUD for entities, filter by category & is_approved, bulk insert, update times_guessed/times_correct
- [x] `app/repositories/teach_repo.py` — Insert teach submission, list by status, update status (approve/reject), link entity_id
- [x] `app/repositories/user_repo.py` — Create user, get by username/email, update last_login_at
- [x] `app/repositories/prompt_repo.py` — Get active prompt by language, list all versions, create new version

### 2.6 Milestone 2 Verification
- [x] All 8 tables created successfully via migration
- [x] Seed script executes idempotently with test fixture
- [x] Admin user created and can be retrieved from DB
- [x] Write `tests/test_models.py` — model creation and relationship integrity tests

---

## Milestone 3 — Game Engine (Knowledge-Base Mode)

### 3.1 Redis Session Store
- [x] Implement `app/services/game/session_store.py`
- [x] `create_session(session_id, category, language, device_id)` → SET `session:{id}` JSON in Redis with TTL 30 min
- [x] `get_session(session_id)` → parse Redis JSON to session state dict
- [x] `update_session(session_id, updates)` → partial update and refresh TTL
- [x] `delete_session(session_id)` → cleanup on game end
- [x] Session state schema: `{state, category, language, device_id, question_count, guesses_made, history[], excluded_entity_ids[], candidate_scores{}}`

### 3.2 Candidate Scoring Engine
- [x] Implement `app/services/game/candidates.py`
- [x] `load_candidates(category)` → fetch all approved entities for the given category from DB, return dict `{entity_id: 1.0}` (initial score)
- [x] `update_scores(candidate_scores, answer, attribute_key)` → apply scoring weights: yes +1.0, probably +0.5, dont_know 0, probably_not −0.5, no −1.0 multiplied by `match(entity.attributes[attr])`
- [x] `get_top_k(candidate_scores, k=10, excluded_ids=[])` → return top-K candidates sorted by score, excluding already-guessed entity IDs
- [x] `get_best_guess(candidate_scores, excluded_ids=[])` → return top-1 candidate with its confidence score

### 3.3 Information Gain Fallback (KB-Only Mode)
- [x] Implement `app/services/game/fallback.py`
- [x] `compute_entropy(candidate_scores)` → H(C) = −Σ P(c) log₂ P(c)
- [x] `compute_information_gain(question_attr, candidates)` → IG(q) = H(C) − Σₐ P(a|q) H(C|a,q)
- [x] `select_best_question(candidates, asked_attributes)` → return attribute with highest IG, excluding already-asked attributes
- [x] `generate_question_text(attribute_key, language)` → map attribute key to a natural-language yes/no question in the correct language

### 3.4 Game Engine Orchestrator
- [x] Implement `app/services/game/engine.py`
- [x] `start_game(category, language, source, device_id=None)` → create DB session, create Redis session state, load candidates, return session_id
- [x] `process_answer(session_id, answer, input_method)` → update candidate scores, increment turn count, insert Turn record in DB, check termination criteria
- [x] `get_next_action(session_id)` → returns `{action: "ask", question, confidence}` or `{action: "guess", guess_name, entity_id, confidence}` based on current state
- [x] `submit_verdict(session_id, is_correct)` → update Guess record, handle win/lose/continue logic
- [x] `submit_teach(session_id, correct_name)` → insert TeachSubmission with full Q&A trail from Redis history
- [x] `abandon_session(session_id)` → mark session as abandoned in DB, delete Redis key
- [x] Implement termination criteria: confidence ≥ 0.85 → guess; turn_count == MAX_QUESTIONS → forced guess; guesses_made ≥ MAX_GUESSES → lose & teach
- [x] Emit `thinking` state immediately upon receiving an answer (before processing)

### 3.5 Game REST API Endpoints
- [x] Create `app/api/games.py` blueprint
- [x] `POST /api/games` — start a new game session: accept `{category, language}`, return `{session_id, first_question}`
- [x] `POST /api/games/{session_id}/answer` — submit an answer: accept `{answer, input_method}`, return next action (question or guess)
- [x] `POST /api/games/{session_id}/verdict` — submit guess verdict: accept `{is_correct}`, return outcome (win, continue, or teach prompt)
- [x] `POST /api/games/{session_id}/teach` — submit correct name on defeat: accept `{correct_name}`, return confirmation
- [x] Register games blueprint in the app factory

### 3.6 Pydantic Request/Response Schemas
- [x] Create `app/api/schemas.py`
- [x] `StartGameRequest` — validate `category` (enum), `language` (enum)
- [x] `SubmitAnswerRequest` — validate `answer` (enum of 5 values), `input_method` (enum)
- [x] `SubmitVerdictRequest` — validate `is_correct` (bool)
- [x] `TeachRequest` — validate `correct_name` (non-empty string)
- [x] Response schemas for: `GameStartedResponse`, `TurnResponse`, `VerdictResponse`, `TeachResponse`

### 3.7 Milestone 3 Verification
- [x] A full game loop can be played via REST (curl / Postman): start → answer 5–20 questions → receive guess → verdict → teach if lost
- [x] Redis session state is correctly created, updated, and deleted
- [x] All turns and guesses are persisted to PostgreSQL
- [x] Write `tests/test_engine.py` — unit tests for candidate scoring, IG calculation, termination criteria, and state transitions

---

## Milestone 4 — Admin API, Auth & Live Monitoring

### 4.1 Security Utilities
- [x] Implement `app/utils/security.py`
- [x] `hash_password(plaintext)` → argon2 or bcrypt hash
- [x] `verify_password(plaintext, hash)` → bool
- [x] `generate_jwt(user_id, role)` → signed JWT token with expiration
- [x] `decode_jwt(token)` → return payload or raise `Unauthorized`
- [x] `generate_device_token()` → cryptographically random token
- [x] `hash_device_token(token)` → SHA-256 hash for storage
- [x] `verify_device_token(token, hash)` → bool

### 4.2 Auth Blueprint
- [ ] Create `app/api/auth.py` blueprint
- [ ] `POST /api/auth/login` — accept `{username, password}`, verify credentials, return `{access_token, refresh_token, user}`
- [ ] `POST /api/auth/refresh` — accept refresh token, return new access token
- [ ] JWT middleware decorator `@jwt_required` for protecting admin routes
- [ ] JWT middleware decorator `@role_required(role)` for role-based access control

### 4.3 Device Management Blueprint
- [ ] Create `app/api/devices.py` blueprint
- [ ] `POST /api/devices/register` — accept `{name}`, create device record, return `{device_id, device_token}` (token shown once)
- [ ] `GET /api/devices` — list all devices with current online status (check Redis heartbeat TTL)
- [ ] `POST /api/devices/{id}/heartbeat` — HTTP heartbeat fallback, update Redis TTL key
- [ ] Protect with `@jwt_required` (admin only)

### 4.4 Entity Management Blueprint
- [ ] Create `app/api/entities.py` blueprint
- [ ] `GET /api/entities` — paginated list with filters: `category`, `is_approved`, `search` (name)
- [ ] `POST /api/entities` — create new entity (admin only)
- [ ] `PUT /api/entities/{id}` — update entity name, names_i18n, attributes (admin only)
- [ ] `DELETE /api/entities/{id}` — soft delete / mark unapproved (admin only)
- [ ] `POST /api/entities/seed` — bulk import from uploaded JSON/CSV file (admin only)

### 4.5 Admin Dashboard API
- [ ] Create `app/api/admin.py` blueprint
- [ ] `GET /api/admin/stats` — aggregate statistics: total games played, win rate, average question count, games per category, games per language, average STT latency, games today/this week/this month
- [ ] `GET /api/admin/sessions` — list sessions with filters (status, source, date range, device_id), pagination
- [ ] `GET /api/admin/sessions/{id}` — session detail with all turns, guesses, and teach submissions
- [ ] `GET /api/admin/teach-submissions` — list pending teach submissions, paginated
- [ ] `POST /api/admin/teach-submissions/{id}/approve` — approve submission: set status = approved, optionally create/update entity with extracted attributes, set `is_approved = true`
- [ ] `POST /api/admin/teach-submissions/{id}/reject` — reject submission: set status = rejected
- [ ] `GET /api/admin/prompt-versions` — list all prompt versions grouped by language
- [ ] `POST /api/admin/prompt-versions` — create a new prompt version (set previous as inactive)
- [ ] Protect all admin routes with `@jwt_required` and `@role_required("admin")`

### 4.6 Redis Pub/Sub Live Stream
- [ ] Implement publishing in the game engine: after each turn, guess, and state change, publish event to `admin:live_stream` channel
- [ ] Implement publishing in the device manager: heartbeat status changes, online/offline transitions
- [ ] Implement publishing in the vision service: face detection events with bounding box data
- [ ] In `ws/admin.py`: subscribe to `admin:live_stream`, filter events by the admin's subscribed `device_id` or `session_id`, forward matching events over the WebSocket

### 4.7 CORS & Rate Limiting
- [ ] Configure Flask-CORS to allow origins for the React web app
- [ ] Configure Flask-Limiter: rate limits on `/api/auth/login` (e.g., 5/min), `/api/games` (e.g., 10/min), global default

### 4.8 Milestone 4 Verification
- [ ] Admin can log in via `/api/auth/login` and receive JWT
- [ ] Protected endpoints reject requests without valid JWT
- [ ] Admin can list, approve, and reject teach submissions
- [ ] Admin WebSocket receives live turn events for a subscribed session
- [ ] Entity CRUD operations work correctly with pagination
- [ ] Write `tests/test_api.py` — auth flow, CRUD endpoints, permissions, rate limiting

---

## Milestone 5 — LLM Integration

### 5.1 Versioned Prompt System
- [ ] Implement `app/services/game/prompts.py`
- [ ] `load_prompt(language, version=None)` → load from `prompt_versions` table (active version) or fall back to file `prompts/v1/system_{lang}.txt`
- [ ] Create `prompts/v1/system_en.txt` — English system prompt instructing the LLM to play Akinator, output strict JSON, stay family-friendly
- [ ] Create `prompts/v1/system_fr.txt` — French system prompt (same structure)
- [ ] Create `prompts/v1/system_ar.txt` — Arabic/Darija system prompt (same structure)
- [ ] Prompt template includes: game rules, current Q&A history, top-K candidates with attributes, excluded guesses, expected JSON output schema

### 5.2 LLM Provider Adapter
- [ ] Implement `app/services/game/llm_client.py`
- [ ] Abstract `LLMClient` base class with `generate(system_prompt, user_message) → str`
- [ ] `AnthropicAdapter` — Claude API integration
- [ ] `OpenAIAdapter` — GPT API integration
- [ ] `GeminiAdapter` — Google Gemini API integration
- [ ] `OllamaAdapter` — local Ollama HTTP API integration (Llama 3.1 8B / Qwen 2.5 7B)
- [ ] Factory function `get_llm_client(provider=config.LLM_PROVIDER)` → returns correct adapter
- [ ] All adapters enforce `temperature`, `max_tokens`, and `response_format` (JSON mode where supported)

### 5.3 JSON Output Validation & Retry
- [ ] Implement `app/services/game/validator.py`
- [ ] Define expected JSON schema: `{action: "ask"|"guess", question: str|null, guess: str|null, confidence: float}`
- [ ] `validate_llm_response(raw_text)` → parse JSON, validate against schema, return typed dict or raise `ValidationError`
- [ ] Retry logic: on validation failure, send 1 retry prompt with the error message appended. On second failure, raise `LLMFallbackError`

### 5.4 Integrate LLM into Game Engine
- [ ] Update `engine.py` → `get_next_action()` to call LLM provider with formatted context (history + candidates + prompt)
- [ ] On successful LLM response: use its `action`, `question`, and `confidence`
- [ ] On `LLMFallbackError`: automatically switch to KB-only fallback (`fallback.py`) for that turn
- [ ] Log LLM latency per call to `turns.latency_ms`
- [ ] Record `llm_model` used in `sessions.llm_model`

### 5.5 Milestone 5 Verification
- [ ] Play a full game via REST with LLM generating questions (test with at least one cloud provider and Ollama)
- [ ] Malformed LLM output triggers retry and then graceful fallback
- [ ] Switching `LLM_PROVIDER` env var changes the adapter used
- [ ] Write `tests/test_llm_client.py` — mock adapter tests, validation tests, retry & fallback tests

---

## Milestone 6 — WebSocket Gateway

### 6.1 WebSocket Protocol Layer
- [ ] Implement `app/ws/protocol.py`
- [ ] `parse_envelope(raw_message)` → decode JSON envelope `{type, session_id, seq, payload}`
- [ ] `build_envelope(msg_type, session_id, payload)` → serialize JSON envelope with server-side seq
- [ ] `parse_binary_frame(data)` → extract 1-byte header (0x01 JPEG, 0x02 PCM, 0x03 TTS) and payload bytes
- [ ] `build_binary_frame(frame_type, payload)` → prepend header byte to binary data
- [ ] Sequence number tracking: maintain per-connection `last_seq` to deduplicate messages after reconnect

### 6.2 Robot WebSocket Handler
- [ ] Implement `app/ws/robot.py`
- [ ] `/ws/robot` route using `flask-sock`
- [ ] Authenticate via device token in the first message or query parameter
- [ ] Handle incoming binary 0x01 (JPEG) → dispatch to vision service
- [ ] Handle incoming binary 0x02 (PCM audio) → buffer and dispatch to speech service
- [ ] Handle incoming JSON messages: `heartbeat`, `start`, `button` (answer), `verdict`, `teach`
- [ ] Send outgoing JSON: `session_started`, `question`, `guess`, `result`, `listening`, `thinking`, `error`
- [ ] Send outgoing binary 0x03 (TTS audio) from Piper
- [ ] Handle connection close: if game active, start abandon timer
- [ ] Implement close codes: `4001` unauthorized, `4008` rate limit, `4010` replaced connection

### 6.3 Player WebSocket Handler
- [ ] Implement `app/ws/player.py`
- [ ] `/ws/player` route using `flask-sock`
- [ ] Authenticate via session token (generated on game start)
- [ ] Handle incoming JSON: `start`, `answer`, `verdict`, `teach`
- [ ] Send outgoing JSON: `session_started`, `question`, `guess`, `result`, `thinking`, `error`
- [ ] Optional: accept binary 0x01 (webcam JPEG) and 0x02 (mic audio) for web-based play

### 6.4 Admin WebSocket Handler
- [ ] Implement `app/ws/admin.py`
- [ ] `/ws/admin` route using `flask-sock`
- [ ] Authenticate via JWT token
- [ ] Handle incoming JSON: `subscribe {device_id | session_id}`
- [ ] Send outgoing events: `robot_status` (online/offline/camera/mic), `session_update` (state changes), `turn` (live Q&A), `frame_preview` (JPEG + face bounding boxes), `stats_tick` (counters)
- [ ] Powered by Redis Pub/Sub subscription to `admin:live_stream` channel

### 6.5 WebSocket Registration
- [ ] Register all 3 WebSocket routes in the app factory via `flask-sock`
- [ ] Ensure Gunicorn gevent/gthread workers support concurrent WebSocket connections

### 6.6 Milestone 6 Verification
- [ ] Robot WebSocket: connect with device token, send JPEG frame, receive face detection event
- [ ] Player WebSocket: start game, exchange Q&A over WS, receive guess
- [ ] Admin WebSocket: subscribe to a device, receive live turn events
- [ ] Reconnection: disconnect and reconnect with same seq, verify no duplicate processing
- [ ] Write `tests/test_protocol.py` — envelope parsing, binary frame parsing, seq deduplication

---

## Milestone 7 — Vision & Speech Services

### 7.1 Face Detection Service
- [ ] Implement `app/services/vision/detector.py`
- [ ] Initialize MediaPipe Face Detection (or YOLOv8-face) model on app startup
- [ ] `detect_faces(jpeg_bytes)` → decode JPEG, run face detection, return list of `{bbox, area, confidence}`
- [ ] `get_largest_face(faces)` → return the face with the largest bounding box area (= active player)
- [ ] Ensure frames are processed in-memory only — **zero disk writes**

### 7.2 Presence State Tracker
- [ ] Implement `app/services/vision/presence.py`
- [ ] Maintain per-device presence state machine: `ABSENT` → `ARRIVING` → `PRESENT` → `LEAVING` → `ABSENT`
- [ ] `ARRIVING` → `PRESENT`: face continuously detected for > `PRESENCE_ARRIVE_S` (default 1.0s)
- [ ] `PRESENT` → `LEAVING`: face absent for > `PRESENCE_LEAVE_S` (default 5.0s)
- [ ] Emit events: `player_arrived`, `player_left`
- [ ] Publish presence events to Redis Pub/Sub for admin live view
- [ ] On `player_left` during active game: trigger session abandon after 10s total absence

### 7.3 Speech-to-Text (STT)
- [ ] Implement `app/services/speech/stt.py`
- [ ] Load `faster-whisper` model (configurable: `small` / `medium`, device: `cuda` / `cpu`)
- [ ] `transcribe(pcm_audio_bytes, language)` → run Whisper inference, return transcribed text string
- [ ] Handle audio buffering: accumulate PCM chunks until end-of-utterance signal, then transcribe full utterance
- [ ] Target latency: ≤ 1.5s for 2-second voice clips

### 7.4 Answer Mapper (Multilingual)
- [ ] Implement `app/services/speech/answer_mapper.py`
- [ ] `map_answer(transcribed_text, language)` → return one of: `yes`, `no`, `dont_know`, `probably`, `probably_not`, or `None` (ambiguous)
- [ ] Keyword dictionaries for each language:
  - **English**: yes/yeah/yep/sure, no/nope/nah, don't know/no idea/not sure, probably/maybe/I think so, probably not/doubt it/I don't think so
  - **French**: oui/ouais/bien sûr, non/pas du tout, je ne sais pas/aucune idée, peut-être/probablement, probablement pas/j'en doute
  - **Arabic (Darija)**: na3am/wah/ih/iyeh, la/lala, ma3labalich/maranich 3aref/ma3raftch, momkin/yimkin/rab3ma, ba3id/chwiya la/ma nadonch
- [ ] Fuzzy matching with confidence threshold for handling transcription errors
- [ ] Return `None` when no confident match → triggers "please repeat" prompt

### 7.5 Text-to-Speech (TTS)
- [ ] Implement `app/services/speech/tts.py`
- [ ] Initialize Piper TTS with models for supported languages
- [ ] `synthesize(text, language)` → generate WAV/PCM audio bytes
- [ ] `stream_to_robot(audio_bytes, ws_connection)` → send as binary 0x03 frames over WebSocket
- [ ] Controlled by `TTS_ENABLED` env variable (can be disabled)

### 7.6 Wire Vision & Speech into WebSocket Handlers
- [ ] In `ws/robot.py`: route incoming 0x01 frames to `detector.detect_faces()` → `presence.update()`
- [ ] In `ws/robot.py`: route incoming 0x02 audio to `stt.transcribe()` → `answer_mapper.map_answer()` → feed result into game engine
- [ ] In `ws/robot.py`: after game engine produces a question, call `tts.synthesize()` → send 0x03 frame back
- [ ] Ensure heavy processing (STT, vision, LLM) runs in a thread pool, never blocking the WS handler

### 7.7 Milestone 7 Verification
- [ ] Send a test JPEG to `/ws/robot` → receive `player_arrived` event after 1s of face presence
- [ ] Send PCM audio of "yes" in English → receive correctly mapped answer
- [ ] TTS generates and streams audio back to the WebSocket client
- [ ] Write `tests/test_mapper.py` — unit tests for all 3 languages × 5 answer types + ambiguous inputs
- [ ] Write `tests/test_detector.py` — face detection returns bounding boxes for test images

---

## Milestone 8 — Hardening, Testing & Performance

### 8.1 Abandon & Timeout Logic
- [ ] Implement session abandon detection: face absent > 5s, WS closed > 60s, or 2 consecutive answer timeouts (ANSWER_TIMEOUT_S = 30)
- [ ] On abandon: update `sessions.status = abandoned`, delete Redis session key, notify admin
- [ ] Idle timeout: session in Redis with no activity for 30 min → auto-expire via TTL → mark abandoned in DB via cleanup job

### 8.2 Reconnection & Deduplication
- [ ] Robot WS: on reconnect, client sends last `seq` → server skips already-processed messages
- [ ] Robot auto-reconnect window: ≤ 10 seconds, game state preserved in Redis
- [ ] Handle `4010` close code when a new WS connection replaces an existing one from the same device

### 8.3 Thread Pool for Heavy Processing
- [ ] Ensure STT, vision detection, and LLM calls run in a `concurrent.futures.ThreadPoolExecutor` (or gevent pool)
- [ ] WS handlers never block on CPU/GPU-bound work
- [ ] Verify no shared mutable state between workers — all game state lives in Redis

### 8.4 Latency Optimization
- [ ] Send `thinking` state to client immediately upon receiving an answer (before LLM call)
- [ ] Measure and log per-turn latency (answer received → next question sent)
- [ ] Target: ≤ 2.0s per turn end-to-end
- [ ] STT target: ≤ 1.5s for a 2-second voice clip
- [ ] Face detection target: ≤ 1.0s reaction to player arrival

### 8.5 Privacy Validation
- [ ] Audit all code paths: confirm zero raw JPEG frames written to disk
- [ ] Audit all code paths: confirm zero raw PCM audio written to disk
- [ ] Only structured data (text transcriptions, answers, entity names) persisted to DB

### 8.6 Error Handling & Resilience
- [ ] REST endpoints return standardized error JSON: `{error: str, code: int, detail: str}`
- [ ] Error codes: `400` validation, `401` / `403` auth, `404` not found, `409` session already finished, `429` rate limit, `503` LLM down (engine switches to KB-only mode, still returns 200)
- [ ] WebSocket error messages: `{type: "error", payload: {code, message}}`
- [ ] Graceful degradation: if LLM provider is unreachable, game continues in KB-only fallback mode
- [ ] Global exception handler: log unexpected errors, return 500 without leaking stack traces

### 8.7 Comprehensive Test Suite
- [ ] `tests/test_engine.py` — game flow: start, answer loop, guess, verdict, teach
- [ ] `tests/test_engine.py` — edge cases: max questions reached, 3 wrong guesses, abandon
- [ ] `tests/test_candidates.py` — scoring weights, top-K selection, exclusion logic
- [ ] `tests/test_fallback.py` — entropy calculation, information gain, best question selection
- [ ] `tests/test_mapper.py` — all 3 languages × 5 answers + ambiguous inputs
- [ ] `tests/test_llm_client.py` — mock provider responses, validation, retry, fallback
- [ ] `tests/test_protocol.py` — JSON envelope parsing, binary frame parsing, seq dedup
- [ ] `tests/test_api.py` — all REST endpoints: auth, games, devices, entities, admin, health
- [ ] `tests/test_ws.py` — WebSocket connection, message exchange, close codes

### 8.8 Soak Test & Benchmarks
- [ ] Run 30 complete test games end-to-end and verify ≥ 60% win rate
- [ ] Run a 4-hour continuous soak test (automated game loop) — no memory leaks, no crashes, no stale Redis keys
- [ ] Benchmark turn latency across 100 turns and confirm p95 ≤ 2.0s
- [ ] Benchmark STT latency across 50 transcriptions and confirm p95 ≤ 1.5s

### 8.9 Documentation & Final Cleanup
- [ ] Add docstrings to all public functions and classes
- [ ] Update `requirements.txt` with pinned dependency versions
- [ ] Verify `.env.example` includes all environment variables used in the code
- [ ] Verify `docker-compose.yml` starts cleanly from a fresh clone
- [ ] Update this `tasks.md` — tick all completed items

---

## Summary — Task Count by Milestone

| Milestone | Description | Tasks |
|---|---|---|
| **M1** | Project Skeleton & Foundation | 19 |
| **M2** | Database Models & Persistence | 24 |
| **M3** | Game Engine (KB Mode) | 26 |
| **M4** | Admin API, Auth & Live Monitoring | 26 |
| **M5** | LLM Integration | 17 |
| **M6** | WebSocket Gateway | 22 |
| **M7** | Vision & Speech Services | 24 |
| **M8** | Hardening, Testing & Performance | 28 |
| | **Total** | **186** |
