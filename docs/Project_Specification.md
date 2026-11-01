# ITC Akinator Robot & Web System — Backend & Project Specifications

**Document Version:** 1.0.0  
**Date:** November 2026  
**Context:** ITC Club Akinator Interactive Device & Web Platform  
**Target Scope:** Backend Engineering, System Architecture & Interface Contracts  

---

## 1. Executive Summary & Project Context

The **ITC Akinator** is an interactive, multi-modal game system inspired by Akinator. It is deployed across two primary client interfaces:
1. **A physical embedded robot** powered by an ESP32-S3 microcontroller, featuring a camera, I2S microphone, 3.5" TFT display, 5 physical arcade buttons, an addressable WS2812 LED ring, and an audio speaker.
2. **A responsive web application** written in React (Vite + Tailwind CSS), catering to both general web players and club operators via an administrative control panel.

### Backend Responsibility
The physical robot and the web client function as **thin clients**. All state management, computer vision processing, speech transcription, candidate scoring, knowledge base retrieval, and Large Language Model (LLM) orchestration run strictly on the **central backend server**.

The backend engineer is responsible for delivering the core API, WebSocket gateway, real-time audio/video inference pipelines, relational and in-memory persistence, and LLM game engine.

---

## 2. High-Level System Architecture

```
  ┌────────────────────────────────┐         ┌────────────────────────────────┐
  │   Physical Robot (ESP32-S3)    │         │      Web App (React + Vite)    │
  │ • OV2640 camera (JPEG frames)  │         │ • Player mode (mobile/desktop) │
  │ • INMP441 mic (16kHz PCM audio)│         │ • Admin panel (live monitor)   │
  │ • 5 Arcade buttons / LED ring  │         │                                │
  └───────────────┬────────────────┘         └────────────────┬───────────────┘
                  │                                           │
                  │ WSS /ws/robot                             │ HTTPS & WSS (/ws/player, /ws/admin)
                  └─────────────────────┬─────────────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────┐
                         │     Nginx Reverse Proxy     │
                         │  • TLS Termination         │
                         │  • Static React Hosting     │
                         │  • WebSocket Upgrades       │
                         └──────────────┬──────────────┘
                                        │
                                        ▼
   ┌──────────────────────────────────────────────────────────────────────────────┐
   │                    Docker Backend Container (Flask 3 API)                    │
   │                                                                              │
   │  ┌────────────────────────────────────────────────────────────────────────┐  │
   │  │                              API Layer                                 │  │
   │  │  • REST Blueprints: /api/{auth, games, admin, devices, entities, health}│  │
   │  │  • WebSocket Endpoints (flask-sock): /ws/robot, /ws/player, /ws/admin   │  │
   │  │  • Middleware: JWT Auth, Device Token Auth, Pydantic Schema Validation │  │
   │  └───────────────────────────────────┬────────────────────────────────────┘  │
   │                                      │                                       │
   │  ┌───────────────────────────────────▼────────────────────────────────────┐  │
   │  │                            Service Layer                               │  │
   │  │  • Vision Service: OpenCV + MediaPipe Face Detection                   │  │
   │  │  • Speech Service: faster-whisper (STT) + Piper (TTS) + Answer Mapper  │  │
   │  │  • Device Manager: Heartbeats, presence tracking, remote controls      │  │
   │  │  • Game Engine: Candidate scoring, Information Gain, LLM orchestrator │  │
   │  └───────────────────┬───────────────────────────────┬────────────────────┘  │
   │                      │                               │                       │
   │  ┌───────────────────▼──────────────┐ ┌──────────────▼────────────────────┐  │
   │  │    Data Access Layer (SQLA)      │ │            Redis Client           │  │
   │  └───────────────────┬──────────────┘ └──────────────┬────────────────────┘  │
   └──────────────────────┼───────────────────────────────┼───────────────────────┘
                          │                               │
                          ▼                               ▼
               ┌──────────────────────┐        ┌──────────────────────┐
               │    PostgreSQL 16     │        │       Redis 7        │
               │ Relational Database  │        │ Ephemeral Session &  │
               │ • sessions, turns    │        │ Pub/Sub Live Stream  │
               │ • entities, devices  │        │ • session:{id}       │
               │ • teach_submissions  │        │ • device:{id}:hb     │
               └──────────────────────┘        └──────────────────────┘
                                  │
                                  ▼ Strict JSON
                       ┌──────────────────────┐
                       │     LLM Provider     │
                       │ Gemini / Claude /    │
                       │ OpenAI / Ollama      │
                       └──────────────────────┘
```

