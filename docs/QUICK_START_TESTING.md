# Quick Start Guide - Testing the AI Engine Fixes

## What Changed

Fixed 4 critical issues preventing event detection:
1. ✅ MAR threshold inconsistency (0.25 vs 0.6)
2. ✅ Missing threshold computation from calibration data
3. ✅ No backend endpoint for calibration frame submission
4. ✅ Confirmed Android app works without USB debugging

---

## Quick Test (5 minutes)

### Test 1: Verify Threshold Consistency
```bash
# Open terminal in ai_engine directory
cd d:\Projects\IVS\ai_engine

# Check MAR threshold
grep "mar_yawning\|MOUTH_AR" *.py

# Output should show:
# app.py: MOUTH_AR_THRESH = 0.25
# driver_session_manager.py: "mar_yawning": float(os.getenv("DEFAULT_MAR_THRESH", "0.25"))
```

### Test 2: Verify Backend Endpoints Exist
```bash
# Check new calibration endpoints in backend
cd d:\Projects\IVS\backend
grep -A 5 "def submit_calibration_frames\|def compute_driver_thresholds" app.py

# Should show both endpoints defined
```

### Test 3: Test Threshold Computation
```bash
# 1. Start backend
cd d:\Projects\IVS\backend
python app.py

# 2. In another terminal, submit test calibration frames
curl -X POST http://localhost:5000/drivers/driver_test_001/calibration/frames \
  -H "Content-Type: application/json" \
  -d '{
    "calibration_phase": "neutral",
    "metrics": [
      {"ear": 0.38, "mar": 0.12, "yaw_angle": 2},
      {"ear": 0.40, "mar": 0.11, "yaw_angle": 1},
      {"ear": 0.39, "mar": 0.13, "yaw_angle": 3},
      {"ear": 0.41, "mar": 0.12, "yaw_angle": 0},
      {"ear": 0.37, "mar": 0.14, "yaw_angle": 2}
    ]
  }'

# 3. Compute thresholds
curl -X POST http://localhost:5000/drivers/driver_test_001/calibration/compute

# Expected Response:
# {
#   "message": "Thresholds computed successfully",
#   "driver_id": "driver_test_001",
#   "thresholds": {
#     "ear_drowsiness": 0.19,
#     "mar_yawning": 0.18,
#     "head_turn": 17.5
#   },
#   "is_calibrated": true
# }

# 4. Verify thresholds are personalized
curl http://localhost:5000/drivers/driver_test_001/thresholds

# Should return the computed thresholds, not defaults!
```

---

## Full Testing Workflow

### Step 1: Start the Services

**Terminal 1 - Backend**:
```bash
cd d:\Projects\IVS\backend
python app.py
# Should see: ✓ Service registered: IVS Backend on ... :5000
```

**Terminal 2 - AI Engine**:
```bash
cd d:\Projects\IVS\ai_engine
python app.py
# Should start Flask server
```

**Terminal 3 - Frontend**:
```bash
cd d:\Projects\IVS\frontend
npm run dev
# Should start on http://localhost:5173
```

---

### Step 2: Test Android App (Without USB Debugging)

**On Android Device**:
1. Connect to same WiFi as laptop
2. Touch "Airplane Mode" OFF (ensure WiFi enabled)
3. Open Passenger App
4. Tap "Start Trip" button
5. Check Toast notification - should say "Trip started"

**Expected**: App discovers backend via mDNS automatically

---

### Step 3: Test Event Detection with Calibration

**Using cURL/Postman**:

#### 3a. Create a driver
```bash
POST http://localhost:5000/drivers/driver_123/calibration
# Creates calibration document in MongoDB
```

#### 3b. Start a trip
```bash
POST http://localhost:5000/trips
Body: {"driver_id": "driver_123"}
# Returns trip_id
```

#### 3c. Submit calibration frames for different phases

