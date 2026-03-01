"""
Backend Model: Driver Calibration Data

Stores personalized EAR/MAR baseline measurements for each driver.
Used by AI engine to calculate dynamic thresholds instead of using fixed values.
"""
from datetime import datetime
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017/"
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
        
        # Calculated thresholds (auto-calculated from samples)
        "thresholds": {
            "ear_drowsiness": 0.25,  # Default, will be personalized
            "mar_yawning": 0.6,      # Default, will be personalized
            "head_turn": 25,         # Default, will be personalized
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


def update_calibration_samples(driver_id: str, frame_metrics: dict):
    """
    Add frame metrics to calibration samples.
    Used during auto-calibration phase (first 10-20 frames).
    """
    cal = calibration_collection.find_one({"driver_id": driver_id})
    if not cal:
        cal = create_driver_calibration(driver_id)
    
    if cal.get("is_calibrated"):
        return  # Don't collect more samples if already calibrated
    
    ear = frame_metrics.get("ear", 0.0)
    mar = frame_metrics.get("mar", 0.0)
    yaw = frame_metrics.get("yaw_angle", 0.0)
    
    # Collect samples with context (user action hints from confidence)
    updates = {
        "last_updated": datetime.utcnow().isoformat(),
        "frames_collected": cal.get("frames_collected", 0) + 1
    }
    
    # Default: assume eyes open, mouth closed, looking straight
    # This will be refined with ML/UI feedback later
    updates_dict = {"$push": {}}
    
    if ear > 0.25:  # Likely eyes open
        updates_dict["$push"]["ear_open_samples"] = ear
    else:  # Likely eyes closed
        updates_dict["$push"]["ear_closed_samples"] = ear
    
    if mar < 0.5:  # Likely mouth closed
        updates_dict["$push"]["mar_closed_samples"] = mar
    else:  # Likely mouth open
        updates_dict["$push"]["mar_open_samples"] = mar
    
    if abs(yaw) < 15:  # Likely looking straight
        updates_dict["$push"]["head_straight_samples"] = yaw
    else:  # Likely head turned
        updates_dict["$push"]["head_turned_samples"] = yaw
    
    updates_dict.update(updates)
    
    calibration_collection.update_one(
        {"driver_id": driver_id},
        updates_dict
    )
    
    # Check if calibration is complete
    if updates.get("frames_collected", 0) >= cal.get("calibration_frames_needed", 10):
        finalize_calibration(driver_id)


def finalize_calibration(driver_id: str):
    """Calculate personalized thresholds from collected samples."""
    cal = calibration_collection.find_one({"driver_id": driver_id})
    if not cal:
        return
    
    import numpy as np
    
    # Calculate personalized thresholds from samples
    thresholds = {"ear_drowsiness": 0.25, "mar_yawning": 0.6, "head_turn": 25}
    
    # EAR threshold: midpoint between open and closed eyes
    ear_open = cal.get("ear_open_samples", [])
    ear_closed = cal.get("ear_closed_samples", [])
    
    if ear_open and ear_closed:
        open_mean = np.mean(ear_open)
        closed_mean = np.mean(ear_closed)
        thresholds["ear_drowsiness"] = (open_mean + closed_mean) / 2
    
    # MAR threshold: midpoint between closed and open mouth
    mar_closed = cal.get("mar_closed_samples", [])
    mar_open = cal.get("mar_open_samples", [])
    
    if mar_closed and mar_open:
        closed_mean = np.mean(mar_closed)
        open_mean = np.mean(mar_open)
        thresholds["mar_yawning"] = (closed_mean + open_mean) / 2
    
    # Head turn threshold: based on straight samples
    head_straight = cal.get("head_straight_samples", [])
    if head_straight:
        straight_std = np.std(head_straight)
        # Threshold is mean + 1.5*std (allows movement but detects excessive turning)
        thresholds["head_turn"] = np.mean(head_straight) + 1.5 * straight_std
    
    # Update calibration
    calibration_collection.update_one(
        {"driver_id": driver_id},
        {
            "$set": {
                "thresholds": thresholds,
                "calibration_status": "COMPLETED",
                "is_calibrated": True,
                "last_updated": datetime.utcnow().isoformat()
            }
        }
    )


def get_personalized_thresholds(driver_id: str) -> dict:
    """
    Get personalized thresholds for a driver.
    Returns default thresholds if not yet calibrated.
    """
    cal = calibration_collection.find_one({"driver_id": driver_id})
    
    if cal and cal.get("is_calibrated"):
        return cal.get("thresholds", {})
    
    # Return defaults if not calibrated
    return {
        "ear_drowsiness": 0.25,
        "mar_yawning": 0.6,
        "head_turn": 25
    }