---

## 3. Communication Contracts & Protocols

### 3.1 Network Protocols
* **REST APIs**: Used for user authentication, CRUD operations on entities/knowledge bases, device registration, and non-streaming game operations.
* **WebSocket (`flask-sock`)**: Used for real-time bidirectional messaging with the robot, player web socket, and admin live telemetry. Plain WebSocket is chosen because the ESP32 `arduinoWebSockets` client communicates over standard WebSockets (avoiding Socket.IO client overhead).

### 3.2 WebSocket Binary Framing & Multiplexing
WebSocket connections support interleaved JSON messages and binary data frames. Binary payloads start with a 1-byte message type header:
* `0x01`: JPEG video frame (Robot camera $\to$ Backend vision service).
* `0x02`: Raw PCM audio stream (16 kHz, 16-bit mono, Little-Endian) (Robot mic $\to$ Backend speech service).
* `0x03`: TTS Audio stream (Backend Piper TTS $\to$ Robot DAC / MAX98357A speaker).

### 3.3 WebSocket JSON Envelope
All structured messages exchanged over WebSockets adhere to the following envelope:

```json
{
  "type": "question",
  "session_id": "c7a82fb0-2051-419b-a0d3-c90b82f091c3",
  "seq": 14,
  "payload": {
    "text": "Is this character known for competitive programming?",
    "turn_no": 4,
    "max_questions": 20,
    "language": "en"
  }
}
```

* **`seq` (Integer)**: Monotonically increasing sequence number sent by clients. The server tracks `seq` to safely ignore duplicate requests during network re-connections.
* **Close Codes**:
  * `4001`: Unauthorized / Invalid device token or expired JWT.
  * `4008`: Rate limit exceeded.
  * `4010`: Connection superseded by newer connection.

---

## 4. Backend Service Specifications

### 4.1 Computer Vision Service (`services/vision`)
* **Input**: 640×480 JPEG frames at 5–10 FPS sent over `/ws/robot`.
* **Engine**: OpenCV + MediaPipe Face Detection (or Ultralytics YOLOv8-face).
* **Face Priority Rule**: When multiple faces appear in the camera frustum, the face with the largest bounding box area is designated the **active player**.
* **Presence State Machine**:
  * `player_arrived`: Face present continuously for $> 1.0\text{ s}$. Triggers robot greeting and game start prompt.
  * `player_left`: Face absent continuously for $> 5.0\text{ s}$. If a game is active, triggers pause/abandon timer. After 10s of absence, session returns to `IDLE`.
* **Privacy Compliance**: **No raw images or video recordings are stored to disk or database.** Video frames are analyzed purely in RAM and discarded immediately.

### 4.2 Speech-to-Text & Text-to-Speech (`services/speech`)
* **Audio Format**: 16 kHz, 16-bit Mono PCM.
* **Speech-to-Text (STT)**: `faster-whisper` (model: `small` or `medium` running on CUDA GPU or optimized CPU).
* **Multi-Language Support**: English, French, and Arabic (specifically Algerian Darija phonetics).
* **Answer Normalization**: The raw transcribed string is parsed by `answer_mapper.py` into one of the 5 canonical game answers:
  1. `yes` (e.g., "yes", "yeah", "oui", "ouais", "na3am", "wah", "ih")
  2. `no` (e.g., "no", "nope", "non", "la", "lala")
  3. `dont_know` (e.g., "don't know", "no idea", "je ne sais pas", "ma3labalich", "maranich 3aref")
  4. `probably` (e.g., "probably", "maybe", "peut-être", "probablement", "momkin", "yimkin")
  5. `probably_not` (e.g., "probably not", "doubt it", "probablement pas", "ba3id", "chwiya la")