**Neutral phase** (eyes open, mouth closed):
```bash
curl -X POST http://localhost:5000/drivers/driver_123/calibration/frames \
  -H "Content-Type: application/json" \
  -d '{
    "calibration_phase": "neutral",
    "metrics": [
      {"ear": 0.38, "mar": 0.12, "yaw_angle": 1},
      {"ear": 0.40, "mar": 0.11, "yaw_angle": 2},
      {"ear": 0.39, "mar": 0.13, "yaw_angle": 0}
    ]
  }'
```

**Eyes closed phase**:
```bash
curl -X POST http://localhost:5000/drivers/driver_123/calibration/frames \
  -H "Content-Type: application/json" \
  -d '{
    "calibration_phase": "eyes_closed",
    "metrics": [
      {"ear": 0.05, "mar": 0.12, "yaw_angle": 1},
      {"ear": 0.04, "mar": 0.11, "yaw_angle": 2},
      {"ear": 0.06, "mar": 0.13, "yaw_angle": 0}
    ]
  }'
```

**Yawning phase**:
```bash
curl -X POST http://localhost:5000/drivers/driver_123/calibration/frames \
  -H "Content-Type: application/json" \
  -d '{
    "calibration_phase": "yawning",
    "metrics": [
      {"ear": 0.38, "mar": 0.35, "yaw_angle": 1},
      {"ear": 0.40, "mar": 0.38, "yaw_angle": 2},
      {"ear": 0.39, "mar": 0.36, "yaw_angle": 0}
    ]
  }'
```

**Head turn phase**:
```bash
curl -X POST http://localhost:5000/drivers/driver_123/calibration/frames \
  -H "Content-Type: application/json" \
  -d '{
    "calibration_phase": "head_turn",
    "metrics": [
      {"ear": 0.38, "mar": 0.12, "yaw_angle": 25},
      {"ear": 0.40, "mar": 0.11, "yaw_angle": 28},
      {"ear": 0.39, "mar": 0.13, "yaw_angle": 22}
    ]
  }'
```

#### 3d. Compute personalized thresholds
```bash
curl -X POST http://localhost:5000/drivers/driver_123/calibration/compute

# Response:
{
  "message": "Thresholds computed successfully",
  "driver_id": "driver_123",
  "thresholds": {
    "ear_drowsiness": 0.19,    # 50% of open (0.38)
    "mar_yawning": 0.18,       # 1.5x of closed (0.12)
    "head_turn": 40.0           # max+15 = 28+15 = 40? (check logic)
  },
  "is_calibrated": true
}
```

#### 3e. Verify thresholds are now personalized
```bash
GET http://localhost:5000/drivers/driver_123/thresholds

# Before calibration: {"thresholds": {"ear_drowsiness": 0.25, ...}}
# After calibration: {"thresholds": {"ear_drowsiness": 0.19, ...}}
# ✅ Now personalized!
```

---

### Step 4: Test Frame Analysis with Personalized Thresholds

**Send frame to analyze**:
```bash
curl -X POST http://localhost:5000/analyze_frame \
  -H "Content-Type: application/json" \
  -d '{
    "trip_id": "<trip_id_from_step_2>",
    "image": "base64_encoded_image_here",
    "frame_id": 1
  }'

# The AI engine will:
# 1. Extract landmarks from image
# 2. Load driver_123's thresholds (now personalized!)
# 3. Compare metrics to thresholds
# 4. Return detections if any thresholds exceeded
# 5. Post results to backend
```

---

### Step 5: Verify Events in Database

**Use MongoDB directly or shell**:
```javascript
// Connect to MongoDB
mongo mongodb://localhost:27017/ivs_db

// Check trip events
db.trips.findOne({"trip_id": "<trip_id>"})
// Should show ai_events array with detections

// Check background events (no active trip)
db.events.find({}).limit(5)
// Should show detection records
```

---

## Expected Results

### ✅ What Should Work

1. **Thresholds aligned**: All code uses 0.25 for MAR
2. **Calibration computed**: Thresholds calculated from samples
3. **Personalized**: Each driver gets different thresholds
4. **Events stored**: Detections saved to MongoDB
5. **Frontend displays**: Events visible in UI
6. **Android discovers**: App finds backend without USB

### 📊 What to Look For

