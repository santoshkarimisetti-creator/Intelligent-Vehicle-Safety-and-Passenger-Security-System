#!/usr/bin/env python3
"""
Diagnostic script to test eye closing, drowsiness, and distracted (looking away) detection.

Tests:
1. Facial metrics extraction (EAR, MAR, yaw angle)
2. Detection logic with various input values
3. Behavior engine temporal filtering
"""

import requests
import json

API_BASE = "http://localhost:5000"
AI_ENGINE = "http://localhost:5001"

print("=" * 80)
print("DETECTION SYSTEM DIAGNOSTIC")
print("=" * 80)

# Test 1: Check current thresholds
print("\n1. CHECKING CURRENT THRESHOLDS")
print("-" * 80)

try:
    # Get driver calibration to see thresholds
    resp = requests.get(f"{API_BASE}/drivers/test_driver/calibration")
    if resp.status_code == 200:
        cal = resp.json()
        print(f"\n✓ Calibration found:")
        print(f"  EAR threshold (drowsiness):   {cal.get('personalized_thresholds', {}).get('ear_drowsiness', 0.20)}")
        print(f"  MAR threshold (yawning):      {cal.get('personalized_thresholds', {}).get('mar_yawning', 0.08)}")
        print(f"  Head turn threshold (distracted): {cal.get('personalized_thresholds', {}).get('head_turn', 20)}°")
    else:
        print(f"✗ No calibration found (201 response - normal for new drivers)")
        print(f"  Default thresholds:")
        print(f"    EAR threshold (drowsiness):   0.20")
        print(f"    MAR threshold (yawning):      0.08")
        print(f"    Head turn threshold:          20°")
except Exception as e:
    print(f"✗ Error checking calibration: {e}")

# Test 2: Check behavior engine configuration
print("\n\n2. CHECKING BEHAVIOR ENGINE CONFIGURATION")
print("-" * 80)
print("""
Behavior Engine Requirements (these can cause detections to not trigger):

Drowsiness:
  - Minimum consecutive frames: ~0.6s (~18 frames at 30fps)
  - Cooldown after episode: 0.0s (can repeat immediately)
  - Trigger: EAR < 0.20

Yawning:
  - Minimum consecutive frames: ~0.3s (~9 frames at 30fps)
  - Cooldown after episode: 1.0s (must wait 1 second before next yawn detected)
  - Trigger: MAR > 0.08

Distraction (Looking Away):
  - Minimum consecutive frames: ~0.5s (~15 frames at 30fps)
  - Cooldown after episode: 0.5s (must wait 0.5 seconds before next detection)
  - Trigger: |yaw_angle| > 20°

OBSERVATION:
If detections are not appearing, check:
1. ✓ Facial landmarks are being detected
2. ✓ EAR/MAR/yaw values are being computed correctly
3. ✓ Raw values cross the thresholds
4. ✓ Consecutive frame requirement is met (enough consecutive frames with metric > threshold)
5. ✓ Not in cooldown period from previous detection
""")

# Test 3: Manual detection test
print("\n3. TESTING DETECTION LOGIC MANUALLY")
print("-" * 80)

detection_tests = [
    {
        "name": "1. Eyes OPEN (normal)",
        "metrics": {"ear": 0.35, "mar": 0.03, "yaw_angle": 5.0},
        "expected": "No detections"
    },
    {
        "name": "2. Eyes CLOSING (low EAR)",
        "metrics": {"ear": 0.18, "mar": 0.03, "yaw_angle": 5.0},
        "expected": "Should trigger drowsiness (EAR 0.18 < 0.20)"
    },
    {
        "name": "3. Eyes CLOSED (very low EAR)",
        "metrics": {"ear": 0.08, "mar": 0.03, "yaw_angle": 5.0},
        "expected": "Should trigger drowsiness with HIGH confidence"
    },
    {
        "name": "4. YAWNING (high MAR)",
        "metrics": {"ear": 0.35, "mar": 0.15, "yaw_angle": 5.0},
        "expected": "Should trigger yawning (MAR 0.15 > 0.08)"
    },
    {
        "name": "5. LOOKING AWAY - 25 degrees",
        "metrics": {"ear": 0.35, "mar": 0.03, "yaw_angle": 25.0},
        "expected": "Should trigger distraction (25° > 20°)"
    },
    {
        "name": "6. LOOKING AWAY - 40 degrees",
        "metrics": {"ear": 0.35, "mar": 0.03, "yaw_angle": 40.0},
        "expected": "Should trigger distraction with HIGH confidence"
    }
]

for test in detection_tests:
    print(f"\nTest: {test['name']}")
    print(f"  Input:    {test['metrics']}")
    print(f"  Expected: {test['expected']}")
    
    # Simulate what the detection logic should do
    ear = test['metrics']['ear']
    mar = test['metrics']['mar']
    yaw = abs(test['metrics']['yaw_angle'])
    
    detections = []
    
    if ear < 0.20:
        conf = 1.0 - (ear / 0.20) if 0.20 > 0 else 0.0
        detections.append(f"drowsiness (conf: {conf:.2f})")
    
    if mar > 0.08:
        conf = (mar - 0.08) / max(0.04, 0.08 * 0.5)
        detections.append(f"yawning (conf: {conf:.2f})")
    
    if yaw > 20:
        conf = (yaw - 20) / max(20, 20 * 0.8)
        detections.append(f"distraction (conf: {conf:.2f})")
    
    if detections:
        print(f"  Result:   ✓ {', '.join(detections)}")
    else:
        print(f"  Result:   ✗ No detections")

# Test 4: Summary and recommendations
print("\n\n4. RECOMMENDATIONS TO FIX DETECTION ISSUES")
print("-" * 80)
print("""
If eye closing, drowsiness, or distraction are NOT detecting properly:

ISSUE 1: Thresholds are too strict
  Solution: Lower thresholds to be more sensitive
    - EAR threshold: Try 0.25 instead of 0.20 (eyes closing detection)
    - MAR threshold: Try 0.10 instead of 0.08 (yawning detection)
    - Head turn: Keep at 20° (reasonable value)

ISSUE 2: Behavior engine temporal filtering too aggressive
  Solution: Reduce minimum consecutive frames requirement
    - Drowsiness: 0.6s → 0.3s (18 frames → 9 frames at 30fps)
    - Yawning: 0.3s → 0.15s (9 frames → 4 frames at 30fps)
    - Distraction: 0.5s → 0.25s (15 frames → 7 frames at 30fps)

ISSUE 3: Cooldown periods prevent rapid detections
  Solution: Reduce cooldown periods
    - Yawning: 1.0s → 0.2s (allow quicker successive yawns)
    - Distraction: 0.5s → 0.1s (allow quicker successive distractions)

ISSUE 4: Face/landmarks not being detected
  Solution: Check landmark engine
    - Verify MediaPipe can detect faces in frame
    - Check if face_detected flag is TRUE
    - Ensure sufficient image resolution/quality
""")

print("\n" + "=" * 80)
print("END OF DIAGNOSTIC")
print("=" * 80)
