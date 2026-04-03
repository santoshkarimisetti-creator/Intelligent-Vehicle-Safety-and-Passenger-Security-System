import os
import json
import base64
import time
import uuid
import threading
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cv2
import numpy as np

from flask import Flask, jsonify, request
from flask_cors import CORS

# Import landmark extraction engine (MediaPipe FaceMesh)
from landmark_engine import get_landmark_engine

# Import face recognition service (identity layer)
from face_recognition_service import get_face_recognition_service

# Structured calibration
from calibration_engine import CalibrationPhase, get_calibration_engine

# Temporal behavior detection
from behavior_engine import get_behavior_engine
from driver_session_manager import get_driver_session_manager

# Risk scoring (separate engine)
from risk_engine import get_risk_engine

# Emotion fusion + final decision
from emotion_engine import default_emotion_result, get_emotion_engine
from final_decision_engine import get_final_decision_engine
from alert_engine import get_alert_engine

# Driver registration (enrollment)
from driver_registry_service import decode_base64_image_to_bgr, get_driver_registry_service

# Try to import MediaPipe for hand detection
try:
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    import mediapipe as mp_image  # Image wrapper for HandLandmarker.detect
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    mp_image = None  # type: ignore[assignment]
    print("MediaPipe not available. Hand gesture detection disabled.")

app = Flask(__name__)
CORS(app)

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:5000")
DEFAULT_AI_SOURCE = "ai_engine"
NO_ACTIVE_TRIP_ID = os.getenv("NO_ACTIVE_TRIP_ID", "NO_ACTIVE_TRIP")

# Face metrics are produced by MediaPipe FaceMesh in landmark_engine.py

# SOS gesture tracking
sos_gesture_state = {
    "is_palm_open": False,
    "palm_start_time": None,
    "trip_id": None
}

# Passenger SOS gesture state (open palm held for longer).
passenger_sos_gesture_state = {
    "is_palm_open": False,
    "palm_start_time": None,
    "trip_id": None
}

# Simplified EAR/MAR simulation constants
# These are used when driver has not completed calibration
EYE_AR_THRESH = 0.20  # Below this indicates drowsiness (FaceMesh EAR range: 0.0-0.4)
MOUTH_AR_THRESH = 0.08  # Above this indicates yawning (FaceMesh MAR range: 0.0-0.4, typically 0.03-0.10)
HEAD_TURN_THRESH = 20  # Degrees from center
SOS_DURATION_THRESH = 2.0  # Seconds to hold palm for SOS trigger
PASSENGER_SOS_DURATION_THRESH = float(os.getenv("PASSENGER_SOS_DURATION_THRESH", "5.0"))

# Driver personalization: Cache for thresholds (to avoid backend calls every frame)
driver_thresholds_cache = {}  # {driver_id: {ear_drowsiness, mar_yawning, head_turn, cached_at}}
THRESHOLD_CACHE_TTL = 300  # 5 minutes

# Slow analytics loop configuration (runs asynchronously and periodically).
SLOW_ANALYTICS_INTERVAL_S = float(os.getenv("SLOW_ANALYTICS_INTERVAL_S", "5.0"))
# Identity verification is session-level and should run less frequently than frame loop.
IDENTITY_VERIFY_INTERVAL_S = float(os.getenv("IDENTITY_VERIFY_INTERVAL_S", "12.0"))

# Per-session cached analytics state; updated by background worker.
_analytics_state: Dict[str, Dict[str, Any]] = {}
_analytics_lock = threading.Lock()
_episode_state: Dict[str, Dict[str, Dict[str, Any]]] = {}
_episode_lock = threading.Lock()
_episode_event_types = tuple(
    t.strip().lower() for t in os.getenv("EPISODE_EVENT_TYPES", "yawning,distraction,driver_not_visible,drowsiness").split(",") if t.strip()
)
_episode_persist_min_s = float(os.getenv("EPISODE_PERSIST_MIN_SECONDS", "0.8"))
_compute_risk_persist_events = str(os.getenv("COMPUTE_RISK_PERSIST_EVENTS", "0")).lower() in {"1", "true", "yes"}


def _empty_emotion_placeholder() -> Dict[str, Any]:
    """Placeholder for future lightweight emotion model integration."""
    return default_emotion_result()


def _analytics_state_defaults() -> Dict[str, Any]:
    return {
        "last_run_ts": 0.0,
        "running": False,
        "updated_at": None,
        "identity_session": {
            "locked": False,
            "driver_id": None,
            "confidence": 0.0,
            "last_verified_ts": 0.0,
            "last_attempt_ts": 0.0,
            "reidentify_required": False,
            "status": "UNVERIFIED",
            "mismatch_count": 0,
        },
        "identity": {
            "driver_id": None,
            "confidence": 0.0,
            "matched": False,
        },
        "driver": None,
        "passengers": [],
        "sos_gesture": {
            "type": "sos_gesture",
            "person": "passenger",
            "sos_detected": False,
            "sos_triggered": False,
            "crossed_arms": False,
            "duration": 0.0,
            "hands_detected": 0,
        },
        "driver_emotion": {
            "driver_emotion": "unknown",
            "confidence": 0.0,
            "stress_level": "LOW",
            "timestamp": None,
            "source": "emotion_placeholder",
        },
        "emotion_result": _empty_emotion_placeholder(),
        "passenger_emotions": [],
    }


def _get_cached_analytics_state(session_key: str) -> Dict[str, Any]:
    with _analytics_lock:
        st = _analytics_state.get(session_key)
        if st is None:
            st = _analytics_state_defaults()
            _analytics_state[session_key] = st
        return dict(st)


def _get_driver_id_from_trip(trip_id: str) -> str:
    """Extract or derive driver_id from trip_id (or use trip_id as default)."""
    # In a real system, query backend to get driver_id from trip
    # For now, use trip_id as driver identifier
    return trip_id or "unknown_driver"


