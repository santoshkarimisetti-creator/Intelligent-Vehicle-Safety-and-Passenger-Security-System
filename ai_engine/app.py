import os
import json
import base64
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cv2
import numpy as np

from flask import Flask, jsonify, request
from flask_cors import CORS

# Try to import MediaPipe for hand detection
try:
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    print("MediaPipe not available. Hand gesture detection disabled.")

app = Flask(__name__)
CORS(app)

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:5000")
DEFAULT_AI_SOURCE = "ai_engine"

# Initialize OpenCV Haar Cascade detectors (built-in with OpenCV)
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')

# SOS gesture tracking
sos_gesture_state = {
    "is_palm_open": False,
    "palm_start_time": None,
    "trip_id": None
}

# Rule-Based Risk Engine: Per-trip event counters
trip_event_counters = {}  # {trip_id: {drowsiness_events, yawning_events, looking_away_events, overspeed_count}}

def _get_trip_counters(trip_id: str) -> Dict[str, int]:
    """Get or initialize counters for a trip."""
    if trip_id not in trip_event_counters:
        trip_event_counters[trip_id] = {
            "drowsiness_events": 0,
            "yawning_events": 0,
            "looking_away_events": 0,
            "overspeed_count": 0,
            "total_frames_analyzed": 0
        }
    return trip_event_counters[trip_id]


def _increment_event_counter(trip_id: str, event_type: str) -> None:
    """Increment counter for specific event type."""
    counters = _get_trip_counters(trip_id)
    if event_type == "drowsiness":
        counters["drowsiness_events"] += 1
    elif event_type == "yawning":
        counters["yawning_events"] += 1
    elif event_type in ["distraction", "looking_away"]:
        counters["looking_away_events"] += 1


def _increment_overspeed(trip_id: str, speed: float, speed_limit: float = 80) -> None:
    """Increment overspeed counter if speed exceeds limit."""
    counters = _get_trip_counters(trip_id)
    counters["total_frames_analyzed"] += 1
    if speed > speed_limit:
        counters["overspeed_count"] += 1

# Simplified EAR/MAR simulation constants
EYE_AR_THRESH = 0.25  # Below this indicates drowsiness
MOUTH_AR_THRESH = 0.6  # Above this indicates yawning
HEAD_TURN_THRESH = 25  # Degrees from center
SOS_DURATION_THRESH = 2.0  # Seconds to hold palm for SOS trigger

# MediaPipe Hand Landmarker (lazy initialization)
hand_landmarker = None


def _euclidean_distance(p1: np.ndarray, p2: np.ndarray) -> float:
    """Calculate Euclidean distance between two points."""
    return float(np.linalg.norm(p1 - p2))


def _get_hand_landmarker():
    """
    Lazy initialization of hand landmarker.
    Returns None if MediaPipe is not available.
    """
    global hand_landmarker
    
    if not MEDIAPIPE_AVAILABLE:
        return None
    
    if hand_landmarker is None:
        try:
            # MediaPipe Hand Landmarker can work without explicit model file in newer versions
            # It uses built-in model
            base_options = python.BaseOptions(model_asset_path='')
            options = vision.HandLandmarkerOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.IMAGE,
                num_hands=2,
                min_hand_detection_confidence=0.5,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5
            )
            # Try to create without model file (uses built-in)
            try:
                hand_landmarker = vision.HandLandmarker.create_from_options(options)
            except:
                # If fails, MediaPipe hands not fully configured
                print("MediaPipe Hands: Model file required but not configured")
                return None
        except Exception as e:
            print(f"Warning: Could not create HandLandmarker: {e}")
            return None
    
    return hand_landmarker


