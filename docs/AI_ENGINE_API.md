# AI Engine API Reference

## Service Overview
- **Port:** 5001 (localhost)
- **Base URL:** `http://localhost:5001`
- **Health:** `GET /health`

---

## Endpoints

### 1. Health Check
```http
GET /health
```

**Response (200 OK):**
```json
{
  "status": "ok",
  "service": "ai_engine",
  "detector": "opencv+haar_cascades"
}
```

---

### 2. Analyze Frame
The main endpoint for submitting a frame and receiving AI detections + risk computation.

```http
POST /analyze_frame
Content-Type: application/json
```

**Request Body:**
```json
{
  "trip_id": "trip_123",
  
  // Frame Data (one of: frame, video_frame, or detection_flags)
  "frame": "base64_encoded_image_string",  // Optional: raw frame image
  
  // Explicit Detection Signals (useful for non-image inputs)
  "drowsiness": true,      // Optional: Set to true if drowsiness detected
  "yawning": false,        // Optional: Set to true if yawning detected
  "distraction": false,    // Optional: Set to true if head turn detected
  
  // Vehicle Metrics
  "speed": 85,             // Optional: Current vehicle speed (km/h)
  "speed_limit": 80,       // Optional: Road speed limit (default: 80)
  
  // GPS (Optional)
  "gps": {
    "latitude": 40.7128,
    "longitude": -74.0060,
    "accuracy": 10
  },
  
  // Metadata (Optional)
  "frame_id": 0,
  "video_id": "video_001",
  "input_type": "frame",   // "frame", "signal", or "combined"
  "timestamp": "2024-01-15T14:32:45.123456+00:00"
}
```

**Response (200 OK):**
```json
{
  "trip_id": "trip_123",
  "detections": {
    "drowsiness": true,
    "yawning": false,
    "distraction": false
  },
  "risk_score": 53.8,
  "risk_level": "MEDIUM",
  "reasons": [
    "DROWSINESS_DETECTED",
    "DROWSINESS_PATTERN"  // If Rule 1 triggered
  ],
  "event_counters": {
    "drowsiness_events": 3,
    "yawning_events": 0,
    "looking_away_events": 0,
    "overspeed_count": 0,
    "total_frames_analyzed": 5
  },
  "sos_triggered": false,
  "sos_gesture": {
    "sos_triggered": false,
    "duration": 0.0,
    "hands_detected": 0
  },
  "cv_metrics": {
    "face_detected": true,
    "eyes_visible": true,
    "ear": 0.18,
    "mar": 0.35,
    "yaw_angle": 15.2,
    "processing_time_ms": 45.3
  },
  "backend_callback": {
    "sent": true,
    "message": "Result posted to backend"
  }
}
```

**Risk Levels:**
- **LOW:** score 0-29
- **MEDIUM:** score 30-59
- **HIGH:** score 60-79
- **CRITICAL:** score 80+

---

### 3. Compute Risk (Standalone)
Get risk computation for current detections without storing state.

```http
POST /compute_risk
Content-Type: application/json
```

**Request Body:**
```json
{
  "drowsiness": true,
  "yawning": false,
  "distraction": false,
  "speed": 75,
  "speed_limit": 80
}
```

**Response (200 OK):**
```json
{
  "risk_score": 35.2,
  "risk_level": "LOW",
  "reasons": [
    "DROWSINESS_DETECTED"
  ],
  "breakdown": {
    "base_score": 35,
    "drowsiness_component": 35,
    "yawning_component": 0,
    "distraction_component": 0,
    "speed_component": 0
  }
}
```

---

### 4. Get Trip Counters
Retrieve current event counters for a specific trip.

```http
GET /trips/{trip_id}/counters
```

**Path Parameters:**
- `trip_id` (string): Unique trip identifier

**Response (200 OK):**
```json
{
  "trip_id": "trip_123",
  "event_counters": {
    "drowsiness_events": 3,
    "yawning_events": 1,
    "looking_away_events": 4,
    "overspeed_count": 2,
    "total_frames_analyzed": 10
  },
  "timestamp": "2024-01-15T14:32:45.123456+00:00"
}
```

**Response (200 OK - Not Found):**
If trip_id has never been seen, returns initialized (zero) counters.

---

### 5. Reset Trip Counters
Clear event counters for a trip (useful for testing or trip restart).

```http
POST /trips/{trip_id}/counters/reset
```

**Path Parameters:**
- `trip_id` (string): Unique trip identifier

**Response (200 OK):**
```json
{
  "trip_id": "trip_123",
  "message": "Event counters reset",
  "timestamp": "2024-01-15T14:32:50.456789+00:00"
}
```

---

### 6. Complete Trip
Mark trip as complete, retrieve final counters, and clear state.

```http
POST /trips/{trip_id}/complete
```

**Path Parameters:**
- `trip_id` (string): Unique trip identifier

**Response (200 OK):**
```json
{
  "trip_id": "trip_123",
  "final_event_counters": {
    "drowsiness_events": 5,
    "yawning_events": 2,
    "looking_away_events": 8,
    "overspeed_count": 3,
    "total_frames_analyzed": 42
  },
  "trip_duration_frames": 42,
  "completion_timestamp": "2024-01-15T14:40:15.789123+00:00"
}
```

---

## Risk Scoring Logic

### Base Score Calculation
```
base_score = 0

If drowsiness:
  base_score += 35

If yawning:
  base_score += 30

If distraction:
  base_score += 25

If speed_overage:
  overage_pct = (current_speed - speed_limit) / speed_limit
  speed_risk = min(20, overage_pct * 100)
  base_score += speed_risk
```

### Temporal Escalation Rules

