# AI Engine - Rule-Based Driver Safety Detection System

**Status:** ✅ Task 6 Complete - Rule-Based Temporal Engine Implemented

## Overview

The AI Engine is an independent Flask microservice (port 5001) that analyzes driver behavior to detect fatigue, distraction, and dangerous driving patterns. 

**Key Innovation:** Tracks event patterns **across a trip** using per-trip state counters. Repeated issues trigger escalation rules that compound risk scores, distinguishing momentary glitches from sustained dangerous behavior.

**Example:** Driver yawns once = 30 pts (MEDIUM). Driver yawns 4+ times = 30 + 15 = 45 pts (increasing concern based on pattern).

## 🚀 Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Start service
python app.py
# Runs on http://localhost:5001

# Health check in another terminal
curl http://localhost:5001/health

# Run tests
python test_rule_engine.py  # Automated test harness (5 scenarios)
# OR
powershell -File test_scenarios.ps1 -Scenario scenario_1  # Individual tests
```

## ✨ Features

### Detection Methods
- **Drowsiness:** OpenCV Haar Cascades → Eye Aspect Ratio (EAR < 0.25)
- **Yawning:** OpenCV Haar Cascades → Mouth Aspect Ratio (MAR > 0.6)
- **Distraction:** Face position analysis → Head yaw angle (> 25°)
- **Overspeed:** GPS/vehicle data comparison (> speed_limit)
- **SOS Gesture:** MediaPipe Hands → Open palm held ≥ 2 seconds (optional)

### Temporal Pattern Recognition (Task 6)
- **Per-Trip State:** Counters accumulate throughout trip
- **Rule 1:** Drowsiness pattern (≥2 events → +10, ≥3 → +20 risk pts)
- **Rule 2:** Yawning pattern (≥2 events → +5, ≥4 → +15 risk pts)
- **Rule 3:** Distraction pattern (≥3 events → +15, ≥5 → +25 risk pts)
- **Rule 4:** Critical combo (fatigue + overspeed → +20 risk pts)

### Risk Management
- **Single-frame scoring:** Immediate risk detection
- **Escalation rules:** Pattern-based risk escalation
- **Risk levels:** LOW (0-29), MEDIUM (30-59), HIGH (60-79), CRITICAL (80-100)

## 📍 Core Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Service health status |
| `/analyze_frame` | POST | Main detection endpoint (frame or signals) |
| `/compute_risk` | POST | Standalone risk computation |
| `/trips/{id}/counters` | GET | Retrieve current event counters |
| `/trips/{id}/counters/reset` | POST | Clear counters for testing |
| `/trips/{id}/complete` | POST | Finalize trip, return summary |

## 📊 Example Usage

```bash
# Analyze a frame with drowsiness detected
curl -X POST http://localhost:5001/analyze_frame \
  -H "Content-Type: application/json" \
  -d '{
    "trip_id": "trip_001",
    "drowsiness": true,
    "yawning": false,
    "distraction": false,
    "speed": 85,
    "speed_limit": 80
  }'

# Response includes:
# {
#   "risk_score": 55,
#   "risk_level": "MEDIUM",
#   "reasons": ["DROWSINESS_DETECTED", "DROWSINESS_PATTERN"],
#   "event_counters": {
#     "drowsiness_events": 3,
#     "yawning_events": 0,
#     "looking_away_events": 0,
#     "overspeed_count": 0,
#     "total_frames_analyzed": 5
#   }
# }