* **Ambiguity Handling**: If the transcribed text cannot be matched with sufficient confidence, the server sends a prompt requesting the user to repeat or use the physical arcade buttons.
* **Text-to-Speech (TTS)**: Piper TTS generates lightweight synthesized voice audio chunks (0x03 binary frame) streamed to the robot.

### 4.3 Device & Presence Manager (`services/devices`)
* **Heartbeat**: Robots send a heartbeat ping every 5 seconds (`{"type": "heartbeat", "ts": 1730480000}`).
* **Health Monitoring**: Redis TTL keys (`device:{id}:hb`) track robot liveness with a 15-second expiration threshold.
* **Status Updates**: Pushed in real time to the admin panel via Redis Pub/Sub.

---

## 5. Game Engine & Decision Logic

The game engine operates as a hybrid knowledge-base scoring algorithm coupled with an LLM conversational agent.

```
       [ Start Game Session ]
                 │
                 ▼
     [ Load Category Candidates ]
     [ Initial Score: 1.0 each  ]
                 │
                 ▼
    ┌──► [ Check Termination Criteria ] ──── Yes ──► [ Emit Final Guess ]
    │    • Confidence ≥ 0.85 OR                      │
    │    • Turn count == 20                          ▼
    │            │                            [ User Verdict ]
    │            ▼ No                          ├── Correct ──► [ WIN ]
    │    [ Formulate Context ]                 └── Incorrect ──► [ Guess count < 3? ]
    │    • Q&A History                                             ├── Yes ──► Exclude & Resume
    │    • Top-K Candidates                                        └── No  ──► [ Lose & Teach Me ]
    │    • Excluded Guesses
    │            │
    │            ▼
    │    [ Call LLM Provider ]
    │    Strict JSON Schema:
    │    {action, question, guess, confidence}
    │            │
    │            ├── [ Valid JSON? ] ── No ──► [ Retry Once ] ── Fail ──► [ Fallback to KB-only ]
    │            │          │
    │            │         Yes
    │            ▼          │
    │    [ Send Question ] ◄┘
    │    [ Push "thinking" state ]
    │            │
    │            ▼
    │    [ Receive Player Answer ]
    │    (Voice / Arcade Button)
    │            │
    │            ▼
    │    [ Update Candidate Scores ]
    │    Turn count ++
    └────────────┘
```

### 5.1 Candidate Weight Updating
Given an entity $e$ with binary attributes $\in [0, 1]$ and an answer $a$, candidate scores are dynamically updated:
* Answer `yes`: $+1.0 \times \text{match}(e.\text{attr})$
* Answer `probably`: $+0.5 \times \text{match}(e.\text{attr})$
* Answer `dont_know`: $0.0$ (neutral)
* Answer `probably_not`: $-0.5 \times \text{match}(e.\text{attr})$
* Answer `no`: $-1.0 \times \text{match}(e.\text{attr})$

### 5.2 Information Gain Fallback (KB-Only Mode)
If LLM connectivity fails or is disabled for offline demonstrations, the engine evaluates available questions using **Expected Information Gain**:

$$\text{IG}(q) = H(C) - \sum_{a \in A} P(a \mid q) H(C \mid a, q)$$

Where:
* $C$ is the set of active candidate entities.
* $H(C) = - \sum_{c \in C} P(c) \log_2 P(c)$ is the current entropy.
* $a \in \{\text{yes}, \text{no}, \text{dont\_know}, \text{probably}, \text{probably\_not}\}$.
* The engine selects $q^* = \arg\max_q \text{IG}(q)$, which achieves the maximum expected candidate separation.

### 5.3 LLM Guardrails & Schema Enforcement
* **Output Format**: Enforced strict JSON response:
  ```json
  {
    "action": "ask",
    "question": "Does this person study in the Computer Science department?",
    "guess": null,
    "confidence": 0.42
  }
  ```
* **Retry Strategy**: In case of malformed JSON or schema violation, 1 immediate retry prompt is sent. If it fails again, fallback mode immediately selects the highest Information Gain question from the pre-indexed database.
* **Safety**: Prompts enforce family-friendly, non-offensive dialogue and restrict questions to approved domains.

