# System Architecture: Intelligent Vehicle Safety (IVS)

## Architecture Style

The IVS system follows a strict linear pattern:  
**Sensing & Perception (ML) → Reasoning (AI) → Action → Storage → Visualization**

This pattern ensures a clean separation between what the system *perceives* from sensors (ML layer), what it *understands* about the situation (AI layer), and how it *communicates* the state (storage & visualization layers).

---

## Layer A: Mobile Layer (Android App)

**Purpose**: Replace external IoT hardware for location sharing and manual emergency trigger.

**Responsibilities**:
- Start and end trip events with trip ID generation
- Foreground GPS tracking and continuous location updates
- Send location data to backend ({trip_id, lat, lon, timestamp})
- Manual SOS trigger via button, long press, or simple gesture ({trip_id, sos_event, source=MOBILE_APP})

**Does NOT do**:
- Machine learning processing or signal detection
- Risk scoring or severity assessment
- Decision-making logic
- Communicate directly with dashboard or other components

This layer is a **utility tool**, not a full mobile product. It acts as a simple IoT device providing raw location and explicit SOS input to the backend.

---

## Layer B: Driver & Passenger Monitoring Layer (ML – Perception)

**Purpose**: Detect patterns in camera video and emit perception signals only—never decisions.

**Inputs**:
- Camera video stream from vehicle system (laptop/vehicle computer)

**ML Outputs** (signals only, not decisions):
- Driver drowsiness signals: PERCLOS (eye closure ratio), yawning patterns, confidence score
- Driver distraction signals: head pose deviation, gaze direction, attention confidence
- Passenger distress signals: abnormal behavior indicators (support-level only)
- SOS gesture detection: hands crossed above head in X-shape (≥3–5 seconds sustained)

**Responsibilities**:
- Process camera frames in real-time
- Emit signal tuples: {trip_id, signal_type, confidence, duration}
- Emit SOS events on sustained gesture detection: {trip_id, sos_event, source=ML_GESTURE}

**Does NOT do**:
- Make emergency decisions or risk assessments
- Trigger irreversible actions alone
- Act on emotion or expression signals as primary triggers
- Send data directly to dashboard or end users

**Key Rule**: ML detects *patterns*, not *meaning*. The AI layer interprets what these patterns mean.

---

## Layer C: AI Decision & Risk Engine (Core AI)

**Purpose**: The brain of the system. Interpret ML signals and temporal context to answer: *"What does the situation mean?"*

**Inputs**:
- ML signals: drowsiness, distraction, passenger distress (with confidence & duration)
- SOS events: from ML gesture detection OR mobile app (dual paths)
- Temporal context: signal frequency, duration, trends, trip progress
- Trip metadata: time of day, duration, speed context

**Responsibilities**:
- Rule-based multi-signal risk scoring combining:
  - Drowsiness confidence × duration
  - Distraction frequency × intensity
  - Combined driver fatigue profile
  - Passenger distress escalation logic
- Generate risk levels: Low → Medium → High → Critical
- Decide on interventions:
  - Generate driver warnings (alert_type, severity)
  - Suggest SOS to passenger (when critical state detected)
  - Escalate emergency status (mark trip = EMERGENCY)
- Manage temporal state: rising risk trends, recovery patterns

**Rules**:
- Emotion/expression signals are *support signals only*, never primary triggers
- Single signal threshold violations trigger alerts (e.g., drowsiness confidence > 0.8)
- Multi-signal confirmation escalates from alert to SOS suggestion
- SOS event (either source) immediately escalates trip to EMERGENCY status
- Risk state transitions are logged for post-trip analysis

**Does NOT do**:
- Control vehicle systems or make autonomous decisions
- Act without explicit SOS event confirmation for emergencies
- Bypass dual-path SOS logic
- Communicate directly with end users (goes through backend/dashboard)

**Output**:
- {trip_id, risk_level, warnings[], suggestions, timestamp}
- {trip_id, emergency_escalation, reason}

---

## Layer D: Backend & Storage (Flask + MongoDB)

**Purpose**: System memory and communication hub. Manages data lifecycle and API contracts.

**Responsibilities**:
- Expose REST APIs for all layers (ML system, Mobile app, Dashboard)
- Trip lifecycle management: create, update, complete, cancel
- Receive and persist:
  - GPS points (ordered sequence with timestamp)
  - ML signals (drowsiness, distraction, behavior)
  - SOS events (source: ML_GESTURE or MOBILE_APP)
  - Risk state transitions and AI decisions
  - Driver warnings and alerts
