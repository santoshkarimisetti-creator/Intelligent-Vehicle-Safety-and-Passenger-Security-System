from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
from zoneinfo import ZoneInfo
import uuid
from math import radians, sin, cos, sqrt, atan2
from zeroconf import ServiceInfo, Zeroconf
import socket
import threading
import os
from calibration_model import (
    get_driver_calibration,
    create_driver_calibration,
    update_calibration_samples,
    get_personalized_thresholds,
    calibration_collection
)


def _get_lan_ipv4_addresses() -> list[str]:
    """Return non-loopback IPv4 addresses from active interfaces for mDNS advertisement."""
    addresses: list[str] = []
    try:
        host_info = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        for info in host_info:
            ip = info[4][0]
            if ip.startswith("127."):
                continue
            if ip not in addresses:
                addresses.append(ip)
    except Exception:
        pass

    # UDP trick to discover default outbound interface IP
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127.") and ip not in addresses:
                addresses.insert(0, ip)
    except Exception:
        pass

    return addresses

app = Flask(__name__)
CORS(app)

# MongoDB Connection
MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client["ivs_db"]
trips_collection = db["trips"]
events_collection = db["events"]  # For detections when no active trip

IST_ZONE = ZoneInfo("Asia/Kolkata")


def to_ist_display(value):
    if value is None:
        return None

    dt = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            normalized = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return value
    else:
        return str(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))

    ist_dt = dt.astimezone(IST_ZONE)
    return ist_dt.strftime("%d/%m/%Y, %I:%M:%S %p IST")


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


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def compute_max_speed(trip):
    max_speed = 0.0

    sensor_data = trip.get("sensor_data", []) or []
    for point in sensor_data:
        max_speed = max(max_speed, _to_float(point.get("speed", 0)))

    path = trip.get("path", []) or []
    for point in path:
        max_speed = max(max_speed, _to_float(point.get("speed", 0)))

    return round(max_speed, 2)


def compute_trip_distance_km(path):
    if not path or len(path) < 2:
        return 0.0

    total_distance = 0.0
    for i in range(1, len(path)):
        prev = path[i - 1]
        curr = path[i]

        try:
            prev_lat = float(prev.get("lat", prev.get("latitude", 0)) or 0)
            prev_lon = float(prev.get("lon", prev.get("longitude", 0)) or 0)
            curr_lat = float(curr.get("lat", curr.get("latitude", 0)) or 0)
            curr_lon = float(curr.get("lon", curr.get("longitude", 0)) or 0)
        except (TypeError, ValueError):
            continue

        if prev_lat and prev_lon and curr_lat and curr_lon:
            total_distance += haversine_distance(prev_lat, prev_lon, curr_lat, curr_lon)

    return round(total_distance, 2)


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
            "start_time": to_ist_display(trip["start_time"]),
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
            formatted_start = to_ist_display(trip.get("start_time") or trip.get("start"))
            formatted_end = to_ist_display(trip.get("end_time") or trip.get("end"))
            trip["start_time"] = formatted_start
            trip["end_time"] = formatted_end
            trip["start"] = formatted_start
            trip["end"] = formatted_end
            trip["max_speed"] = compute_max_speed(trip)
            
            # Calculate duration for display (fallback if not stored)
            if "duration_minutes" not in trip:
                start_time = trip.get("start_time")
                end_time = trip.get("end_time")
                if start_time and end_time:
                    try:
                        if isinstance(start_time, str):
                            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                        else:
                            start_dt = start_time
                        if isinstance(end_time, str):
                            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                        else:
                            end_dt = end_time
                        duration_seconds = (end_dt - start_dt).total_seconds()
                        trip["duration_minutes"] = round(duration_seconds / 60, 2)
                    except:
                        trip["duration_minutes"] = 0
                else:
                    trip["duration_minutes"] = 0
            
            path = trip.get("path", [])
            total_distance = 0.0

            for i in range(1, len(path)):
                prev = path[i - 1]
                curr = path[i]

                total_distance += haversine_distance(
                    float(prev.get("lat", 0)),
                    float(prev.get("lon", 0)),
                    float(curr.get("lat", 0)),
                    float(curr.get("lon", 0))
                )

            trip["distance_km"] = round(total_distance, 2)
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
        formatted_start = to_ist_display(trip.get("start_time") or trip.get("start"))
        formatted_end = to_ist_display(trip.get("end_time") or trip.get("end"))
        trip["start_time"] = formatted_start
        trip["end_time"] = formatted_end
        trip["start"] = formatted_start
        trip["end"] = formatted_end
        trip["max_speed"] = compute_max_speed(trip)
        trip["ai_events"] = trip.get("ai_events", [])
        trip["sos_triggered"] = trip.get("sos_triggered", False)
        trip["sos_events"] = trip.get("sos_events", [])
        
        # Consolidate all events for frontend
        consolidated_events = []
        
        # Add AI detection events
        for ai_event in trip.get("ai_events", []):
            consolidated_events.append({
                "timestamp": ai_event.get("timestamp"),
                "type": "AI Detection",
                "event_type": "AI Detection",
                "description": f"Risk: {ai_event.get('risk_level', 'UNKNOWN')} - Detections: {', '.join(ai_event.get('detections', []))}",
                "details": ai_event.get("reasons", []),
                "risk_level": ai_event.get("risk_level"),
                "detections": ai_event.get("detections", [])
            })
        
        # Add SOS events
        for sos_event in trip.get("sos_events", []):
            consolidated_events.append({
                "timestamp": sos_event.get("timestamp"),
                "type": "SOS Alert",
                "event_type": "SOS",
                "description": f"Emergency SOS triggered from {sos_event.get('source', 'unknown')}",
                "details": sos_event.get("metadata", {}),
                "is_sos": True
            })
        
        # Sort events by timestamp
        consolidated_events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        trip["events"] = consolidated_events
        
        return jsonify(trip), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/trips/<trip_id>/ai-results")