def _is_palm_open(hand_landmarks) -> bool:
    """
    Check if palm is open (all fingers extended).
    Uses fingertip vs base landmark positions.
    """
    if not hand_landmarks or len(hand_landmarks) < 21:
        return False
    
    # MediaPipe hand landmark indices:
    # 0: Wrist, 4: Thumb tip, 8: Index tip, 12: Middle tip, 16: Ring tip, 20: Pinky tip
    # 2: Thumb base, 5: Index base, 9: Middle base, 13: Ring base, 17: Pinky base
    
    wrist = hand_landmarks[0]
    
    # Check each finger (except thumb, different geometry)
    fingers_extended = 0
    
    # Index finger
    if hand_landmarks[8].y < hand_landmarks[5].y:  # Tip above base
        fingers_extended += 1
    
    # Middle finger
    if hand_landmarks[12].y < hand_landmarks[9].y:
        fingers_extended += 1
    
    # Ring finger
    if hand_landmarks[16].y < hand_landmarks[13].y:
        fingers_extended += 1
    
    # Pinky finger
    if hand_landmarks[20].y < hand_landmarks[17].y:
        fingers_extended += 1
    
    # Thumb (check horizontal extension)
    thumb_extended = abs(hand_landmarks[4].x - wrist.x) > abs(hand_landmarks[2].x - wrist.x)
    
    # Palm is open if at least 4 fingers are extended (including thumb)
    return fingers_extended >= 3 and thumb_extended


def _detect_sos_gesture(image: np.ndarray, trip_id: str) -> Dict[str, Any]:
    """
    Detect SOS hand gesture (open palm held for > 2 seconds).
    Returns: {sos_detected, sos_triggered, palm_open, duration}
    """
    global sos_gesture_state
    
    landmarker = _get_hand_landmarker()
    
    if landmarker is None:
        # MediaPipe not available, return no SOS
        return {
            "sos_detected": False,
            "sos_triggered": False,
            "palm_open": False,
            "duration": 0.0,
            "message": "MediaPipe Hands not available"
        }
    
    if image is None or image.size == 0:
        return {
            "sos_detected": False,
            "sos_triggered": False,
            "palm_open": False,
            "duration": 0.0
        }
    
    # Convert BGR to RGB
    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    
    # Create MediaPipe Image
    try:
        mp_image = python.vision.Image(
            image_format=python.vision.ImageFormat.SRGB,
            data=rgb_image
        )
        
        # Detect hands
        results = landmarker.detect(mp_image)
    except Exception as e:
        print(f"Hand detection error: {e}")
        return {
            "sos_detected": False,
            "sos_triggered": False,
            "palm_open": False,
            "duration": 0.0,
            "error": str(e)
        }
    
    current_time = time.time()
    palm_open = False
    
    # Check if any hand has open palm
    if results.hand_landmarks:
        for hand_landmarks in results.hand_landmarks:
            if _is_palm_open(hand_landmarks):
                palm_open = True
                break
    
    # Update gesture state
    if palm_open:
        if not sos_gesture_state["is_palm_open"] or sos_gesture_state["trip_id"] != trip_id:
            # Palm just opened or new trip
            sos_gesture_state["is_palm_open"] = True
            sos_gesture_state["palm_start_time"] = current_time
            sos_gesture_state["trip_id"] = trip_id
        
        # Calculate duration
        duration = current_time - sos_gesture_state["palm_start_time"]
        
        # Check if SOS should be triggered
        sos_triggered = duration >= SOS_DURATION_THRESH
        
        return {
            "sos_detected": True,
            "sos_triggered": sos_triggered,
            "palm_open": True,
            "duration": round(duration, 2),
            "hands_detected": len(results.hand_landmarks) if results.hand_landmarks else 0
        }
    else:
        # Reset state if palm is not open
        sos_gesture_state["is_palm_open"] = False
        sos_gesture_state["palm_start_time"] = None
        
        return {
            "sos_detected": False,
            "sos_triggered": False,
            "palm_open": False,
            "duration": 0.0,
            "hands_detected": len(results.hand_landmarks) if results.hand_landmarks else 0
        }


def _decode_image(image_data: str) -> Optional[np.ndarray]:
    """
    Decode base64 image string to numpy array.
    Supports both data URI and raw base64.
    """
    try:
        # Remove data URI prefix if present
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        
        # Decode base64
        img_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(img_bytes, np.uint8)
        
        # Decode image
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        return img
    except Exception as e:
        print(f"Error decoding image: {e}")
        return None