- Maintain ordered event logs per trip
- Serve live trip state to dashboard
- Aggregate data for post-trip report generation

**Database Schema** (MongoDB):
```
trips: {trip_id, driver_id, status, start_time, end_time, start_location, end_location}
gps_points: {trip_id, lat, lon, timestamp, accuracy}
events: {trip_id, event_type, source, signal_type, confidence, timestamp}
risk_history: {trip_id, risk_level, transition_reason, timestamp}
sos_events: {trip_id, source, timestamp, action_taken}
```

**Does NOT do**:
- Make risk decisions (all decisions come from AI layer)
- Trigger SOS directly (logs SOS from upstream layers)
- Control system flow or state machines

Backend is the **system memory** — it faithfully records and retrieves what other layers tell it.

---

## Layer E: Web Dashboard (Visualization)

**Purpose**: Provide situational awareness and post-trip analysis. Observer layer only.

**Responsibilities**:
- **Live Trip View**: Real-time vehicle location on map (via WebSocket/polling)
- **Route Polyline**: Current and historical path visualization
- **Event Timeline**: Chronological display of drowsiness, distraction, and SOS events
- **Risk Status Display**: Current risk level, active warnings, driver state indicators
- **Emergency Indicator**: Highlight when trip is in EMERGENCY status
- **Post-Trip Safety Report**: 
  - Risk timeline graph
  - Event summary (total drowsiness events, distraction duration, etc.)
  - Aggregated safety score
  - Observations and trends from the trip

**Does NOT do**:
- Trigger SOS or emergency actions
- Make any system decisions
- Modify trip status directly
- Run ML or risk computations
- Send commands to other layers

Dashboard is a **read-only observer** of system state.

---

## Data Flow Summary

### Normal Trip (No Emergency)
1. **Mobile layer**: Trip start → backend receives trip_id
2. **Mobile layer**: GPS stream continuously → backend stores location history
3. **ML layer**: Camera frames processed → drowsiness/distraction signals → AI layer
4. **AI layer**: Risk scoring → backend logs risk transitions
5. **Dashboard**: Polls backend for live state, shows location + risk timeline

### SOS Flow (Dual Path)
**Path 1 - ML Gesture SOS**:
1. Passenger performs X-shape gesture
2. ML layer detects sustained (3–5 sec) gesture
3. ML sends SOS event to backend (source=ML_GESTURE)
4. AI layer confirms via rule (immediate escalation)
5. Backend marks trip = EMERGENCY
6. Dashboard shows emergency state, enforces location sharing
7. Event logged for analysis

**Path 2 - Mobile App SOS**:
1. Passenger presses SOS button in mobile app
2. App sends SOS event to backend (source=MOBILE_APP)
3. Backend marks trip = EMERGENCY
4. AI layer processes escalation logic in next decision cycle
5. Same emergency flow as above

Both paths → same backend emergency logic and dashboard display.

### Post-Trip Flow
1. Trip ends → backend finalizes event log
2. AI layer aggregates all signals and risk transitions
3. Risk timeline generated (drowsiness curve, distraction events, SOS history)
4. Post-trip safety report created (event count, peak risk, recovery patterns)
5. Dashboard displays full report for review

---

## Architectural Rules (Non-Negotiable)

1. **ML never triggers irreversible actions alone** — All critical decisions pass through AI layer
2. **Mobile app never computes risk** — Computation happens at AI layer only
3. **Dashboard never controls system** — It observes only; changes flow through backend REST APIs
4. **AI logic lives in ONE place** — No distributed decision-making; single source of truth
5. **Emotion detection is support only** — Never a primary trigger for warnings or escalation
6. **SOS has dual trigger paths** — Both ML gesture and mobile app can trigger emergency
7. **ML signals are time-windowed** — Drowsiness/distraction require sustained duration, not instantaneous spikes
8. **Risk state is stateful** — Recovery from critical risk must be explicit and logged

---

## Why This Architecture Works

- **Clear Separation of Concerns**: Each layer has one job; layers don't duplicate responsibilities
- **Defensible AI/ML Boundary**: ML ≠ decision-making; this is the key insight
- **Traceability**: Every action is logged with source (ML or Mobile) for viva/audit
- **Redundancy**: Dual SOS paths ensure emergency access from ML *or* passenger choice
- **Scalability**: Backend can later add cloud sync, more sensors, without changing core logic
- **Safety**: No single ML model failure can trigger emergency; requires confirmation via AI layer

