"""
Check detections stored in events_collection (for trips without active status)
"""
from pymongo import MongoClient

# Connect to MongoDB
client = MongoClient("mongodb://localhost:27017/")
db = client["ivs_db"]
events = db["events_collection"]

# Query recent events sorted by timestamp
recent_events = list(events.find().sort("timestamp", -1).limit(10))

print("\n=== Recent Events in events_collection ===\n")
print(f"Total events: {events.count_documents({})}\n")

if recent_events:
    for idx, event in enumerate(recent_events, 1):
        print(f"{idx}. Event ID: {event.get('_id')}")
        print(f"   Trip ID: {event.get('trip_id', 'N/A')}")
        print(f"   Timestamp: {event.get('timestamp', 'N/A')}")
        print(f"   Risk Level: {event.get('risk_level', 'N/A')}")
        print(f"   Is SOS: {event.get('is_sos', False)}")
        
        detections = event.get('detections', [])
        if detections:
            print(f"   Detections:")
            for det in detections:
                print(f"     - {det.get('type')}: {det.get('confidence', 0)*100:.0f}% confidence")
        
        reasons = event.get('reasons', [])
        if reasons:
            print(f"   Reasons: {', '.join(reasons)}")
        
        print()
else:
    print("No events found in database.")
    print("\nTroubleshooting:")
    print("1. Make sure AI engine is running on port 3001")
    print("2. Check backend is running on port 5000")
    print("3. Open Live Monitoring page and allow camera")
    print("4. Make sure you see 🤖 AI: Active indicator")
    print("5. Yawn WIDELY for 2-3 seconds")
    print("6. Wait 2-3 seconds for detection cycle")

client.close()