def _estimate_ear_from_eyes(gray_face, eyes) -> float:
    """
    Estimate EAR (Eye Aspect Ratio) from detected eyes.
    Uses simplified heuristic based on eye region analysis.
    """
    if len(eyes) < 2:
        return 0.3  # Default open eyes value
    
    # Analyze eye regions for closure
    ear_values = []
    for (ex, ey, ew, eh) in eyes:
        eye_region = gray_face[ey:ey+eh, ex:ex+ew]
        if eye_region.size == 0:
            continue
        
        # Calculate vertical to horizontal ratio
        # Closed eyes have lower ratio
        vertical_profile = np.mean(eye_region, axis=1)
        if len(vertical_profile) == 0:
            continue
        
        # Simple closure detection: measure intensity variation
        intensity_var = np.var(vertical_profile)
        
        # Normalize to EAR-like scale (higher var = more open)
        # Typical range: closed ~0.1-0.2, open ~0.25-0.35
        estimated_ear = min(0.35, max(0.1, intensity_var / 1000.0 + 0.15))
        ear_values.append(estimated_ear)
    
    return float(np.mean(ear_values)) if ear_values else 0.3


def _estimate_mar_from_face(gray_face, face_height) -> float:
    """
    Estimate MAR (Mouth Aspect Ratio) from lower face region.
    Uses simplified heuristic based on mouth region analysis.
    """
    # Focus on lower 40% of face for mouth region
    mouth_region_start = int(face_height * 0.6)
    mouth_region = gray_face[mouth_region_start:, :]
    
    if mouth_region.size == 0:
        return 0.3  # Default closed mouth
    
    # Analyze vertical intensity profile in mouth region
    vertical_profile = np.mean(mouth_region, axis=1)
    
    # Detect dark region (open mouth) by finding intensity drops
    if len(vertical_profile) < 3:
        return 0.3
    
    intensity_diff = np.max(vertical_profile) - np.min(vertical_profile)
    
    # Normalize to MAR-like scale
    # Typical range: closed ~0.2-0.4, yawning ~0.6-1.0
    estimated_mar = min(1.0, max(0.2, intensity_diff / 100.0))
    
    return float(estimated_mar)


def _estimate_head_yaw(face_x, face_w, image_width) -> float:
    """
    Estimate head yaw angle (looking away) based on face position.
    Simplified approach using face center deviation from image center.
    """
    face_center_x = face_x + face_w / 2
    image_center_x = image_width / 2
    
    # Calculate deviation as percentage
    deviation = (face_center_x - image_center_x) / (image_width / 2)
    
    # Convert to approximate yaw angle (-45 to +45 degrees)
    yaw_angle = deviation * 45.0
    
    return float(yaw_angle)


def _process_frame_with_opencv(image: np.ndarray) -> Dict[str, Any]:
    """
    Process frame with OpenCV Haar Cascades and estimate metrics.
    Returns: {ear, mar, yaw_angle, face_detected}
    """
    if image is None or image.size == 0:
        return {
            "face_detected": False,
            "landmarks_detected": False,
            "ear": 0.0,
            "mar": 0.0,
            "yaw_angle": 0.0
        }
    
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    
    # Detect faces
    faces = face_cascade.detectMultiScale(gray, 1.3, 5)
    
    if len(faces) == 0:
        return {
            "face_detected": False,
            "landmarks_detected": False,
            "ear": 0.0,
            "mar": 0.0,
            "yaw_angle": 0.0
        }
    
    # Use first detected face
    (x, y, w, h) = faces[0]
    face_gray = gray[y:y+h, x:x+w]
    
    # Detect eyes in face region
    eyes = eye_cascade.detectMultiScale(face_gray, 1.1, 5)
    
    # Estimate EAR from detected eyes
    ear = _estimate_ear_from_eyes(face_gray, eyes)
    
    # Estimate MAR from face region
    mar = _estimate_mar_from_face(face_gray, h)
    
    # Estimate head yaw
    yaw_angle = _estimate_head_yaw(x, w, width)
    
    return {
        "face_detected": True,
        "landmarks_detected": True,
        "ear": round(ear, 3),
        "mar": round(mar, 3),
        "yaw_angle": round(yaw_angle, 2),
        "eyes_detected": len(eyes)
    }


