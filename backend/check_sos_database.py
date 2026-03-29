"""
Diagnostic script to debug SOS events in database
"""
from pymongo import MongoClient
from datetime import datetime

MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client["ivs_db"]
trips_collection = db["trips"]
events_collection = db["events"]

def check_database():
    """Check database contents for SOS-related data."""
    print("\n" + "=" * 70)
    print("IVS DATABASE DIAGNOSTIC REPORT")
    print("=" * 70)
    
    # Check trips collection
    print("\n1. TRIPS COLLECTION:")
    print("-" * 70)
    total_trips = trips_collection.count_documents({})
    print(f"   Total trips: {total_trips}")
    
    # Trips with sos_triggered = True
    sos_triggered_trips = trips_collection.find({"sos_triggered": True})
    sos_count = 0
    for trip in sos_triggered_trips:
        sos_count += 1
        print(f"\n   Trip ID: {trip.get('trip_id')}")
        print(f"   - Driver: {trip.get('driver_id')}")
        print(f"   - Status: {trip.get('status')}")
        print(f"   - SOS Triggered: {trip.get('sos_triggered')}")
        print(f"   - SOS Events in trip: {len(trip.get('sos_events', []))}")
        
        # Show SOS event details
        for idx, sos_evt in enumerate(trip.get('sos_events', [])):
            print(f"     SOS Event {idx + 1}:")
            print(f"       - Timestamp: {sos_evt.get('timestamp')}")
            print(f"       - Type: {sos_evt.get('event_type')}")
            print(f"       - Source: {sos_evt.get('source')}")
    
    if sos_count == 0:
        print("   ⚠ No trips with sos_triggered = True found")
    else:
        print(f"\n   ✓ Found {sos_count} trips with SOS triggered")
    
    # Check events collection
    print("\n2. EVENTS COLLECTION:")
    print("-" * 70)
    total_events = events_collection.count_documents({})
    print(f"   Total events: {total_events}")
    
    # Events with is_sos = True
    sos_events = list(events_collection.find({"is_sos": True}))
    print(f"   Events with is_sos=True: {len(sos_events)}")
    
    if len(sos_events) > 0:
        for idx, evt in enumerate(sos_events[:5]):  # Show first 5
            print(f"\n   SOS Event {idx + 1}:")
            print(f"   - Event ID: {evt.get('event_id')}")
            print(f"   - Trip ID: {evt.get('trip_id')}")
            print(f"   - Driver ID: {evt.get('driver_id')}")
            print(f"   - Timestamp: {evt.get('timestamp')}")
            print(f"   - Timestamp type: {type(evt.get('timestamp'))}")
            print(f"   - is_sos: {evt.get('is_sos')}")
            print(f"   - Source: {evt.get('source')}")
        
        if len(sos_events) > 5:
            print(f"\n   ... and {len(sos_events) - 5} more SOS events")
    else:
        print("   ⚠ No events with is_sos=True found!")
    
    # Check all events (non-SOS)
    non_sos_events = events_collection.count_documents({"is_sos": {"$ne": True}})
    print(f"\n   Events with is_sos≠True or missing: {non_sos_events}")
    
    # Check for any SOS in events without is_sos field
    missing_sos_field = events_collection.count_documents({"is_sos": {"$exists": False}})
    print(f"   Events missing is_sos field: {missing_sos_field}")
    
    # Summary
    print("\n3. SUMMARY:")
    print("-" * 70)
    print(f"   Trips with SOS: {sos_count}")
    print(f"   Events with is_sos=True: {len(sos_events)}")
    
    if sos_count > 0 and len(sos_events) == 0:
        print("\n   ⚠ ISSUE FOUND: Trips have SOS_TRIGGERED but no events in events_collection!")
        print("     This means the SOS events are not being persisted to events_collection")
        print("     Solution: Need to fix the add_sos_event endpoint or run a migration")
    elif len(sos_events) == 0:
        print("\n   ⚠ No SOS events found in database")
        print("     Make sure to trigger a real SOS event in the app")
    else:
        print(f"\n   ✓ Found {len(sos_events)} SOS events - they should appear on the page")
    
    print("\n" + "=" * 70)
    client.close()

if __name__ == "__main__":
    check_database()
