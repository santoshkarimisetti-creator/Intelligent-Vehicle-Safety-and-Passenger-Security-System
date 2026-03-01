"""
Debug script to check SOS-triggered trips in the database
"""
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client["ivs_db"]
trips_collection = db["trips"]

print("=" * 60)
print("Checking SOS-triggered trips in database...")
print("=" * 60)

# Count trips with sos_triggered = True
sos_trip_count = trips_collection.count_documents({"sos_triggered": True})
print(f"\nTotal trips with SOS triggered: {sos_trip_count}")

if sos_trip_count > 0:
    # Show first 5 SOS trips
    sos_trips = list(trips_collection.find({"sos_triggered": True}).limit(5))
    print(f"\nFirst {min(5, len(sos_trips))} SOS trips:")
    for i, trip in enumerate(sos_trips, 1):
        print(f"\n  {i}. Trip ID: {trip.get('trip_id')}")
        print(f"     Driver ID: {trip.get('driver_id')}")
        print(f"     Status: {trip.get('status')}")
        print(f"     SOS Timestamp: {trip.get('sos_timestamp')}")
        print(f"     Risk Level: {trip.get('risk_level')}")
        print(f"     SOS Events: {len(trip.get('sos_events', []))} event(s)")
else:
    print("\n⚠️  No SOS-triggered trips found!")
    print("\nChecking total trips in database...")
    total_trips = trips_collection.count_documents({})
    print(f"Total trips: {total_trips}")

print("\n" + "=" * 60)
client.close()
