# AI Safety Engine - Quick Reference

## 🎯 What it Does
Monitors driver for fatigue, distraction, and dangerous speeding. Tracks patterns over trip duration to detect sustained issues.

---

## 🚀 Quick Start

### Start Services
```bash
# Terminal 1: AI Engine (port 5001)
cd d:\Projects\IVS\ai_engine
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py

# Terminal 2: Backend (port 5000)
cd d:\Projects\IVS\backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

### Test
```bash
cd d:\Projects\IVS\ai_engine
python test_rule_engine.py
```

---

## 📡 API Cheat Sheet

### Health Check
```bash
curl http://localhost:5001/health
```

### Analyze Frame
```bash
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
```

### Get Counters
```bash
curl http://localhost:5001/trips/trip_001/counters
```

### Reset Trip
```bash
curl -X POST http://localhost:5001/trips/trip_001/counters/reset
```

### Complete Trip
```bash
curl -X POST http://localhost:5001/trips/trip_001/complete
```

---

## 📊 Risk Scoring

| Detection | Base Score | Escalation Rule |
|-----------|-----------|-----------------|
| Drowsiness (EAR < 0.25) | +35 | Rule 1: ≥3 events → +20 |
| Yawning (MAR > 0.6) | +30 | Rule 2: ≥4 events → +15 |
| Distraction (Yaw > 25°) | +25 | Rule 3: ≥5 events → +25 |
| Overspeed (> limit) | +20 | Rule 4: + fatigue → +20 |

**Risk Levels:**
- 0-29: **LOW** ✅
- 30-59: **MEDIUM** ⚠️
- 60-79: **HIGH** 🔴
- 80-100: **CRITICAL** 🚨

---

## 🧮 Per-Trip Event Counters

```json
{
  "drowsiness_events": 0,      // Frames with EAR < 0.25
  "yawning_events": 0,          // Frames with MAR > 0.6
  "looking_away_events": 0,     // Frames with yaw > 25°
  "overspeed_count": 0,         // Frames exceeding speed limit
  "total_frames_analyzed": 0    // Total frames processed
}
```

---

## 🎬 Example: Detect Drowsiness Pattern

**Frame 1:** drowsiness detected
```
drowsiness_events = 1
risk_score = 35 (no escalation yet)
```

**Frame 2:** drowsiness detected again
```
drowsiness_events = 2
risk_score = 35 + 10 (Rule 1 at ≥2) = 45 ⚠️
```

**Frame 3:** drowsiness detected again
```
drowsiness_events = 3
risk_score = 35 + 20 (Rule 1 at ≥3) = 55 ⚠️ MEDIUM
```

---

## 🔍 Detection Methods

| Type | Method | Hardware |
|------|--------|----------|
| Drowsiness | OpenCV Haar Cascades (EAR) | CPU ✓ |
| Yawning | OpenCV Haar Cascades (MAR) | CPU ✓ |
| Distraction | OpenCV Head Pose (yaw angle) | CPU ✓ |
| Overspeed | GPS/vehicle data | External |
| SOS Gesture | MediaPipe Hands (optional) | CPU |

---

## 📁 Key Files

| Path | Purpose |
|------|---------|
| `ai_engine/app.py` | Main AI service |
| `ai_engine/test_rule_engine.py` | Test harness |
| `backend/app.py` | Storage & trip management |
| `docs/AI_ENGINE_API.md` | Full API reference |
| `docs/RULE_BASED_ENGINE_TEST_GUIDE.md` | Testing guide |

---

## ⚙️ Configuration

### Speed Limit
Edit `ai_engine/app.py` line ~665:
```python
def _increment_overspeed(trip_id: str, speed: float, speed_limit: float = 80):
    # speed_limit defaults to 80 km/h