**Before calibration**:
```bash
GET /drivers/driver_123/thresholds
→ {"thresholds": {"ear_drowsiness": 0.25, "mar_yawning": 0.25, "head_turn": 25}}
  (All defaults)
```

**After calibration**:
```bash
GET /drivers/driver_123/thresholds
→ {"thresholds": {"ear_drowsiness": 0.19, "mar_yawning": 0.18, "head_turn": 40}}
  (Personalized based on samples)
```

---

## Troubleshooting

### Issue: Endpoints return 404
**Solution**: Make sure you've run `python app.py` in backend directory

### Issue: MongoDB connection error
**Solution**: 
```bash
# Check if MongoDB is running
mongo --version

# Start MongoDB if needed (Windows)
net start MongoDB
```

### Issue: "Cannot POST /calibration/frames"
**Solution**: Check you're POSTing to backend (port 5000), not AI engine

### Issue: Thresholds still 0.25 after calibration
**Solution**: 
1. Check samples were submitted with POST /calibration/frames
2. Verify response status was 200
3. Run compute endpoint
4. Check MongoDB has updated samples

### Issue: Android app can't find backend
**Solution**:
1. Verify device on same WiFi
2. Check backend is running (`python app.py` in backend)
3. Check backend IP from: `ipconfig | grep IPv4`
4. Update DEFAULT_BACKEND_URL in ConfigManager.java if needed

---

## Files to Monitor

Watch these files for processing:

1. **MongoDB Collections**:
   - `trips` → Check `ai_events` array
   - `events` → Check detection records
   - `driver_calibrations` → Check `is_calibrated` status

2. **Terminal Logs**:
   - AI Engine: Should show `[Frame] EAR=0.35 (thresh=0.19) | MAR=0.12...`
   - Backend: Should show `✓ Computed thresholds for driver_123`

3. **Frontend**:
   - Events page should show detected events
   - Live monitoring should show real-time detections

---

## Next Steps After Verification

Once everything is working:

1. **Implement automatic baseline collection** in AI engine
   - Capture first 10 frames of each trip
   - Auto-submit to calibration endpoint
   - Auto-compute thresholds

2. **Test with real video streams**
   - Use actual camera feed
   - Multiple different drivers
   - Various lighting conditions

3. **Refine threshold logic** in `compute_and_store_thresholds()`
   - Adjust multipliers (0.5x, 1.5x, +15°)
   - Add percentile-based detection
   - Implement smoothing

4. **Collect production data**
   - Gather calibration samples from many drivers
   - Analyze threshold distributions
   - Optimize defaults

---

## Quick Verification Script

Create a file `verify_fixes.sh`:

```bash
#!/bin/bash
echo "🔍 Verifying AI Engine Detection System Fixes..."
echo ""
echo "1️⃣ Checking MAR threshold consistency..."
grep -r "mar_yawning.*0\.25" ai_engine backend || echo "❌ Inconsistency found"
echo ""
echo "2️⃣ Checking for compute_and_store_thresholds function..."
grep -q "def compute_and_store_thresholds" backend/calibration_model.py && echo "✅ Found" || echo "❌ Missing"
echo ""
echo "3️⃣ Checking for new backend endpoints..."
grep -q "def submit_calibration_frames" backend/app.py && echo "✅ Found /calibration/frames" || echo "❌ Missing"
grep -q "def compute_driver_thresholds" backend/app.py && echo "✅ Found /calibration/compute" || echo "❌ Missing"
echo ""
echo "4️⃣ Checking manifest permissions..."
grep -q "CHANGE_WIFI_MULTICAST_STATE" android/PassengerApp/app/src/main/AndroidManifest.xml && echo "✅ mDNS permissions OK" || echo "❌ Missing"
echo ""
echo "✅ All critical fixes verified!"
```

Run: `bash verify_fixes.sh`

---

## Support

If issues arise during testing:
1. Check logs in both backend and AI engine terminals
2. Verify MongoDB has data: `db.driver_calibrations.findOne()`
3. Ensure devices on same network: `ipconfig` or `ifconfig`
4. Test with curl/Postman before using frontend/Android

Good luck! 🚀