### 5.4 The "Teach Me" Knowledge Expansion Flow
If the robot fails 3 consecutive guesses or reaches question 20 without finding the correct answer:
1. The game ends as a `lose`.
2. The user is invited to input the true identity of the entity they had in mind.
3. The server logs the input alongside the full game turn history into `teach_submissions` with state `pending`.
4. Admins can review, adjust extracted attributes, and approve the submission in the admin panel, expanding the knowledge base dynamically.

---

## 6. Database Schema (PostgreSQL 16)

```
 ┌──────────────────────┐             ┌──────────────────────┐
 │       devices        │             │   prompt_versions    │
 ├──────────────────────┤             ├──────────────────────┤
 │ PK id (UUID)         │             │ PK id (INT)          │
 │    name (VARCHAR)    │             │    name (VARCHAR)    │
 │    token_hash (STR)  │             │    version (INT)     │
 │    status (ENUM)     │             │    language (ENUM)   │
 │    camera_ok (BOOL)  │             │    content (TEXT)    │
 │    mic_ok (BOOL)     │             │    is_active (BOOL)  │
 │    last_heartbeat    │             │    created_at (TZ)   │
 └──────────┬───────────┘             └──────────┬───────────┘
            │                                    │
            │ 1:N                                │ 1:N
            ▼                                    ▼
 ┌───────────────────────────────────────────────────────────┐
 │                         sessions                          │
 ├───────────────────────────────────────────────────────────┤
 │ PK id (UUID)                                              │
 │    source (ENUM: robot, web)                              │
 │ FK device_id (UUID -> devices.id, NULLABLE)               │
 │ FK prompt_version_id (INT -> prompt_versions.id)          │
 │    language (ENUM: ar, fr, en)                            │
 │    category (ENUM: character, animal, object)             │
 │    status (ENUM: active, finished, abandoned)             │
 │    result (ENUM: win, lose, NULLABLE)                     │
 │    question_count (SMALLINT)                              │
 │    llm_model (VARCHAR)                                    │
 │    started_at (TIMESTAMPTZ)                               │
 │    ended_at (TIMESTAMPTZ, NULLABLE)                       │
 └─────────────┬─────────────────┬─────────────────┬─────────┘
               │                 │                 │
               │ 1:N             │ 1:N             │ 1:N
               ▼                 ▼                 ▼
 ┌──────────────────────┐ ┌───────────────┐ ┌──────────────────────┐
 │        turns         │ │    guesses    │ │  teach_submissions   │
 ├──────────────────────┤ ├───────────────┤ ├──────────────────────┤
 │ PK id (BIGINT)       │ │ PK id (BIGINT)│ │ PK id (INT)          │
 │ FK session_id (UUID) │ │ FK session_id │ │ FK session_id (UUID) │
 │    turn_no (SMALLINT)│ │ FK entity_id  │ │ FK entity_id (NULL)  │
 │    question (TEXT)   │ │    guess_name │ │    submitted_name    │
 │    answer (ENUM)     │ │    guess_no   │ │    qa_trail (JSONB)  │
 │    input_method      │ │    confidence │ │    status (ENUM)     │
 │    confidence (FLOAT)│ │    is_correct │ │ FK reviewed_by (INT) │
 │    latency_ms (INT)  │ │    created_at │ │    created_at (TZ)   │
 └──────────────────────┘ └───────┬───────┘ └──────────────────────┘
                                  │
                                  ▼ N:1
                       ┌──────────────────────┐        ┌──────────────────────┐
                       │       entities       │        │        users         │
                       ├──────────────────────┤        ├──────────────────────┤
                       │ PK id (INT)          │        │ PK id (INT)          │
                       │    name (VARCHAR)    │        │    username (VARCHAR)│
                       │    names_i18n (JSONB)│◄───────┤    email (VARCHAR)   │
                       │    category (ENUM)   │ Review │    password_hash     │
                       │    attributes (JSONB)│        │    role (ENUM)       │
                       │    times_guessed     │        │    is_active (BOOL)  │
                       │    times_correct     │        │    last_login_at     │
                       │    is_approved (BOOL)│        └──────────────────────┘
                       └──────────────────────┘
```