def _detect_from_opencv_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Detect drowsiness, yawning, and looking away from OpenCV metrics.
    
    Thresholds:
    - EAR < 0.25: Drowsiness (eyes closing)
    - MAR > 0.6: Yawning (mouth open wide)
    - |yaw_angle| > 25°: Looking away (head turned)
    """
    ear = metrics.get("ear", 0.0)
    mar = metrics.get("mar", 0.0)
    yaw_angle = abs(metrics.get("yaw_angle", 0.0))
    face_detected = metrics.get("face_detected", False)
    
    detections = []
    
    if not face_detected:
        return {
            "detections": [],
            "metrics": metrics,
            "message": "No face detected"
        }
    
    # Drowsiness detection (low EAR)
    if ear < EYE_AR_THRESH:
        confidence = 1.0 - (ear / EYE_AR_THRESH)  # Lower EAR = higher confidence
        detections.append({
            "type": "drowsiness",
            "confidence": round(min(1.0, confidence), 3),
            "source": "opencv_haar",
            "metric": "ear",
            "value": ear
        })
    
    # Yawning detection (high MAR)
    if mar > MOUTH_AR_THRESH:
        confidence = (mar - MOUTH_AR_THRESH) / 0.4  # MAR above threshold indicates yawning
        detections.append({
            "type": "yawning",
            "confidence": round(min(1.0, confidence), 3),
            "source": "opencv_haar",
            "metric": "mar",
            "value": mar
        })
    
    # Looking away detection (high yaw angle)
    if yaw_angle > HEAD_TURN_THRESH:
        confidence = (yaw_angle - HEAD_TURN_THRESH) / 20  # Yaw > threshold indicates looking away
        detections.append({
            "type": "distraction",
            "confidence": round(min(1.0, confidence), 3),
            "source": "opencv_haar",
            "metric": "yaw_angle",
            "value": yaw_angle
        })
    
    return {
        "detections": detections,
        "metrics": metrics
    }


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _compute_detection(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute detections from either:
    1. Base64 image data (uses OpenCV with Haar Cascades)
    2. Pre-computed signal scores (legacy mode)
    """
    # Check if image data is provided
    image_data = payload.get("image") or payload.get("frame")
    trip_id = payload.get("trip_id", "")
    
    if image_data:
        # OpenCV-based detection
        image = _decode_image(image_data)
        if image is not None:
            cv_metrics = _process_frame_with_opencv(image)
            detection_result = _detect_from_opencv_metrics(cv_metrics)
            
            # Add SOS gesture detection
            sos_result = _detect_sos_gesture(image, trip_id)
            
            # Add raw scores for risk computation
            detection_result["raw_scores"] = {
                "eyes_closed_score": 1.0 - cv_metrics.get("ear", 0.3) if cv_metrics.get("ear", 0.3) < EYE_AR_THRESH else 0.0,
                "head_off_road_score": min(1.0, abs(cv_metrics.get("yaw_angle", 0.0)) / 45.0),
                "yawning_score": max(0.0, (cv_metrics.get("mar", 0.0) - 0.3) / 0.7)
            }
            
            # Add SOS data
            detection_result["sos_gesture"] = sos_result
            
            return detection_result
        else:
            return {
                "detections": [],
                "raw_scores": {
                    "eyes_closed_score": 0.0,
                    "head_off_road_score": 0.0,
                    "yawning_score": 0.0
                },
                "sos_gesture": {
                    "sos_detected": False,
                    "sos_triggered": False,
                    "palm_open": False,
                    "duration": 0.0
                },
                "message": "Failed to decode image"
            }
    
    # Legacy mode: use pre-computed signal scores
    signal = payload.get("signal", {}) or {}
    metrics = payload.get("metrics", {}) or {}

    eyes_closed_score = _to_float(signal.get("eyes_closed_score", metrics.get("eyes_closed_score", 0.0)))
    head_off_road_score = _to_float(signal.get("head_off_road_score", metrics.get("head_off_road_score", 0.0)))
    yawning_score = _to_float(signal.get("yawning_score", metrics.get("yawning_score", 0.0)))

    detections: List[Dict[str, Any]] = []

    if eyes_closed_score >= 0.6:
        detections.append({
            "type": "drowsiness",
            "confidence": round(min(1.0, eyes_closed_score), 3),
            "source": DEFAULT_AI_SOURCE,
        })

    if head_off_road_score >= 0.5:
        detections.append({
            "type": "distraction",
            "confidence": round(min(1.0, head_off_road_score), 3),
            "source": DEFAULT_AI_SOURCE,
        })

    if yawning_score >= 0.55:
        detections.append({
            "type": "fatigue_yawn",
            "confidence": round(min(1.0, yawning_score), 3),
            "source": DEFAULT_AI_SOURCE,
        })

    return {
        "detections": detections,
        "raw_scores": {
            "eyes_closed_score": eyes_closed_score,
            "head_off_road_score": head_off_road_score,
            "yawning_score": yawning_score,
        },
        "sos_gesture": {
            "sos_detected": False,
            "sos_triggered": False,
            "palm_open": False,
            "duration": 0.0,
            "message": "Legacy mode: no image provided"
        }
    }


