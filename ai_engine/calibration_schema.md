"""
Personalized EAR/MAR Calibration System for per-person adaptive detection
"""

# Database Schema for drivers_calibration_collection
CALIBRATION_SCHEMA = {
    "_id": "ObjectId",
    "driver_id": "str",
    "calibration_status": "PENDING | IN_PROGRESS | COMPLETED",
    "created_at": "datetime",
    "last_updated": "datetime",
    
    # Baseline measurements (in neutral/alert state)
    "baseline": {
        "ear_open": 0.32,        # Average EAR when eyes fully open
        "ear_closed": 0.12,      # Average EAR when eyes closed (baseline for drowsiness)
        "mar_closed": 0.25,      # Average MAR when mouth closed (normal)
        "mar_yawning": 0.75,     # Average MAR when yawning widely
        "head_forward": 0.0,     # Head yaw angle when looking forward
        "frames_collected": 150  # Number of calibration frames used
    },
    
    # Calculated thresholds (derived from baseline)
    "thresholds": {
        "drowsiness_ear": 0.18,               # 0.3 * (ear_open - ear_closed) + ear_closed
        "alert_ear": 0.28,                    # 0.9 * ear_open
        "yawning_mar": 0.60,                  # 0.8 * mar_yawning
        "distraction_head_turn": 22,          # degrees
        "eyes_detection_confidence_min": 0.6  # Minimum confidence for detection
    },
    
    # Personalization factors
    "factors": {
        "eye_shape": "almond | round | hooded | other",  # Facial characteristic
        "mouth_size": "small | medium | large",
        "face_width": "narrow | medium | wide",
        "sensitivity": 1.0  # User can adjust sensitivity 0.5-1.5x
    },
    
    # Session history
    "calibration_sessions": [
        {
            "session_id": "str",
            "timestamp": "datetime",
            "frames_processed": 150,
            "avg_ear_open": 0.32,
            "avg_ear_closed": 0.12,
            "avg_mar_closed": 0.25,
            "avg_mar_yawning": 0.75,
            "status": "COMPLETED"
        }
    ]
}

# Detection thresholds will be PERSONALIZED instead of global:
# OLD (fixed for everyone):
# EYE_AR_THRESH = 0.25
# MOUTH_AR_THRESH = 0.6

# NEW (per-person):
# drowsiness_threshold = baseline.ear_closed + (baseline.ear_open - baseline.ear_closed) * 0.3
# yawning_threshold = baseline.mar_closed + (baseline.mar_yawning - baseline.mar_closed) * 0.8
