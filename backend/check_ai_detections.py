"""
Check AI Detection Results in Database
"""
from pymongo import MongoClient
from pprint import pprint

MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client["ivs_db"]
trips_collection = db["trips"]
events_collection = db["events"]

print("=" * 80)
print("AI Detection Results")
print("=" * 80)

# Check test trip
trip = trips_collection.find_one({"trip_id": "test-ai-detection"})
if trip:
    print(f"\n📊 Trip: test-ai-detection")
    print(f"   Status: {trip.get('status')}")
    print(f"   Risk Level: {trip.get('risk_level', 'N/A')}")
    print(f"   AI Events: {len(trip.get('ai_events', []))}")
    
    if trip.get('ai_events'):
        print("\n   Latest AI Detections:")
        for i, event in enumerate(trip['ai_events'][-5:], 1):  # Show last 5
            print(f"\n   Event {i}:")
            print(f"      Timestamp: {event.get('timestamp')}")
            print(f"      Risk Level: {event.get('risk_level', 'N/A')}")
            print(f"      Detections: {event.get('detections', [])}")
            if event.get('reasons'):
                print(f"      Reasons: {event.get('reasons')}")
    else:
        print("\n   ⚠️  No AI events detected yet")
        print("      Make sure:")
        print("      - AI engine is running (port 3001)")
        print("      - Frontend is connected")
        print("      - Camera is active and facing you")
else:
    print("\n⚠️  Test trip not found. Run setup_test_trip.py first")

# Check events collection for non-trip detections
print("\n" + "=" * 80)
print("Background Events (no active trip)")
print("=" * 80)

bg_events = list(events_collection.find({"is_sos": False}).sort("timestamp", -1).limit(5))
if bg_events:
    print(f"\nFound {len(bg_events)} background detection events:")
    for i, event in enumerate(bg_events, 1):
        print(f"\n   Event {i}:")
        print(f"      Timestamp: {event.get('timestamp')}")
        print(f"      Risk Level: {event.get('risk_level', 'N/A')}")
        print(f"      Event Type: {event.get('event_type', 'N/A')}")
else:
    print("\nNo background events found")

print("\n" + "=" * 80)
client.close()
