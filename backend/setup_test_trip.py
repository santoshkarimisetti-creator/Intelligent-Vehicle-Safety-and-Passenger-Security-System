"""
Test AI Engine Detection and Database Storage
This script creates an active trip for testing AI detections
"""
from pymongo import MongoClient
from datetime import datetime
import uuid

MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client["ivs_db"]
trips_collection = db["trips"]

print("=" * 60)
print("Creating Test Trip for AI Detection")
print("=" * 60)

# Create active test trip
trip_id = "test-ai-detection"
start_time = datetime.utcnow()

# Check if trip already exists
existing = trips_collection.find_one({"trip_id": trip_id})
if existing:
    print(f"\nTrip '{trip_id}' already exists")
    if existing.get("status") != "ACTIVE":
        # Reactivate it
        trips_collection.update_one(
            {"trip_id": trip_id},
            {"$set": {"status": "ACTIVE", "start_time": start_time}}
        )
        print("✓ Reactivated existing trip")
    else:
        print("✓ Trip is already active")
else:
    # Create new trip
    new_trip = {
        "trip_id": trip_id,
        "driver_id": "TEST_DRIVER",
        "status": "ACTIVE",
        "start_time": start_time,
        "risk_level": "SAFE",
        "ai_events": [],
        "sos_events": [],
        "path": [],
        "sensor_data": [],
        "sos_triggered": False
    }
    trips_collection.insert_one(new_trip)
    print(f"✓ Created new active trip: {trip_id}")

print("\n" + "=" * 60)
print("Setup Complete!")
print("=" * 60)
print(f"\nTrip ID: {trip_id}")
print("Status: ACTIVE")
print("\nNext Steps:")
print("1. Update LiveMonitoring.jsx to use trip_id: 'test-ai-detection'")
print("2. Start AI engine: cd ai_engine && python app.py")
print("3. Start frontend: cd frontend && npm run dev")
print("4. Yawn in front of camera and check for detections")
print("5. Run check_ai_detections.py to see stored events")
print("=" * 60)

client.close()
