"""
Migration script to update old trips with missing fields:
1. Calculate and store duration_minutes for trips without it
2. Set risk_level to 'SAFE' for trips with no events
"""
from pymongo import MongoClient
from datetime import datetime
from zoneinfo import ZoneInfo

# MongoDB Connection
MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client["ivs_db"]
trips_collection = db["trips"]

def migrate_trip_durations():
    """Calculate and update duration for trips that don't have it."""
    print("Starting duration migration...")
    
    # Find trips without duration_minutes field
    trips_without_duration = trips_collection.find({
        "$or": [
            {"duration_minutes": {"$exists": False}},
            {"duration_minutes": None}
        ],
        "status": "COMPLETED"
    })
    
    updated_count = 0
    skipped_count = 0
    
    for trip in trips_without_duration:
        trip_id = trip.get("trip_id")
        start_time = trip.get("start_time")
        end_time = trip.get("end_time")
        
        if not start_time or not end_time:
            print(f"  Skipping {trip_id}: Missing start or end time")
            skipped_count += 1
            continue
        
        try:
            # Parse timestamps
            if isinstance(start_time, str):
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            elif isinstance(start_time, datetime):
                start_dt = start_time
            else:
                print(f"  Skipping {trip_id}: Invalid start_time type")
                skipped_count += 1
                continue
            
            if isinstance(end_time, str):
                end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            elif isinstance(end_time, datetime):
                end_dt = end_time
            else:
                print(f"  Skipping {trip_id}: Invalid end_time type")
                skipped_count += 1
                continue
            
            # Calculate duration
            duration_seconds = (end_dt - start_dt).total_seconds()
            duration_minutes = round(duration_seconds / 60, 2)
            
            # Update trip
            trips_collection.update_one(
                {"trip_id": trip_id},
                {"$set": {"duration_minutes": duration_minutes}}
            )
            
            print(f"  ✓ Updated {trip_id}: {duration_minutes} minutes")
            updated_count += 1
            
        except Exception as e:
            print(f"  Error processing {trip_id}: {e}")
            skipped_count += 1
    
    print(f"\nDuration migration complete:")
    print(f"  Updated: {updated_count} trips")
    print(f"  Skipped: {skipped_count} trips")
    return updated_count, skipped_count


def migrate_safe_risk_level():
    """Set risk_level to 'SAFE' for trips with no events."""
    print("\nStarting risk level migration...")
    
    # Find trips with no ai_events or sos_events
    trips_without_events = trips_collection.find({
        "$and": [
            {
                "$or": [
                    {"ai_events": {"$exists": False}},
                    {"ai_events": []},
                    {"ai_events": None}
                ]
            },
            {
                "$or": [
                    {"sos_events": {"$exists": False}},
                    {"sos_events": []},
                    {"sos_events": None}
                ]
            },
            {
                "$or": [
                    {"risk_level": {"$exists": False}},
                    {"risk_level": None},
                    {"risk_level": "UNKNOWN"},
                    {"risk_level": ""}
                ]
            }
        ]
    })
    
    updated_count = 0
    
    for trip in trips_without_events:
        trip_id = trip.get("trip_id")
        
        # Update to SAFE
        trips_collection.update_one(
            {"trip_id": trip_id},
            {"$set": {"risk_level": "SAFE"}}
        )
        
        print(f"  ✓ Updated {trip_id}: Set to SAFE")
        updated_count += 1
    
    print(f"\nRisk level migration complete:")
    print(f"  Updated: {updated_count} trips to SAFE")
    return updated_count


if __name__ == "__main__":
    print("=" * 60)
    print("IVS Trip Migration Script")
    print("=" * 60)
    
    try:
        # Run duration migration
        duration_updated, duration_skipped = migrate_trip_durations()
        
        # Run risk level migration
        risk_updated = migrate_safe_risk_level()
        
        print("\n" + "=" * 60)
        print("Migration Summary:")
        print(f"  Duration updates: {duration_updated}")
        print(f"  Duration skipped: {duration_skipped}")
        print(f"  Risk level updates: {risk_updated}")
        print("=" * 60)
        print("✓ Migration completed successfully!")
        
    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
    finally:
        client.close()
