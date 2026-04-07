# Intelligent Vehicle Safety and Passenger Security System (IVS)

End-to-end safety monitoring system that combines:

- **Backend (Flask + MongoDB)**: trip lifecycle, telemetry ingestion, persistence, exports, SOS messaging, calibration storage.
- **AI Engine (Flask)**: camera-frame analysis (MediaPipe FaceLandmarker + temporal behavior engine), identity verification, emotion inference (ONNX), passenger SOS gesture, risk scoring, and asynchronous persistence back to backend.
- **Frontend (React + Vite)**: live monitoring dashboard with webcam, live map, trips, trip replay, background events, SOS feed.

This README is written to match what is **actually implemented in this repository** (endpoints, fields, thresholds, intervals, and defaults).

---

## Table of contents

- [Repository layout](#repository-layout)
- [System overview](#system-overview)
- [Key implemented features](#key-implemented-features)
- [Component details](#component-details)
  - [Frontend (React)](#frontend-react)
  - [Backend (Flask + MongoDB)](#backend-flask--mongodb)
  - [AI Engine (Flask)](#ai-engine-flask)
- [Data model (MongoDB)](#data-model-mongodb)
- [Behavior detection and temporal rules](#behavior-detection-and-temporal-rules)
- [Risk scoring](#risk-scoring)
- [Alerts and audio behavior](#alerts-and-audio-behavior)
- [SOS (Emergency) flow](#sos-emergency-flow)
- [Environment variables](#environment-variables)
- [Setup and run](#setup-and-run)
- [API reference](#api-reference)
  - [Backend API (port 5000)](#backend-api-port-5000)
  - [AI Engine API (port 5001)](#ai-engine-api-port-5001)
- [Tools and scripts](#tools-and-scripts)
- [Known limitations / mismatches](#known-limitations--mismatches)
- [Troubleshooting](#troubleshooting)

---

## Repository layout

High-level folders:

```
ai_engine/                # AI service (Flask) - CV + temporal detection + risk + emotion + persistence
backend/                  # Backend API (Flask) - trips, telemetry, events, SOS, exports, calibration
frontend/                 # React + Vite dashboard
android/PassengerApp/     # Android project (present in repo; integration not documented in code here)
docs/                     # Architecture + explanatory docs (may be more conceptual than code)
tools/                    # Helper scripts (Mongo checks, manual insert, etc.)
```

---

## System overview

### Runtime components and default ports

- **Backend API**: `http://localhost:5000`
- **AI Engine**: `http://localhost:5001`
- **Frontend (Vite dev server)**: typically `http://localhost:5173` (Vite default; may vary)
- **MongoDB**: `mongodb://localhost:27017/` (backend uses a fixed URI; AI engine supports env override)

### End-to-end flow (what happens at runtime)

1. **Frontend**:
   - Reads backend health `GET /` to detect backend restarts via `boot_id`.
   - Requires a **Driver Setup** step (stored in `localStorage`), then stores that session on backend via `POST /driver-session`.
   - Live Monitoring:
     - Captures webcam frames and posts them to AI Engine `POST /analyze_frame`.
     - Polls backend `GET /trips/active-trip/live_map` every **5s** to obtain active-trip state + last location.
     - Polls backend distance endpoint every **5s**.
2. **AI Engine** (fast loop):
   - Decodes base64 JPEG, runs **MediaPipe FaceLandmarker** (up to 6 faces) and selects a “driver” face.
   - Computes face metrics (EAR/MAR/head pose/quality signals).
   - Runs **temporal behavior engine** (stateful) to output current-frame detections.
   - Runs **risk engine** (stateful per-trip counters) to compute risk.
   - Applies **final decision fusion** (driver risk + emotion support signal) and generates warnings (with cooldown).
   - If detections represent episode transitions, queues asynchronous persistence back to backend.
3. **AI Engine** (slow loop, background):
   - Runs every `SLOW_ANALYTICS_INTERVAL_S` (default **5s**).
   - Performs passenger **crossed-arms SOS gesture** analysis.
   - Performs driver **emotion inference** via ONNX model.
4. **Backend**:
   - Stores trips, path points, sensor data.
   - Stores AI events on active trips via `POST /trips/<trip_id>/ai-results`.
   - Stores “background events” when there is no active trip via `POST /events`.
   - Stores SOS events via `POST /trips/<trip_id>/sos` and can send Twilio WhatsApp alerts.
   - Provides exports: JSON, CSV, map image PNG, PDF report (optional dependency).
   - Provides live map payloads used by frontend.
   - Advertises the service via Zeroconf/mDNS.

---

## Key implemented features

### Driver state detection (AI)

- Face detection + landmark extraction via **MediaPipe FaceLandmarker** (FaceMesh-style 468 landmarks).
- Per-frame metrics:
  - EAR (eye aspect ratio)
  - MAR (mouth aspect ratio)
  - head pose yaw/pitch/roll
  - quality metrics: landmark ratio, face presence confidence, face area ratio, eye distance norm, mouth visibility ratios
- Temporal behavior detection via `ai_engine/behavior_engine.py`:
  - drowsiness (eye closure)
  - yawning (mouth opening pattern)
  - distraction (head/yaw off-road)
  - driver_not_visible (identity visibility model)
  - camera-blocked and occlusion-related warnings (mouth occluded, too far)

### Identity + personalization (AI)

- Uses OpenCV Zoo **YuNet + SFace** to extract embeddings.
- Stores driver embeddings in MongoDB `drivers` (preferred) or `ai_engine/driver_embeddings.json` fallback.
- “Fixed identity per trip”: it verifies a driver against a **fixed calibration encoding** periodically.
- Adds `driver_last_seen_s_ago` to CV metrics, and can trigger `driver_not_visible` when beyond threshold.

### Emotion inference (AI)

- ONNX Runtime model: `ai_engine/models/emotion_model.onnx`.
- Preprocessing:
  - crop driver face
  - resize to model input (default 64x64)
  - grayscale
  - float32 **without normalization** (keeps 0–255)
  - shape `[1, 1, H, W]`
- Runs periodically (interval design is 5 seconds in code).
- Maintains a small smoothing buffer (last-3) and produces:
  - `dominant_emotion`, `confidence`, `stress_level`, `emotion_risk_score`

### Passenger SOS gesture (AI)

- Passenger SOS is detected by a **crossed-arms gesture** (MediaPipe pose-based logic in AI engine).
- Configurable ratio threshold and duration.
- When triggered:
  - AI engine returns `sos_triggered: true`
  - It posts an SOS event to backend asynchronously
  - Frontend shows emergency banner and plays a critical alert

### Trip lifecycle + telemetry (Backend)

- Enforces **at most one ACTIVE trip**:
  - `POST /trips` auto-ends any existing active trip(s) with `end_reason: auto_end_new_trip`
- Stores:
  - GPS path points (`path[]`)
  - sensor telemetry (`sensor_data[]`)
  - AI events (`ai_events[]`)
  - SOS events (`sos_events[]`)
- Computes trip summaries:
  - distance (haversine over path)
  - max speed
  - duration minutes
  - emotion summary at trip end

### Exports and reporting (Backend)

- Download trip JSON
- Download CSV
- Render trip route map image (PNG)
- Generate PDF trip report (returns 501 if `reportlab` not installed)

### Network discoverability (Backend)

- Advertises services using Zeroconf/mDNS:
  - `_ivs._tcp.local.`
  - `_http._tcp.local.`

---

## Component details

## Frontend (React)

Folder: `frontend/`

### Pages / routes

Route registration is in `frontend/src/App.jsx`.

- `/setup` → DriverSetup
- `/live` → LiveMonitoring
- `/trips` → Trips list
- `/trips/:id` → TripDetail (map replay + report download)
- `/events` → Background events feed
- `/events/emergency` → SOS feed

### Driver setup gating

Driver fields required:

- `driver_name`
- `vehicle_no`
- `license_no`

Storage behavior:

- Stored in `localStorage` keys:
  - `driver_name`, `vehicle_no`, `license_no`
- Backend restart detection:
  - Frontend calls `GET /` and compares `boot_id`.
  - If `boot_id` changes, frontend clears the stored local driver details to force re-setup.

Backend session storage:

- DriverSetup posts `POST /driver-session` with:
  ```json
  {
    "driver_name": "...",
    "vehicle_no": "...",
    "license_no": "...",
    "driver_id": "<license_no>"
  }
  ```

### Live monitoring loop

Webcam:

- Uses `navigator.mediaDevices.getUserMedia({ video: true, audio: false })`.

Frame capture:

- Implemented in `frontend/src/services/aiEngineService.js`:
  - downscales to max **480x360**
  - JPEG encode at quality **0.65**
  - base64 payload without prefix

AI frame analysis schedule:

- LiveMonitoring runs an interval every **250 ms** (4 Hz), but it is throttled by an `inFlight` guard, so the effective rate is “as fast as the round-trip permits” (no request pile-up).

Live map polling:

- Calls backend `GET /trips/active-trip/live_map` every **5 seconds** and:
  - sets `tripId` and `tripStartTimeIso`
  - sets `position` from `current_location` when present

Distance polling:

- Every **5 seconds**:
  - if `tripId` exists → `GET /trips/<tripId>/distance`
  - else → `GET /trips/active-trip/distance`

Trip status banner:

- Implements an overwrite-safe state machine:
  - `NO_ACTIVE` → `TRIP_STARTED` → `TRIP_ACTIVE`
  - `TRIP_ENDED` shown for 5s after trip end
- Elapsed time is computed from backend-provided `trip_start_time` (UTC ISO) where available.

Detections display and driver status:

- UI is driven strictly by the *current frame’s* `detections[]` from AI engine.
- Driver status is determined by the priority order:
  - `DROWSY` if detection `drowsiness`
  - else `DISTRACTED` if `distraction`
  - else `NOT_VISIBLE` if `driver_not_visible`
  - else `ALERT`

Emotion display:

- Always displays `driver_emotion` continuously.
- Contains a “sudden emotion change” alert rule:
  - transition keys watched: `neutral->angry`, `happy->fear`, `calm->sad`
  - requires both prev and current confidence >= **0.65**
  - must persist for **>= 1200ms**
  - cooldown between emotion alerts: **15 seconds**

Audio alerts (frontend-side)

- Web Audio oscillator beep:
  - global minimum spacing: **1200ms**
  - beep duration: **3 seconds**
  - frequency: HIGH=660Hz, CRITICAL=880Hz
- Transition-only detection beeps:
  - sounds play only when a detection becomes active (inactive → active)
  - per-type cooldown map is used (`playDetectionBeep(key, cooldownMs)`)
  - also uses a global “same-type” cooldown of 4 seconds to prevent repeated transitions

Trips page

- Client-side filters:
  - query: matches trip id or driver id
  - date filter: supports both `DD/MM/YYYY` (from backend IST formatting) and ISO-like `YYYY-MM-DD`

Trip detail page

- Uses `GET /trips/:id` and:
  - replays the path in Leaflet
  - shows consolidated events timeline
- Report download:
  - fetches `GET /trip/<id>/report` and expects `application/pdf`
  - shows friendly error if backend returns JSON error

Events page (background detections)

- Fetches `GET /events` with pagination (10/page) and filters:
  - risk level
  - event type
  - date presets: today / yesterday / custom date range
- Performs a second fetch (limit=500) to populate the “event type” dropdown options.

SOS events page

- Fetches `GET /events/emergency` with pagination (10/page).
- Links to trip details when `trip_id` is present.

---

## Backend (Flask + MongoDB)

Folder: `backend/`

### Storage

- MongoDB DB name: `ivs_db`
- Backend Mongo URI is currently fixed in code to: `mongodb://localhost:27017/`
- Collections used:
  - `trips`
  - `events`
  - `drivers` (via calibration model)
  - `driver_calibrations` (via calibration model)

### Time formatting

- Backend formats many timestamps for display using `Asia/Kolkata` (IST).
- Some endpoints also return UTC ISO strings (notably `trip_start_time` in live_map payloads).

### Driver session fallback

- `POST /driver-session` stores driver details in-memory for the current backend boot.
- When `POST /trips` is called with missing/null driver fields, backend fills them from this session snapshot.

### Trip lifecycle

- `POST /trips`:
  - auto-completes existing ACTIVE trips
  - creates a new `trip_id` (UUID)
  - stores driver info and initializes `sensor_data: []` and `path: []`

- `PUT /trips/<trip_id>/end`:
  - computes distance, max speed, duration, and emotion summary
  - marks trip COMPLETED and sets `end_time`

### Telemetry

- `POST /trips/<trip_id>/location`:
  - appends to `path[]`
  - updates last location fields

- `POST /trips/<trip_id>/sensor`:
  - appends to `sensor_data[]`

### AI results persistence

- `POST /trips/<trip_id>/ai-results`:
  - only allowed while trip is ACTIVE; otherwise returns 409 `TRIP_NOT_ACTIVE`
  - supports episode persistence via `event_action`:
    - `start`: deduped using `event_key`
    - `frame`: stored as a frame event
    - `end`: updates matching episode by `episode_id` or `event_key`
  - stores AI event fields under `ai_events[]`

### Background events persistence

- `POST /events` stores AI events even when no trip is active.
- Has anti-flood protections:
  - generic empty frames are skipped when there are no detections and the event is a generic type.
- Supports episode end updates (`event_action=end`) by `episode_id` or `event_key`.

### SOS + emergency feed

- `POST /trips/<trip_id>/sos`:
  - stores in `trips.sos_events[]`
  - sets `sos_triggered=true`
  - inserts an emergency record into `events` collection
  - triggers WhatsApp sending via Twilio (if configured)

- `GET /events/emergency`:
  - returns a list of trips with `sos_triggered=true`
  - builds a feed payload used by the frontend

### Live map

- `GET /trips/active-trip/live_map`:
  - returns `trip_active`, `trip_id`, `trip_start_time` (UTC ISO), `current_location`, and full `path[]`
- `GET /trips/<trip_id>/live_map`:
  - same payload shape but for a specific trip

### Exports

- JSON: `GET /trip/<trip_id>/download`
- CSV: `GET /trip/<trip_id>/download_csv`
- PNG map image: `GET /trip/<trip_id>/map_image`
- PDF report: `GET /trip/<trip_id>/report` (requires `reportlab`; otherwise 501)

### HTML tracking page

- `GET /tracking` renders `backend/templates/tracking.html` (Leaflet live tracking UI).

---

## AI Engine (Flask)

Folder: `ai_engine/`

### Fast loop vs slow loop

Fast loop:

- Implemented by `POST /analyze_frame`.
- Performs:
  1) base64 decode
  2) FaceLandmarker metrics extraction
  3) identity visibility update (periodic)
  4) temporal behavior detection
  5) risk scoring
  6) alert generation (cooldowns)
  7) final decision fusion
  8) queues async backend persistence (never blocks request)

Slow loop:

- Scheduled internally when frames arrive and only when due.
- Interval: `SLOW_ANALYTICS_INTERVAL_S` (default 5s).
- Computes and caches:
  - passenger crossed-arms SOS gesture
  - driver emotion inference result

### Supported detection input modes

`/analyze_frame` supports:

1) Image mode (preferred):
   - request contains `image` (or `frame`) base64
2) Legacy signal mode:
   - request contains `signal` or boolean flags like `drowsiness`, `yawning`, `distraction`

### Episode persistence and dedupe

The AI engine computes per-event “episodes” for selected event types.

- Event types are controlled by `EPISODE_EVENT_TYPES`.
- Episode persistence starts only if duration >= `EPISODE_PERSIST_MIN_SECONDS`.
- The engine builds a stable `event_key`:

```
event_key = "{trip_id}|{driver_id}|{event_type}|{episode_start_iso}"
```

It posts to backend:

- If trip active: `POST /trips/<trip_id>/ai-results`
- If trip not active: `POST /events` (with `trip_id` omitted / background mode)

### Warnings (AI engine)

Warnings are derived from detections and risk levels with cooldowns:

- Cooldown defaults:
  - `ALERT_COOLDOWN_SEC` default 10
  - occlusion cooldown `OCCLUSION_ALERT_COOLDOWN` default 3

Warning keys include:

- `drowsiness`, `yawning`, `distraction`
- `driver_not_visible`
- `mouth_occluded`
- `driver_too_far_from_camera`
- `camera_blocked`
- `risk_high`, `risk_critical`
- `sos_triggered`

---

## Data model (MongoDB)

This section documents the fields used by code paths in this repo.

### `trips` collection

Core trip document fields (not exhaustive; includes the fields actively read/written):

```json
{
  "_id": "ObjectId",
  "trip_id": "uuid",
  "driver_id": "string",
  "driver_name": "string",
  "vehicle_no": "string",
  "license_no": "string",
  "start_time": "datetime",
  "end_time": "datetime|null",
  "status": "ACTIVE|COMPLETED",
  "end_reason": "string|null",

  "sensor_data": [
    {
      "timestamp": "...",
      "speed": 0,
      "...": "arbitrary sensor payload"
    }
  ],

  "path": [
    {
      "lat": 0.0,
      "lon": 0.0,
      "lng": 0.0,
      "timestamp": "...",
      "risk": 0
    }
  ],

  "ai_events": [
    {
      "timestamp": "ISO string",
      "start_time": "ISO string|null",
      "end_time": "ISO string|null",
      "duration_s": 0.0,
      "status": "active|frame|ended",
      "event_action": "start|frame|end",
      "event_key": "stable dedupe key|null",
      "episode_id": "string|null",
      "event_type": "string",
      "event_labels": ["drowsiness", "yawning"],
      "detections": [{"type":"drowsiness","confidence":1.0,"source":"behavior_engine"}],
      "risk_score": 0,
      "risk_score_temporal": 0,
      "risk_score_weighted": 0,
      "risk_level": "SAFE|MODERATE|HIGH|CRITICAL",
      "risk_level_temporal": "LOW|MEDIUM|HIGH|CRITICAL",
      "risk_level_weighted": "SAFE|MODERATE|HIGH|CRITICAL",
      "reasons": ["..."],
      "driver_emotion": {"driver_emotion":"neutral","confidence":0.8,"stress_level":"LOW"},
      "passenger_emotions": [],
      "metadata": {"cv_metrics": {"...": "..."}, "warnings": []},
      "source": "ai_engine|mobile_app"
    }
  ],

  "sos_triggered": true,
  "sos_timestamp": "datetime|null",
  "sos_events": [
    {
      "event_type": "SOS",
      "timestamp": "datetime",
      "source": "ai_engine|mobile_app",
      "duration": 0.0,
      "metadata": {"location": {"lat": 0.0, "lng": 0.0}},
      "received_at": "datetime"
    }
  ],

  "distance_km": 0.0,
  "max_speed": 0.0,
  "duration_minutes": 0.0,
  "emotion_summary": {"stress_level":"LOW", "dominant_emotion":"neutral", "...": "..."},

  "risk_score": 0.0,
  "risk_level": "SAFE"
}
```

### `events` collection (background detections + emergency feed)

```json
{
  "_id": "ObjectId",
  "event_id": "uuid",
  "trip_id": "uuid|null",
  "timestamp": "ISO|string|datetime (older docs may vary)",
  "received_at": "datetime",
  "start_time": "ISO",
  "end_time": "ISO|null",
  "duration_s": 0.0,
  "status": "active|frame|ended",
  "event_action": "start|frame|end",
  "episode_id": "string|null",
  "event_key": "string|null",
  "event_type": "string",
  "event_labels": ["..."],
  "detections": [{"type":"..."}],
  "risk_score_temporal": 0,
  "risk_score_weighted": 0,
  "risk_level": "SAFE|MODERATE|HIGH|CRITICAL",
  "reasons": [],
  "is_sos": false,
  "sos_source": "...",
  "driver_emotion": {"...": "..."},
  "passenger_emotions": [],
  "source": "ai_engine|mobile_app",
  "metadata": {"...": "..."}
}
```

### `drivers` collection (embeddings)

Used by the AI engine identity layer:

```json
{
  "driver_id": "string",
  "embedding": [0.0123, 0.0456, "..."],
  "embedding_dim": 128,
  "embedding_updated_at": "datetime"
}
```

### `driver_calibrations` collection (structured calibration)

Used by both backend-side calibration model and AI-engine structured calibration.

The AI engine persists phase capture progress and freezes thresholds on completion.

---

## Behavior detection and temporal rules

Behavior detection is stateful and implemented in `ai_engine/behavior_engine.py`.

### Temporal buffering and smoothing

- Rolling buffer: **2.0 seconds** of samples
- Smoothing: **0.6 seconds**
- Assumed FPS: **15** (used to derive frame-based gates)

### Episode activation gates

Defaults (unless overridden by env):

- Min consecutive time (derived):
  - drowsiness ~0.6s
  - yawning ~0.3s
  - distraction immediate

- Min duration (time-based):
  - drowsiness: 0.45s
  - yawning: 0.25s
  - distraction: 0.0s

- Cooldowns (to prevent immediate duplicates):
  - yawning: 1.0s
  - distraction: 0.5s

### Blink filtering (anti-false-positive)

Blink-related tunables:

- ignore low-EAR dips shorter than `BLINK_IGNORE_SECONDS` (default 0.5s)
- blink event min/max duration:
  - `BLINK_EVENT_MIN_SECONDS` default 0.05
  - `BLINK_EVENT_MAX_SECONDS` default 0.8
- blink window for counting: `BLINK_WINDOW_SECONDS` default 60

### Distraction detection

- Requires duration >= `DISTRACTION_MIN_SECONDS` (default 0.6s)
- Trigger yaw angle threshold: `DISTRACTION_YAW_TRIGGER_DEG` (default 45°)
- Uses a short averaging window: `DISTRACTION_YAW_AVG_FRAMES` (default 3)
- Eye-closure gating factor: `DISTRACTION_EAR_GATE_FACTOR` (default 0.3)

### Yawning detection

Yawning uses a sustained open-mouth + peak requirement:

- Min duration: `YAWNING_MIN_SECONDS` default 0.9s
- Absolute thresholds:
  - `YAWNING_OPEN_THRESHOLD_ABS` default 0.58
  - `YAWNING_PEAK_THRESHOLD_ABS` default 0.70
- Scaling:
  - `YAWNING_MAR_THRESHOLD_SCALE` default 1.10
  - `YAWNING_PEAK_THRESHOLD_SCALE` default 1.30
- Averaging window: `YAWNING_MAR_AVG_FRAMES` default 5
- EAR gate factor: `YAWNING_EAR_GATE_FACTOR` default 0.97
- Variance/noise controls:
  - `YAWNING_VARIANCE_WINDOW` default 10
  - `YAWNING_MAX_VARIANCE` default 0.012
  - `YAWNING_MAX_STEP` default 0.10
  - `YAWNING_MIN_RISE_RATIO` default 0.6

### Occlusion and camera quality

The engine can warn about:

- face missing:
  - warning after `FACE_MISSING_WARN_SECONDS` default 2.0s
  - critical camera blocked after `CAMERA_BLOCKED_CRITICAL_SECONDS` default 5.0s
- driver not visible:
  - when `driver_last_seen_s_ago` >= `DRIVER_NOT_VISIBLE_AFTER_S` (default 3.0s)
- too far from camera:
  - warn after `TOO_FAR_WARN_SECONDS` default 2.0s
  - based on `TOO_FAR_FACE_AREA_RATIO` (default 0.018) and `TOO_FAR_EYE_DISTANCE_NORM` (default 0.055)
- mouth occluded:
  - warn after `MOUTH_OCCLUDED_WARN_SECONDS` default 1.0s
  - drop ratio threshold: `MOUTH_OCCLUDED_DROP_RATIO` default 0.22
  - visibility min ratio: `MOUTH_VISIBILITY_MIN_RATIO` default 0.40

---

## Risk scoring

Risk scoring is implemented in `ai_engine/risk_engine.py`.

### Inputs

- `detections[]` (types like drowsiness/yawning/distraction/driver_not_visible)
- `raw_scores` in 0..1:
  - `eyes_closed_score`
  - `head_off_road_score`
  - `yawning_score`
- `speed_kmh`

### Per-trip counters (stateful)

Maintained per `trip_id`:

- `drowsiness_events`
- `yawning_events`
- `looking_away_events`
- `overspeed_count`
- `total_frames_analyzed`

### Temporal risk score

Base score formula:

```
base_score = 45*eyes_closed_score + 30*head_off_road_score + 15*yawning_score + 10*speed_norm
speed_norm = min(speed, speed_norm_cap_kmh) / speed_norm_cap_kmh
```

Escalation rules:

- Drowsiness: +10 (>=2), +20 (>=3)
- Yawning: +5 (>=2), +15 (>=4)
- Distraction: +15 (>=3), +25 (>=5)
- Overspeed + fatigue combo: +20 when overspeed ratio > 0.5 and (drowsiness>0 or yawning>0)

Temporal score is clamped to 0..100.

Temporal label buckets:

- `LOW` < 35
- `MEDIUM` 35–59
- `HIGH` 60–79
- `CRITICAL` >= 80

### Weighted risk score

Default weights:

- overspeed: 0.25
- drowsiness: 0.30
- distraction: 0.35
- yawning: 0.10

Weighted label buckets:

- `SAFE` < 21
- `MODERATE` 21–50
- `HIGH` 51–75
- `CRITICAL` >= 76

### Policy override: driver not visible

If `driver_not_visible` is active:

- temporal score is floored to at least 60
- weighted score is floored to at least 51 (HIGH)

### Final fusion decision

Implemented in `ai_engine/final_decision_engine.py`:

- Combines driver weighted risk with emotion risk using `beta = 0.15`.
- SOS overrides final score to 100.

---

## Alerts and audio behavior

There are two alert layers:

1. **AI Engine warnings** (`warnings[]` in `/analyze_frame` response)
   - Generated with cooldown in `ai_engine/alert_engine.py`.
2. **Frontend audio beeps** (`frontend/src/pages/LiveMonitoring.jsx`)
   - Transition-based beeps for detections
   - Longer 3-second beep tones

Frontend transition rules:

- Plays only when a type becomes active (inactive → active).
- Uses both per-type cooldowns and a small global spacing.

---

## SOS (Emergency) flow

### Trigger sources

- **AI engine passenger gesture**: crossed-arms held long enough
- **AI engine driver SOS**: supported by SOS payload structure (and warnings)
- **Mobile/manual SOS**: backend exposes `POST /sos/<trip_id>`

### Backend persistence

When backend receives `POST /trips/<trip_id>/sos`:

- sets `trips.sos_triggered = true`
- appends a record to `trips.sos_events[]`
- inserts a record into `events` as an emergency feed event

### WhatsApp messaging via Twilio

If Twilio env vars are configured, backend will send a WhatsApp SOS message.

- It uses `PUBLIC_BASE_URL` (if set) to build a tracking link for the trip.

---

## Environment variables

### Frontend (`frontend/`)

- `VITE_API_BASE` (default `http://localhost:5000`)
- `VITE_AI_ENGINE_BASE` (default `http://localhost:5001`)

### Backend (`backend/`)

Loaded via `python-dotenv` (`load_dotenv()`), so you can use a `.env` file.

- `PUBLIC_BASE_URL` (optional; used to build links in SOS messages)
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_WHATSAPP_FROM` (default `whatsapp:+14155238886`)
- `TWILIO_WHATSAPP_TO`

### AI engine (`ai_engine/`)

Core wiring:

- `AI_ENGINE_PORT` (default `5001`)
- `BACKEND_BASE_URL` (default `http://localhost:5000`)
- `NO_ACTIVE_TRIP_ID` (default `NO_ACTIVE_TRIP`)

Mongo / storage:

- `MONGO_URI` (default `mongodb://localhost:27017/`)
- `MONGO_DB` (default `ivs_db`)
- `DB_NAME` (alternative DB-name override used by driver registry service)
- `MONGO_CONNECT_TIMEOUT_MS` (default `1500`)
- `MONGO_DRIVERS_COLLECTION` (default `drivers`)
- `MONGO_CALIBRATION_COLLECTION` (default `driver_calibrations`)

Identity verification:

- `IDENTITY_MATCH_EVERY_N_FRAMES` (default `20`)
- `IDENTITY_MATCH_TOLERANCE` (default `0.5`)
- `DRIVER_NOT_VISIBLE_AFTER_S` (default `3.0`)
- `IDENTITY_VERIFY_INTERVAL_S` (default `12.0`)
- `TRIP_DRIVER_CACHE_TTL` (default `600`)
- `DRIVER_EMBEDDINGS_CACHE_TTL` (default `30`)
- `AI_ENGINE_MODELS_DIR` (default `ai_engine/models`)
- `DRIVER_EMBEDDINGS_PATH` (default `ai_engine/driver_embeddings.json`)

Session + thresholds:

- `THRESHOLD_CACHE_TTL` (default `300` in app, used as TTL)
- `DRIVER_SESSION_TTL` (default `1800`)
- `DEFAULT_EAR_THRESH` (default `0.20`)
- `DEFAULT_MAR_THRESH` (default `0.08`)
- `DEFAULT_HEAD_TURN_THRESH` (default `20`)

Slow analytics loop:

- `SLOW_ANALYTICS_INTERVAL_S` (default `5.0`)

Episode persistence:

- `EPISODE_EVENT_TYPES` (default `yawning,distraction,driver_not_visible,drowsiness`)
- `EPISODE_PERSIST_MIN_SECONDS` (default `0.8`)
- `COMPUTE_RISK_PERSIST_EVENTS` (default `0`)

Passenger SOS gesture:

- `CROSS_ARMS_RATIO_THRESH` (default `0.55`)
- `CROSS_ARMS_SOS_DURATION_S` (default `4.0`)

Alert engine cooldowns:

- `ALERT_COOLDOWN_SEC` (default `10`)
- `OCCLUSION_ALERT_COOLDOWN` (default `3`)

Landmark engine:

- `FACE_LANDMARK_EXPECTED` (default `468`)
- `FACE_LANDMARK_MIN_RATIO` (default `0.45`)

Calibration engine:

- phase capture counts:
  - `CALIB_NEUTRAL_FRAMES` (default 30)
  - `CALIB_EYES_CLOSED_FRAMES` (default 20)
  - `CALIB_YAWNING_FRAMES` (default 20)
  - `CALIB_HEAD_TURN_FRAMES` (default 20)
- session TTL: `CALIB_SESSION_TTL` (default 1200)
- safe defaults:
  - `SAFE_DEFAULT_EAR_DROWSINESS` (default 0.20)
  - `SAFE_DEFAULT_MAR_YAWNING` (default 0.60)
  - `SAFE_DEFAULT_HEAD_TURN` (default 35.0)
- clamp ranges:
  - `CALIB_EAR_MIN` (default 0.10), `CALIB_EAR_MAX` (default 0.30)
  - `CALIB_MAR_MIN` (default 0.45), `CALIB_MAR_MAX` (default 0.90)
  - `CALIB_HEAD_MIN` (default 25.0), `CALIB_HEAD_MAX` (default 70.0)

Behavior engine tunables (quality + detection tuning):

- Blink:
  - `BLINK_IGNORE_SECONDS` (0.5)
  - `BLINK_EVENT_MIN_SECONDS` (0.05)
  - `BLINK_EVENT_MAX_SECONDS` (0.8)
  - `BLINK_WINDOW_SECONDS` (60.0)
- Face/visibility/camera:
  - `FACE_MISSING_WARN_SECONDS` (2.0)
  - `CAMERA_BLOCKED_CRITICAL_SECONDS` (5.0)
  - `MIN_FACE_PRESENCE_CONF` (0.5)
  - `MIN_LANDMARK_RATIO` (0.7)
  - `BASELINE_LEARNING_SECONDS` (10.0)
- Too far:
  - `TOO_FAR_WARN_SECONDS` (2.0)
  - `TOO_FAR_FACE_AREA_RATIO` (0.018)
  - `TOO_FAR_EYE_DISTANCE_NORM` (0.055)
- Occlusion:
  - `MOUTH_OCCLUDED_WARN_SECONDS` (1.0)
  - `MOUTH_OCCLUDED_DROP_RATIO` (0.22)
  - `MOUTH_VISIBILITY_MIN_RATIO` (0.40)
  - `MOUTH_JUMP_THRESHOLD` (0.06)
  - `MAR_NOISE_OCCLUSION_VAR` (0.03)
- Distraction:
  - `DISTRACTION_MIN_SECONDS` (0.6)
  - `DISTRACTION_YAW_TRIGGER_DEG` (45.0)
  - `DISTRACTION_YAW_AVG_FRAMES` (3)
  - `DISTRACTION_EAR_GATE_FACTOR` (0.3)
- Yawning:
  - `YAWNING_MIN_SECONDS` (0.9)
  - `YAWNING_MAR_THRESHOLD_SCALE` (1.10)
  - `YAWNING_PEAK_THRESHOLD_SCALE` (1.30)
  - `YAWNING_MAR_AVG_FRAMES` (5)
  - `YAWNING_OPEN_THRESHOLD_ABS` (0.58)
  - `YAWNING_PEAK_THRESHOLD_ABS` (0.70)
  - `YAWNING_EAR_GATE_FACTOR` (0.97)
  - `YAWNING_STRONG_PEAK_MARGIN` (1.10)
  - `YAWNING_OPEN_RELEASE_SCALE` (0.97)
  - `YAWNING_VARIANCE_WINDOW` (10)
  - `YAWNING_MAX_VARIANCE` (0.012)
  - `YAWNING_MAX_STEP` (0.10)
  - `YAWNING_MIN_RISE_RATIO` (0.6)
- Head pose extra thresholds:
  - `DEFAULT_HEAD_PITCH_THRESH` (18)
  - `DEFAULT_HEAD_ROLL_THRESH` (17)
- EMA:
  - `YAW_EMA_ALPHA` (0.3)

---

## Setup and run

### Prerequisites

- Python 3.10+ recommended (MediaPipe / ONNX Runtime compatibility)
- Node.js (for Vite)
- MongoDB running locally
- A webcam (for live monitoring)

### 1) Start MongoDB

Make sure MongoDB is running and listening on `mongodb://localhost:27017/`.

The backend currently connects to MongoDB using a fixed URI in code.

### 2) Backend setup (port 5000)

From `backend/`:

```bash
python -m venv .venv
```

Activate venv (Windows PowerShell):

```bash
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Optional `.env` (in `backend/`):

```env
PUBLIC_BASE_URL=https://<your-ngrok-or-public-host>

TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
TWILIO_WHATSAPP_TO=whatsapp:+<your-number>
```

Run:

```bash
python app.py
```

### 3) AI engine setup (port 5001)

From `ai_engine/`:

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run:

```bash
python app.py
```

Optional env config (examples):

```env
BACKEND_BASE_URL=http://localhost:5000
AI_ENGINE_PORT=5001

MONGO_URI=mongodb://localhost:27017/
MONGO_DB=ivs_db

SLOW_ANALYTICS_INTERVAL_S=5.0
EPISODE_PERSIST_MIN_SECONDS=0.8
```

### 4) Frontend setup

From `frontend/`:

```bash
npm install
```

Optional `.env` (in `frontend/`):

```env
VITE_API_BASE=http://localhost:5000
VITE_AI_ENGINE_BASE=http://localhost:5001
```

Run dev server:

```bash
npm run dev
```

Open the printed local URL (usually `http://localhost:5173`).

---

## API reference

## Backend API (port 5000)

### Health

`GET /`

Response:

```json
{ "status": "ok", "boot_id": "...", "boot_at": "...Z" }
```

### Driver session

`POST /driver-session`

Body:

```json
{
  "driver_name": "Alice",
  "vehicle_no": "KA-01-AB-1234",
  "license_no": "DL-123",
  "driver_id": "DL-123"
}
```

### Create trip

`POST /trips`

Notes:

- Requires `driver_id` (or `license_no`) either in the request or previously stored in `/driver-session`.
- Auto-ends existing ACTIVE trips.

Example:

```bash
curl -X POST http://localhost:5000/trips \
  -H "Content-Type: application/json" \
  -d '{
    "driver_id": "DL-123",
    "driver_name": "Alice",
    "vehicle_no": "KA-01-AB-1234",
    "license_no": "DL-123"
  }'
```

### List trips

`GET /trips`

Response includes computed fields like `max_speed` and `distance_km`.

### Trip details

`GET /trips/<trip_id>`

- Returns trip plus a consolidated `events[]` timeline (AI + SOS, sorted).

### End trip

`PUT /trips/<trip_id>/end`

- Computes and stores: `distance_km`, `max_speed`, `duration_minutes`, `emotion_summary`.

### Telemetry ingestion

`POST /trips/<trip_id>/location`

`POST /trips/<trip_id>/sensor`

### Live map payloads

`GET /trips/active-trip/live_map`

Response shape:

```json
{
  "trip_active": true,
  "trip_id": "...",
  "trip_start_time": "2026-01-01T00:00:00Z",
  "current_location": {"lat": 12.34, "lng": 56.78},
  "path": [ {"lat": 12.34, "lon": 56.78, "timestamp": "..."} ]
}
```

`GET /trips/<trip_id>/live_map`

### Distance endpoints

`GET /trips/<trip_id>/distance`

`GET /trips/active-trip/distance`

### AI results persistence

`POST /trips/<trip_id>/ai-results`

Episode-style payloads (simplified example):

```json
{
  "timestamp": "2026-01-01T00:00:00Z",
  "event_action": "start",
  "event_type": "drowsiness",
  "event_key": "<trip|driver|type|start>",
  "episode_id": "optional",
  "episode_start_ts": "2026-01-01T00:00:00Z",
  "detections": [{"type":"drowsiness","confidence":1.0}],
  "risk_score_weighted": 72.3,
  "risk_level_weighted": "HIGH",
  "risk_level": "HIGH",
  "driver_emotion": {"driver_emotion":"neutral","confidence":0.7,"stress_level":"LOW"},
  "metadata": {"cv_metrics": {"ear": 0.19}}
}
```

To end an episode:

```json
{
  "event_action": "end",
  "event_key": "...",
  "episode_end_ts": "2026-01-01T00:00:10Z",
  "duration_s": 10.0
}
```

### Background events

`POST /events`

Used when there is no active trip; shares the same episode semantics.

`GET /events`

Query params:

- `limit`, `skip`
- `risk_level`
- `event_type`
- `start`, `end` (ISO; filtered on `received_at`)
- `include_empty` (default `1`)

### SOS

`POST /trips/<trip_id>/sos`

`POST /sos/<trip_id>` (manual send; accepts trip_id or Mongo _id)

`GET /events/emergency`

### Exports

- `GET /trip/<trip_id>/download`
- `GET /trip/<trip_id>/download_csv`
- `GET /trip/<trip_id>/map_image`
- `GET /trip/<trip_id>/report` (PDF)

---

## AI Engine API (port 5001)

### Health

`GET /health`

### Analyze frame

`POST /analyze_frame`

Image-mode request (frontend uses this pattern):

```json
{
  "trip_id": "<uuid or null>",
  "image": "<base64 jpeg (no data: prefix)>",
  "frame_id": "optional",
  "input_type": "webcam",
  "speed": 45
}
```

Response (high-level fields; many nested details exist):

```json
{
  "trip_id": "...",
  "trip_active": true,
  "detections": [{"type":"drowsiness","confidence":1.0,"source":"behavior_engine"}],
  "risk_score_weighted": 0.0,
  "risk_level_weighted": "SAFE",
  "risk_score": 0.0,
  "risk_level": "SAFE",
  "event_counters": {"drowsiness_events":0,"yawning_events":0,"looking_away_events":0,"overspeed_count":0,"total_frames_analyzed":1},
  "driver_emotion": {"driver_emotion":"neutral","confidence":0.8,"stress_level":"LOW"},
  "emotion_result": {"dominant_emotion":"neutral","confidence":0.8,"stress_level":"LOW","emotion_risk_score":0.0},
  "cv_metrics": {"ear":0.25,"mar":0.05,"yaw_angle":0.0,"faces_meta":[]},
  "warnings": [{"type":"drowsiness","severity":"MEDIUM","message":"Driver drowsiness detected."}],
  "sos_triggered": false,
  "processing_ms": 12.34
}
```

### Compute risk (no image required)

`POST /compute_risk`

- Can optionally persist events when `COMPUTE_RISK_PERSIST_EVENTS=1`.

### Driver registration (embeddings)

`POST /drivers/register`

```json
{
  "driver_id": "DL-123",
  "images": ["<base64>", "<base64>"]
}
```

### Calibration (AI engine)

The AI engine exposes structured calibration endpoints:

- `POST /drivers/<driver_id>/calibration/start`
- `GET /drivers/<driver_id>/calibration/status`
- `POST /drivers/<driver_id>/calibration/frame`
- `POST /drivers/<driver_id>/calibration/complete`

### Trip counters

- `GET /trips/<trip_id>/counters`
- `POST /trips/<trip_id>/counters/reset`

### Session reset helpers

- `POST /trips/<trip_id>/complete`
- `POST /trips/<trip_id>/session/reset`

---

## Tools and scripts

Folder: `tools/`

- `check_mongo.py`: connectivity / basic DB checks
- `check_persistence.py`: checks whether events are being stored
- `manual_episode_insert.py`: helper to insert episode-shaped events
- `test_detection.py`: detection testing harness
- `test_sort.py`: sorting test utility
- `view_trip_detail.py`: view trip contents
- `view_trips.py`: list trips

---

## Known limitations / mismatches

These items are based on current code state:

1. **Backend Mongo URI is hardcoded** (`mongodb://localhost:27017/`) in `backend/app.py`.
2. **Frontend calibration page calls non-existent endpoints on backend**:
   - `frontend/src/pages/CalibrationPage.jsx` calls `/drivers/<id>/calibrate/*` on `VITE_API_BASE`, but the implemented calibration endpoints are:
     - Backend: `/drivers/<driver_id>/calibration/*` (backend-side calibration model)
     - AI engine: `/drivers/<driver_id>/calibration/*` (structured calibration)
3. **Frontend speed telemetry is synthetic**:
   - LiveMonitoring uses `subscribeLive()` from `frontend/src/services/liveTelemetry.js`, which generates randomized speed/state.
   - Map position is *not* synthetic (it polls backend live_map). If the backend has no GPS points, the map shows “No location coordinates available”.
4. Docs under `docs/` may describe conceptual flows that do not exactly match current implementation defaults.

---

## Troubleshooting

### AI engine shows Offline in UI

- Confirm AI engine is running on `VITE_AI_ENGINE_BASE` (default `http://localhost:5001`).
- Check `GET /health` on AI engine.

### No live position on map

- Backend only returns coordinates if your trip has `path[]` points.
- Post GPS points via `POST /trips/<trip_id>/location` (or ensure your data source is doing so).

### PDF report download fails

- Backend returns 501 if `reportlab` is not installed.
- Install in backend venv: `pip install reportlab`.

### WhatsApp SOS messages not sending

- Configure Twilio env vars in backend `.env`.
- Ensure `TWILIO_WHATSAPP_TO` is correct and you have WhatsApp sandbox/number approved.

### Webcam / audio blocked by browser

- Camera requires HTTPS in some contexts; localhost is typically allowed.
- Audio beeps require a user interaction; LiveMonitoring adds listeners for pointerdown/keydown to unlock audio.
