from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
import uuid

app = Flask(__name__)
CORS(app)

# MongoDB Connection
MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client["ivs_db"]
collection = db["items"]
trips_collection = db["trips"]


@app.get("/")
def health_check():
    return jsonify({"status": "ok"})


@app.post("/items")
def create_item():
    """Insert a test item into MongoDB"""
    try:
        item = {
            "name": request.json.get("name", "Test Item"),
            "description": request.json.get("description", "Test Description"),
            "created_at": datetime.utcnow()
        }
        result = collection.insert_one(item)
        return jsonify({
            "message": "Item created successfully",
            "id": str(result.inserted_id)
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/items")
def fetch_items():
    """Fetch all items from MongoDB"""
    try:
        items = list(collection.find())
        # Convert ObjectId to string for JSON serialization
        for item in items:
            item["_id"] = str(item["_id"])
            item["created_at"] = item["created_at"].isoformat() if isinstance(item["created_at"], datetime) else item["created_at"]
        return jsonify({"items": items}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/items/<item_id>")
def fetch_item(item_id):
    """Fetch a single item by ID"""
    try:
        item = collection.find_one({"_id": ObjectId(item_id)})
        if not item:
            return jsonify({"error": "Item not found"}), 404
        item["_id"] = str(item["_id"])
        item["created_at"] = item["created_at"].isoformat() if isinstance(item["created_at"], datetime) else item["created_at"]
        return jsonify(item), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/trips")
def create_trip():
    """Create a new trip with unique trip ID"""
    try:
        # Generate unique trip ID
        trip_id = str(uuid.uuid4())
        
        # Get driver ID from request
        driver_id = request.json.get("driver_id")
        if not driver_id:
            return jsonify({"error": "driver_id is required"}), 400
        
        # Create trip document
        trip = {
            "trip_id": trip_id,
            "driver_id": driver_id,
            "start_time": datetime.utcnow(),
            "status": "ACTIVE",
            "sensor_data": [],  # Initialize empty sensor data array
            "path": []  # Initialize empty path array for GPS points
        }
        
        # Insert into MongoDB
        result = trips_collection.insert_one(trip)
        
        return jsonify({
            "message": "Trip created successfully",
            "trip_id": trip_id,
            "driver_id": driver_id,
            "start_time": trip["start_time"].isoformat(),
            "status": trip["status"]
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/trips")
def get_trips():
    """Fetch all trips"""
    try:
        trips = list(trips_collection.find())
        # Convert ObjectId and datetime to string for JSON serialization
        for trip in trips:
            trip["_id"] = str(trip["_id"])
            trip["start_time"] = trip["start_time"].isoformat() if isinstance(trip["start_time"], datetime) else trip["start_time"]
        return jsonify({"trips": trips}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/trips/<trip_id>")
def get_trip(trip_id):
    """Fetch a single trip by trip_id"""
    try:
        trip = trips_collection.find_one({"trip_id": trip_id})
        if not trip:
            return jsonify({"error": "Trip not found"}), 404
        trip["_id"] = str(trip["_id"])
        trip["start_time"] = trip["start_time"].isoformat() if isinstance(trip["start_time"], datetime) else trip["start_time"]
        if trip.get("end_time"):
            trip["end_time"] = trip["end_time"].isoformat() if isinstance(trip["end_time"], datetime) else trip["end_time"]
        return jsonify(trip), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/trips/<trip_id>/sensor")
def add_sensor_data(trip_id):
    """Add sensor data to a trip"""
    try:
        # Find the trip
        trip = trips_collection.find_one({"trip_id": trip_id})
        if not trip:
            return jsonify({"error": "Trip not found"}), 404
        
        # Check if trip is still active
        if trip.get("status") != "ACTIVE":
            return jsonify({"error": f"Cannot add sensor data to {trip['status']} trip"}), 400
        
        # Get sensor data from request
        sensor_data = request.json
        
        # Validate required fields
        required_fields = ["latitude", "longitude", "speed", "accelerometer", "timestamp"]
        for field in required_fields:
            if field not in sensor_data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Create sensor record with server timestamp
        sensor_record = {
            "latitude": sensor_data["latitude"],
            "longitude": sensor_data["longitude"],
            "speed": sensor_data["speed"],
            "accelerometer": sensor_data["accelerometer"],  # Can be dict/array
            "timestamp": sensor_data["timestamp"],
            "received_at": datetime.utcnow()
        }
        
        # Append sensor data to trip (using $push to append to array)
        result = trips_collection.update_one(
            {"trip_id": trip_id},
            {
                "$push": {"sensor_data": sensor_record},
                "$set": {"last_update": datetime.utcnow()}
            }
        )
        
        if result.matched_count == 0:
            return jsonify({"error": "Trip not found"}), 404
        
        return jsonify({
            "message": "Sensor data added successfully",
            "trip_id": trip_id,
            "sensor_count": len(trip.get("sensor_data", [])) + 1
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/trips/<trip_id>/location")
def add_location(trip_id):
    """Add a GPS location point to trip path"""
    try:
        # Find the trip
        trip = trips_collection.find_one({"trip_id": trip_id})
        if not trip:
            return jsonify({"error": "Trip not found"}), 404
        
        # Check if trip is still active
        if trip.get("status") != "ACTIVE":
            return jsonify({"error": f"Cannot add location to {trip['status']} trip"}), 400
        
        # Get location data from request
        location_data = request.json
        
        # Validate required fields
        required_fields = ["latitude", "longitude", "timestamp"]
        for field in required_fields:
            if field not in location_data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Create location point
        location_point = {
            "lat": location_data["latitude"],
            "lon": location_data["longitude"],
            "timestamp": location_data["timestamp"]
        }
        
        # Append location to path array using $push (append, never overwrite)
        result = trips_collection.update_one(
            {"trip_id": trip_id},
            {
                "$push": {"path": location_point},
                "$set": {"last_update": datetime.utcnow()}
            }
        )
        
        if result.matched_count == 0:
            return jsonify({"error": "Trip not found"}), 404
        
        return jsonify({
            "message": "Location added to path",
            "trip_id": trip_id,
            "latitude": location_data["latitude"],
            "longitude": location_data["longitude"],
            "timestamp": location_data["timestamp"]
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/trips/<trip_id>/sensor")
def get_sensor_data(trip_id):
    """Fetch all sensor data for a trip"""
    try:
        trip = trips_collection.find_one({"trip_id": trip_id})
        if not trip:
            return jsonify({"error": "Trip not found"}), 404
        
        sensor_data = trip.get("sensor_data", [])
        
        # Convert timestamps to ISO format
        for record in sensor_data:
            if isinstance(record.get("received_at"), datetime):
                record["received_at"] = record["received_at"].isoformat()
        
        return jsonify({
            "trip_id": trip_id,
            "sensor_count": len(sensor_data),
            "sensor_data": sensor_data
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.put("/trips/<trip_id>/end")
def end_trip(trip_id):
    """End a trip and mark it as COMPLETED"""
    try:
        # Find the trip
        trip = trips_collection.find_one({"trip_id": trip_id})
        if not trip:
            return jsonify({"error": "Trip not found"}), 404
        
        # Check if trip is already completed
        if trip.get("status") == "COMPLETED":
            return jsonify({"error": "Trip is already completed"}), 400
        
        # Update trip status and end time
        result = trips_collection.update_one(
            {"trip_id": trip_id},
            {
                "$set": {
                    "status": "COMPLETED",
                    "end_time": datetime.utcnow()
                }
            }
        )
        
        if result.matched_count == 0:
            return jsonify({"error": "Trip not found"}), 404
        
        sensor_count = len(trip.get("sensor_data", []))
        
        return jsonify({
            "message": "Trip completed successfully",
            "trip_id": trip_id,
            "status": "COMPLETED",
            "sensor_records_collected": sensor_count,
            "end_time": datetime.utcnow().isoformat()
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
