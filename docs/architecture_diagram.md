# IVS System Architecture Diagram

```
╔════════════════════════════════════════════════════════════════════════════════════╗
║              INTELLIGENT VEHICLE SAFETY (IVS) SYSTEM ARCHITECTURE                  ║
║                                                                                    ║
║           Sensing & Perception (ML) → Reasoning (AI) → Action → Storage → Viz    ║
╚════════════════════════════════════════════════════════════════════════════════════╝


┌──────────────────────────────────────────────────────────────────────────────────────┐
│ LAYER E: WEB DASHBOARD (Visualization / Observer Only)                              │
│ ────────────────────────────────────────────────────────────────────────────────────  │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐    │
│  │  • Live Map with Vehicle Location                                           │    │
│  │  • Route Polyline (current path)                                            │    │
│  │  • Event Timeline (drowsiness, distraction, SOS)                            │    │
│  │  • Risk Status Display (Low / Medium / High / Critical)                      │    │
│  │  • Emergency Indicator (EMERGENCY flag when trip in critical state)          │    │
│  │  • Post-Trip Safety Report (aggregated timeline, observations)              │    │
│  │                                                                             │    │
│  │  Does NOT: Make decisions, trigger SOS, control system                      │    │
│  └─────────────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────────────┘
                                        △
                                        │
                    REST APIs (GET trip state, events, risk)
                                        │
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ LAYER D: BACKEND & STORAGE (Flask + MongoDB / System Memory Hub)                    │
│ ────────────────────────────────────────────────────────────────────────────────────  │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐    │
│  │  REST API Endpoints:                                                        │    │
│  │  • /trip/{id}/start                                                         │    │
│  │  • /trip/{id}/end                                                           │    │
│  │  • /trip/{id}/gps  (receive location)                                       │    │
│  │  • /trip/{id}/signal  (receive ML signals)                                  │    │
│  │  • /trip/{id}/sos  (receive SOS events)                                     │    │
│  │  • /trip/{id}/state  (serve live state)                                     │    │
│  │                                                                             │    │
│  │  MongoDB Collections:                                                       │    │
│  │  • trips (trip_id, status, timestamps)                                      │    │
│  │  • gps_points (ordered location history)                                    │    │
│  │  • events (signals, SOS, timestamps)                                        │    │
│  │  • risk_history (risk transitions, reasons)                                 │    │
│  │  • sos_events (source: ML_GESTURE or MOBILE_APP)                            │    │
│  │                                                                             │    │
│  │  Responsibilities:                                                          │    │
│  │  ✓ Receive and persist all data                                             │    │
│  │  ✓ Manage trip lifecycle                                                    │    │
│  │  ✓ Log events with timestamps and sources                                   │    │
│  │  ✓ Serve aggregated data for reports                                        │    │
│  │                                                                             │    │
│  │  Does NOT: Make decisions, score risk, trigger actions alone                │    │
│  └─────────────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────────────┘
      △                 △                        △                         △
      │                 │                        │                         │
      │                 │                        │                         │
      │                 │                        │                         │
   POST /trip       POST /trip            POST /trip/{id}/              POST /trip/{id}/
   /gps             /signal               signal & /sos                 /sos
   {lat, lon,       {signal_type,         (AI layer decision)           (Mobile app button)
   timestamp}       confidence, dur}
      │                 │                        │                         │
      └─────────────────┴────────────────────────┴─────────────────────────┘
                                        │
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ LAYER C: AI DECISION & RISK ENGINE (Core Brain / Reasoning)                         │
│ ────────────────────────────────────────────────────────────────────────────────────  │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐    │
│  │  INPUTS:                                                                    │    │
│  │  • ML signals: drowsiness, distraction, passenger distress                  │    │
│  │  • SOS events: from ML_GESTURE or MOBILE_APP (dual paths)                   │    │
│  │  • Temporal context: signal duration, frequency, trends                     │    │
│  │                                                                             │    │
│  │  RULE-BASED RISK SCORING:                                                  │    │
│  │  • Drowsiness confidence × duration → drowsiness risk score                 │    │
│  │  • Distraction frequency × intensity → distraction risk score               │    │
│  │  • Combined multi-signal assessment → aggregate risk level                  │    │
│  │  • Emotion/expression signals = SUPPORT ONLY (never primary)                │    │
│  │                                                                             │    │
│  │  OUTPUTS & DECISIONS:                                                       │    │
│  │  ✓ Risk Level: Low / Medium / High / Critical                               │    │
│  │  ✓ Driver Warnings: audio/visual alert when threshold exceeded              │    │
│  │  ✓ SOS Suggestion: recommend SOS to passenger at critical state             │    │
│  │  ✓ Emergency Escalation: mark trip = EMERGENCY on SOS (either source)       │    │
│  │  ✓ Risk Timeline: for post-trip analysis                                    │    │
│  │                                                                             │    │
│  │  KEY RULE:                                                                  │    │
│  │  "ML detects PATTERNS. AI interprets MEANING."                              │    │
│  │                                                                             │    │
│  │  SOS Escalation Flow:                                                       │    │
│  │    SOS event (ML or Mobile) → Immediate trip = EMERGENCY status             │    │
│  │                            → Force location sharing                          │    │
│  │                            → Alert escalation                                │    │
│  │                            → Log source for accountability                   │    │
│  │                                                                             │    │
│  │  Does NOT: Control vehicle, trigger actions without SOS confirmation        │    │
│  └─────────────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────────────┘
      △                                          △
      │                                          │
      │ {trip_id, signal_type,              {trip_id, sos_event,
      │  confidence, duration}              source=ML_GESTURE}
      │                                          │
      └──────────────────────┬───────────────────┘
                             │
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ LAYER B: ML MONITORING (Driver & Passenger / Perception / Sensing)                  │
│ ────────────────────────────────────────────────────────────────────────────────────  │
│                                                                                      │
│  ┌────────────────────────────────────┬─────────────────────────────────────┐       │
│  │ DRIVER MONITORING                  │ PASSENGER MONITORING (Support)      │       │
│  │                                    │                                     │       │
│  │ • Drowsiness Detection:            │ • Abnormal behavior signals         │       │
│  │   - PERCLOS (eye closure %)        │ • Distress indicators               │       │
│  │   - Yawning patterns               │                                     │       │
│  │   - Confidence scores              │ • SOS Gesture Detection:             │       │
│  │                                    │   - X-shape (hands above head)      │       │
│  │ • Distraction Detection:           │   - ≥ 3–5 sec sustained duration    │       │
│  │   - Head pose deviation            │   - Emit SOS event to backend       │       │
│  │   - Gaze direction                 │                                     │       │
│  │   - Attention confidence           │                                     │       │
│  │                                    │                                     │       │
│  │ INPUT: Camera video stream         │ INPUT: Camera video stream          │       │
│  │        (continuous)                │        (continuous)                 │       │
│  │                                    │                                     │       │
│  │ OUTPUTS (signals only):            │ OUTPUTS (SOS or behavior):          │       │
│  │ {trip_id, signal_type,             │ {trip_id, signal_type,              │       │
│  │  confidence, duration}             │  confidence, duration}              │       │
│  │                                    │                                     │       │
│  │ Detects PATTERNS (not meaning)     │                                     │       │
│  │ Does NOT decide emergencies        │ Does NOT decide emergencies         │       │
│  │ Does NOT trigger actions           │ Does NOT trigger actions            │       │
│  └────────────────────────────────────┴─────────────────────────────────────┘       │
└──────────────────────────────────────────────────────────────────────────────────────┘
      △                                                  △
      │                                                  │
      │ Camera video stream (vehicle/laptop)            │
      │                                                  │
      └──────────────────────┬───────────────────────────┘
                             │
                    INPUT: Vehicle Camera
                             │
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ LAYER A: MOBILE APP (Android / Lightweight IoT Device)                              │
│ ────────────────────────────────────────────────────────────────────────────────────  │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐    │
│  │  Functionality:                                                             │    │
│  │  • Start / End Trip Button                                                  │    │
│  │    → Sends trip start/end to backend                                        │    │
│  │                                                                             │    │
│  │  • Foreground GPS Tracking Service                                          │    │
│  │    → Continuous location updates (background while app is active)           │    │
│  │    → Send to backend: {trip_id, lat, lon, timestamp}                        │    │
│  │                                                                             │    │
│  │  • Manual SOS Trigger                                                       │    │
│  │    → Button press OR Long press OR Swipe gesture                             │    │
│  │    → Send to backend: {trip_id, sos_event, source=MOBILE_APP}               │    │
│  │                                                                             │    │
│  │  Does NOT:                                                                  │    │
│  │  ✗ Run ML models                                                            │    │
│  │  ✗ Compute risk scores                                                      │    │
│  │  ✗ Make decisions                                                           │    │
│  │  ✗ Show emergency alerts (only sends SOS)                                   │    │
│  │                                                                             │    │
│  │  Role: SIMPLE IoT DEVICE (location + explicit SOS input)                    │    │
│  └─────────────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────────────┘


════════════════════════════════════════════════════════════════════════════════════════
DUAL SOS PATHS (Both → Same Emergency Flow)
════════════════════════════════════════════════════════════════════════════════════════

PATH 1: ML GESTURE SOS                      PATH 2: MOBILE APP SOS
─────────────────────────────────────────────────────────────────

1. Passenger performs X-shape gesture  │  1. Passenger presses SOS button
2. ML detects sustained gesture (3–5s) │  2. App sends SOS immediately
3. ML layer emits SOS intent signal    │  3. Backend receives SOS
   based on sustained gesture          │     source=MOBILE_APP
   source=ML_GESTURE                   │
4. Backend marks trip=EMERGENCY        │  4. Backend marks trip=EMERGENCY
5. AI processes escalation logic       │  5. AI processes escalation logic
6. Location sharing forced             │  6. Location sharing forced
7. Dashboard shows EMERGENCY           │  7. Dashboard shows EMERGENCY
8. Event logged with source            │  8. Event logged with source

                    ↓
        SAME BACKEND EMERGENCY LOGIC
                    ↓
   (Both sources treated equally for emergency handling)


════════════════════════════════════════════════════════════════════════════════════════
NORMAL TRIP DATA FLOW (Timeline)
════════════════════════════════════════════════════════════════════════════════════════

1. [Mobile Layer] Passenger starts trip
   → Backend creates trip_id
   → Foreground GPS service starts

2. [Mobile Layer] GPS updates continuously
   → {trip_id, lat, lon, timestamp} → Backend storage

3. [ML Layer] Camera processing (real-time)
   → Drowsiness & distraction signals → AI layer
   → {trip_id, signal_type, confidence, duration}

4. [AI Layer] Risk scoring (continuous)
   → Rules applied: drowsiness + duration → risk level
   → Backend receives: {trip_id, risk_level, warnings}

5. [Backend] Stores and aggregates
   → Events ordered by timestamp
   → Risk state transitions logged

6. [Dashboard] Live visualization
   → Polls backend every 2–5 sec
   → Shows vehicle location + risk timeline
   → Updates event list in real-time

7. [Mobile Layer] Trip ends
   → Backend finalizes trip record

8. [Dashboard] Post-trip report
   → AI layer aggregates all signals
   → Risk timeline generated
   → Observations and trends summarized


════════════════════════════════════════════════════════════════════════════════════════
ARCHITECTURAL RULES (NON-NEGOTIABLE)
════════════════════════════════════════════════════════════════════════════════════════

1. ML NEVER TRIGGERS IRREVERSIBLE ACTIONS ALONE
   → ML emits signals only
   → AI layer makes decisions
   → Backend executes actions
   → Confirmed by SOS event

2. MOBILE APP NEVER COMPUTES RISK
   → App is IoT device (location + button)
   → All logic at backend + AI layer

3. DASHBOARD NEVER CONTROLS SYSTEM
   → Read-only observer
   → No direct API calls to modify state
   → Changes only via backend REST APIs

4. AI LOGIC LIVES IN ONE PLACE
   → Single source of truth for decisions
   → No distributed decision-making
   → Easy to audit and viva

5. EMOTION DETECTION IS SUPPORT ONLY
   → Facial expressions = secondary signals
   → Never primary trigger
   → Always combined with behavior signals

6. SOS HAS DUAL TRIGGER PATHS
   → ML gesture detection (ML layer)
   → Mobile app button (Mobile layer)
   → Both reach backend equally
   → Both trigger same emergency logic

7. RISK STATE IS STATEFUL & TEMPORAL
   → Signals must exceed thresholds for duration
   → Instantaneous spikes don't trigger alerts
   → Recovery must be explicit and logged

8. TRACEABILITY & AUDITABILITY
   → Every action logged with source
   → SOS source recorded (ML vs Mobile)
   → Event timeline preserved for analysis
   → Post-trip reports include all transitions


════════════════════════════════════════════════════════════════════════════════════════
WHY THIS ARCHITECTURE WORKS
════════════════════════════════════════════════════════════════════════════════════════

✓ CLEAR SEPARATION OF CONCERNS
  • Each layer has ONE responsibility
  • No layer duplicates another's function
  • Dependencies flow top-down only

✓ DEFENSIBLE ML ≠ AI BOUNDARY
  • ML is for perception (pattern detection)
  • AI is for reasoning (decision-making)
  • Easy to explain in viva: "ML detects, AI decides"

✓ REDUNDANCY & SAFETY
  • Dual SOS paths prevent single points of failure
  • ML gesture SOS works even if app fails
  • Mobile app SOS works if camera fails

✓ AUDITABILITY & TRACEABILITY
  • Every action has a source (ML or Mobile)
  • Complete event timeline preserved
  • Viva questions answered by logs

✓ SCALABILITY
  • Backend can add cloud sync later
  • Additional sensors integrate via new APIs
  • Core logic unchanged
  • Dashboard can add new visualizations

✓ TEMPORAL CORRECTNESS
  • Signals are time-windowed (not instantaneous)
  • Duration-based thresholds prevent false positives
  • Risk transitions logged for analysis
```

---

## How to Visualize This Diagram

This architecture can be drawn as a diagram using:

1. **Draw.io** (free web tool): Copy this ASCII art and redraw as boxes + arrows
2. **Lucidchart**: Create layers as horizontal bands, data flows as arrows
3. **Hand-drawn**: Use graph paper, label each layer clearly, draw arrows showing data direction
4. **Figma**: Create component library for layers, connect with dataflow arrows

**Key visual rules**:
- Layer E at top (dashboard)
- Layer D in middle (backend)
- Layer C below (AI engine)
- Layer B below (ML monitoring)
- Layer A at bottom (mobile)
- Arrows flow UP (to backend) and DOWN (to dashboard)
- Two arrows for SOS paths (one from ML, one from Mobile) both pointing to backend
- Make the ML → AI → Backend → Dashboard pipeline visually clear