### Table Definitions & Keys

1. **`devices`**: Registered ESP32-S3 robots.
   * `id` UUID PK, `name` VARCHAR(100), `token_hash` VARCHAR(255), `status` ENUM (`online`, `offline`, `error`), `camera_ok` BOOL, `mic_ok` BOOL, `firmware_version` VARCHAR(50), `last_heartbeat` TIMESTAMPTZ.
2. **`prompt_versions`**: Version-controlled prompts for the game engine.
   * `id` SERIAL PK, `name` VARCHAR(50), `version` INT, `language` ENUM (`ar`, `fr`, `en`), `content` TEXT, `is_active` BOOL.
3. **`sessions`**: Every played game session.
   * `id` UUID PK, `source` ENUM (`robot`, `web`), `device_id` UUID FK (nullable), `prompt_version_id` INT FK, `language` ENUM (`ar`, `fr`, `en`), `category` ENUM (`character`, `animal`, `object`), `status` ENUM (`active`, `finished`, `abandoned`), `result` ENUM (`win`, `lose`), `question_count` SMALLINT, `llm_model` VARCHAR(50), `started_at` TIMESTAMPTZ, `ended_at` TIMESTAMPTZ.
4. **`turns`**: Granular record of each question-and-answer exchange.
   * `id` BIGSERIAL PK, `session_id` UUID FK, `turn_no` SMALLINT, `question` TEXT, `answer` ENUM (`yes`, `no`, `dont_know`, `probably`, `probably_not`), `input_method` ENUM (`voice`, `button`, `touch`), `confidence` FLOAT, `latency_ms` INT, `created_at` TIMESTAMPTZ.
   * *Constraint*: `UNIQUE(session_id, turn_no)`.
5. **`guesses`**: Log of each guess attempt (up to 3 per session).
   * `id` BIGSERIAL PK, `session_id` UUID FK, `entity_id` INT FK (nullable), `guess_name` VARCHAR(150), `guess_no` SMALLINT (1..3), `confidence` FLOAT, `is_correct` BOOL, `created_at` TIMESTAMPTZ.
6. **`entities`**: The knowledge base of guessable items/people.
   * `id` SERIAL PK, `name` VARCHAR(150), `names_i18n` JSONB (`{"ar": "...", "fr": "...", "en": "..."}`), `category` ENUM (`character`, `animal`, `object`), `attributes` JSONB (`{"is_developer": 1.0, "is_club_lead": 0.0}`), `times_guessed` INT DEFAULT 0, `times_correct` INT DEFAULT 0, `source` ENUM (`seed`, `learned`), `is_approved` BOOL DEFAULT TRUE, `created_at` TIMESTAMPTZ.
7. **`teach_submissions`**: Submissions provided by users when the Akinator loses.
   * `id` SERIAL PK, `session_id` UUID FK, `entity_id` INT FK (nullable), `submitted_name` VARCHAR(150), `qa_trail` JSONB, `status` ENUM (`pending`, `approved`, `rejected`), `reviewed_by` INT FK (users.id, nullable), `created_at` TIMESTAMPTZ, `reviewed_at` TIMESTAMPTZ.
8. **`users`**: Operator and administrator credentials.
   * `id` SERIAL PK, `username` VARCHAR(50) UNIQUE, `email` VARCHAR(120) UNIQUE, `password_hash` VARCHAR(255), `role` ENUM (`admin`, `operator`), `is_active` BOOL, `last_login_at` TIMESTAMPTZ.

---

## 7. Redis Ephemeral State & Cache Architecture

Redis 7 serves as the fast in-memory coordinating layer across Gunicorn worker threads.

### Keys & Data Structures
* **`session:{session_id}` (Hash / JSON string, TTL: 30 minutes)**:
  ```json
  {
    "state": "ASKING",
    "category": "character",
    "language": "en",
    "device_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "question_count": 5,
    "guesses_made": 0,
    "history": [
      {"turn": 1, "q": "Is it human?", "a": "yes"},
      {"turn": 2, "q": "Is the person female?", "a": "no"}
    ],
    "excluded_entity_ids": [],
    "candidate_scores": {"14": 3.5, "28": 2.0, "103": -1.5}
  }
  ```
