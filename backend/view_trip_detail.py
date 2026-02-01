from pymongo import MongoClient
from datetime import datetime

# Connect to MongoDB
client = MongoClient("mongodb://localhost:27017/")
trips = list(client['ivs_db']['trips'].find().sort("_id", -1).limit(1))

if trips:
    trip = trips[0]
    print(f"\n{'='*60}")
    print(f"Trip ID: {trip['trip_id']}")
    print(f"Driver ID: {trip['driver_id']}")
    print(f"Status: {trip['status']}")
    print(f"Start Time: {trip['start_time']}")
    print(f"End Time: {trip.get('end_time', 'N/A')}")
    print(f"{'='*60}")
    
    sensor_data = trip.get('sensor_data', [])
    print(f"\nSensor Records: {len(sensor_data)}")
    print(f"{'-'*60}")
    
    for i, record in enumerate(sensor_data, 1):
        print(f"\nRecord {i}:")
        print(f"  Timestamp: {record['timestamp']}")
        print(f"  Location: ({record['latitude']}, {record['longitude']})")
        print(f"  Speed: {record['speed']} m/s")
        print(f"  Accelerometer: {record['accelerometer']}")
        print(f"  Received: {record['received_at']}")
