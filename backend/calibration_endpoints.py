"""
Backend calibration endpoints for personalized EAR/MAR detection
Add these endpoints to backend/app.py
"""

from datetime import datetime
from pymongo import MongoClient
import uuid

# Initialize MongoDB collection for calibrations
client = MongoClient("mongodb://localhost:27017/")
db = client["ivs_db"]
calibration_collection = db["drivers_calibration"]

# Create index
calibration_collection.create_index("driver_id", unique=False)


# ============================================================================
# CALIBRATION ENDPOINTS
# ============================================================================

@app.post("/drivers/<driver_id>/calibrate/start")
def start_calibration(driver_id: str):
    """
    Start calibration process for a driver.
    Returns session_id to use for frame submissions.
    """
    try:
        session_id = str(uuid.uuid4())
        
        # Check if calibration exists
        existing = calibration_collection.find_one({"driver_id": driver_id})
        
        if existing:
            # Update status
            calibration_collection.update_one(
                {"driver_id": driver_id},
                {
                    "$set": {
                        "calibration_status": "IN_PROGRESS",
                        "current_session_id": session_id,
                        "last_updated": datetime.utcnow()
                    }
                }
            )
        else:
            # Create new calibration document
            calibration_collection.insert_one({
                "driver_id": driver_id,
                "calibration_status": "IN_PROGRESS",
                "created_at": datetime.utcnow(),
                "last_updated": datetime.utcnow(),
                "current_session_id": session_id,
                "baseline": {},
                "thresholds": {},
                "factors": {
                    "sensitivity": 1.0
                },
                "calibration_sessions": []
            })
        
        return jsonify({
            "session_id": session_id,
            "driver_id": driver_id,
            "message": "Calibration started. Follow instructions on screen.",
            "instructions": [
                "Look straight ahead with neutral face for 30 frames",
                "Keep eyes open naturally",
                "Then yawn 3-4 times widely",
                "Move head side-to-side slowly"
            ]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/drivers/<driver_id>/calibrate/frame")
def submit_calibration_frame(driver_id: str):
    """
    Submit a frame during calibration with computed EAR/MAR metrics.
    Expected payload:
    {
        "session_id": "str",
        "ear": float,
        "mar": float,
        "yaw_angle": float,
        "phase": "neutral | yawning | head_turn",
        "face_detected": bool
    }
    """
    try:
        payload = request.get_json(silent=True) or {}
        session_id = payload.get("session_id")
        ear = payload.get("ear", 0.0)
        mar = payload.get("mar", 0.0)
        yaw_angle = payload.get("yaw_angle", 0.0)
        phase = payload.get("phase", "neutral")
        face_detected = payload.get("face_detected", False)
        
        if not face_detected:
            return jsonify({"error": "Face not detected. Try again."}), 400
        
        # Get current calibration
        calib = calibration_collection.find_one({"driver_id": driver_id})
        if not calib:
            return jsonify({"error": "Calibration not started"}), 404
        
        # Initialize collections if needed
        if "frames_by_phase" not in calib:
            calib["frames_by_phase"] = {
                "neutral": [],
                "yawning": [],
                "head_turn": []
            }
        
        # Store frame data
        calib["frames_by_phase"][phase].append({
            "ear": ear,
            "mar": mar,
            "yaw_angle": yaw_angle,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Update in DB
        calibration_collection.update_one(
            {"driver_id": driver_id},
            {
                "$set": {
                    "frames_by_phase": calib.get("frames_by_phase", {}),
                    "last_updated": datetime.utcnow()
                }
            }
        )
        
        frames_collected = sum(len(f) for f in calib.get("frames_by_phase", {}).values())
        
        return jsonify({
            "status": "frame_received",
            "phase": phase,
            "frames_in_phase": len(calib["frames_by_phase"].get(phase, [])),
            "total_frames": frames_collected,
            "progress": f"{frames_collected}/150"
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/drivers/<driver_id>/calibrate/complete")
def complete_calibration(driver_id: str):
    """
    Complete calibration and calculate personalized thresholds.
    Analyzes all collected frames and computes adaptive thresholds.
    """
    try:
        calib = calibration_collection.find_one({"driver_id": driver_id})
        if not calib:
            return jsonify({"error": "Calibration not found"}), 404
        
        frames = calib.get("frames_by_phase", {})
        
        # Validate sufficient data
        if (len(frames.get("neutral", [])) < 30 or 
            len(frames.get("yawning", [])) < 20 or
            len(frames.get("head_turn", [])) < 20):
            return jsonify({
                "error": "Insufficient frames",
                "required": {"neutral": 30, "yawning": 20, "head_turn": 20},
                "collected": {
                    "neutral": len(frames.get("neutral", [])),
                    "yawning": len(frames.get("yawning", [])),
                    "head_turn": len(frames.get("head_turn", []))
                }
            }), 400
        
        # Calculate baseline from neutral phase
        neutral_ears = [f["ear"] for f in frames.get("neutral", [])]
        neutral_mars = [f["mar"] for f in frames.get("neutral", [])]
        
        # Calculate yawning baseline
        yawning_mars = [f["mar"] for f in frames.get("yawning", [])]
        
        # Calculate averages
        baseline = {
            "ear_open": round(sum(neutral_ears) / len(neutral_ears), 3),
            "ear_closed": round(sum(neutral_ears) / len(neutral_ears) * 0.4, 3),  # ~40% of open
            "mar_closed": round(sum(neutral_mars) / len(neutral_mars), 3),
            "mar_yawning": round(sum(yawning_mars) / len(yawning_mars), 3),
            "frames_collected": sum(len(f) for f in frames.values())
        }
        
        # Calculate personalized thresholds
        ear_range = baseline["ear_open"] - baseline["ear_closed"]
        mar_range = baseline["mar_yawning"] - baseline["mar_closed"]
        
        thresholds = {
            "drowsiness_ear": round(baseline["ear_closed"] + ear_range * 0.35, 3),
            "alert_ear": round(baseline["ear_open"] * 0.85, 3),
            "yawning_mar": round(baseline["mar_closed"] + mar_range * 0.75, 3),
            "distraction_head_turn": 25,
            "eyes_detection_confidence_min": 0.6
        }
        
        # Save session history
        session_data = {
            "session_id": calib.get("current_session_id"),
            "timestamp": datetime.utcnow().isoformat(),
            "frames_processed": baseline["frames_collected"],
            "baseline": baseline,
            "status": "COMPLETED"
        }
        
        # Update calibration document
        calibration_collection.update_one(
            {"driver_id": driver_id},
            {
                "$set": {
                    "calibration_status": "COMPLETED",
                    "baseline": baseline,
                    "thresholds": thresholds,
                    "last_updated": datetime.utcnow()
                },
                "$push": {
                    "calibration_sessions": session_data
                }
            }
        )
        
        return jsonify({
            "status": "COMPLETED",
            "message": "Calibration complete!",
            "baseline": baseline,
            "thresholds": thresholds,
            "calibration_data": {
                "frames_collected": baseline["frames_collected"],
                "ear_range": round(ear_range, 3),
                "mar_range": round(mar_range, 3)
            }
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/drivers/<driver_id>/calibration")
def get_calibration(driver_id: str):
    """Get driver's calibration data and thresholds."""
    try:
        calib = calibration_collection.find_one({"driver_id": driver_id})
        
        if not calib:
            return jsonify({
                "calibration_status": "NOT_CALIBRATED",
                "driver_id": driver_id,
                "message": "No calibration found. Start calibration first."
            }), 200
        
        calib["_id"] = str(calib["_id"])
        
        return jsonify({
            "calibration_status": calib.get("calibration_status"),
            "driver_id": driver_id,
            "baseline": calib.get("baseline", {}),
            "thresholds": calib.get("thresholds", {}),
            "factors": calib.get("factors", {}),
            "created_at": calib.get("created_at"),
            "last_updated": calib.get("last_updated")
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.put("/drivers/<driver_id>/calibration/sensitivity")
def update_calibration_sensitivity(driver_id: str):
    """
    Adjust sensitivity multiplier (0.5 to 1.5).
    Lower = more sensitive, Higher = less sensitive
    """
    try:
        payload = request.get_json(silent=True) or {}
        sensitivity = payload.get("sensitivity", 1.0)
        
        # Validate
        if not (0.5 <= sensitivity <= 1.5):
            return jsonify({"error": "Sensitivity must be between 0.5 and 1.5"}), 400
        
        calib = calibration_collection.find_one({"driver_id": driver_id})
        if not calib:
            return jsonify({"error": "Calibration not found"}), 404
        
        # Apply sensitivity multiplier to thresholds
        thresholds = calib.get("thresholds", {})
        adjusted_thresholds = {
            "drowsiness_ear": round(thresholds.get("drowsiness_ear", 0.18) / sensitivity, 3),
            "alert_ear": round(thresholds.get("alert_ear", 0.28) / sensitivity, 3),
            "yawning_mar": round(thresholds.get("yawning_mar", 0.60) * sensitivity, 3),
            "distraction_head_turn": thresholds.get("distraction_head_turn", 25),
        }
        
        calibration_collection.update_one(
            {"driver_id": driver_id},
            {
                "$set": {
                    "factors.sensitivity": sensitivity,
                    "thresholds": adjusted_thresholds,
                    "last_updated": datetime.utcnow()
                }
            }
        )
        
        return jsonify({
            "driver_id": driver_id,
            "sensitivity": sensitivity,
            "adjusted_thresholds": adjusted_thresholds,
            "message": f"Sensitivity updated to {sensitivity}x"
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