* **`device:{device_id}:hb` (String timestamp, TTL: 15 seconds)**: Stores current heartbeat to detect robot power loss or Wi-Fi disconnection.
* **`admin:live_stream` (Pub/Sub Channel)**: Real-time broadcast channel carrying live turn updates, face detection events, and diagnostic telemetries for the admin panel.

---

## 8. REST & WebSocket API Specification

### 8.1 REST Blueprints

#### Authentication (`/api/auth`)
* `POST /api/auth/login`: Admin/Operator login returning JWT token.
* `POST /api/auth/refresh`: Refresh expired JWT token.

#### Games & Sessions (`/api/games`)
* `POST /api/games`: Initialize game session (Web client fallback). Returns `{session_id, first_question}`.
* `POST /api/games/{session_id}/answer`: Submit answer (`{answer: "yes", input_method: "touch"}`).
* `POST /api/games/{session_id}/verdict`: Submit guess verdict (`{is_correct: true}`).
* `POST /api/games/{session_id}/teach`: Submit correct entity name on defeat.

#### Devices (`/api/devices`)
* `POST /api/devices/register`: Register new robot hardware and generate device token.
* `GET /api/devices`: List all registered devices and real-time online status.
* `POST /api/devices/{id}/heartbeat`: HTTP heartbeat fallback.

#### Entities (`/api/entities`)
* `GET /api/entities`: Paginated list of entities in knowledge base.
* `POST /api/entities`: Create new entity.
* `PUT /api/entities/{id}`: Update attributes or translations.
* `POST /api/entities/seed`: Bulk import initial entities from JSON/CSV.

#### Admin & Review (`/api/admin`)
* `GET /api/admin/stats`: Get game counts, win rates, average questions per game, STT latency metrics.
* `GET /api/admin/teach-submissions`: List pending "Teach Me" submissions.
* `POST /api/admin/teach-submissions/{id}/approve`: Promote learned entry to official knowledge base.
* `POST /api/admin/teach-submissions/{id}/reject`: Discard submission.

#### System Health (`/api/health`)
* `GET /api/health`: Check database connection, Redis connectivity, and LLM provider ping.

---

## 9. Non-Functional Requirements & Performance Metrics

| Metric | Target | Rationale |
|---|---|---|
| **Turn-to-Question Latency** | $\le 2.0\text{ seconds}$ | From receipt of user answer to question render. Backend immediately sends a `thinking` state to animate the LCD/LEDs while LLM responds. |
| **Face Detection Response** | $\le 1.0\text{ second}$ | Robot must greet the user promptly upon arrival. |
| **STT Latency** | $\le 1.5\text{ seconds}$ | Whisper transcription turnaround time on 2-second voice clips. |
| **Game Accuracy** | $\ge 60\%$ wins in $\le 20$ questions | Target benchmark on initial 30 test games. |
| **Continuous Uptime** | $\ge 4.0\text{ hours}$ | System must sustain prolonged club exhibition events without memory leaks or crash restarts. |
| **Reconnection Window** | $\le 10\text{ seconds}$ | ESP32 Wi-Fi reconnect recovery with deduplicated `seq` messaging. |
| **Privacy Compliance** | Zero raw media persistence | Camera frames and microphone audio buffers remain strictly in RAM. |

---

## 10. Repository Structure & Build Plan