def _risk_level(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 35:
        return "MEDIUM"
    return "LOW"


def _risk_level_weighted(score: float) -> str:
    """Classify weighted risk score to safety level."""
    if score >= 76:
        return "CRITICAL"
    if score >= 51:
        return "HIGH"
    if score >= 21:
        return "MODERATE"
    return "SAFE"


def _compute_weighted_risk(detection_result: Dict[str, Any], metrics: Dict[str, Any] = None) -> Dict[str, Any]:
    """Compute composite weighted risk score (Task 7).
    
    Weights based on driver safety research:
    - Overspeed (w1):    0.25  (speed danger)
    - Drowsiness (w2):   0.30  (fatigue danger)
    - Distraction (w3):  0.35  (most dangerous - eyes off road)
    - Yawning (w4):      0.10  (often recovers quickly)
    
    Score range: 0-100
    Risk levels:
    - SAFE (0-20):      Safe driving
    - MODERATE (21-50): Caution advised
    - HIGH (51-75):     Dangerous behavior
    - CRITICAL (76-100): Immediate intervention needed
    """
    if metrics is None:
        metrics = {}
    
    # Extract detection scores (0-1 normalized)
    raw_scores = detection_result.get("raw_scores", {})
    eyes_closed_score = max(0.0, min(1.0, float(raw_scores.get("eyes_closed_score", 0) or 0)))
    head_off_road_score = max(0.0, min(1.0, float(raw_scores.get("head_off_road_score", 0) or 0)))
    yawning_score = max(0.0, min(1.0, float(raw_scores.get("yawning_score", 0) or 0)))
    
    # Speed component (normalize to 0-1: 0 at 0 km/h, 1 at 120+ km/h)
    speed = max(0.0, float(metrics.get("speed", 0) or 0))
    speed_normalized = min(1.0, speed / 120.0)
    
    # Weighted formula
    w1 = 0.25  # overspeed weight
    w2 = 0.30  # drowsiness weight
    w3 = 0.35  # distraction weight
    w4 = 0.10  # yawning weight
    
    # Compose weighted score (0-100 scale)
    weighted_score = (
        w1 * speed_normalized * 100.0 +
        w2 * eyes_closed_score * 100.0 +
        w3 * head_off_road_score * 100.0 +
        w4 * yawning_score * 100.0
    )
    
    # Ensure score is in valid range
    weighted_score = max(0.0, min(100.0, weighted_score))
    
    return {
        "weighted_score": round(weighted_score, 2),
        "weighted_level": _risk_level_weighted(weighted_score),
        "component_scores": {
            "overspeed_component": round(w1 * speed_normalized * 100.0, 2),
            "drowsiness_component": round(w2 * eyes_closed_score * 100.0, 2),
            "distraction_component": round(w3 * head_off_road_score * 100.0, 2),
            "yawning_component": round(w4 * yawning_score * 100.0, 2),
        },
        "weights": {"w1_overspeed": w1, "w2_drowsiness": w2, "w3_distraction": w3, "w4_yawning": w4}
    }


def _compute_risk(payload: Dict[str, Any], detection_result: Dict[str, Any] | None = None) -> Dict[str, Any]:
    metrics = payload.get("metrics", {}) or {}
    trip_id = payload.get("trip_id", "")

    if detection_result is None:
        detection_result = _compute_detection(payload)

    raw_scores = detection_result.get("raw_scores", {})

    speed = max(0.0, _to_float(metrics.get("speed", payload.get("speed", 0.0))))
    eyes_closed_score = _to_float(raw_scores.get("eyes_closed_score", metrics.get("eyes_closed_score", 0.0)))
    head_off_road_score = _to_float(raw_scores.get("head_off_road_score", metrics.get("head_off_road_score", 0.0)))
    yawning_score = _to_float(raw_scores.get("yawning_score", metrics.get("yawning_score", 0.0)))

    # Update event counters based on current frame detections
    if eyes_closed_score >= 0.6:
        _increment_event_counter(trip_id, "drowsiness")
    
    if yawning_score >= 0.55:
        _increment_event_counter(trip_id, "yawning")
    
    if head_off_road_score >= 0.5:
        _increment_event_counter(trip_id, "looking_away")
    
    # Track overspeed
    _increment_overspeed(trip_id, speed)
    
    # Get current counters for this trip
    counters = _get_trip_counters(trip_id)

    # **RULE-BASED RISK SCORING**
    # Base score from current frame
    base_score = (
        eyes_closed_score * 45.0
        + head_off_road_score * 30.0
        + yawning_score * 15.0
        + min(speed, 120.0) / 120.0 * 10.0
    )
    
    # **Risk Escalation Rules** (temporal patterns)
    # Rule 1: Repeated drowsiness events escalate risk
    if counters["drowsiness_events"] >= 3:
        base_score += 20.0  # Escalate for pattern
    elif counters["drowsiness_events"] >= 2:
        base_score += 10.0
    
    # Rule 2: Multiple yawning events (fatigue pattern)
    if counters["yawning_events"] >= 4:
        base_score += 15.0
    elif counters["yawning_events"] >= 2:
        base_score += 5.0
    
    # Rule 3: Repeated distraction (not focusing on road)
    if counters["looking_away_events"] >= 5:
        base_score += 25.0
    elif counters["looking_away_events"] >= 3:
        base_score += 15.0
    
    # Rule 4: Overspeed + fatigue = critical
    if counters["overspeed_count"] > 0:
        overspeed_ratio = counters["overspeed_count"] / max(counters["total_frames_analyzed"], 1)
        if overspeed_ratio > 0.5 and (counters["drowsiness_events"] > 0 or counters["yawning_events"] > 0):
            base_score += 20.0  # Critical combination

    score = max(0.0, min(100.0, base_score))

    reasons = []
    if eyes_closed_score >= 0.6:
        reasons.append("high_eye_closure")
    if head_off_road_score >= 0.5:
        reasons.append("driver_distraction")
    if yawning_score >= 0.55:
        reasons.append("frequent_yawning")
    if speed >= 80:
        reasons.append("elevated_speed")
    
    # Pattern-based reasons
    if counters["drowsiness_events"] >= 3:
        reasons.append("repeated_drowsiness")
    if counters["looking_away_events"] >= 3:
        reasons.append("persistent_distraction")
    if counters["overspeed_count"] > 3:
        reasons.append("continuous_speeding")

    # Compute weighted risk score (Task 7)
    raw_scores = detection_result.get("raw_scores", {})
    weighted_result = _compute_weighted_risk(
        detection_result,
        {**metrics, "speed": speed}
    )
    
    # Determine recommended risk level (use weighted as primary)
    recommended_level = weighted_result["weighted_level"]
    
    return {
        "risk_score_temporal": round(score, 2),  # Task 6 temporal escalation
        "risk_level_temporal": _risk_level(score),  # LOW/MEDIUM/HIGH/CRITICAL
        "risk_score_weighted": weighted_result["weighted_score"],  # Task 7 composite
        "risk_level_weighted": weighted_result["weighted_level"],  # SAFE/MODERATE/HIGH/CRITICAL
        "risk_level": recommended_level,  # Recommended (weighted primary)
        "reasons": reasons,
        "event_counters": counters,
        "weighted_breakdown": weighted_result["component_scores"],
        "weights": weighted_result["weights"],
    }


def _post_result_to_backend(result_payload: Dict[str, Any]) -> Tuple[bool, str]:
    trip_id = result_payload.get("trip_id")
    if not trip_id:
        return False, "trip_id missing; callback skipped"

    endpoint = f"{BACKEND_BASE_URL.rstrip('/')}/trips/{trip_id}/ai-results"
    try:
        body = json.dumps(result_payload).encode("utf-8")
        req = Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=5) as response:
            status = getattr(response, "status", 200)
        if 200 <= status < 300:
            return True, "sent"
        return False, f"backend returned {status}"
    except HTTPError as exc:
        return False, f"backend returned {exc.code}"
    except URLError as exc:
        return False, str(exc)
    except TimeoutError as exc:
        return False, str(exc)