def add_ai_result(trip_id):
    """Receive AI-engine detection/risk result and attach it to trip record."""
    try:
        trip = trips_collection.find_one({"trip_id": trip_id})
        if not trip:
            return jsonify({"error": "Trip not found"}), 404

        payload = request.get_json(silent=True) or {}

        event = {
            "timestamp": payload.get("timestamp") or datetime.utcnow().isoformat(),
            "detections": payload.get("detections", []),
            "risk_score": payload.get("risk_score"),
            "risk_level": payload.get("risk_level", "UNKNOWN"),
            "reasons": payload.get("reasons", []),
            "metadata": payload.get("metadata", {}),
            "source": "ai_engine"
        }

        update_doc = {
            "$set": {
                "risk_score": payload.get("risk_score"),
                "risk_level": payload.get("risk_level", "UNKNOWN"),
                "last_ai_update": datetime.utcnow()
            },
            "$push": {
                "ai_events": event
            }
        }

        trips_collection.update_one({"trip_id": trip_id}, update_doc)

        return jsonify({
            "message": "AI result recorded",
            "trip_id": trip_id,
            "risk_level": payload.get("risk_level", "UNKNOWN"),
            "risk_score": payload.get("risk_score")
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/trips/<trip_id>/sos")
def add_sos_event(trip_id):
    """Receive SOS event from AI engine or mobile app and store in both trip and emergency feed."""
    try:
        trip = trips_collection.find_one({"trip_id": trip_id})
        if not trip:
            return jsonify({"error": "Trip not found"}), 404

        payload = request.get_json(silent=True) or {}
        
        # Determine source - normalize to either "ai_engine" or "mobile_app"
        source = payload.get("source", "mobile_app").lower().strip()
        if "ai" in source:
            source = "ai_engine"
        elif "mobile" in source or source == "app" or source == "unknown":
            source = "mobile_app"
        else:
            source = payload.get("source", "mobile_app")
        
        # Parse timestamp properly - store as datetime object for proper sorting
        event_ts_str = payload.get("timestamp")
        if event_ts_str:
            try:
                event_ts = datetime.fromisoformat(event_ts_str.replace("Z", "+00:00"))
            except:
                event_ts = datetime.utcnow()
        else:
            event_ts = datetime.utcnow()

        sos_event = {
            "event_type": "SOS",
            "timestamp": event_ts,
            "source": source,
            "duration": payload.get("duration", 0.0),
            "metadata": payload.get("metadata", {}),
            "received_at": datetime.utcnow()
        }

        emergency_event = {
            "event_id": str(uuid.uuid4()),
            "trip_id": trip_id,
            "driver_id": trip.get("driver_id"),
            "timestamp": event_ts,
            "event_type": "SOS",
            "is_sos": True,
            "source": source,
            "message": payload.get("message", "SOS triggered"),
            "location": payload.get("location", payload.get("metadata", {}).get("location", {})),
            "detections": payload.get("detections", {}),
            "risk_score_weighted": payload.get("risk_score_weighted"),
            "metadata": payload.get("metadata", {}),
            "received_at": datetime.utcnow()
        }

        # Update trip with SOS flag and add to events
        update_doc = {
            "$set": {
                "sos_triggered": True,
                "sos_timestamp": datetime.utcnow()
            },
            "$push": {
                "sos_events": sos_event
            }
        }

        trips_collection.update_one({"trip_id": trip_id}, update_doc)
        events_collection.insert_one(emergency_event)

        return jsonify({
            "message": "SOS event recorded",
            "trip_id": trip_id,
            "source": payload.get("source", "unknown"),
            "timestamp": sos_event["timestamp"]
        }), 200
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
        "speed": location_data["speed"],
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

        path = trip.get("path", []) or []
        distance_km = compute_trip_distance_km(path)
        max_speed = compute_max_speed(trip)
        end_time = datetime.utcnow()
        
        # Calculate trip duration
        start_time = trip.get("start_time")
        duration_minutes = 0
        if start_time:
            if isinstance(start_time, str):
                try:
                    start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                except:
                    start_time = None
            if start_time:
                duration_seconds = (end_time - start_time).total_seconds()
                duration_minutes = round(duration_seconds / 60, 2)
        
        # Update trip status, summary metrics and end time
        result = trips_collection.update_one(
            {"trip_id": trip_id},
            {
                "$set": {
                    "status": "COMPLETED",
                    "end_time": end_time,
                    "distance_km": distance_km,
                    "max_speed": max_speed,
                    "duration_minutes": duration_minutes
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
            "distance_km": distance_km,
            "max_speed": max_speed,
            "duration_minutes": duration_minutes,
            "end_time": to_ist_display(end_time)
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


@app.get("/trips/active-trip/distance")
def get_active_trip_distance():
    """Return distance summary for the currently active trip (if any)."""
    try:
        trip = trips_collection.find_one({"status": "ACTIVE"}, sort=[("start_time", -1)])
        if not trip:
            return jsonify({
                "active_trip": False,
                "distance_km": 0.0,
                "trip_id": None,
                "points_count": 0
            }), 200

        trip_id = trip.get("trip_id")
        path = trip.get("path", [])
        if len(path) < 2:
            return jsonify({
                "active_trip": True,
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
                total_distance += haversine_distance(prev_lat, prev_lon, curr_lat, curr_lon)

        return jsonify({
            "active_trip": True,
            "trip_id": trip_id,
            "distance_km": round(total_distance, 2),
            "points_count": len(path)
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/is-active-trip/<trip_id>")
def is_active_trip(trip_id):
    """Check if trip is currently active."""
    try:
        trip = trips_collection.find_one({"trip_id": trip_id})
        if not trip:
            return jsonify({"is_active": False, "message": "Trip not found"}), 200
        
        is_active = trip.get("status") == "ACTIVE"
        return jsonify({
            "trip_id": trip_id,
            "is_active": is_active,
            "status": trip.get("status")
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/events")
def add_event():
    """Store event when no active trip (background monitoring mode)."""
    try:
        payload = request.get_json(silent=True) or {}
        
        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": payload.get("timestamp") or datetime.utcnow().isoformat(),
            "event_type": payload.get("event_type", "DETECTION"),
            "detections": payload.get("detections", {}),
            "risk_score_temporal": payload.get("risk_score_temporal"),
            "risk_score_weighted": payload.get("risk_score_weighted"),
            "risk_level": payload.get("risk_level"),
            "reasons": payload.get("reasons", []),
            "is_sos": payload.get("is_sos", False),
            "metadata": payload.get("metadata", {}),
            "received_at": datetime.utcnow()
        }
        
        result = events_collection.insert_one(event)
        
        return jsonify({
            "message": "Event recorded",
            "event_id": event["event_id"],
            "risk_level": event.get("risk_level")
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/events")
def get_events():
    """Fetch all events (background detections when no active trip)."""
    try:
        limit = request.args.get("limit", 100, type=int)
        skip = request.args.get("skip", 0, type=int)
        
        events = list(events_collection.find()
                     .sort("timestamp", -1)
                     .skip(skip)
                     .limit(limit))
        
        for event in events:
            event["_id"] = str(event["_id"])
            event["timestamp"] = to_ist_display(event.get("timestamp"))
            event["received_at"] = to_ist_display(event.get("received_at"))
        
        total_count = events_collection.count_documents({})
        
        return jsonify({
            "events": events,
            "total_count": total_count,
            "returned": len(events)
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/events/emergency")
def get_emergency_events():
    """Fetch all trips that triggered SOS (filter for sos_triggered trips)."""
    try:
        limit = request.args.get("limit", 100, type=int)
        skip = request.args.get("skip", 0, type=int)
        
        # Query trips that have sos_triggered set to True
        sos_trips = list(trips_collection.find({"sos_triggered": True})
                        .sort("sos_timestamp", -1)
                        .skip(skip)
                        .limit(limit))
        
        # Format the trips for display
        emergency_events = []
        for trip in sos_trips:
            trip["_id"] = str(trip["_id"])
            
            # Get SOS event details from the trip's sos_events array (latest one)
            sos_event_detail = trip.get("sos_events", [])[0] if trip.get("sos_events") else {}
            
            event_obj = {
                "event_id": trip.get("trip_id"),
                "trip_id": trip.get("trip_id"),
                "driver_id": trip.get("driver_id"),
                "timestamp": to_ist_display(sos_event_detail.get("timestamp") or trip.get("sos_timestamp")),
                "received_at": to_ist_display(trip.get("sos_timestamp")),
                "event_type": "SOS",
                "is_sos": True,
                "message": f"SOS triggered during trip {trip.get('trip_id')}",
                "source": sos_event_detail.get("source", "mobile_app"),
                "trip_status": trip.get("status"),
                "start_time": to_ist_display(trip.get("start_time")),
                "end_time": to_ist_display(trip.get("end_time")),
                "location": sos_event_detail.get("metadata", {}).get("location", {}),
                "detections": trip.get("ai_events", [])[0].get("detections", []) if trip.get("ai_events") else [],
                "risk_level": trip.get("risk_level"),
                "max_speed": trip.get("max_speed"),
                "distance_km": trip.get("distance_km")
            }
            emergency_events.append(event_obj)
        
        total_sos_count = trips_collection.count_documents({"sos_triggered": True})
        
        return jsonify({
            "emergency_events": emergency_events,
            "total_sos_count": total_sos_count,
            "returned": len(emergency_events)
        }), 200
    except Exception as e:
        return jsonify({"error": str(e), "details": str(e)}), 500


# ===================== DRIVER CALIBRATION ENDPOINTS =====================

@app.get("/drivers/<driver_id>/calibration")
def get_driver_calibration_status(driver_id):
    """Get calibration status and thresholds for a driver."""
    try:
        cal = get_driver_calibration(driver_id)
        
        if not cal:
            # Create new calibration if doesn't exist
            cal = create_driver_calibration(driver_id)
        
        return jsonify({
            "driver_id": driver_id,
            "calibration_status": cal.get("calibration_status"),
            "is_calibrated": cal.get("is_calibrated"),
            "frames_collected": cal.get("frames_collected", 0),
            "calibration_frames_needed": cal.get("calibration_frames_needed", 10),
            "thresholds": cal.get("thresholds", {}),
            "created_at": cal.get("created_at"),
            "last_updated": cal.get("last_updated")
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/drivers/<driver_id>/calibration/update")
def update_driver_calibration(driver_id):
    """Update calibration with new frame metrics (called by AI engine during auto-calibration)."""
    try:
        payload = request.get_json(silent=True) or {}
        frame_metrics = payload.get("metrics", {})
        
        # Add samples to driver's calibration
        update_calibration_samples(driver_id, frame_metrics)
        
        cal = get_driver_calibration(driver_id)
        
        return jsonify({
            "driver_id": driver_id,
            "frames_collected": cal.get("frames_collected", 0),
            "calibration_status": cal.get("calibration_status"),
            "is_calibrated": cal.get("is_calibrated")
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/drivers/<driver_id>/thresholds")
def get_driver_thresholds(driver_id):
    """Get personalized thresholds for a driver."""
    try:
        # Ensure calibration exists
        if not get_driver_calibration(driver_id):
            create_driver_calibration(driver_id)
        
        thresholds = get_personalized_thresholds(driver_id)
        
        return jsonify({
            "driver_id": driver_id,
            "thresholds": thresholds
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/drivers/<driver_id>/calibration/reset")
def reset_driver_calibration(driver_id):
    """Reset calibration for a driver (collect new baseline)."""
    try:
        calibration_collection.update_one(
            {"driver_id": driver_id},
            {
                "$set": {
                    "calibration_status": "PENDING",
                    "is_calibrated": False,
                    "frames_collected": 0,
                    "ear_open_samples": [],
                    "ear_closed_samples": [],
                    "mar_closed_samples": [],
                    "mar_open_samples": [],
                    "head_straight_samples": [],
                    "head_turned_samples": [],
                    "last_updated": datetime.utcnow().isoformat()
                }
            },
            upsert=True
        )
        
        return jsonify({
            "driver_id": driver_id,
            "message": "Calibration reset. New baseline will be collected on next trip."
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Register service on network via mDNS
    try:
        hostname = socket.gethostname()
        lan_ips = _get_lan_ipv4_addresses()
        if not lan_ips:
            local_ip = socket.gethostbyname(hostname)
            lan_ips = [local_ip]

        port = 5000
        service_instance = f"IVS-Backend-{hostname}"
        
        # Create service info for custom type
        ivs_service_info = ServiceInfo(
            "_ivs._tcp.local.",
            f"{service_instance}._ivs._tcp.local.",
            addresses=[socket.inet_aton(ip) for ip in lan_ips],
            port=port,
            properties={"version": "1.0", "service": "ivs-backend"},
            server=f"{hostname}.local.",
        )

        # Create service info for standard HTTP type (better Android NSD compatibility)
        http_service_info = ServiceInfo(
            "_http._tcp.local.",
            f"{service_instance}._http._tcp.local.",
            addresses=[socket.inet_aton(ip) for ip in lan_ips],
            port=port,
            properties={"version": "1.0", "service": "ivs-backend"},
            server=f"{hostname}.local.",
        )
        
        # Register services
        zeroconf = Zeroconf()
        zeroconf.register_service(ivs_service_info)
        zeroconf.register_service(http_service_info)
        print(f"\n✓ Service registered: IVS Backend on {', '.join([f'{ip}:{port}' for ip in lan_ips])}")
        
        # Start Flask app in main thread
        try:
            app.run(host="0.0.0.0", port=port, debug=False)
        finally:
            # Unregister service when app stops
            zeroconf.unregister_service(ivs_service_info)
            zeroconf.unregister_service(http_service_info)
            zeroconf.close()
            print("\n✓ Service unregistered")
    except Exception as e:
        print(f"Warning: Could not register mDNS service: {e}")
        print("Backend will still run but won't be discoverable via mDNS")
        app.run(host="0.0.0.0", port=5000, debug=False)