```

### Detection Thresholds
Edit `ai_engine/app.py` _process_frame_with_opencv():
```python
EAR_THRESHOLD = 0.25        # Drowsiness
MAR_THRESHOLD = 0.6         # Yawning
YAW_THRESHOLD = 25          # Distraction (degrees)
```

### Escalation Rules
Edit _compute_risk():
```python
# Rule 1: Drowsiness
if event_counters["drowsiness_events"] >= 3:
    risk_score += 20  # Change to tune
elif event_counters["drowsiness_events"] >= 2:
    risk_score += 10
```

---

## 🧪 Testing Workflow

### 1. Check Health
```bash
curl http://localhost:5001/health
```

### 2. Reset Trip
```bash
curl -X POST http://localhost:5001/trips/test_001/counters/reset
```

### 3. Send Test Signals
```bash
# Send drowsiness 3 times
for i in {1..3}; do
  curl -X POST http://localhost:5001/analyze_frame \
    -H "Content-Type: application/json" \
    -d '{
      "trip_id": "test_001",
      "drowsiness": true,
      "yawning": false,
      "distraction": false
    }'
  sleep 0.5
done
```

### 4. Verify Escalation
```bash
curl http://localhost:5001/trips/test_001/counters
# Should show drowsiness_events: 3
# Risk score should include Rule 1 bonus
```

### 5. Run Full Test Suite
```bash
cd ai_engine
python test_rule_engine.py
```

---

## 🐛 Debugging

**Q: Counters not incrementing?**
- Check trip_id is consistent
- Verify drowsiness/yawning/distraction flags in request
- Check /trips/{id}/counters endpoint shows counters

**Q: Risk score not escalating?**
- Verify counter thresholds matched (2, 3, 4, 5)
- Review _compute_risk() logic
- Check "reasons" field in response for rule names

**Q: Services won't start?**
- Ensure ports 5000, 5001 not in use
- Check Python venv activated
- Verify requirements.txt installed

---

## 📈 Response Example

```json
{
  "trip_id": "trip_001",
  "detections": {
    "drowsiness": true,
    "yawning": false,
    "distraction": false
  },
  "risk_score": 55,
  "risk_level": "MEDIUM",
  "reasons": [
    "DROWSINESS_DETECTED",
    "DROWSINESS_PATTERN"
  ],
  "event_counters": {
    "drowsiness_events": 3,
    "yawning_events": 0,
    "looking_away_events": 0,
    "overspeed_count": 0,
    "total_frames_analyzed": 3
  },
  "cv_metrics": {
    "face_detected": true,
    "eyes_visible": true,
    "ear": 0.18,
    "mar": 0.35,
    "yaw_angle": 5.2
  }
}
```

---

## 🎓 Key Concepts

**Single-Frame Risk:** Computed from immediate detections (drowsiness, yawning, distraction, overspeed)

**Temporal Risk:** Added on top via escalation rules when patterns of repeated events detected

**Per-Trip State:** Event counters persist across multiple frames within same trip_id

**Pattern Detection:** Repeated issues (3+ drowsiness, 5+ distraction) indicate sustained dangerous behavior

**Escalation:** Rules add 10-25 risk points when patterns trigger, compounding risk assessment

---

## 📞 Contact/Support

For issues with:
- **AI Detection:** Check cv_metrics in response, validate Haar Cascade files
- **Risk Scoring:** Review reason[] field, check _compute_risk() logic
- **Backend Storage:** Verify backend service running, check database
- **Frontend:** See TripDetail.jsx component integration

---

## 🚀 Next Steps

1. ✅ **Task 6 Done:** Rule-based temporal engine complete
2. ⏳ **Task 7:** Frontend webcam integration
3. ⏳ **Task 8:** MediaPipe Hands setup
4. ⏳ **Task 9:** Threshold tuning with real data
5. ⏳ **Task 10:** Full documentation & deployment

---

**Version:** 1.0 (Task 6 Complete)  
**Last Updated:** 2024-01-15  
**Status:** Ready for Frontend Integration