def _post_sos_event_to_backend(sos_payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Send SOS event to backend."""
    trip_id = sos_payload.get("trip_id")
    if not trip_id:
        return False, "trip_id missing"

    endpoint = f"{BACKEND_BASE_URL.rstrip('/')}/trips/{trip_id}/sos"
    try:
        body = json.dumps(sos_payload).encode("utf-8")
        req = Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=5) as response:
            status = getattr(response, "status", 200)
        if 200 <= status < 300:
            return True, "SOS sent"
        return False, f"backend returned {status}"
    except HTTPError as exc:
        return False, f"backend returned {exc.code}"
    except URLError as exc:
        return False, str(exc)
    except TimeoutError as exc:
        return False, str(exc)


@app.get("/trips/<trip_id>/counters")
def get_trip_counters_endpoint(trip_id: str) -> Any:
    """Get current event counters for a specific trip."""
    counters = _get_trip_counters(trip_id)
    return jsonify({
        "trip_id": trip_id,
        "event_counters": counters,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }), 200


@app.post("/trips/<trip_id>/counters/reset")
def reset_trip_counters_endpoint(trip_id: str) -> Any:
    """Reset event counters for a trip (useful for testing or trip restart)."""
    if trip_id in trip_event_counters:
        del trip_event_counters[trip_id]
    return jsonify({
        "trip_id": trip_id,
        "message": "Event counters reset",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }), 200


@app.post("/trips/<trip_id>/complete")
def complete_trip_endpoint(trip_id: str) -> Any:
    """Mark trip as complete and clear event counters."""
    counters = _get_trip_counters(trip_id)
    summary = {
        "trip_id": trip_id,
        "final_event_counters": counters.copy(),
        "trip_duration_frames": counters.get("total_frames_analyzed", 0),
        "completion_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    # Clear counters for this trip
    if trip_id in trip_event_counters:
        del trip_event_counters[trip_id]
    
    return jsonify(summary), 200


@app.get("/health")
def health() -> Any:
    return jsonify({"status": "ok", "service": "ai_engine", "detector": "opencv+haar_cascades"}), 200


@app.post("/analyze_frame")
def analyze_frame() -> Any:
    payload = request.get_json(silent=True) or {}
    trip_id = payload.get("trip_id")

    detection_result = _compute_detection(payload)
    risk_result = _compute_risk(payload, detection_result)
    
    sos_gesture = detection_result.get("sos_gesture", {})
    sos_triggered = sos_gesture.get("sos_triggered", False)
    
    event_counters = risk_result.get("event_counters", {})

    ts = datetime.now(timezone.utc).isoformat()
    result_payload = {
        "trip_id": trip_id,
        "timestamp": ts,
        "detections": detection_result["detections"],
        "risk_score_temporal": risk_result.get("risk_score_temporal"),
        "risk_level_temporal": risk_result.get("risk_level_temporal"),
        "risk_score_weighted": risk_result.get("risk_score_weighted"),
        "risk_level_weighted": risk_result.get("risk_level_weighted"),
        "risk_score": risk_result.get("risk_level"),  # Primary recommendation
        "risk_level": risk_result.get("risk_level"),  # Primary recommendation
        "reasons": risk_result["reasons"],
        "event_counters": event_counters,
        "sos_triggered": sos_triggered,
        "sos_gesture": sos_gesture,
        "metadata": {
            "input_type": payload.get("input_type", "frame"),
            "frame_id": payload.get("frame_id"),
            "video_id": payload.get("video_id"),
            "cv_metrics": detection_result.get("metrics", {})
        },
    }

    sent_to_backend, callback_message = _post_result_to_backend(result_payload)
    
    # If SOS triggered, also send separate SOS event to backend
    if sos_triggered:
        sos_event_payload = {
            "trip_id": trip_id,
            "event_type": "SOS",
            "timestamp": ts,
            "source": "ai_engine_hand_gesture",
            "duration": sos_gesture.get("duration", 0.0),
            "metadata": {
                "palm_open": True,
                "hands_detected": sos_gesture.get("hands_detected", 0)
            }
        }
        _post_sos_event_to_backend(sos_event_payload)

    return jsonify({
        "trip_id": trip_id,
        "detections": detection_result["detections"],
        "risk_score_temporal": risk_result.get("risk_score_temporal"),
        "risk_level_temporal": risk_result.get("risk_level_temporal"),
        "risk_score_weighted": risk_result.get("risk_score_weighted"),
        "risk_level_weighted": risk_result.get("risk_level_weighted"),
        "risk_score": risk_result.get("risk_level"),  # Primary recommendation
        "risk_level": risk_result.get("risk_level"),  # Primary recommendation
        "reasons": risk_result["reasons"],
        "event_counters": event_counters,
        "weighted_breakdown": risk_result.get("weighted_breakdown"),
        "weights": risk_result.get("weights"),
        "sos_triggered": sos_triggered,
        "sos_gesture": sos_gesture,
        "cv_metrics": detection_result.get("metrics", {}),
        "backend_callback": {
            "sent": sent_to_backend,
            "message": callback_message,
        },
    }), 200


@app.post("/compute_risk")
def compute_risk() -> Any:
    payload = request.get_json(silent=True) or {}
    trip_id = payload.get("trip_id")

    risk_result = _compute_risk(payload)
    ts = datetime.now(timezone.utc).isoformat()

    result_payload = {
        "trip_id": trip_id,
        "timestamp": ts,
        "detections": payload.get("detections", []),
        "risk_score_temporal": risk_result.get("risk_score_temporal"),
        "risk_level_temporal": risk_result.get("risk_level_temporal"),
        "risk_score_weighted": risk_result.get("risk_score_weighted"),
        "risk_level_weighted": risk_result.get("risk_level_weighted"),
        "risk_score": risk_result.get("risk_level"),
        "risk_level": risk_result.get("risk_level"),
        "reasons": risk_result.get("reasons", []),
        "metadata": {
            "input_type": payload.get("input_type", "computed"),
            "frame_id": payload.get("frame_id"),
            "video_id": payload.get("video_id"),
        },
    }

    sent_to_backend, callback_message = _post_result_to_backend(result_payload)

    return jsonify({
        "trip_id": trip_id,
        "risk_score_temporal": risk_result.get("risk_score_temporal"),
        "risk_level_temporal": risk_result.get("risk_level_temporal"),
        "risk_score_weighted": risk_result.get("risk_score_weighted"),
        "risk_level_weighted": risk_result.get("risk_level_weighted"),
        "risk_score": risk_result.get("risk_level"),
        "risk_level": risk_result.get("risk_level"),
        "reasons": risk_result.get("reasons", []),
        "weighted_breakdown": risk_result.get("weighted_breakdown"),
        "weights": risk_result.get("weights"),
        "backend_callback": {
            "sent": sent_to_backend,
            "message": callback_message,
        },
    }), 200


if __name__ == "__main__":
    port = int(os.getenv("AI_ENGINE_PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=False)