def _parse_iso_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _detection_map_by_type(detections: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for d in detections or []:
        t = str(d.get("type") or "").strip().lower()
        if t and t not in out:
            out[t] = d
    return out


def _build_episode_persistence_payloads(
    *,
    session_key: str,
    trip_id: str,
    driver_id: str,
    detections: List[Dict[str, Any]],
    ts_iso: str,
    risk_result: Dict[str, Any],
    driver_emotion_payload: Dict[str, Any],
    metadata: Dict[str, Any],
) -> List[Dict[str, Any]]:
    now_dt = _parse_iso_utc(ts_iso) or datetime.now(timezone.utc)
    det_by_type = _detection_map_by_type(detections)
    payloads: List[Dict[str, Any]] = []

    with _episode_lock:
        session_state = _episode_state.setdefault(session_key, {})

        for event_type in _episode_event_types:
            entry = session_state.setdefault(
                event_type,
                {
                    "active": False,
                    "episode_id": None,
                    "start_time": None,
                    "event_key": None,
                },
            )

            det = det_by_type.get(event_type)
            active_now = det is not None
            det_duration = 0.0
            if det is not None:
                try:
                    det_duration = max(0.0, float(det.get("duration_s", 0.0) or 0.0))
                except Exception:
                    det_duration = 0.0

            if active_now and not bool(entry.get("active", False)):
                if det_duration < float(_episode_persist_min_s):
                    continue

                start_dt = now_dt - timedelta(seconds=det_duration)
                start_iso = start_dt.isoformat()
                episode_id = str(uuid.uuid4())
                event_key = f"{trip_id}|{driver_id}|{event_type}|{start_iso}"

                payloads.append(
                    {
                        "trip_id": trip_id,
                        "timestamp": ts_iso,
                        "source": "ai_engine",
                        "event_action": "start",
                        "event_type": event_type,
                        "event_key": event_key,
                        "episode_id": episode_id,
                        "episode_start_ts": start_iso,
                        "detections": [det],
                        "risk_score_temporal": risk_result.get("risk_score_temporal"),
                        "risk_level_temporal": risk_result.get("risk_level_temporal"),
                        "risk_score_weighted": risk_result.get("risk_score_weighted"),
                        "risk_level_weighted": risk_result.get("risk_level_weighted"),
                        "risk_score": risk_result.get("risk_score_weighted"),
                        "risk_level": risk_result.get("risk_level"),
                        "reasons": risk_result.get("reasons", []),
                        "driver_emotion": driver_emotion_payload,
                        "metadata": dict(metadata),
                    }
                )

                entry["active"] = True
                entry["episode_id"] = episode_id
                entry["start_time"] = start_iso
                entry["event_key"] = event_key

            elif (not active_now) and bool(entry.get("active", False)):
                start_iso = str(entry.get("start_time") or ts_iso)
                start_dt = _parse_iso_utc(start_iso) or now_dt
                dur = max(0.0, (now_dt - start_dt).total_seconds())

                payloads.append(
                    {
                        "trip_id": trip_id,
                        "timestamp": ts_iso,
                        "source": "ai_engine",
                        "event_action": "end",
                        "event_type": event_type,
                        "event_key": entry.get("event_key"),
                        "episode_id": entry.get("episode_id"),
                        "episode_start_ts": start_iso,
                        "episode_end_ts": ts_iso,
                        "duration_s": round(dur, 3),
                        "detections": [],
                        "risk_score_temporal": risk_result.get("risk_score_temporal"),
                        "risk_level_temporal": risk_result.get("risk_level_temporal"),
                        "risk_score_weighted": risk_result.get("risk_score_weighted"),
                        "risk_level_weighted": risk_result.get("risk_level_weighted"),
                        "risk_score": risk_result.get("risk_score_weighted"),
                        "risk_level": risk_result.get("risk_level"),
                        "reasons": risk_result.get("reasons", []),
                        "driver_emotion": driver_emotion_payload,
                        "metadata": dict(metadata),
                    }
                )

                entry["active"] = False
                entry["episode_id"] = None
                entry["start_time"] = None
                entry["event_key"] = None

    return payloads


def _reset_episode_state(session_key: str) -> None:
    with _episode_lock:
        _episode_state.pop(session_key, None)


def _get_cached_thresholds(driver_id: str) -> Dict[str, float]:
    """Get cached thresholds for driver."""
    if driver_id in driver_thresholds_cache:
        cached = driver_thresholds_cache[driver_id]
        # Check if cache is still fresh
        if time.time() - cached.get("cached_at", 0) < THRESHOLD_CACHE_TTL:
            return {
                "ear_drowsiness": cached.get("ear_drowsiness", EYE_AR_THRESH),
                "mar_yawning": cached.get("mar_yawning", MOUTH_AR_THRESH),
                "head_turn": cached.get("head_turn", HEAD_TURN_THRESH)
            }
    
    # Try to fetch from backend if not cached or cache expired
    try:
        endpoint = f"{BACKEND_BASE_URL.rstrip('/')}/drivers/{driver_id}/thresholds"
        with urlopen(Request(endpoint, method="GET"), timeout=2) as response:
            if response.status == 200:
                data = json.load(response)
                thresholds = data.get("thresholds", {})
                
                # Cache the result
                driver_thresholds_cache[driver_id] = {
                    "ear_drowsiness": thresholds.get("ear_drowsiness", EYE_AR_THRESH),
                    "mar_yawning": thresholds.get("mar_yawning", MOUTH_AR_THRESH),
                    "head_turn": thresholds.get("head_turn", HEAD_TURN_THRESH),
                    "cached_at": time.time()
                }
                
                return driver_thresholds_cache[driver_id]
    except Exception as e:
        print(f"Warning: Could not fetch thresholds for {driver_id}: {e}")
    
    # Return defaults if backend unavailable
    return {
        "ear_drowsiness": EYE_AR_THRESH,
        "mar_yawning": MOUTH_AR_THRESH,
        "head_turn": HEAD_TURN_THRESH
    }

# MediaPipe Hand Landmarker (lazy initialization)
hand_landmarker = None
hand_landmarker_init_attempted = False  # Flag to avoid repeated warnings

# MediaPipe Pose Landmarker (lazy initialization) for crossed-arms SOS gesture
pose_landmarker = None
pose_landmarker_init_attempted = False


def _ensure_hand_landmarker_model_path() -> Optional[str]:
    """Resolve `hand_landmarker.task` (repo-local, cache, or download)."""
    local_path = os.path.join(os.path.dirname(__file__), "hand_landmarker.task")
    if os.path.exists(local_path):
        return local_path
    cache_path = os.path.join(tempfile.gettempdir(), "hand_landmarker.task")
    if os.path.exists(cache_path):
        return cache_path
    try:
        url = (
            "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
            "hand_landmarker/float16/1/hand_landmarker.task"
        )
        print(f"Downloading hand landmarker model to {cache_path}...")
        urllib.request.urlretrieve(url, cache_path)
        return cache_path
    except Exception as e:
        print(f"⚠ Could not download hand landmarker model: {e}")
        return None


def _ensure_pose_landmarker_model_path() -> Optional[str]:
    """Resolve `pose_landmarker_full.task` (repo-local, cache, or download)."""
    local_path = os.path.join(os.path.dirname(__file__), "pose_landmarker_full.task")
    if os.path.exists(local_path):
        return local_path
    cache_path = os.path.join(tempfile.gettempdir(), "pose_landmarker_full.task")
    if os.path.exists(cache_path):
        return cache_path
    try:
        url = (
            "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
            "pose_landmarker_full/float16/1/pose_landmarker_full.task"
        )
        print(f"Downloading pose landmarker model to {cache_path}...")
        urllib.request.urlretrieve(url, cache_path)
        return cache_path
    except Exception as e:
        print(f"⚠ Could not download pose landmarker model: {e}")
        return None


def _get_pose_landmarker():
    """Lazy init pose landmarker; returns None if MediaPipe unavailable."""
    global pose_landmarker, pose_landmarker_init_attempted
    if not MEDIAPIPE_AVAILABLE:
        return None
    if pose_landmarker_init_attempted:
        return pose_landmarker
    pose_landmarker_init_attempted = True
    try:
        model_path = _ensure_pose_landmarker_model_path()
        if not model_path:
            print("⚠ MediaPipe Pose: model path unavailable (cross-arms SOS disabled)")
            return None
        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.IMAGE,
            num_poses=2,
            min_pose_detection_confidence=0.45,
            min_pose_presence_confidence=0.45,
            min_tracking_confidence=0.45,
        )
        pose_landmarker = vision.PoseLandmarker.create_from_options(options)
        print("✓ MediaPipe Pose initialized successfully")
        return pose_landmarker
    except Exception as e:
        print(f"⚠ Warning: Could not create PoseLandmarker: {e}")
        return None


def _bbox_array_to_dict(bbox: Any) -> Optional[Dict[str, int]]:
    if isinstance(bbox, dict) and all(k in bbox for k in ("x", "y", "w", "h")):
        return {"x": int(bbox["x"]), "y": int(bbox["y"]), "w": int(bbox["w"]), "h": int(bbox["h"])}
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        return {"x": int(bbox[0]), "y": int(bbox[1]), "w": int(bbox[2]), "h": int(bbox[3])}
    return None


def _wrist_in_expanded_bbox(
    wrist_nx: float,
    wrist_ny: float,
    bbox: Dict[str, int],
    iw: int,
    ih: int,
    margin: float = 0.55,
) -> bool:
    """Normalized wrist (0..1) inside face bbox expanded for arm reach."""
    cx = wrist_nx * float(iw)
    cy = wrist_ny * float(ih)
    bx, by, bw, bh = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
    mx, my = float(bw) * margin, float(bh) * margin
    return (bx - mx) <= cx <= (bx + bw + mx) and (by - my) <= cy <= (by + bh + my)


def _norm_dist(a, b) -> float:
    try:
        dx = float(a.x) - float(b.x)
        dy = float(a.y) - float(b.y)
        return float((dx * dx + dy * dy) ** 0.5)
    except Exception:
        return 9e9


