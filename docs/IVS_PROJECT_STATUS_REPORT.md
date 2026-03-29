# Intelligent Vehicle Safety and Passenger Security System (IVS)
## Presentation Report: What We Have Done

## 1. Project Modules Completed

- AI Engine module for driver monitoring and event generation.
- Backend API module for trip, events, SOS, and report services.
- Frontend dashboard module for live monitoring and trip/event views.
- Android passenger app integration module.
- MongoDB data storage integration for trips, events, and calibration.

## 2. Features Implemented

- Trip lifecycle APIs:
  - Create trip
  - Update trip telemetry/path
  - End trip
  - Fetch trip list and trip detail

- Event and SOS handling:
  - AI detection event ingestion
  - SOS event ingestion (mobile/AI sources)
  - Consolidated event timeline for each trip
  - Newest-first event ordering in APIs/UI

- Driver monitoring pipeline:
  - Face landmark-based metric extraction (EAR, MAR, yaw, pitch, roll)
  - Temporal behavior detection for drowsiness, yawning, distraction
  - Driver-specific adaptive baseline logic
  - Risk scoring with weighted and temporal levels
  - Fatigue score and fatigue level output

- Live monitoring UI:
  - Real-time detection and risk display
  - Driver status visualization (ALERT, DROWSY, DISTRACTED)
  - Audio alert/beep integration with cooldown behavior

- Reporting and exports:
  - Trip JSON download
  - Trip CSV download
  - Route map image download
  - PDF trip report generation with map and event summary

## 3. Thresholds and Rules Used

### Behavior Engine Thresholds

- EAR drowsiness threshold (default): `0.20`
- MAR yawning threshold (default): `0.08`
- Head turn yaw threshold (default): `20`
- Head pitch threshold (default): `18`
- Head roll threshold (default): `17`

### Time-Based Detection Rules

- Drowsiness minimum duration: `0.45 s`
- Yawning minimum duration: `0.25 s`
- Distraction base duration: `0.45 s`
- Distraction minimum required duration: `5.0 s`
- Blink ignore duration: `0.5 s`

### Cooldown Rules

- Drowsiness cooldown: `0.0 s`
- Yawning cooldown: `1.0 s`
- Distraction cooldown: `0.5 s`

### Adaptive Baseline Parameters

- EAR dynamic range clamp: `0.14` to `0.33`
- MAR dynamic range clamp: `0.05` to `0.20`
- Head dynamic range clamp: `10` to `50`
- EMA alpha for baseline update: `0.12`

### Risk Engine Levels

- Temporal risk level:
  - LOW: `<35`
  - MEDIUM: `35–59`
  - HIGH: `60–79`
  - CRITICAL: `>=80`

- Weighted risk level:
  - SAFE: `<21`
  - MODERATE: `21–50`
  - HIGH: `51–75`
  - CRITICAL: `>=76`

- Fatigue level:
  - LOW: `<25`
  - MODERATE: `25–49`
  - HIGH: `50–74`
  - SEVERE: `>=75`

### Risk Weights

- Overspeed: `0.25`
- Drowsiness: `0.30`
- Distraction: `0.35`
- Yawning: `0.10`

## 4. Techniques Used

- Rule-based temporal detection.
- Per-driver adaptive thresholding.
- Median smoothing and EMA tracking.
- Confidence-based event scoring.
- Hysteresis logic for stable state transitions.
- Event counter-based risk escalation.
- Composite weighted risk fusion.
- Consolidated event timeline modeling.
- Map tile rendering with route overlay for report visuals.

## 5. Technologies Used

### Frontend

- React
- React Router
- Vite
- Leaflet / React-Leaflet

### Backend

- Flask
- Flask-CORS
- PyMongo
- ReportLab
- Pillow
- Zeroconf

### AI Engine

- OpenCV
- NumPy
- MediaPipe
- DeepFace
- Flask
- PyMongo

### Database

- MongoDB

## 6. Main Files in Implementation

- `ai_engine/behavior_engine.py`
- `ai_engine/risk_engine.py`
- `ai_engine/landmark_engine.py`
- `ai_engine/final_decision_engine.py`
- `backend/app.py`
- `backend/calibration_model.py`
- `frontend/src/pages/LiveMonitoring.jsx`
- `frontend/src/pages/TripDetail.jsx`
- `frontend/src/pages/EventsPage.jsx`
- `frontend/src/pages/EmergencyEventsPage.jsx`

## 7. One-Line Presentation Summary

IVS implements real-time driver behavior detection, risk intelligence, SOS/event management, live dashboard monitoring, and trip report exports with map-based evidence.