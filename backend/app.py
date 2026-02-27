from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
import uuid
from math import radians, sin, cos, sqrt, atan2

app = Flask(__name__)
CORS(app)

# MongoDB Connection
MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client["ivs_db"]
trips_collection = db["trips"]


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance in kilometers between two lat/lon points using Haversine formula."""
    R = 6371  # Earth's radius in km
    
    lat1_rad = radians(lat1)
    lat2_rad = radians(lat2)
    delta_lat = radians(lat2 - lat1)
    delta_lon = radians(lon2 - lon1)
    
    a = sin(delta_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    distance = R * c
    return distance


@app.get("/")
def health_check():
    return jsonify({"status": "ok"})


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


@app.get("/trips/<trip_id>/distance")
def get_trip_distance(trip_id):
    """Calculate and return total distance traveled for a trip."""
    try:
        trip = trips_collection.find_one({"trip_id": trip_id})
        if not trip:
            return jsonify({"error": "Trip not found"}), 404
        
        path = trip.get("path", [])
        if len(path) < 2:
            return jsonify({
                "trip_id": trip_id,
                "distance_km": 0.0,
                "points_count": len(path)
            }), 200
        
        total_distance = 0.0
        for i in range(1, len(path)):
            prev = path[i - 1]
            current = path[i]
            
            prev_lat = float(prev.get("lat", 0))
            prev_lon = float(prev.get("lon", 0))
            curr_lat = float(current.get("lat", 0))
            curr_lon = float(current.get("lon", 0))
            
            if prev_lat and prev_lon and curr_lat and curr_lon:
                distance = haversine_distance(prev_lat, prev_lon, curr_lat, curr_lon)
                total_distance += distance
        
        return jsonify({
            "trip_id": trip_id,
            "distance_km": round(total_distance, 2),
            "points_count": len(path)
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