# Get current counters for a trip
curl http://localhost:5001/trips/trip_001/counters
```

## 🔧 Configuration

### Detection Thresholds
Edit `app.py` around lines 500-520:
```python
EAR_THRESHOLD = 0.25      # Eye closure (lower = more sensitive)
MAR_THRESHOLD = 0.6       # Mouth opening (lower = more sensitive)
YAW_THRESHOLD = 25        # Head turn in degrees (lower = more sensitive)
```

### Speed Limit
Edit `app.py` line ~665:
```python
speed_limit: float = 80   # Default speed limit (km/h)
```

### Backend URL
Edit `app.py` lines 750-760:
```python
BACKEND_URL = "http://localhost:5000"
```

## 🧪 Testing

### Automated Test Suite (All 5 Scenarios)
```bash
python test_rule_engine.py
# Output: Total: 5/5 tests passed ✓
```

### Individual Test Scenarios

**Windows PowerShell:**
```powershell
powershell -File test_scenarios.ps1 -Scenario scenario_1   # Drowsiness escalation
powershell -File test_scenarios.ps1 -Scenario scenario_2   # Yawning escalation
powershell -File test_scenarios.ps1 -Scenario scenario_3   # Distraction escalation
powershell -File test_scenarios.ps1 -Scenario scenario_4   # Critical combo
powershell -File test_scenarios.ps1 -Scenario scenario_5   # State persistence
powershell -File test_scenarios.ps1 -Scenario combo        # Mixed patterns
```

**Linux/Mac Bash:**
```bash
bash test_scenarios.sh scenario_1
bash test_scenarios.sh scenario_4
bash test_scenarios.sh combo
```

## 📈 Risk Scoring Logic

### Base Frame Score
```
score = 0
if drowsiness:    score += 35
if yawning:       score += 30
if distraction:   score += 25
if overspeed:     score += (speed_excess / limit) * 100, capped at 20
```

### Escalation Rules (Temporal)
```
Rule 1: if drowsiness_events >= 3: score += 20
Rule 2: if yawning_events >= 4: score += 15
Rule 3: if looking_away_events >= 5: score += 25
Rule 4: if (drowsiness OR yawning) AND overspeed: score += 20

final_score = min(100, score)
```

### Example: Drowsiness Pattern
```
Frame 1: drowsiness=true
  Base: 35, drowsiness_events: 1 → score: 35 (LOW)

Frame 2: drowsiness=true
  Base: 35, drowsiness_events: 2 (Rule 1 at ≥2: +10) → score: 45 (MEDIUM)

Frame 3: drowsiness=true
  Base: 35, drowsiness_events: 3 (Rule 1 at ≥3: +20) → score: 55 (MEDIUM)
```

## 📁 Project Structure

```
ai_engine/
├── app.py                  # Main service (566+ lines)
├── requirements.txt        # Windows: pip install -r requirements.txt
├── test_rule_engine.py    # Automated test harness (5 scenarios)
├── test_scenarios.ps1     # Individual test scenarios (PowerShell)
├── test_scenarios.sh      # Individual test scenarios (Bash)
└── README.md (this file)
```

## 📚 Documentation

- **[AI_ENGINE_API.md](../docs/AI_ENGINE_API.md)** - Complete API reference with all response formats
- **[RULE_BASED_ENGINE_TEST_GUIDE.md](../docs/RULE_BASED_ENGINE_TEST_GUIDE.md)** - Detailed testing guide with 5 scenarios
- **[QUICK_REFERENCE.md](../docs/QUICK_REFERENCE.md)** - Quick cheat sheet for developers
- **[TASK_6_COMPLETION_SUMMARY.md](../docs/TASK_6_COMPLETION_SUMMARY.md)** - Implementation details and validation
- **[ARCHITECTURE_RULE_BASED_ENGINE.md](../docs/ARCHITECTURE_RULE_BASED_ENGINE.md)** - System architecture with diagrams

## 🔗 Integration

### Backend (Flask on :5000)
- Receives: `POST /trips/{trip_id}/ai-results` with detection results
- Receives: `POST /trips/{trip_id}/sos` with SOS events
- Stores: `ai_events[]` array per trip, updates `risk_score` and `risk_level`

### Frontend (Port 3000 - Ready for Task 7)
- Will capture: Real-time webcam frames
- Will send: Base64 frames to `/analyze_frame`
- Will display: `risk_score`, `risk_level`, `event_counters` in real-time

## ⚙️ Performance

- Frame processing: ~40-50ms (OpenCV + Intel i7)
- Throughput: ~15-25 fps typical
- Memory per trip: <1KB (counters)
- Baseline memory: ~50MB
- API response: <100ms (excluding backend callback)

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| Port 5001 in use | `netstat -ano \| findstr :5001` → kill process |
| "OpenCV not found" | `pip install -r requirements.txt` |
| Counters not incrementing | Verify `trip_id` consistent, check `detections` in response |
| Cascade files missing | Check OpenCV installation: `python -c "import cv2; print(cv2.data.haarcascades)"` |
| Backend not receiving | Verify backend running on :5000: `curl http://localhost:5000/health` |