### 10.1 Recommended Codebase Layout
```
ITC_AKINATOR_BACKEND/
├── wsgi.py                     # Production Gunicorn entry point
├── Dockerfile                  # Multi-stage Python 3.11 build
├── docker-compose.yml          # api, postgres, redis, nginx
├── requirements.txt            # Python dependencies
├── .env.example                # Config environment template
├── docs/                       # Project documentation & schemas
│   ├── Cahier_des_Charges_Akinator_Robot.pdf
│   ├── akinator_backend_schemas.drawio
│   ├── akinator itc.drawio
│   └── Project_Specification.md
├── app/
│   ├── __init__.py             # Flask App Factory (create_app)
│   ├── config.py               # Environment configuration loaders
│   ├── extensions.py           # db, migrate, redis_client, sock, cors
│   ├── api/                    # REST Blueprints
│   │   ├── auth.py
│   │   ├── games.py
│   │   ├── admin.py
│   │   ├── devices.py
│   │   ├── entities.py
│   │   ├── health.py
│   │   └── schemas.py          # Pydantic validation schemas
│   ├── ws/                     # WebSocket Handlers (flask-sock)
│   │   ├── robot.py            # /ws/robot connection
│   │   ├── player.py           # /ws/player connection
│   │   ├── admin.py            # /ws/admin connection
│   │   └── protocol.py         # Frame parsing & envelope serialization
│   ├── services/               # Core Business Logic
│   │   ├── vision/
│   │   │   ├── detector.py     # MediaPipe/YOLO face detection
│   │   │   └── presence.py     # Presence state tracking
│   │   ├── speech/
│   │   │   ├── stt.py          # faster-whisper inference
│   │   │   ├── tts.py          # Piper TTS integration
│   │   │   └── answer_mapper.py# Multilingual answer normalization
│   │   ├── game/
│   │   │   ├── engine.py       # Turn-by-turn game flow orchestrator
│   │   │   ├── session_store.py# Redis session cache manager
│   │   │   ├── candidates.py   # Bayesian / heuristic KB scoring
│   │   │   ├── prompts.py      # Versioned prompt loader
│   │   │   ├── llm_client.py   # Cloud & Ollama LLM provider adapter
│   │   │   ├── validator.py    # JSON output schema validation & retries
│   │   │   ├── fallback.py     # Information Gain calculation
│   │   │   └── learner.py      # Teach me submission handler
│   │   └── devices.py          # Robot status & heartbeat monitors
│   ├── models/                 # SQLAlchemy DB Models
│   │   ├── device.py
│   │   ├── prompt_version.py
│   │   ├── session.py
│   │   ├── turn.py
│   │   ├── guess.py
│   │   ├── entity.py
│   │   ├── teach_submission.py
│   │   └── user.py
│   ├── repositories/           # Isolated database query logic
│   └── utils/
│       ├── security.py         # Passwords, JWT, and device token hashing
│       ├── logging.py          # Structured JSON logging
│       └── ws_helpers.py
├── prompts/                    # Versioned Prompt Files
│   └── v1/
│       ├── system_en.txt
│       ├── system_fr.txt
│       └── system_ar.txt
├── data/
│   └── seed_entities.json      # Seed Knowledge Base
├── migrations/                 # Alembic DB Migrations
├── scripts/
│   ├── seed_kb.py              # Knowledge base seeding CLI script
│   └── create_admin.py         # Bootstrap admin user script
└── tests/
    ├── test_engine.py          # Unit tests for scoring & state machine
    ├── test_mapper.py          # Multilingual answer mapping tests
    ├── test_api.py             # REST API endpoint tests
    └── test_protocol.py        # WebSocket protocol framing tests
```

### 10.2 Recommended Build Order
1. **Milestone 1 — Foundation**: Project skeleton, Flask factory, Docker Compose (`postgres`, `redis`, `api`), `.env`, and `/api/health`.
2. **Milestone 2 — Persistence Layer**: SQLAlchemy models, Alembic migrations, and seed script loading the initial knowledge base.
3. **Milestone 3 — Game Engine (KB Mode)**: State machine, Redis session store, candidate scoring, and Information Gain fallback playable via REST.
4. **Milestone 4 — LLM Integration**: Multi-provider LLM adapter (Gemini/Claude/Ollama), prompt loader, JSON schema validation, and retry handlers.
5. **Milestone 5 — WebSocket Gateway**: `flask-sock` setup, binary frame demuxing, device authentication, and sequence number handling.
6. **Milestone 6 — Speech & Vision Services**: MediaPipe face detection, `faster-whisper` STT integration, and multilingual answer normalization.
7. **Milestone 7 — Admin API & Live Monitoring**: Admin endpoints, Redis live stream broadcasting, and "Teach Me" review workflows.
8. **Milestone 8 — Hardening & SLA Benchmarks**: Soak testing (4-hour continuous run), turn latency optimization ($\le 2\text{s}$), and privacy validation.
