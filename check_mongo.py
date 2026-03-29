from pymongo import MongoClient

# Connect to MongoDB
client = MongoClient("mongodb://localhost:27017/")
db = client["ivs_db"]
collection = db["items"]

# List all databases
print("Available databases:")
for db_name in client.list_database_names():
    print(f"  - {db_name}")

# Count documents
count = collection.count_documents({})
print(f"\nTotal documents in 'ivs_db.items': {count}")

# Fetch all items
if count > 0:
    items = list(collection.find())
    print(f"\nItems in collection:")
    for item in items:
        print(f"  - {item['name']}: {item['description']}")
        print(f"    ID: {item['_id']}")
        print(f"    Created: {item['created_at']}")
else:
    print("\nNo items found in collection!")
