"""Check recent AI detections in events_collection"""
from pymongo import MongoClient
from datetime import datetime, timedelta

client = MongoClient("mongodb://localhost:27017/")
db = client["ivs_db"]
events = db["events_collection"]

# Get events from last 5 minutes
cutoff = datetime.utcnow() - timedelta(minutes=5)
recent = list(events.find({"timestamp": {"$gte": cutoff.isoformat()}}).sort("timestamp", -1).limit(10))

print(f"\n=== Detections in Last 5 Minutes ===\n")
print(f"Total events: {len(recent)}\n")

if recent:
    for i, event in enumerate(recent, 1):
        print(f"{i}. {event.get('timestamp', 'N/A')}")
        print(f"   Risk: {event.get('risk_level', 'N/A')}")
        detections = event.get('detections', [])
        for d in detections:
            print(f"   - {d['type']}: {d.get('confidence', 0)*100:.0f}%")
        print()
else:
    print("No recent detections. Try yawning widely!")

client.close()