def _detect_crossed_arms_info(image: np.ndarray) -> Dict[str, Any]:
    """Detect crossed arms (X) using pose landmarks (wrist near opposite shoulder)."""
    landmarker = _get_pose_landmarker()
    if landmarker is None:
        return {"crossed": False, "error": None, "message": "MediaPipe Pose not available"}
    if image is None or image.size == 0:
        return {"crossed": False, "error": None, "message": None}

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    try:
        if mp_image is None:
            raise RuntimeError("mediapipe Image not available")
        mp_img = mp_image.Image(image_format=mp_image.ImageFormat.SRGB, data=rgb)
        results = landmarker.detect(mp_img)
    except Exception as e:
        return {"crossed": False, "error": str(e), "message": "Pose detection error"}

    if not results.pose_landmarks:
        return {"crossed": False, "error": None, "message": None}

    # Use the most confident pose (first).
    lm = results.pose_landmarks[0]
    if len(lm) < 13:
        return {"crossed": False, "error": None, "message": None}

    # MediaPipe pose landmark indices: 11 L-shoulder, 12 R-shoulder, 15 L-wrist, 16 R-wrist
    l_sh, r_sh = lm[11], lm[12]
    l_wr, r_wr = lm[15], lm[16]

    d_lwr_rsh = _norm_dist(l_wr, r_sh)
    d_rwr_lsh = _norm_dist(r_wr, l_sh)
    d_lsh_rsh = _norm_dist(l_sh, r_sh)
    if not (d_lsh_rsh > 0 and d_lsh_rsh < 2.0):
        return {"crossed": False, "error": None, "message": None}

    # Require both wrists close to opposite shoulder relative to shoulder width.
    ratio_l = d_lwr_rsh / d_lsh_rsh
    ratio_r = d_rwr_lsh / d_lsh_rsh

    thr = float(os.getenv("CROSS_ARMS_RATIO_THRESH", "0.55"))
    crossed = (ratio_l <= thr) and (ratio_r <= thr)
    return {
        "crossed": bool(crossed),
        "ratios": {"left_wrist_to_right_shoulder": round(ratio_l, 3), "right_wrist_to_left_shoulder": round(ratio_r, 3)},
        "error": None,
        "message": None,
    }


def _euclidean_distance(p1: np.ndarray, p2: np.ndarray) -> float:
    """Calculate Euclidean distance between two points."""
    return float(np.linalg.norm(p1 - p2))


def _get_hand_landmarker():
    """
    Lazy initialization of hand landmarker.
    Returns None if MediaPipe is not available.
    """
    global hand_landmarker, hand_landmarker_init_attempted
    
    if not MEDIAPIPE_AVAILABLE:
        return None
    
    # Return cached result (success or failure)
    if hand_landmarker_init_attempted:
        return hand_landmarker
    
    hand_landmarker_init_attempted = True
    
    if hand_landmarker is None:
        try:
            model_path = _ensure_hand_landmarker_model_path()
            if not model_path:
                print("⚠ MediaPipe Hands: model path unavailable (SOS gesture detection disabled)")
                return None
            base_options = python.BaseOptions(model_asset_path=model_path)
            options = vision.HandLandmarkerOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.IMAGE,
                num_hands=4,
                min_hand_detection_confidence=0.42,
                min_hand_presence_confidence=0.42,
                min_tracking_confidence=0.42,
            )
            hand_landmarker = vision.HandLandmarker.create_from_options(options)
            print("✓ MediaPipe Hands initialized successfully")
        except Exception as e:
            print(f"⚠ Warning: Could not create HandLandmarker: {e}")
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


