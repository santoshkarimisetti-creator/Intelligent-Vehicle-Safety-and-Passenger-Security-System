"""
Backend Model: Driver Calibration Data

Stores personalized EAR/MAR baseline measurements for each driver.
Used by AI engine to calculate dynamic thresholds instead of using fixed values.
"""
import os
from datetime import datetime
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017/"
# Use existing database with records
DB_NAME = "ivs_db"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

# Collections
drivers_collection = db["drivers"]
calibration_collection = db["driver_calibrations"]


def get_driver_calibration(driver_id: str) -> dict:
    """Get calibration profile for a driver."""
    cal = calibration_collection.find_one({"driver_id": driver_id})
    if not cal:
        return None
    
    cal["_id"] = str(cal["_id"])
    return cal


def create_driver_calibration(driver_id: str, driver_name: str = "Unknown"):
    """Create initial calibration profile for new driver."""
    existing = calibration_collection.find_one({"driver_id": driver_id})
    if existing:
        return existing  # Already calibrated
    
    calibration = {
        "driver_id": driver_id,
        "driver_name": driver_name,
        "created_at": datetime.utcnow().isoformat(),
        "last_updated": datetime.utcnow().isoformat(),
        
        # Calibration data - collected during first 5-10 frames
        "ear_open_samples": [],      # EAR values when eyes are open (normal)
        "ear_closed_samples": [],    # EAR values when eyes are closed
        "mar_closed_samples": [],    # MAR values when mouth is closed
        "mar_open_samples": [],      # MAR values when mouth is open/yawning
        "head_straight_samples": [], # Yaw angles when looking straight
        "head_turned_samples": [],   # Yaw angles when head is turned
        
        # Thresholds (auto-calculated from samples)
        "thresholds": {
            "ear_drowsiness": 0.20,  # Default, will be personalized (FaceMesh EAR)
            "mar_yawning": 0.08,     # Default for FaceMesh MAR (lip_opening / mouth_width)
            "head_turn": 20,         # Default, will be personalized
        },
        
        # Status tracking
        "calibration_status": "PENDING",  # PENDING, IN_PROGRESS, COMPLETED
        "frames_collected": 0,
        "calibration_frames_needed": 10,
        "is_calibrated": False
    }
    
    result = calibration_collection.insert_one(calibration)
    calibration["_id"] = str(result.inserted_id)
    return calibration


def get_personalized_thresholds(driver_id: str) -> dict:
    """
    Get personalized thresholds for a driver.
    Returns default thresholds if not yet calibrated.
    """
    cal = calibration_collection.find_one({"driver_id": driver_id})
    
    defaults = {
        "ear_drowsiness": 0.20,
        "mar_yawning": 0.08,
        "head_turn": 20,
    }

    if cal and cal.get("is_calibrated"):
        thresholds = cal.get("thresholds", {}) or {}

        # Sanity-check thresholds. If calibration was collected incorrectly (wrong phases / old metric scales),
        # it can effectively disable detections. In that case, fall back to safe defaults.
        try:
            ear = float(thresholds.get("ear_drowsiness", defaults["ear_drowsiness"]))
            mar = float(thresholds.get("mar_yawning", defaults["mar_yawning"]))
            head = float(thresholds.get("head_turn", defaults["head_turn"]))
        except Exception:
            return defaults

        # Expected ranges for FaceMesh-derived metrics (keep wide enough for adaptive baselines)
        if not (0.10 <= ear <= 0.38):
            return defaults
        if not (0.04 <= mar <= 0.30):
            return defaults
        if not (10.0 <= head <= 48.0):
            return defaults

        return {
            "ear_drowsiness": ear,
            "mar_yawning": mar,
            "head_turn": head,
        }
    
    # Return defaults if not calibrated
    return defaults


def compute_and_store_thresholds(driver_id: str) -> dict:
    """
    Compute personalized thresholds from collected baseline samples.
    
    Uses statistical analysis of the calibration samples to establish driver-specific thresholds.
    - EAR threshold: mean(open_samples) * 0.5 (trigger when 50% of normal opening)
    - MAR threshold: mean(closed_samples) * 1.5 (trigger when 1.5x normal mouth opening)
    - Head turn threshold: max(head_straight_angles) + 15 degrees
    
    Returns the computed thresholds dict, or defaults if insufficient samples.
    """
    import numpy as np
    
    cal = calibration_collection.find_one({"driver_id": driver_id})
    if not cal:
        return {
            "ear_drowsiness": 0.20,
            "mar_yawning": 0.08,
            "head_turn": 20,
        }
    
    defaults = {
        "ear_drowsiness": 0.20,
        "mar_yawning": 0.08,
        "head_turn": 20,
    }
    
    try:
        # Get collected samples
        ear_open = cal.get("ear_open_samples", [])
        ear_closed = cal.get("ear_closed_samples", [])
        mar_closed = cal.get("mar_closed_samples", [])
        mar_open = cal.get("mar_open_samples", [])
        head_straight = cal.get("head_straight_samples", [])
        head_turned = cal.get("head_turned_samples", [])
        
        computed = {}
        
        # EAR threshold: 60% of normal open value (drowsiness threshold)
        # When EAR drops below this, driver is getting drowsy
        if ear_open and len(ear_open) >= 3:
            ear_open_vals = [float(x) for x in ear_open if isinstance(x, (int, float))]
            if ear_open_vals:
                ear_mean = np.mean(ear_open_vals)
                # Set threshold at ~60% of open value (more sensitive than 50%)
                computed["ear_drowsiness"] = round(max(0.15, min(0.25, ear_mean * 0.6)), 4)
        
        # MAR threshold: 2x of closed value (yawning threshold)
        # When MAR exceeds this, driver is yawning
        if mar_closed and len(mar_closed) >= 3:
            mar_closed_vals = [float(x) for x in mar_closed if isinstance(x, (int, float))]
            if mar_closed_vals:
                mar_mean = np.mean(mar_closed_vals)
                # Set threshold at 2x of closed value (more sensitive detection)
                computed["mar_yawning"] = round(min(0.15, max(0.06, mar_mean * 2.0)), 4)
        
        # Head turn threshold: max of straight + 15 degrees buffer
        if head_straight and len(head_straight) >= 3:
            head_straight_vals = [abs(float(x)) for x in head_straight if isinstance(x, (int, float))]
            if head_straight_vals:
                head_max = np.max(head_straight_vals)
                # Add 15 degree buffer
                computed["head_turn"] = round(min(45.0, head_max + 15), 1)
        
        # Use computed values if available, otherwise use defaults
        thresholds = {
            "ear_drowsiness": computed.get("ear_drowsiness", defaults["ear_drowsiness"]),
            "mar_yawning": computed.get("mar_yawning", defaults["mar_yawning"]),
            "head_turn": computed.get("head_turn", defaults["head_turn"]),
        }
        
        # Store computed thresholds and mark as calibrated
        calibration_collection.update_one(
            {"driver_id": driver_id},
            {
                "$set": {
                    "thresholds": thresholds,
                    "is_calibrated": True,
                    "calibration_status": "COMPLETED",
                    "last_updated": datetime.utcnow().isoformat()
                }
            }
        )
        
        print(f"✓ Computed thresholds for {driver_id}: EAR={thresholds['ear_drowsiness']}, MAR={thresholds['mar_yawning']}, Head={thresholds['head_turn']}")
        return thresholds
        
    except Exception as e:
        print(f"Error computing thresholds for {driver_id}: {e}")
        return defaults
