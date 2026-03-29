from pymongo import MongoClient
from datetime import datetime, timedelta

# MongoDB Connection
client = MongoClient("mongodb://localhost:27017/")
db = client["ivs_db"]
trips_collection = db["trips"]
events_collection = db["events"]

# Don't clear existing data - just add new test data
now = datetime.now()

# Insert sample trips with events
trips_data = [
    {
        "trip_id": "TRIP001",
        "driver_id": "DRIVER123",
        "start_time": (now - timedelta(hours=2)).isoformat(),
        "end_time": (now - timedelta(hours=1)).isoformat(),
        "status": "COMPLETED",
        "max_speed": 85.5,
        "risk_level": "HIGH",
        "distance_km": 45.3,
        "path": [
            {"lat": 28.6139, "lon": 77.2090, "timestamp": (now - timedelta(hours=2)).isoformat()},
            {"lat": 28.6200, "lon": 77.2150, "timestamp": (now - timedelta(hours=1, minutes=30)).isoformat()},
        ],
        "ai_events": [
            {
                "timestamp": (now - timedelta(hours=1, minutes=45)).isoformat(),
                "event_type": "DROWSINESS_DETECTED",
                "risk_level": "HIGH",
                "risk_score_weighted": 68.5,
                "detections": {"drowsiness_detected": True, "eye_closure_duration": 3.2}
            },
            {
                "timestamp": (now - timedelta(hours=1, minutes=30)).isoformat(),
                "event_type": "YAWNING_DETECTED",
                "risk_level": "MODERATE",
                "risk_score_weighted": 42.0,
                "detections": {"yawning_detected": True, "yawn_count": 3}
            }
        ],
        "sos_triggered": True,
        "sos_events": [
            {
                "timestamp": (now - timedelta(hours=1, minutes=20)).isoformat(),
                "location": {"latitude": 28.6200, "longitude": 77.2150},
                "message": "Emergency SOS triggered by driver"
            }
        ]
    },
    {
        "trip_id": "TRIP002",
        "driver_id": "DRIVER456",
        "start_time": (now - timedelta(hours=5)).isoformat(),
        "end_time": (now - timedelta(hours=3)).isoformat(),
        "status": "COMPLETED",
        "max_speed": 72.0,
        "risk_level": "MODERATE",
        "distance_km": 32.7,
        "path": [
            {"lat": 28.7041, "lon": 77.1025, "timestamp": (now - timedelta(hours=5)).isoformat()},
            {"lat": 28.7100, "lon": 77.1100, "timestamp": (now - timedelta(hours=4)).isoformat()},
        ],
        "ai_events": [
            {
                "timestamp": (now - timedelta(hours=4, minutes=15)).isoformat(),
                "event_type": "DISTRACTION_DETECTED",
                "risk_level": "MODERATE",
                "risk_score_weighted": 45.2,
                "detections": {"looking_away": True, "looking_away_duration": 5.1}
            }
        ],
        "sos_triggered": False
    },
    {
        "trip_id": "TRIP003",
        "driver_id": "DRIVER789",
        "start_time": now.isoformat(),
        "status": "ACTIVE",
        "max_speed": 55.0,
        "risk_level": "SAFE",
        "distance_km": 12.5,
        "path": [
            {"lat": 28.5355, "lon": 77.3910, "timestamp": now.isoformat()},
        ],
        "ai_events": [],
        "sos_triggered": False
    }
]

trips_collection.insert_many(trips_data)

# Insert standalone events (no active trip)
events_data = [
    {
        "trip_id": "NO_ACTIVE_TRIP",
        "timestamp": (now - timedelta(minutes=30)).isoformat(),
        "event_type": "DROWSINESS_DETECTED",
        "risk_level": "HIGH",
        "risk_score_weighted": 72.0,
        "risk_score_temporal": 65.0,
        "detections": {"drowsiness_detected": True, "eye_closure_duration": 4.5},
        "location": {"latitude": 28.6139, "longitude": 77.2090},
        "is_sos": False
    },
    {
        "trip_id": "NO_ACTIVE_TRIP",
        "timestamp": (now - timedelta(minutes=15)).isoformat(),
        "event_type": "YAWNING_DETECTED",
        "risk_level": "MODERATE",
        "risk_score_weighted": 38.5,
        "risk_score_temporal": 32.0,
        "detections": {"yawning_detected": True, "yawn_count": 2},
        "location": {"latitude": 28.6200, "longitude": 77.2150},
        "is_sos": False
    },
    {
        "trip_id": "NO_ACTIVE_TRIP",
        "timestamp": (now - timedelta(minutes=5)).isoformat(),
        "event_type": "SOS_EMERGENCY",
        "risk_level": "CRITICAL",
        "risk_score_weighted": 95.0,
        "detections": {"sos_triggered": True},
        "location": {"latitude": 28.7041, "longitude": 77.1025},
        "is_sos": True,
        "message": "Driver triggered SOS - Immediate assistance required"
    },
    {
        "trip_id": "NO_ACTIVE_TRIP",
        "timestamp": (now - timedelta(hours=1)).isoformat(),
        "event_type": "DISTRACTION_DETECTED",
        "risk_level": "MODERATE",
        "risk_score_weighted": 41.0,
        "detections": {"looking_away": True, "looking_away_duration": 6.0},
        "location": {"latitude": 28.5355, "longitude": 77.3910},
        "is_sos": False
    }
]

events_collection.insert_many(events_data)

print(f"✅ Inserted {len(trips_data)} trips")
print(f"✅ Inserted {len(events_data)} standalone events")
print("Database populated successfully!")