def _detect_sos_gesture(
    image: np.ndarray,
    trip_id: str,
    palm_open_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Detect SOS hand gesture (open palm held for > 2 seconds).
    Returns: {sos_detected, sos_triggered, palm_open, duration}
    """
    global sos_gesture_state

    # This function only uses the driver/any SOS timer.
    # Passenger SOS uses a separate state and is implemented in `_detect_passenger_sos_gesture`.
    if palm_open_info is None:
        palm_open_info = _detect_palm_open_info(image)
    if "error" in palm_open_info and palm_open_info["error"]:
        return {
            "type": "sos_gesture",
            "person": "driver",
            "sos_detected": False,
            "sos_triggered": False,
            "palm_open": False,
            "duration": 0.0,
            "message": palm_open_info.get("message", "MediaPipe Hands not available"),
            "error": palm_open_info.get("error"),
        }

    palm_signal = bool(
        palm_open_info.get("driver_palm_effective", palm_open_info.get("palm_open", False))
    )
    hands_detected = int(palm_open_info.get("hands_detected", 0))

    current_time = time.time()

    if palm_signal:
        if not sos_gesture_state["is_palm_open"] or sos_gesture_state["trip_id"] != trip_id:
            sos_gesture_state["is_palm_open"] = True
            sos_gesture_state["palm_start_time"] = current_time
            sos_gesture_state["trip_id"] = trip_id

        duration = current_time - sos_gesture_state["palm_start_time"]
        sos_triggered = duration >= SOS_DURATION_THRESH
        return {
            "type": "sos_gesture",
            "person": "driver",
            "sos_detected": True,
            "sos_triggered": sos_triggered,
            "palm_open": True,
            "duration": round(duration, 2),
            "hands_detected": hands_detected,
        }

    # Reset state if palm is not open
    sos_gesture_state["is_palm_open"] = False
    sos_gesture_state["palm_start_time"] = None
    return {
        "type": "sos_gesture",
        "person": "driver",
        "sos_detected": False,
        "sos_triggered": False,
        "palm_open": False,
        "duration": 0.0,
        "hands_detected": hands_detected,
    }


def _detect_palm_open_info(
    image: np.ndarray,
    driver_bbox: Optional[Dict[str, int]] = None,
    passenger_bboxes: Optional[List[Dict[str, int]]] = None,
) -> Dict[str, Any]:
    """
    Detect open palm(s) with MediaPipe Hands and optional spatial attribution
    to driver vs passenger face regions (for separate SOS timers).
    """
    landmarker = _get_hand_landmarker()
    if landmarker is None:
        return {
            "palm_open": False,
            "driver_palm_open": False,
            "passenger_palm_open": False,
            "driver_palm_effective": False,
            "passenger_palm_effective": False,
            "hands_detected": 0,
            "error": None,
            "message": "MediaPipe Hands not available",
        }

    if image is None or image.size == 0:
        return {
            "palm_open": False,
            "driver_palm_open": False,
            "passenger_palm_open": False,
            "driver_palm_effective": False,
            "passenger_palm_effective": False,
            "hands_detected": 0,
            "error": None,
            "message": None,
        }

    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    ih, iw = rgb_image.shape[:2]
    try:
        if mp_image is None:
            raise RuntimeError("mediapipe Image not available")
        mp_img = mp_image.Image(image_format=mp_image.ImageFormat.SRGB, data=rgb_image)
        results = landmarker.detect(mp_img)
    except Exception as e:
        return {
            "palm_open": False,
            "driver_palm_open": False,
            "passenger_palm_open": False,
            "driver_palm_effective": False,
            "passenger_palm_effective": False,
            "hands_detected": 0,
            "error": str(e),
            "message": "Hand detection error",
        }

    palm_open = False
    driver_palm_open = False
    passenger_palm_open = False
    hands_detected = len(results.hand_landmarks) if results.hand_landmarks else 0
    pboxes = passenger_bboxes or []

    if results.hand_landmarks:
        for hand_landmarks in results.hand_landmarks:
            if not _is_palm_open(hand_landmarks):
                continue
            palm_open = True
            wrist = hand_landmarks[0]
            wx, wy = float(wrist.x), float(wrist.y)
            if driver_bbox and _wrist_in_expanded_bbox(wx, wy, driver_bbox, iw, ih):
                driver_palm_open = True
            for pb in pboxes:
                if _wrist_in_expanded_bbox(wx, wy, pb, iw, ih):
                    passenger_palm_open = True
                    break

    has_passengers = len(pboxes) > 0
    driver_palm_effective = bool(driver_palm_open or (not has_passengers and palm_open))
    passenger_palm_effective = bool(has_passengers and passenger_palm_open)

    return {
        "palm_open": palm_open,
        "driver_palm_open": driver_palm_open,
        "passenger_palm_open": passenger_palm_open,
        "driver_palm_effective": driver_palm_effective,
        "passenger_palm_effective": passenger_palm_effective,
        "hands_detected": hands_detected,
        "error": None,
        "message": None,
    }


def _detect_passenger_sos_gesture(
    image: np.ndarray,
    trip_id: str,
    has_passengers: bool,
    palm_open_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Passenger SOS gesture:
    - trigger when crossed arms (X) persists for 3–5 seconds
    - reset immediately when palm disappears
    - only evaluated when `has_passengers` is True
    """
    global passenger_sos_gesture_state

    if not has_passengers:
        # Reset passenger SOS state if no passengers.
        passenger_sos_gesture_state["is_palm_open"] = False
        passenger_sos_gesture_state["palm_start_time"] = None
        passenger_sos_gesture_state["trip_id"] = None
        return {
            "type": "sos_gesture",
            "person": "passenger",
            "sos_detected": False,
            "sos_triggered": False,
            "crossed_arms": False,
            "duration": 0.0,
            "hands_detected": 0,
        }

    crossed_info = _detect_crossed_arms_info(image)
    if crossed_info.get("error"):
        return {
            "type": "sos_gesture",
            "person": "passenger",
            "sos_detected": False,
            "sos_triggered": False,
            "crossed_arms": False,
            "duration": 0.0,
            "hands_detected": 0,
            "message": crossed_info.get("message"),
        }

    crossed = bool(crossed_info.get("crossed", False))
    hands_detected = 0

    current_time = time.time()

    if crossed:
        if (
            not passenger_sos_gesture_state["is_palm_open"]
            or passenger_sos_gesture_state["trip_id"] != trip_id
        ):
            passenger_sos_gesture_state["is_palm_open"] = True
            passenger_sos_gesture_state["palm_start_time"] = current_time
            passenger_sos_gesture_state["trip_id"] = trip_id

        duration = current_time - passenger_sos_gesture_state["palm_start_time"]
        gesture_s = float(os.getenv("CROSS_ARMS_SOS_DURATION_S", "4.0"))
        sos_triggered = duration >= gesture_s
        return {
            "type": "sos_gesture",
            "person": "passenger",
            "sos_detected": True,
            "sos_triggered": sos_triggered,
            "crossed_arms": True,
            "duration": round(duration, 2),
            "hands_detected": hands_detected,
            "ratios": crossed_info.get("ratios"),
        }

    # Reset state if palm is not open
    passenger_sos_gesture_state["is_palm_open"] = False
    passenger_sos_gesture_state["palm_start_time"] = None
    passenger_sos_gesture_state["trip_id"] = None
    return {
        "type": "sos_gesture",
        "person": "passenger",
        "sos_detected": False,
        "sos_triggered": False,
        "crossed_arms": False,
        "duration": 0.0,
        "hands_detected": hands_detected,
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


def _process_frame_with_landmarks(image: np.ndarray) -> Dict[str, Any]:
    """Extract face metrics from an image frame.

    All landmark/vision computation is delegated to `ai_engine.landmark_engine`.
    This wrapper exists to keep the rest of the API code stable.
    """
    landmark_engine = get_landmark_engine()
    return landmark_engine.process_frame(image)


def _detect_from_landmark_metrics(metrics: Dict[str, Any], thresholds: Dict[str, float] = None) -> Dict[str, Any]:
    """
    Detect drowsiness, yawning, and looking away from OpenCV metrics.
    
    Uses personalized thresholds if provided, otherwise uses defaults:
    - EAR < threshold: Drowsiness (eyes closing)
    - MAR > threshold: Yawning (mouth open wide)
    - |yaw_angle| > threshold: Looking away (head turned)
    """
    # Use personalized thresholds or defaults
    if thresholds is None:
        thresholds = {
            "ear_drowsiness": EYE_AR_THRESH,
            "mar_yawning": MOUTH_AR_THRESH,
            "head_turn": HEAD_TURN_THRESH
        }
    
    ear_thresh = thresholds.get("ear_drowsiness", EYE_AR_THRESH)
    mar_thresh = thresholds.get("mar_yawning", MOUTH_AR_THRESH)
    head_thresh = thresholds.get("head_turn", HEAD_TURN_THRESH)
    
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
    if ear < ear_thresh:
        confidence = 1.0 - (ear / ear_thresh) if ear_thresh > 0 else 0.0  # Lower EAR = higher confidence
        detections.append({
            "type": "drowsiness",
            "confidence": round(min(1.0, max(0.0, confidence)), 3),
            "source": "mediapipe_facemesh",
            "metric": "ear",
            "value": ear,
            "threshold": ear_thresh
        })
    
    # Yawning detection (high MAR)
    if mar > mar_thresh:
        confidence = (mar - mar_thresh) / max(0.4, mar_thresh * 0.5)  # MAR above threshold indicates yawning
        detections.append({
            "type": "yawning",
            "confidence": round(min(1.0, max(0.0, confidence)), 3),
            "source": "mediapipe_facemesh",
            "metric": "mar",
            "value": mar,
            "threshold": mar_thresh
        })
    
    # Looking away detection (high yaw angle)
    if yaw_angle > head_thresh:
        confidence = (yaw_angle - head_thresh) / max(20, head_thresh * 0.8)  # Yaw > threshold indicates looking away
        detections.append({
            "type": "distraction",
            "confidence": round(min(1.0, max(0.0, confidence)), 3),
            "source": "mediapipe_facemesh",
            "metric": "yaw_angle",
            "value": yaw_angle,
            "threshold": head_thresh
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


def _build_passenger_emotions_placeholder(passenger_meta: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for idx, p in enumerate(passenger_meta or []):
        pb = _bbox_array_to_dict(p.get("bbox") if isinstance(p, dict) else None)
        if pb is None:
            continue
        out.append(
            {
                "passenger_index": idx,
                "bbox": pb,
                "dominant_emotion": "unknown",
                "confidence": 0.0,
                "source": "emotion_placeholder",
            }
        )
    return out


def _driver_bbox_from_faces_meta(
    faces_meta: List[Dict[str, Any]],
    cv_metrics: Dict[str, Any],
) -> Optional[Dict[str, int]]:
    driver_meta = next((m for m in (faces_meta or []) if m.get("role") == "driver"), None)
    if isinstance(driver_meta, dict):
        pb = _bbox_array_to_dict(driver_meta.get("bbox"))
        if pb is not None:
            return pb
    return _bbox_array_to_dict(cv_metrics.get("face_bbox"))


def _run_slow_analytics(
    *,
    session_key: str,
    trip_id: str,
    image_bgr: np.ndarray,
    cv_metrics: Dict[str, Any],
) -> None:
    """Background analytics worker. Must never block fast loop."""
    now_ts = time.time()
    with _analytics_lock:
        prev_state = dict(_analytics_state.get(session_key) or _analytics_state_defaults())

    identity_session = dict(prev_state.get("identity_session") or {})
    identity_payload = {
        "driver_id": None,
        "confidence": 0.0,
        "matched": False,
    }
    driver_meta = None
    passenger_meta: List[Dict[str, Any]] = []
    passenger_sos = {
        "type": "sos_gesture",
        "person": "passenger",
        "sos_detected": False,
        "sos_triggered": False,
        "crossed_arms": False,
        "duration": 0.0,
        "hands_detected": 0,
    }

    try:
        faces_meta = cv_metrics.get("faces_meta", []) or []
        driver_meta = next((m for m in faces_meta if m.get("role") == "driver"), None)
        passenger_meta = [m for m in faces_meta if m.get("role") == "passenger"]
        face_detected = bool(cv_metrics.get("face_detected", False))

        # Slow analytics task 1: session-level identity management.
        # - initial identification once a face is present
        # - periodic verification every IDENTITY_VERIFY_INTERVAL_S
        # - trigger re-identification on mismatch/failure
        locked = bool(identity_session.get("locked", False))
        last_verified_ts = float(identity_session.get("last_verified_ts", 0.0) or 0.0)
        reidentify_required = bool(identity_session.get("reidentify_required", False))

        should_identify = False
        if not locked:
            should_identify = face_detected
        else:
            should_identify = reidentify_required or ((now_ts - last_verified_ts) >= float(IDENTITY_VERIFY_INTERVAL_S))

        if should_identify:
            identity_service = get_face_recognition_service()
            identity = identity_service.identify_driver(
                image_bgr=image_bgr,
                target_face_bbox=cv_metrics.get("face_bbox"),
            )
            identity_session["last_attempt_ts"] = now_ts

            matched = bool(identity.matched)
            found_driver_id = str(identity.driver_id or "").strip() or None
            found_conf = round(float(identity.confidence), 3)

            if (not locked) and matched and found_driver_id:
                identity_session["locked"] = True
                identity_session["driver_id"] = found_driver_id
                identity_session["confidence"] = found_conf
                identity_session["last_verified_ts"] = now_ts
                identity_session["reidentify_required"] = False
                identity_session["status"] = "VERIFIED"
                identity_session["mismatch_count"] = 0
            elif (not locked) and (not matched):
                identity_session["status"] = "INITIAL_IDENTIFICATION_FAILED"
                identity_session["reidentify_required"] = True
            elif locked and matched and found_driver_id == identity_session.get("driver_id"):
                identity_session["confidence"] = found_conf
                identity_session["last_verified_ts"] = now_ts
                identity_session["reidentify_required"] = False
                identity_session["status"] = "VERIFIED"
            elif locked and matched and found_driver_id and found_driver_id != identity_session.get("driver_id"):
                identity_session["locked"] = False
                identity_session["reidentify_required"] = True
                identity_session["status"] = "REIDENTIFY_REQUIRED"
                identity_session["mismatch_count"] = int(identity_session.get("mismatch_count", 0) or 0) + 1
                identity_session["driver_id"] = None
                identity_session["confidence"] = 0.0
            else:
                identity_session["locked"] = False
                identity_session["reidentify_required"] = True
                identity_session["status"] = "VERIFY_FAILED"
                identity_session["driver_id"] = None
                identity_session["confidence"] = 0.0

        identity_payload = {
            "driver_id": identity_session.get("driver_id"),
            "confidence": float(identity_session.get("confidence", 0.0) or 0.0),
            "matched": bool(identity_session.get("locked", False)),
            "status": identity_session.get("status", "UNVERIFIED"),
        }

        # Slow analytics task 2: passenger monitoring and SOS gesture.
        has_passengers = len(passenger_meta) > 0
        passenger_sos = _detect_passenger_sos_gesture(
            image_bgr,
            trip_id,
            has_passengers=has_passengers,
            palm_open_info=None,
        )

        # Slow analytics task 3: scheduled placeholder emotion analysis.
        passenger_bboxes = []
        for p in passenger_meta:
            pb = _bbox_array_to_dict(p.get("bbox") if isinstance(p, dict) else None)
            if pb is not None:
                passenger_bboxes.append(pb)

        emotion_payload = get_emotion_engine().analyze_periodic(
            session_key=session_key,
            image_bgr=image_bgr,
            driver_bbox=_driver_bbox_from_faces_meta(faces_meta, cv_metrics),
            passenger_bboxes=passenger_bboxes if has_passengers else [],
            force=True,
            is_trip_active=bool(trip_id),
        )
    except Exception as e:
        passenger_sos = {
            "type": "sos_gesture",
            "person": "passenger",
            "sos_detected": False,
            "sos_triggered": False,
            "crossed_arms": False,
            "duration": 0.0,
            "hands_detected": 0,
            "message": f"slow_analytics_error: {e}",
        }
        emotion_payload = {
            "emotion_result": _empty_emotion_placeholder(),
            "driver_emotion": {
                "driver_emotion": "unknown",
                "confidence": 0.0,
                "stress_level": "LOW",
                "timestamp": None,
                "source": "emotion_placeholder",
            },
            "passenger_emotions": _build_passenger_emotions_placeholder(passenger_meta),
            "reused_cached": False,
        }
    finally:
        now_iso = datetime.now(timezone.utc).isoformat()
        emotion_result = emotion_payload.get("emotion_result", _empty_emotion_placeholder())
        passenger_emotions = emotion_payload.get("passenger_emotions", _build_passenger_emotions_placeholder(passenger_meta))
        driver_emotion_payload = emotion_payload.get("driver_emotion") or {
            "driver_emotion": str(emotion_result.get("dominant_emotion") or "unknown"),
            "confidence": float(emotion_result.get("confidence") or 0.0),
            "stress_level": str(emotion_result.get("stress_level") or "LOW"),
            "timestamp": emotion_result.get("timestamp"),
            "source": "emotion_placeholder",
        }
        with _analytics_lock:
            state = _analytics_state.get(session_key) or _analytics_state_defaults()
            state["running"] = False
            state["updated_at"] = now_iso
            state["identity_session"] = identity_session
            state["identity"] = identity_payload
            state["driver"] = driver_meta
            state["passengers"] = passenger_meta
            state["sos_gesture"] = passenger_sos
            state["emotion_result"] = emotion_result
            state["driver_emotion"] = driver_emotion_payload
            state["passenger_emotions"] = passenger_emotions
            _analytics_state[session_key] = state


def _schedule_slow_analytics(
    *,
    session_key: str,
    trip_id: str,
    image_bgr: Optional[np.ndarray],
    cv_metrics: Dict[str, Any],
) -> None:
    """Start periodic background analytics if due. Non-blocking by design."""
    if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
        return

    now = time.time()
    with _analytics_lock:
        state = _analytics_state.get(session_key)
        if state is None:
            state = _analytics_state_defaults()
            _analytics_state[session_key] = state

        if bool(state.get("running", False)):
            return
        last_run_ts = float(state.get("last_run_ts", 0.0) or 0.0)
        if (now - last_run_ts) < max(0.5, float(SLOW_ANALYTICS_INTERVAL_S)):
            return

        state["running"] = True
        state["last_run_ts"] = now

    worker = threading.Thread(
        target=_run_slow_analytics,
        kwargs={
            "session_key": session_key,
            "trip_id": trip_id,
            "image_bgr": np.copy(image_bgr),
            "cv_metrics": dict(cv_metrics or {}),
        },
        daemon=True,
        name=f"slow-analytics-{session_key}",
    )
    worker.start()


def _compute_detection(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute detections from either:
    1. Base64 image data (uses MediaPipe FaceMesh landmarks + personalized thresholds)
    2. Pre-computed signal scores (legacy mode)
    """
    # Check if image data is provided
    image_data = payload.get("image") or payload.get("frame")
    trip_id = payload.get("trip_id", "")
    fallback_driver_id = _get_driver_id_from_trip(trip_id)
    session_key = trip_id or f"driver:{fallback_driver_id}"
    
    if image_data:
        # Landmark-based detection with personalized thresholds
        image = _decode_image(image_data)
        if image is not None:
            cv_metrics = _process_frame_with_landmarks(image)

            # Read latest cached slow analytics state and schedule refresh if due.
            cached_analytics = _get_cached_analytics_state(session_key)
            _schedule_slow_analytics(
                session_key=session_key,
                trip_id=trip_id,
                image_bgr=image,
                cv_metrics=cv_metrics,
            )

            identity_info = cached_analytics.get("identity") or {}
            identity_session = cached_analytics.get("identity_session") or {}
            active_driver_id = (
                str(identity_session.get("driver_id") or identity_info.get("driver_id") or "").strip()
                if bool(identity_session.get("locked", identity_info.get("matched", False)))
                else ""
            ) or fallback_driver_id

            # Load thresholds for the active driver (session-cached)
            session_mgr = get_driver_session_manager()
            thresholds = session_mgr.get_thresholds(
                session_key=session_key,
                driver_id=active_driver_id,
            )

            # Temporal behavior detection (stateful) keyed by ACTIVE driver id
            behavior = get_behavior_engine().update(
                driver_id=active_driver_id,
                cv_metrics=cv_metrics,
                thresholds=thresholds,
            )
            detection_result = {
                "detections": behavior.get("detections", []),
                "metrics": cv_metrics,
            }

            # Lightweight per-frame face roles from FaceLandmarker.
            faces_meta = cv_metrics.get("faces_meta", []) or []
            detection_result["driver"] = next((m for m in faces_meta if m.get("role") == "driver"), None)
            detection_result["passengers"] = [m for m in faces_meta if m.get("role") == "passenger"]

            # Heavy analytics outputs are sourced from cached slow loop.
            detection_result["identity"] = identity_info
            detection_result["session"] = session_mgr.export_session(session_key=session_key)
            detection_result["emotion"] = cached_analytics.get("emotion_result", _empty_emotion_placeholder())
            detection_result["passenger_emotions"] = cached_analytics.get("passenger_emotions", [])

            # Optional: structured calibration sample submission via analyze_frame
            # (preferred flow is via /drivers/<id>/calibration/* endpoints)
            calibration_phase = payload.get("calibration_phase")
            if calibration_phase:
                try:
                    phase = CalibrationPhase(str(calibration_phase))
                    calib_progress = get_calibration_engine().add_metrics(
                        driver_id=active_driver_id,
                        metrics=cv_metrics,
                        phase=phase,
                        auto_advance=bool(payload.get("calibration_auto_advance", True)),
                    )
                    detection_result["calibration"] = {
                        "driver_id": active_driver_id,
                        "phase": calib_progress.current_phase.value,
                        "frames_collected": calib_progress.frames_collected,
                        "frames_needed": calib_progress.frames_needed,
                        "is_complete": calib_progress.is_complete,
                    }
                except Exception as e:
                    detection_result["calibration"] = {"error": str(e)}
            
            # Passenger SOS gesture is produced by slow analytics and reused here.
            passenger_sos_result = cached_analytics.get("sos_gesture") or {
                "type": "sos_gesture",
                "person": "passenger",
                "sos_detected": False,
                "sos_triggered": False,
                "crossed_arms": False,
                "duration": 0.0,
                "hands_detected": 0,
            }
            
            # Add raw scores for risk computation (temporal & threshold-based)
            detection_result["raw_scores"] = behavior.get("raw_scores", {
                "eyes_closed_score": 0.0,
                "head_off_road_score": 0.0,
                "yawning_score": 0.0,
            })
            
            # Add personalization metadata
            detection_result["personalization"] = {
                "driver_id": active_driver_id,
                "thresholds_used": thresholds,
                "identity_locked": bool(identity_info.get("matched", False)),
            }
            
            detection_result["sos_gesture"] = passenger_sos_result
            
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

    # Legacy compatibility:
    # - tests and older clients often send boolean flags:
    #   {drowsiness: bool, yawning: bool, distraction: bool}
    # - while current implementation expects numeric signal/metrics scores.
    has_numeric_scores = (
        any(k in signal for k in ["eyes_closed_score", "head_off_road_score", "yawning_score"])
        or any(k in metrics for k in ["eyes_closed_score", "head_off_road_score", "yawning_score"])
    )

    if not has_numeric_scores and any(
        bool(payload.get(k, False)) for k in ["drowsiness", "yawning", "distraction"]
    ):
        eyes_closed_score = 1.0 if bool(payload.get("drowsiness", False)) else 0.0
        head_off_road_score = 1.0 if bool(payload.get("distraction", False)) else 0.0
        yawning_score = 1.0 if bool(payload.get("yawning", False)) else 0.0
    else:
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
            "type": "yawning",
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


def _compute_risk(payload: Dict[str, Any], detection_result: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Compute risk using the separate risk engine.

    This function intentionally does not extract face metrics.
    It consumes behavior events + raw_scores (from behavior layer) and speed.
    """
    metrics = payload.get("metrics", {}) or {}
    trip_id = payload.get("trip_id", "")

    if detection_result is None:
        detection_result = _compute_detection(payload)

    speed = max(0.0, _to_float(metrics.get("speed", payload.get("speed", 0.0))))
    detections = detection_result.get("detections", []) or []
    raw_scores = detection_result.get("raw_scores", None)

    return get_risk_engine().compute(
        trip_id=trip_id or "unknown_trip",
        detections=detections,
        raw_scores=raw_scores,
        speed_kmh=speed,
    )


def _is_trip_active(trip_id: str) -> bool:
    """
    Check if a trip is currently active (backend source of truth).
    On transport errors returns False so results route to /events instead of a stale trip doc.
    """
    if (not trip_id) or (str(trip_id).strip() == NO_ACTIVE_TRIP_ID):
        return False
    
    try:
        check_url = f"{BACKEND_BASE_URL.rstrip('/')}/is-active-trip/{trip_id}"
        check_req = Request(check_url, method="GET")
        with urlopen(check_req, timeout=5) as check_resp:
            check_data = json.loads(check_resp.read().decode("utf-8"))
            return check_data.get("is_active", False)
    except Exception:
        # If check fails, prefer background /events routing (avoids appending to completed trips).
        return False


def _post_result_to_backend(result_payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Post AI results to backend. Routes to /trips/{id}/ai-results if active trip, else to /events."""
    trip_id = result_payload.get("trip_id")
    if not trip_id:
        # Background monitoring mode: persist into /events under a fixed sentinel.
        trip_id = NO_ACTIVE_TRIP_ID
        result_payload["trip_id"] = trip_id

    try:
        is_active = _is_trip_active(trip_id)
    except Exception:
        is_active = False

    # Route to appropriate endpoint
    if is_active:
        endpoint = f"{BACKEND_BASE_URL.rstrip('/')}/trips/{trip_id}/ai-results"
    else:
        endpoint = f"{BACKEND_BASE_URL.rstrip('/')}/events"
        # Never leak an inactive/stale trip_id into background events.
        result_payload["trip_id"] = NO_ACTIVE_TRIP_ID
        result_payload["is_sos"] = result_payload.get("sos_triggered", False)

    def _post_to(url: str) -> Tuple[int, str]:
        body = json.dumps(result_payload).encode("utf-8")
        req = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=5) as response:
            status = getattr(response, "status", 200)
        return int(status), url

    try:
        status, _ = _post_to(endpoint)
        if 200 <= status < 300:
            return True, "sent"
        return False, f"backend returned {status}"
    except HTTPError as exc:
        # Completed / inactive trip: store under global events instead of trip history.
        if is_active and int(exc.code) == 409:
            try:
                fallback = dict(result_payload)
                fallback["is_sos"] = fallback.get("sos_triggered", False)
                body_fb = json.dumps(fallback).encode("utf-8")
                fb_url = f"{BACKEND_BASE_URL.rstrip('/')}/events"
                req_fb = Request(
                    fb_url,
                    data=body_fb,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(req_fb, timeout=5) as resp_fb:
                    st = getattr(resp_fb, "status", 200)
                if 200 <= int(st) < 300:
                    return True, "sent (events; trip not active)"
            except Exception:
                pass
        return False, f"backend returned {exc.code}"
    except URLError as exc:
        return False, str(exc)
    except TimeoutError as exc:
        return False, str(exc)


def _post_sos_event_to_backend(sos_payload: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Send SOS event to backend with dual-mode routing.
    If trip is active: route to /trips/{trip_id}/sos
    If trip is inactive: route to /events with is_sos=True flag
    """
    trip_id = sos_payload.get("trip_id")
    if not trip_id:
        trip_id = NO_ACTIVE_TRIP_ID
        sos_payload["trip_id"] = trip_id

    try:
        # Check if trip is active
        is_active = _is_trip_active(trip_id)

        # Determine endpoint based on trip status
        if is_active:
            # Route to trip-specific SOS endpoint
            endpoint = f"{BACKEND_BASE_URL.rstrip('/')}/trips/{trip_id}/sos"
        else:
            # Route to events collection with is_sos flag
            endpoint = f"{BACKEND_BASE_URL.rstrip('/')}/events"
            sos_payload["trip_id"] = NO_ACTIVE_TRIP_ID
            sos_payload["is_sos"] = True

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


def _post_backend_async(
    *,
    result_payloads: Optional[List[Dict[str, Any]]] = None,
    sos_event_payload: Optional[Dict[str, Any]] = None,
) -> None:
    """Background backend persistence so /analyze_frame stays low-latency."""
    for payload in (result_payloads or []):
        try:
            _post_result_to_backend(dict(payload))
        except Exception as e:
            print(f"[AsyncPost] result post failed: {e}")

    if sos_event_payload:
        try:
            _post_sos_event_to_backend(dict(sos_event_payload))
        except Exception as e:
            print(f"[AsyncPost] SOS post failed: {e}")


@app.get("/trips/<trip_id>/counters")
def get_trip_counters_endpoint(trip_id: str) -> Any:
    """Get current event counters for a specific trip."""
    counters = get_risk_engine().get_trip_counters(trip_id)
    return jsonify({
        "trip_id": trip_id,
        "event_counters": counters,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }), 200


@app.post("/trips/<trip_id>/counters/reset")
def reset_trip_counters_endpoint(trip_id: str) -> Any:
    """Reset event counters for a trip (useful for testing or trip restart)."""
    get_risk_engine().reset_trip(trip_id)
    return jsonify({
        "trip_id": trip_id,
        "message": "Event counters reset",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }), 200


@app.post("/trips/<trip_id>/complete")
def complete_trip_endpoint(trip_id: str) -> Any:
    """Mark trip as complete and clear event counters."""
    counters = get_risk_engine().get_trip_counters(trip_id)
    summary = {
        "trip_id": trip_id,
        "final_event_counters": counters.copy(),
        "trip_duration_frames": counters.get("total_frames_analyzed", 0),
        "completion_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    # Clear counters for this trip
    get_risk_engine().reset_trip(trip_id)

    # Clear locked identity/session state for this trip
    try:
        get_driver_session_manager().reset_session(session_key=trip_id)
    except Exception:
        pass
    
    # Clear emotion engine session state
    try:
        get_emotion_engine().clear_session(trip_id)
    except Exception:
        pass
    
    _reset_episode_state(session_key=trip_id)
    
    return jsonify(summary), 200


@app.post("/trips/<trip_id>/session/reset")
def reset_trip_session_endpoint(trip_id: str) -> Any:
    """Reset cached identity/threshold session state for a trip.

    This is useful when backend calibration/threshold values change and you want
    the AI engine to re-fetch thresholds immediately (instead of waiting for TTL).
    """
    try:
        get_driver_session_manager().reset_session(session_key=trip_id)
    except Exception:
        pass
    
    # Clear emotion engine session state
    try:
        get_emotion_engine().clear_session(trip_id)
    except Exception:
        pass
    
    _reset_episode_state(session_key=trip_id)

    # Also clear temporal state so detections don't carry over.
    try:
        get_behavior_engine().reset_all()
    except Exception:
        pass

    return jsonify(
        {
            "trip_id": trip_id,
            "message": "Trip session state reset",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    ), 200


@app.get("/health")
def health() -> Any:
    return jsonify({"status": "ok", "service": "ai_engine", "detector": "mediapipe_facemesh"}), 200


@app.post("/drivers/<driver_id>/calibration/start")
def start_driver_calibration(driver_id: str) -> Any:
    engine = get_calibration_engine()
    progress = engine.start(driver_id=driver_id)
    return jsonify({
        "driver_id": driver_id,
        "phase": progress.current_phase.value,
        "instructions": engine.phase_instructions(progress.current_phase),
        "frames_collected": progress.frames_collected,
        "frames_needed": progress.frames_needed,
        "is_complete": progress.is_complete,
    }), 200


@app.get("/drivers/<driver_id>/calibration/status")
def get_driver_calibration_status(driver_id: str) -> Any:
    engine = get_calibration_engine()
    progress = engine.get_progress(driver_id=driver_id)
    return jsonify({
        "driver_id": driver_id,
        "phase": progress.current_phase.value,
        "instructions": engine.phase_instructions(progress.current_phase),
        "frames_collected": progress.frames_collected,
        "frames_needed": progress.frames_needed,
        "is_complete": progress.is_complete,
    }), 200


@app.post("/drivers/<driver_id>/calibration/frame")
def submit_driver_calibration_frame(driver_id: str) -> Any:
    payload = request.get_json(silent=True) or {}
    image_data = payload.get("image") or payload.get("frame")
    phase_raw = payload.get("phase")
    auto_advance = bool(payload.get("auto_advance", True))

    if not image_data:
        return jsonify({"error": "image is required"}), 400
    if not phase_raw:
        return jsonify({"error": "phase is required"}), 400

    try:
        phase = CalibrationPhase(str(phase_raw))
    except Exception:
        return jsonify({"error": f"invalid phase: {phase_raw}"}), 400

    image = _decode_image(str(image_data))
    if image is None:
        return jsonify({"error": "failed to decode image"}), 400

    cv_metrics = _process_frame_with_landmarks(image)
    engine = get_calibration_engine()
    try:
        progress = engine.add_metrics(
            driver_id=driver_id,
            metrics=cv_metrics,
            phase=phase,
            auto_advance=auto_advance,
        )

        resp: Dict[str, Any] = {
            "driver_id": driver_id,
            "phase": progress.current_phase.value,
            "instructions": engine.phase_instructions(progress.current_phase),
            "frames_collected": progress.frames_collected,
            "frames_needed": progress.frames_needed,
            "is_complete": progress.is_complete,
            "cv_metrics": cv_metrics,
        }
        if progress.thresholds:
            resp["thresholds"] = progress.thresholds
        if progress.baseline:
            resp["baseline"] = progress.baseline
        return jsonify(resp), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"calibration frame failed: {e}"}), 500


@app.post("/drivers/<driver_id>/calibration/complete")
def complete_driver_calibration(driver_id: str) -> Any:
    engine = get_calibration_engine()
    try:
        result = engine.freeze_thresholds(driver_id=driver_id)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"calibration complete failed: {e}"}), 500


@app.post("/drivers/register")
def register_driver() -> Any:
    payload = request.get_json(silent=True) or {}
    driver_id = (payload.get("driver_id") or "").strip()
    images_b64 = payload.get("images") or []

    if not driver_id:
        return jsonify({"error": "driver_id is required"}), 400
    if not isinstance(images_b64, list) or len(images_b64) == 0:
        return jsonify({"error": "images must be a non-empty list of base64 strings"}), 400

    try:
        images_bgr = [decode_base64_image_to_bgr(s) for s in images_b64]
        result = get_driver_registry_service().register_driver_from_images(
            driver_id=driver_id,
            images_bgr=images_bgr,
        )
        return jsonify({
            "driver_id": result.driver_id,
            "samples_used": result.samples_used,
            "embedding_dim": result.embedding_dim,
            "registered": True,
        }), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"registration failed: {e}"}), 500


@app.post("/analyze_frame")
def analyze_frame() -> Any:
    started_at = time.perf_counter()
    payload = request.get_json(silent=True) or {}
    trip_id = payload.get("trip_id")

    detection_result = _compute_detection(payload)
    risk_result = _compute_risk(payload, detection_result)
    
    # Debug output for detection values
    metrics = detection_result.get("metrics", {})
    if metrics:
        ear = metrics.get("ear", 0.0)
        mar = metrics.get("mar", 0.0)
        yaw = metrics.get("yaw_angle", 0.0)
        personalization = detection_result.get("personalization", {})
        thresholds = personalization.get("thresholds_used", {})
        
        print(f"[Frame] EAR={ear:.3f} (thresh={thresholds.get('ear_drowsiness', 0.20):.3f}) | "
              f"MAR={mar:.3f} (thresh={thresholds.get('mar_yawning', 0.08):.3f}) | "
              f"Yaw={yaw:.1f}° | Detections: {len(detection_result['detections'])}")
    
    sos_gesture = detection_result.get("sos_gesture", {})
    # Keep fast loop independent from backend/network activity checks.
    trip_is_active = bool(trip_id)
    sos_triggered = bool(sos_gesture.get("sos_triggered", False))

    event_counters = risk_result.get("event_counters", {})

    # Final fusion decision (driver risk + emotion support signal + SOS override).
    emotion_result = detection_result.get("emotion")
    final_decision = get_final_decision_engine().decide(
        risk_result=risk_result,
        emotion_result=emotion_result,
        sos_triggered=bool(sos_triggered),
    )

    ts = datetime.now(timezone.utc).isoformat()
    recommended_score = final_decision.get("risk_score")
    risk_score_weighted = final_decision.get("risk_score_weighted")
    risk_level_weighted = final_decision.get("risk_level_weighted")
    risk_level = final_decision.get("risk_level")

    # Compute user-facing warnings (with cooldown). Audio/UI is handled elsewhere.
    alert_engine = get_alert_engine()
    warnings = alert_engine.get_warnings(
        trip_id=str(trip_id or "unknown_trip"),
        detections=detection_result.get("detections", []),
        risk_level_weighted=str(risk_level_weighted or ""),
        sos_triggered=bool(sos_triggered),
    )

    emo = (emotion_result or {}) if isinstance(emotion_result, dict) else {}
    driver_emotion_payload = {
        "driver_emotion": str(emo.get("dominant_emotion") or "unknown"),
        "confidence": float(emo.get("confidence") or 0.0),
        "stress_level": str(emo.get("stress_level") or "LOW"),
        "timestamp": emo.get("timestamp"),
    }

    persist_metadata = {
        "input_type": payload.get("input_type", "frame"),
        "frame_id": payload.get("frame_id"),
        "video_id": payload.get("video_id"),
        "cv_metrics": detection_result.get("metrics", {}),
        "driver": detection_result.get("driver"),
        "passengers": detection_result.get("passengers", []),
        "trip_active": trip_is_active,
        "driver_emotion": driver_emotion_payload,
        "passenger_emotions": detection_result.get("passenger_emotions", []),
        "warnings": warnings,
    }
    active_driver_id = str((detection_result.get("personalization") or {}).get("driver_id") or _get_driver_id_from_trip(str(trip_id or "")))
    session_key = str(trip_id or f"driver:{active_driver_id}")
    episode_payloads = _build_episode_persistence_payloads(
        session_key=session_key,
        trip_id=str(trip_id or ""),
        driver_id=active_driver_id,
        detections=list(detection_result.get("detections", []) or []),
        ts_iso=ts,
        risk_result={
            "risk_score_temporal": risk_result.get("risk_score_temporal"),
            "risk_level_temporal": risk_result.get("risk_level_temporal"),
            "risk_score_weighted": risk_score_weighted,
            "risk_level_weighted": risk_level_weighted,
            "risk_level": risk_level,
            "reasons": risk_result.get("reasons", []),
        },
        driver_emotion_payload=driver_emotion_payload,
        metadata=persist_metadata,
    )

    sos_event_payload = None
    if sos_triggered:
        sos_person = str(sos_gesture.get("person") or "driver")
        sos_source = (
            "ai_engine_passenger_hand_gesture"
            if sos_person == "passenger"
            else "ai_engine_hand_gesture"
        )
        sos_event_payload = {
            "trip_id": trip_id,
            "event_type": "SOS",
            "timestamp": ts,
            "source": sos_source,
            "duration": sos_gesture.get("duration", 0.0),
            "risk_score_weighted": risk_score_weighted,
            "risk_level": risk_level,
            "metadata": {
                "palm_open": True,
                "hands_detected": sos_gesture.get("hands_detected", 0),
                "person": sos_person,
            },
        }

    # Fire-and-forget backend persistence (never block request thread).
    if episode_payloads or sos_event_payload:
        threading.Thread(
            target=_post_backend_async,
            kwargs={
                "result_payloads": episode_payloads,
                "sos_event_payload": sos_event_payload,
            },
            daemon=True,
            name=f"backend-post-{trip_id or 'unknown'}",
        ).start()

    fast_loop_ms = (time.perf_counter() - started_at) * 1000.0
    print(f"[AnalyzeFrame] fast_loop_ms={fast_loop_ms:.1f} detections={len(detection_result['detections'])} trip_id={trip_id}")

    return jsonify({
        "trip_id": trip_id,
        "trip_active": trip_is_active,
        "detections": detection_result["detections"],
        "driver": detection_result.get("driver"),
        "passengers": detection_result.get("passengers", []),
        "risk_score_temporal": risk_result.get("risk_score_temporal"),
        "risk_level_temporal": risk_result.get("risk_level_temporal"),
        "risk_score_weighted": risk_score_weighted,
        "risk_level_weighted": risk_level_weighted,
        "risk_score": recommended_score,  # Primary recommendation score
        "risk_level": risk_level,  # Primary recommendation label
        "reasons": risk_result["reasons"],
        "event_counters": event_counters,
        "weighted_breakdown": risk_result.get("weighted_breakdown"),
        "weights": risk_result.get("weights"),
        "sos_triggered": sos_triggered,
        "sos_gesture": sos_gesture,
        "driver_emotion": driver_emotion_payload,
        "passenger_emotions": detection_result.get("passenger_emotions", []),
        "emotion_result": emotion_result,
        "cv_metrics": detection_result.get("metrics", {}),
        "warnings": warnings,
        "processing_ms": round(float(fast_loop_ms), 2),
        "backend_callback": {
            "sent": None,
            "message": "queued_async",
        },
    }), 200


@app.post("/compute_risk")
def compute_risk() -> Any:
    payload = request.get_json(silent=True) or {}
    trip_id = payload.get("trip_id")

    risk_result = _compute_risk(payload)
    ts = datetime.now(timezone.utc).isoformat()
    recommended_score = risk_result.get("risk_score_weighted")
    if recommended_score is None:
        recommended_score = risk_result.get("risk_score_temporal")

    result_payload = {
        "trip_id": trip_id,
        "timestamp": ts,
        "source": "ai_engine",
        "detections": payload.get("detections", []),
        "risk_score_temporal": risk_result.get("risk_score_temporal"),
        "risk_level_temporal": risk_result.get("risk_level_temporal"),
        "risk_score_weighted": risk_result.get("risk_score_weighted"),
        "risk_level_weighted": risk_result.get("risk_level_weighted"),
        "risk_score": recommended_score,
        "risk_level": risk_result.get("risk_level"),
        "reasons": risk_result.get("reasons", []),
        "metadata": {
            "input_type": payload.get("input_type", "computed"),
            "frame_id": payload.get("frame_id"),
            "video_id": payload.get("video_id"),
        },
    }

    if _compute_risk_persist_events:
        sent_to_backend, callback_message = _post_result_to_backend(result_payload)
    else:
        sent_to_backend, callback_message = (False, "disabled_for_dedupe")

    return jsonify({
        "trip_id": trip_id,
        "risk_score_temporal": risk_result.get("risk_score_temporal"),
        "risk_level_temporal": risk_result.get("risk_level_temporal"),
        "risk_score_weighted": risk_result.get("risk_score_weighted"),
        "risk_level_weighted": risk_result.get("risk_level_weighted"),
        "risk_score": recommended_score,
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