## 📋 Deployment

- [ ] Python 3.8+ installed
- [ ] Dependencies: `pip install -r requirements.txt`
- [ ] Port 5001 available
- [ ] Backend service running (for callbacks)
- [ ] Test health: `curl http://localhost:5001/health`
- [ ] Run tests: `python test_rule_engine.py`
- [ ] All 5 tests pass ✓
- [ ] Ready for Task 7 (Frontend Integration)

---

**Version:** 1.0 (Task 6 Complete - Rule-Based Engine)  
**Last Updated:** 2024-01-15  
**Next Task:** Task 7 - Frontend Webcam Integration

To enable MediaPipe Hands:
```bash
# Set environment variable with path to hand landmarker model
export MEDIAPIPE_HAND_MODEL_PATH=/path/to/hand_landmarker.task
```

Download model from: https://developers.google.com/mediapipe/solutions/vision/hand_landmarker

## Behavior

- Receives frame/video input (base64 encoded image or pre-computed signals)
- Processes with OpenCV Haar Cascades for face/eye detection
- Estimates EAR, MAR, and head yaw angle from detected features
- Returns detection and risk output
- Sends computed result to backend callback endpoint:
  - `POST {BACKEND_BASE_URL}/trips/<trip_id>/ai-results`

## API Usage

### Analyze Frame (OpenCV + Hand Gesture Mode)

```bash
POST /analyze_frame
Content-Type: application/json

{
  "trip_id": "trip-123",
  "frame_id": "frame-001",
  "image": "data:image/jpeg;base64,/9j/4AAQSkZJRg...",
  "metrics": {
    "speed": 80
  }
}
```

**Response:**
```json
{
  "trip_id": "trip-123",
  "detections": [
    {
      "type": "drowsiness",
      "confidence": 0.85,
      "source": "opencv_haar",
      "metric": "ear",
      "value": 0.18
    }
  ],
  "risk_score": 45.2,
  "risk_level": "MEDIUM",
  "reasons": ["high_eye_closure"],
  "sos_triggered": false,
  "sos_gesture": {
    "sos_detected": false,
    "sos_triggered": false,
    "palm_open": false,
    "duration": 0.0,
    "hands_detected": 0
  },
  "cv_metrics": {
    "ear": 0.18,
    "mar": 0.35,
    "yaw_angle": 5.2,
    "face_detected": true
  },
  "backend_callback": {
    "sent": true,
    "message": "sent"
  }
}
```

### Analyze Frame (Legacy Signal Mode)

```bash
POST /analyze_frame
Content-Type: application/json

{
  "trip_id": "trip-123",
  "signal": {
    "eyes_closed_score": 0.8,
    "head_off_road_score": 0.6,
    "yawning_score": 0.4
  },
  "metrics": {
    "speed": 80
  }
}
```

## Run

```bash
cd ai_engine
pip install -r requirements.txt
python app.py
```

Default port: `5001`

## Environment Variables

- `BACKEND_BASE_URL` (default: `http://localhost:5000`)
- `AI_ENGINE_PORT` (default: `5001`)

## Dependencies

- Flask: Web framework
- OpenCV: Face/eye detection with Haar Cascades
- NumPy: Numerical computations
- MediaPipe: Hand gesture detection (optional, for SOS feature)

**Note**: 
- All OpenCV Haar Cascade models are included with opencv-python package
- MediaPipe Hands requires separate model file download for SOS gesture detection
