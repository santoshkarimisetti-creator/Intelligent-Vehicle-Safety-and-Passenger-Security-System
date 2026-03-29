"""
AI Engine updates to use personalized EAR/MAR calibration
Integrate this into ai_engine/app.py
"""

import os
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# Global cache for driver calibrations
_calibration_cache = {}

# Default thresholds (fallback when no calibration exists)
DEFAULT_THRESHOLDS = {
    "drowsiness_ear": 0.18,
    "alert_ear": 0.28,
    "yawning_mar": 0.60,
    "distraction_head_turn": 25,
    "eyes_detection_confidence_min": 0.6
}

# Update global thresholds to use defaults
EYE_AR_THRESH = DEFAULT_THRESHOLDS["drowsiness_ear"]
MOUTH_AR_THRESH = DEFAULT_THRESHOLDS["yawning_mar"]
HEAD_TURN_THRESH = DEFAULT_THRESHOLDS["distraction_head_turn"]


def _fetch_driver_calibration(driver_id: str) -> Dict[str, Any]:
    """
    Fetch driver's calibration from backend.
    Caches result for 1 hour to reduce overhead.
    Falls back to DEFAULT_THRESHOLDS if not calibrated.
    """
    # Check cache first
    if driver_id in _calibration_cache:
        cached_data, cached_time = _calibration_cache[driver_id]
        if time.time() - cached_time < 3600:  # 1 hour cache
            return cached_data
    
    try:
        # Request calibration from backend
        url = f"{BACKEND_BASE_URL.rstrip('/')}/drivers/{driver_id}/calibration"
        with urlopen(url, timeout=2) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        calibration_status = data.get("calibration_status", "NOT_CALIBRATED")
        
        if calibration_status == "COMPLETED":
            thresholds = data.get("thresholds", DEFAULT_THRESHOLDS)
            baseline = data.get("baseline", {})
            
            result = {
                "status": "CALIBRATED",
                "thresholds": thresholds,
                "baseline": baseline,
                "source": "backend"
            }
        else:
            result = {
                "status": "NOT_CALIBRATED",
                "thresholds": DEFAULT_THRESHOLDS,
                "baseline": {},
                "source": "default"
            }
        
        # Cache the result
        _calibration_cache[driver_id] = (result, time.time())
        return result
        
    except Exception as e:
        print(f"Warning: Could not fetch calibration for {driver_id}: {e}")
        return {
            "status": "ERROR",
            "thresholds": DEFAULT_THRESHOLDS,
            "baseline": {},
            "source": "default_fallback",
            "error": str(e)
        }


def _get_detection_thresholds(driver_id: str) -> Dict[str, float]:
    """
    Get personalized thresholds for a driver.
    Returns calibrated thresholds if available, else defaults.
    """
    calibration = _fetch_driver_calibration(driver_id)
    thresholds = calibration.get("thresholds", DEFAULT_THRESHOLDS)
    
    # Log calibration status
    status = calibration.get("source", "unknown")
    if status != "default" and status != "default_fallback":
        print(f"[{driver_id}] Using personalized thresholds from {calibration['source']}")
    
    return thresholds


def _detect_from_opencv_metrics_adaptive(
    metrics: Dict[str, Any],
    driver_id: str = None
) -> Dict[str, Any]:
    """
    Detect drowsiness, yawning, and looking away using PERSONALIZED thresholds.
    
    If driver_id provided, uses their calibrated thresholds.
    Otherwise uses global DEFAULT_THRESHOLDS.
    
    Args:
        metrics: {ear, mar, yaw_angle, face_detected, ...}
        driver_id: Optional driver ID for personalized thresholds
    
    Returns:
        {detections, metrics, message}
    """
    ear = metrics.get("ear", 0.0)
    mar = metrics.get("mar", 0.0)
    yaw_angle = abs(metrics.get("yaw_angle", 0.0))
    face_detected = metrics.get("face_detected", False)
    
    # Get personalized thresholds
    if driver_id:
        thresholds = _get_detection_thresholds(driver_id)
    else:
        thresholds = DEFAULT_THRESHOLDS
    
    ear_threshold = thresholds.get("drowsiness_ear", 0.18)
    mar_threshold = thresholds.get("yawning_mar", 0.60)
    yaw_threshold = thresholds.get("distraction_head_turn", 25)
    
    detections = []
    
    if not face_detected:
        return {
            "detections": [],
            "metrics": metrics,
            "message": "No face detected",
            "thresholds_used": {
                "source": "driver_id" if driver_id else "default",
                "ear_threshold": ear_threshold,
                "mar_threshold": mar_threshold,
                "yaw_threshold": yaw_threshold
            }
        }
    
    # DROWSINESS DETECTION (low EAR - eyes closing)
    if ear < ear_threshold:
        # Confidence: lower EAR = higher confidence of drowsiness
        confidence = 1.0 - (ear / ear_threshold)
        detections.append({
            "type": "drowsiness",
            "confidence": round(min(1.0, confidence), 3),
            "source": "opencv_haar",
            "metric": "ear",
            "value": round(ear, 3),
            "threshold": round(ear_threshold, 3),
            "personalized": driver_id is not None
        })
    
    # YAWNING DETECTION (high MAR - mouth open wide)
    if mar > mar_threshold:
        # Confidence: higher MAR above threshold = higher confidence
        confidence = (mar - mar_threshold) / 0.4
        detections.append({
            "type": "yawning",
            "confidence": round(min(1.0, confidence), 3),
            "source": "opencv_haar",
            "metric": "mar",
            "value": round(mar, 3),
            "threshold": round(mar_threshold, 3),
            "personalized": driver_id is not None
        })
    
    # DISTRACTION DETECTION (high yaw angle - head turned)
    if yaw_angle > yaw_threshold:
        # Confidence: larger angle = higher confidence
        confidence = (yaw_angle - yaw_threshold) / 20
        detections.append({
            "type": "distraction",
            "confidence": round(min(1.0, confidence), 3),
            "source": "opencv_haar",
            "metric": "yaw_angle",
            "value": round(yaw_angle, 2),
            "threshold": round(yaw_threshold, 2),
            "personalized": driver_id is not None
        })
    
    return {
        "detections": detections,
        "metrics": metrics,
        "thresholds_used": {
            "source": "driver_calibration" if driver_id else "default_global",
            "ear_threshold": round(ear_threshold, 3),
            "mar_threshold": round(mar_threshold, 3),
            "yaw_threshold": round(yaw_threshold, 2),
            "driver_id": driver_id
        }
    }


# ============================================================================
# UPDATE ANALYZE_FRAME ENDPOINT
# ============================================================================

# In the analyze_frame() function, change:
# OLD: detection_result = _detect_from_opencv_metrics(cv_metrics)
# NEW:
def analyze_frame_updated() -> Any:
    """Updated analyze_frame with personalized thresholds"""
    payload = request.get_json(silent=True) or {}
    trip_id = payload.get("trip_id")
    driver_id = payload.get("driver_id")  # NEW: Accept driver_id
    
    detection_result = _compute_detection(payload)
    
    # Get image metrics
    image_data = payload.get("image") or payload.get("frame")
    if image_data:
        image = _decode_image(image_data)
        if image is not None:
            cv_metrics = _process_frame_with_opencv(image)
            
            # Use PERSONALIZED detection with driver_id
            detection_result = _detect_from_opencv_metrics_adaptive(cv_metrics, driver_id)
            
            # Rest of the function remains the same...
    
    return detection_result
