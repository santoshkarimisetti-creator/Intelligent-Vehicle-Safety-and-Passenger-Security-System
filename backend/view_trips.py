from pymongo import MongoClient

# Connect to MongoDB
client = MongoClient("mongodb://localhost:27017/")
trips = list(client['ivs_db']['trips'].find())

print(f"Total trips in database: {len(trips)}\n")

for trip in trips:
    print(f"Trip ID: {trip['trip_id']}")
    print(f"Driver ID: {trip['driver_id']}")
    print(f"Status: {trip['status']}")
    print(f"Start Time: {trip['start_time']}")
    print("-" * 50)