Applied AFTER base_score computation:

**Rule 1: Drowsiness Pattern**
```
IF drowsiness_events >= 3:
  base_score += 20
ELSE IF drowsiness_events >= 2:
  base_score += 10
```

**Rule 2: Yawning Pattern**
```
IF yawning_events >= 4:
  base_score += 15
ELSE IF yawning_events >= 2:
  base_score += 5
```

**Rule 3: Distraction Pattern**
```
IF looking_away_events >= 5:
  base_score += 25
ELSE IF looking_away_events >= 3:
  base_score += 15
```

**Rule 4: Critical Combo**
```
IF (drowsiness_events > 0 OR yawning_events > 0) AND overspeed_count > 0:
  base_score += 20
```

### Final Score Capping
```
final_score = min(100, base_score)
```

---

## Detection Flags

### Drowsiness
- **Detection:** Eye Aspect Ratio (EAR) < 0.25
- **Meaning:** Eyes closing to ≤25% of normal openness
- **Escalation:** Pattern Rule 1 (≥3 events = +20 risk pts)

### Yawning
- **Detection:** Mouth Aspect Ratio (MAR) > 0.6
- **Meaning:** Mouth opening > 60% of normal
- **Escalation:** Pattern Rule 2 (≥4 events = +15 risk pts)

### Distraction (Looking Away)
- **Detection:** Head yaw angle > 25°
- **Meaning:** Head turned away from road center for >1.8 seconds (typical 30fps)
- **Escalation:** Pattern Rule 3 (≥5 events = +25 risk pts)

### Overspeed
- **Detection:** Current speed > speed_limit (default 80 km/h)
- **Meaning:** Vehicle exceeding posted/default speed limit
- **Escalation:** Pattern Rule 4 (fatigue + overspeed = +20 risk pts)

### SOS Gesture
- **Detection:** Both hands open with palms forward for ≥2.0 seconds
- **Meaning:** Driver actively requesting assistance
- **Action:** Immediate `sos_triggered=true` and API callback to backend
- **Backend Effect:** Stores in `sos_events` array, sets `sos_triggered=true` flag

---

## Event Counters

Maintained per-trip, incremented with each frame analysis:

| Counter | Condition | Purpose |
|---------|-----------|---------|
| **drowsiness_events** | EAR < 0.25 | Detect fatigue patterns |
| **yawning_events** | MAR > 0.6 | Detect extreme fatigue |
| **looking_away_events** | Yaw > 25° | Detect sustained distraction |
| **overspeed_count** | Speed > limit | Track dangerous speeding |
| **total_frames_analyzed** | Each frame | Track trip duration |

---

## Integration Examples

### Example 1: Signal-Based Input (No Image)
```bash
curl -X POST http://localhost:5001/analyze_frame \
  -H "Content-Type: application/json" \
  -d '{
    "trip_id": "trip_001",
    "drowsiness": true,
    "yawning": false,
    "distraction": false,
    "speed": 85,
    "input_type": "signal"
  }'
```

### Example 2: Image-Based Input (OpenCV Processing)
```bash
# Create base64 encoded image
IMAGE_B64=$(base64 -w0 /path/to/image.jpg)

curl -X POST http://localhost:5001/analyze_frame \
  -H "Content-Type: application/json" \
  -d "{
    \"trip_id\": \"trip_001\",
    \"frame\": \"$IMAGE_B64\",
    \"speed\": 75,
    \"input_type\": \"frame\"
  }"
```

### Example 3: Combined Multi-Pattern Detection
```bash
# Send multiple detections in one frame
curl -X POST http://localhost:5001/analyze_frame \
  -H "Content-Type: application/json" \
  -d '{
    "trip_id": "trip_001",
    "drowsiness": true,
    "yawning": true,
    "distraction": true,
    "speed": 95,
    "speed_limit": 80,
    "input_type": "combined"
  }'

# Expected response:
# - base_score = 35 + 30 + 25 + risk_from_speed
# - Rule 1: drowsiness (need ≥2 more) = not yet
# - Rule 4: fatigue + overspeed = +20
# - final_score should be HIGH-CRITICAL range
```

---

## Error Responses

### 400 Bad Request
```json
{
  "error": "Missing required field: trip_id",
  "status": 400
}
```

### 500 Internal Server Error
```json
{
  "error": "Failed to process frame",
  "details": "OpenCV detection failed",
  "status": 500
}
```

---

## Performance Notes

- **Frame Processing:** ~40-50ms per frame (Intel i7, OpenCV Haar Cascades)
- **Throughput:** ~20-25 fps with Python Flask
- **State Overhead:** <1KB per trip (counters dict)
- **Memory:** ~50MB baseline + ~10MB per trip analysis session

---

## Architecture Notes

1. **Stateful Design:** Event counters persist in `trip_event_counters` dict
2. **Pattern Recognition:** Temporal escalation rules detect sustained issues vs momentary glitches
3. **Backend Integration:** Async HTTP POST to `http://localhost:5000/trips/{trip_id}/ai-results`
4. **Graceful Degradation:** Falls back to signal-based detection if image processing fails

---

## Future Enhancement Hooks

- **[TODO]** Per-trip configurable risk thresholds (e.g., escalation at 2 instead of 3 drowsiness)
- **[TODO]** Time-decay for older events (5-min sliding window)
- **[TODO]** Geo-fenced speed limits from GPS coordinates
- **[TODO]** Multi-person detection in vehicle
- **[TODO]** Real-time WebSocket streaming for dashboard

---

## See Also
- [Rule-Based Engine Test Guide](./RULE_BASED_ENGINE_TEST_GUIDE.md)
- [Architecture Overview](./architecture_explanation.md)
