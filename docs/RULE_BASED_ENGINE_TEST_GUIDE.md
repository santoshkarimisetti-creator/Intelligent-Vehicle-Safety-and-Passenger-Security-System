# Rule-Based Risk Engine Test Guide

## Overview
This guide explains how to test the **Rule-Based Risk Engine** which tracks temporal patterns of driver fatigue and distraction across a trip.

---

## Architecture

### Per-Trip State Tracking
The AI Engine maintains a `trip_event_counters` dictionary that persists across multiple frame analyses:

```python
trip_event_counters = {
    "trip_123": {
        "drowsiness_events": 2,
        "yawning_events": 1,
        "looking_away_events": 4,
        "overspeed_count": 3,
        "total_frames_analyzed": 25
    }
}
```

**Counter Definitions:**
- **drowsiness_events**: Frames where EAR < 0.25 (eyes closing over 25% of normal)
- **yawning_events**: Frames where MAR > 0.6 (mouth open > 60% of normal)
- **looking_away_events**: Frames where head yaw > 25° (turning away from road)
- **overspeed_count**: Frames where speed > speed_limit (default 80 km/h)
- **total_frames_analyzed**: Total frames processed for this trip

### Risk Escalation Rules

The AI Engine applies **4 temporal escalation rules** after computing the base single-frame risk score:

| Rule | Condition | Escalation | Risk Category |
|------|-----------|-----------|---|
| **Rule 1** | drowsiness_events ≥ 3 | +20 points | Fatigue Pattern |
| | drowsiness_events ≥ 2 | +10 points | Early Warning |
| **Rule 2** | yawning_events ≥ 4 | +15 points | Fatigue Pattern |
| | yawning_events ≥ 2 | +5 points | Early Warning |
| **Rule 3** | looking_away_events ≥ 5 | +25 points | Distraction Pattern |
| | looking_away_events ≥ 3 | +15 points | Moderate Distraction |
| **Rule 4** | (drowsiness OR yawning) + overspeed | +20 points | Critical Combo |

---

## API Endpoints for Testing

### 1. **Analyze Frame** (Main Detection)
```http
POST http://localhost:5001/analyze_frame
Content-Type: application/json

{
  "trip_id": "trip_123",
  "frame": "base64_encoded_image_data",
  "speed": 85,
  "gps": {"latitude": 40.7128, "longitude": -74.0060}
}
```

**Response includes:**
```json
{
  "trip_id": "trip_123",
  "detections": {
    "drowsiness": false,
    "yawning": false,
    "distraction": true
  },
  "risk_score": 42.5,
  "risk_level": "MEDIUM",
  "event_counters": {
    "drowsiness_events": 2,
    "yawning_events": 0,
    "looking_away_events": 4,
    "overspeed_count": 0,
    "total_frames_analyzed": 5
  },
  "reasons": ["DISTRACTION_PATTERN"] // If escalation rules triggered
}
```

### 2. **Get Trip Counters**
```http
GET http://localhost:5001/trips/trip_123/counters
```

**Response:**
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

### 3. **Reset Trip Counters** (Testing cleanup)
```http
POST http://localhost:5001/trips/trip_123/counters/reset
```

**Response:**
```json
{
  "trip_id": "trip_123",
  "message": "Event counters reset",
  "timestamp": "2024-01-15T14:32:50.456789+00:00"
}
```

### 4. **Complete Trip** (End of trip)
```http
POST http://localhost:5001/trips/trip_123/complete
```

**Response:**
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

## Test Scenarios

### Scenario 1: Drowsiness Escalation
**Objective:** Verify that repeated drowsiness events trigger Rule 1 escalation

**Setup:**
```bash
POST /trips/test_001/counters/reset
```

**Test Steps:**
1. Send 3 frames with drowsiness detected:
   ```
   POST /analyze_frame
   {
     "trip_id": "test_001",
     "drowsiness": true,
     "yawning": false,
     "distraction": false
   }
   ```
   
2. After 1st drowsiness frame:
   - Expected: drowsiness_events=1, risk_score ≈ 35-40
   
3. After 2nd drowsiness frame:
   - Expected: drowsiness_events=2, risk_score ≈ 40-45
   - **+10 from Rule 1** (≥2 drowsiness)
   
4. After 3rd drowsiness frame:
   - Expected: drowsiness_events=3, risk_score ≈ 50-55
   - **+20 from Rule 1** (≥3 drowsiness)
   
5. **Verification:**
   ```
   GET /trips/test_001/counters
   {
     "drowsiness_events": 3,
     "yawning_events": 0,
     "looking_away_events": 0,
     "overspeed_count": 0
   }
   ```

---

### Scenario 2: Yawning Pattern Detection
**Objective:** Verify that 4+ yawning events trigger Rule 2 escalation

**Setup:**
```bash
POST /trips/test_002/counters/reset
```

**Test Sequence:**
- Frame 1: yawning detected → yawning_events=1, risk ≈ 30
- Frame 2: yawning detected → yawning_events=2, risk ≈ 35 (+5 from Rule 2)
- Frame 3: yawning detected → yawning_events=3, risk ≈ 40
- Frame 4: yawning detected → yawning_events=4, risk ≈ 55 (+15 from Rule 2)

**Expected Final State:**
```json
{
  "yawning_events": 4,
  "risk_level": "HIGH"
}
```

---

### Scenario 3: Distraction Pattern (Looking Away)
**Objective:** Verify that 5+ looking_away events trigger Rule 3 escalation

**Setup:**
```bash
POST /trips/test_003/counters/reset
```

**Test Sequence:**
- Frames 1-2: distraction → looking_away_events=2, escalation +15 (Rule 3)
- Frames 3-5: distraction → looking_away_events=5, escalation +25 (Rule 3)

