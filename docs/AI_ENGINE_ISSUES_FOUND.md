# AI Engine Detection System - Issues Found and Fixes

## Critical Issues Preventing Event Detection

### 1. **MAR Threshold Inconsistency (SEVERITY: HIGH)**
The mouth aspect ratio (MAR) threshold is defined differently across the codebase:
- **ai_engine/app.py (line 33)**: `MOUTH_AR_THRESH = 0.25` 
- **ai_engine/driver_session_manager.py**: Defaults to `0.6` (via environment variable)
- **Difference**: 2.4x - This causes unpredictable yawning detection behavior

**Impact**: Yawning and fatigue detection fails because the behavior engine uses 0.25 but the session manager expects 0.6.

---

### 2. **No Automatic Baseline Metric Collection (SEVERITY: CRITICAL)**
**Problem**: The system is supposed to collect driver facial metrics on AI engine startup to establish personalized baselines, but this is NOT happening.

**Current behavior**: 
- Calibration is ONLY triggered via explicit POST endpoints
- No automatic initialization of driver baseline measurements
- Every driver starts with hard-coded defaults (0.25, 0.25, 25.0)

**Impact**: Without personalized baselines, all drivers use the same thresholds regardless of facial characteristics.

---

### 3. **Threshold Computation Never Happens (SEVERITY: CRITICAL)**
**Problem**: The calibration system collects samples but NEVER computes personalized thresholds from them.

**Current flow**:
1. Calibration frames are collected and stored (ear_open_samples, ear_closed_samples, etc.)
2. Backend's `get_personalized_thresholds()` checks if `is_calibrated == True`
3. **BUT**: There's no code that:
   - Processes the collected samples
   - Computes statistics (mean, std, percentiles)
   - Calculates threshold values
   - Sets `is_calibrated = True`

**Impact**: Even if calibration frames are collected, personalized thresholds are never computed or used.

---

### 4. **Missing Backend Endpoint for Calibration Frame Submission (SEVERITY: CRITICAL)**
**Problem**: The AI engine has calibration endpoints, but there's no corresponding backend endpoint to:
- Receive calibration frame submissions
- Update the driver calibration document
- Trigger threshold computation

**AI Engine endpoints (exist)**:
- `POST /drivers/<driver_id>/calibration/frame` 
- `POST /drivers/<driver_id>/calibration/complete`

**Backend endpoints (missing)**:
- No endpoint to submit/process calibration frames
- No endpoint to compute thresholds from collected samples
- The calibration data is collected but not communicated back to the backend

**Impact**: Calibration data collected at AI engine is lost. Backends can never compute personalized thresholds.

---

### 5. **No Initial Driver Baseline Metrics Storage (SEVERITY: HIGH)**
**Problem**: When a driver starts a trip, there's no mechanism to:
- Capture their first 5-10 frames automatically
- Store them as baseline metrics (when face is neutral/normal state)
- Use these to establish dynamic thresholds

**Expected flow** (not happening):
```
Trip starts → AI engine captures ~10 baseline frames → Stores metrics → 
Backend computes personalized thresholds from baseline → 
Thresholds used for this driver's trip
```

**Actual flow** (currently):
```
Trip starts → Uses hard-coded defaults for all drivers → 
No personalized thresholds ever computed
```

---

## Summary: Why Events Aren't Being Detected

1. **All drivers use identical fixed thresholds** (0.25 EAR, 0.25 MAR, 25° head turn)
2. **No person-specific baseline metrics** stored or referenced
3. **Calibration system disabled** - even if you trigger it manually, thresholds never computed
4. **Backend can't help** - no way to pass calibration data back to it
5. **Result**: Thresholds either too loose (no detections) or too strict (false positives), and never personalized

---

## How the Fix Will Work

### Phase 1: Store Baseline Metrics
- When a trip starts or driver identified, automatically capture 5-10 neutral frames
- Store EAR, MAR, yaw values as baseline
- Calculate personalized thresholds: 
  - EAR threshold = baseline_ear_open * 0.6 (trigger at 60% of open value)
  - MAR threshold = baseline_mar_closed * 1.5 (trigger at 1.5x closed value)
  - Head turn threshold = baseline_head_straight ± 15°

### Phase 2: Use Personalized Thresholds
- Compute thresholds from stored baseline
- Pass to behavior engine for detection
- Store computed thresholds in backend

### Phase 3: Persist to Backend
- Send calibration data to backend after each trip
- Allow reuse for that driver on future trips
- Improve accuracy over multiple trips

---

## Android App Analysis

✅ **Good News**: The Android app is properly configured for mDNS discovery and will work without USB debugging.

**Configuration verified**:
- mDNS discovery enabled via NSD API (ConfigManager.java)
- Proper permissions in AndroidManifest.xml (INTERNET, ACCESS_NETWORK_STATE)
- Backend registers itself via mDNS (app.py: lines 1060-1080)
- Falls back to default IP (192.168.55.101:5000) if discovery fails

**IP change handling**: The mDNS approach actually handles network changes well because discovery runs on each connection attempt.

---

## Files to Modify

1. **ai_engine/app.py** - Fix MAR threshold constant + add baseline metric collection
2. **ai_engine/driver_session_manager.py** - Align threshold defaults  
3. **ai_engine/calibration_engine.py** - Add threshold computation logic
4. **backend/calibration_model.py** - Add threshold computation function
5. **backend/app.py** - Add endpoint for calibration frame processing
6. **ai_engine/behavior_engine.py** - Use computed thresholds on first detection

