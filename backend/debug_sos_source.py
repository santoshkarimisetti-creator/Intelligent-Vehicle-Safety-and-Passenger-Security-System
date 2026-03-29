"""
Debug script to check SOS event details including source
"""
from pymongo import MongoClient
from pprint import pprint

MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client["ivs_db"]
trips_collection = db["trips"]

print("=" * 80)
print("SOS Event Details in Database")
print("=" * 80)

# Get trips with sos_triggered = True
sos_trips = list(trips_collection.find({"sos_triggered": True}))

for trip in sos_trips:
    print(f"\n💾 Trip ID: {trip.get('trip_id')}")
    print(f"   Driver ID: {trip.get('driver_id')}")
    print(f"   Status: {trip.get('status')}")
    print(f"   SOS Events: {len(trip.get('sos_events', []))}")
    
    sos_events = trip.get('sos_events', [])
    if sos_events:
        print(f"\n   SOS Event Details:")
        for i, event in enumerate(sos_events, 1):
            print(f"     Event {i}:")
            print(f"       - Source: {event.get('source', 'NOT SET')}")
            print(f"       - Type: {event.get('event_type')}")
            print(f"       - Timestamp: {event.get('timestamp')}")
            print(f"       - Duration: {event.get('duration')}")
            if event.get('metadata'):
                print(f"       - Metadata: {event.get('metadata')}")

print("\n" + "=" * 80)
client.close()