**Expected Final:** risk_level should escalate to CRITICAL

---

### Scenario 4: Critical Combo (Drowsiness + Overspeed)
**Objective:** Verify Rule 4 escalation when fatigue + speed violation combine

**Setup:**
```bash
POST /trips/test_004/counters/reset
```

**Test Steps:**
1. Analyze frame: drowsiness=true, speed=75 (normal)
   - drowsiness_events=1, overspeed_count=0

2. Analyze frame: drowsiness=true, speed=85 (exceeds 80 km/h limit)
   - drowsiness_events=2, overspeed_count=1
   - **+20 from Rule 4** (fatigue + overspeed combo)

3. Check final risk_score:
   - Should be significantly higher than single-frame score

---

### Scenario 5: State Persistence Across Multiple Calls
**Objective:** Verify that event counters persist across multiple API calls

**Execution:**
1. Call 1: `POST /analyze_frame` with drowsiness → drowsiness_events=1
2. Call 2: `POST /analyze_frame` with yawning → drowsiness_events=1, yawning_events=1
3. Call 3: `GET /trips/{id}/counters` → Should return BOTH counters

**Expected:** All counters accumulate, not reset between calls

---

## Manual Testing with cURL

### Test Drowsiness Pattern
```bash
# Reset counters
curl -X POST http://localhost:5001/trips/test_001/counters/reset

# Send 3 drowsiness detections
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

# Check final counters
curl -X GET http://localhost:5001/trips/test_001/counters
```

### Test Combo Risk
```bash
# Reset
curl -X POST http://localhost:5001/trips/combo_test/counters/reset

# Frame 1: Drowsiness only
curl -X POST http://localhost:5001/analyze_frame \
  -H "Content-Type: application/json" \
  -d '{
    "trip_id": "combo_test",
    "drowsiness": true,
    "yawning": false,
    "distraction": false,
    "speed": 75
  }'

# Frame 2: Drowsiness + Overspeed
curl -X POST http://localhost:5001/analyze_frame \
  -H "Content-Type: application/json" \
  -d '{
    "trip_id": "combo_test",
    "drowsiness": true,
    "yawning": false,
    "distraction": false,
    "speed": 90
  }'

# Check counters and note risk_score increase
curl -X GET http://localhost:5001/trips/combo_test/counters
```

---

## Expected Behavior Summary

| Pattern | After Threshold | Risk Increase | Flags |
|---------|-----------------|---------------|----|
| **3+ Drowsiness** | 3rd event | +20 pts | FATIGUE_PATTERN, HIGH |
| **4+ Yawning** | 4th event | +15 pts | FATIGUE_PATTERN, HIGH |
| **5+ Distraction** | 5th event | +25 pts | DISTRACTION_PATTERN, CRITICAL |
| **Drowsiness + Overspeed** | Both active | +20 pts | CRITICAL_COMBO, CRITICAL |
| **Multiple Patterns** | 2+ rules | Cumulative | Risk compounds |

---

## Validation Checklist

- [ ] Event counters initialize correctly (`/trips/{id}/counters`)
- [ ] Counters persist across multiple `/analyze_frame` calls
- [ ] Rule 1 (+10 at ≥2, +20 at ≥3) triggers correctly
- [ ] Rule 2 (+5 at ≥2, +15 at ≥4) triggers correctly
- [ ] Rule 3 (+15 at ≥3, +25 at ≥5) triggers correctly
- [ ] Rule 4 (+20 when fatigue + overspeed) triggers correctly
- [ ] Risk score increases beyond single-frame baseline
- [ ] Risk level escalates appropriately (LOW → MEDIUM → HIGH → CRITICAL)
- [ ] `/trips/{id}/counters/reset` clears state
- [ ] `/trips/{id}/complete` archives final counters

---

## Notes for Developers

1. **State Isolation:** Each trip_id has independent event counters. Don't reuse trip_ids across test runs without resetting.

2. **Frame Rate Consideration:** In production, ~30 fps means 3600 frames/hour. Thresholds (3, 4, 5 events) should occur within ~5-10 seconds of observed behavior.

3. **Speed Limit:** Currently hardcoded to 80 km/h. Modify `_increment_overspeed()` if testing different limits.

4. **Escalation Stacking:** If both Rule 2 AND Rule 3 trigger, escalations stack:
   ```
   base_score = 45
   + Rule 2 (+15) = 60
   + Rule 3 (+25) = 85
   Result: CRITICAL risk
   ```

5. **Future Enhancements:**
   - Per-trip configurable thresholds
   - Graduated escalation decay (events older than 5min count less)
   - Per-region speed limits from GPS data

---

## Debugging

If counters don't increment as expected:

1. **Check trip_id consistency:** Ensure same trip_id used in all calls
2. **Verify detection flags:** Check `detections` in `/analyze_frame` response
3. **Review event_counters field:** Response payload includes current counters after increment
4. **See backend logs:** MongoDB stores all AI results with event timestamps

Example debug flow:
```bash
# Check if detection was recognized
curl -X POST http://localhost:5001/analyze_frame ... | jq '.detections'

# Inspect returned counters
curl -X POST http://localhost:5001/analyze_frame ... | jq '.event_counters'

# Compare with fresh GET
curl -X GET http://localhost:5001/trips/{trip_id}/counters | jq '.event_counters'
```

---

## Next Steps After Validation

1. ✅ Test all 4 escalation rules with sample payloads
2. ⏳ Frontend integration: Send real webcam frames to `/analyze_frame`
3. ⏳ Configure MongoDB backend to receive cumulative AI results
4. ⏳ Dashboard visualization of risk trends over trip duration
