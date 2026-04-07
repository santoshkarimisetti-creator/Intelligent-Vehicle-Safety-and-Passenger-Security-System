from flask import Flask, jsonify, request, Response, render_template
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import uuid
from math import radians, sin, cos, sqrt, atan2, log, tan, pi
from zeroconf import ServiceInfo, Zeroconf
import socket
import threading
import os
import io
import csv
import urllib.request
import traceback

from dotenv import load_dotenv

load_dotenv()
from calibration_model import (
    get_driver_calibration,
    create_driver_calibration,
    get_personalized_thresholds,
    compute_and_store_thresholds,
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

SERVER_BOOT_ID = str(uuid.uuid4())
SERVER_BOOT_AT = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

# MongoDB Connection
MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
# DB selection: Connect to ivs_db (existing database with records)
db_name = "ivs_db"
db = client[db_name]
trips_collection = db["trips"]
events_collection = db["events"]  # For detections when no active trip

IST_ZONE = ZoneInfo("Asia/Kolkata")

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886").strip()
TWILIO_WHATSAPP_TO = os.getenv("TWILIO_WHATSAPP_TO", "").strip()

print("TWILIO_ACCOUNT_SID:", TWILIO_ACCOUNT_SID)
print("TWILIO_WHATSAPP_TO:", TWILIO_WHATSAPP_TO)


def _clean_str(value):
    if value is None:
        return None
    try:
        s = str(value).strip()
    except Exception:
        return None
    if not s:
        return None
    if s.lower() in {"null", "none", "undefined"}:
        return None
    return s


_DRIVER_SESSION_LOCK = threading.Lock()
_DRIVER_SESSION = {
    "boot_id": SERVER_BOOT_ID,
    "driver_id": None,
    "driver_name": None,
    "vehicle_no": None,
    "license_no": None,
    "updated_at": None,
}


def _get_driver_session_snapshot():
    with _DRIVER_SESSION_LOCK:
        return dict(_DRIVER_SESSION)


def _set_driver_session(details: dict):
    with _DRIVER_SESSION_LOCK:
        _DRIVER_SESSION.update(details)


@app.post("/driver-session")
def set_driver_session():
    """Store driver details for the current backend boot/session.

    This is used as a fallback when clients start trips without providing
    driver_name/vehicle_no/license_no (or they arrive as null).
    """
    payload = request.get_json(silent=True) or {}

    driver_name = _clean_str(payload.get("driver_name"))
    vehicle_no = _clean_str(payload.get("vehicle_no"))
    license_no = _clean_str(payload.get("license_no"))
    driver_id = _clean_str(payload.get("driver_id")) or license_no

    if not driver_name or not vehicle_no or not license_no:
        return jsonify({"error": "driver_name, vehicle_no, license_no are required"}), 400

    _set_driver_session(
        {
            "boot_id": SERVER_BOOT_ID,
            "driver_id": driver_id,
            "driver_name": driver_name,
            "vehicle_no": vehicle_no,
            "license_no": license_no,
            "updated_at": datetime.utcnow(),
        }
    )

    # If a trip is already ACTIVE (e.g., started by another client), ensure its
    # driver metadata is not left as null.
    try:
        result = trips_collection.update_many(
            {
                "status": "ACTIVE",
                "$or": [
                    {"driver_name": {"$exists": False}},
                    {"driver_name": None},
                    {"vehicle_no": {"$exists": False}},
                    {"vehicle_no": None},
                    {"license_no": {"$exists": False}},
                    {"license_no": None},
                ],
            },
            {
                "$set": {
                    "driver_id": driver_id,
                    "driver_name": driver_name,
                    "vehicle_no": vehicle_no,
                    "license_no": license_no,
                }
            },
        )
        updated = int(getattr(result, "modified_count", 0) or 0)
    except Exception:
        updated = 0

    return jsonify({"status": "ok", "boot_id": SERVER_BOOT_ID, "updated_active_trips": updated}), 200


def send_sos_alert(trip: dict):
    """Send a minimal SOS alert with maps + tracking links via Twilio WhatsApp."""
    try:
        from twilio.rest import Client
    except Exception:
        raise RuntimeError("twilio package not installed")
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        raise RuntimeError("Missing TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN")
    if not TWILIO_WHATSAPP_TO:
        raise RuntimeError("Missing TWILIO_WHATSAPP_TO")

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    trip_oid = str(trip.get("_id"))
    base_url = (PUBLIC_BASE_URL or "https://drew-onrushing-loverly.ngrok-free.dev").rstrip("/")
    tracking_link = f"{base_url}/tracking?trip_id={trip_oid}"

    last_lat = trip.get("last_lat")
    last_lng = trip.get("last_lng")
    if last_lat is not None and last_lng is not None:
        maps_link = f"https://www.google.com/maps?q={last_lat},{last_lng}"
    else:
        maps_link = "Location not available"

    driver_name = trip.get("driver_name") or "Unknown"
    vehicle_number = trip.get("vehicle_number") or trip.get("vehicle_no") or "Unknown"

    message = f"""
🚨 SOS ALERT 🚨

Driver: {driver_name}
Vehicle: {vehicle_number}

📍 Location:
{maps_link}

📡 Live Tracking:
{tracking_link}
""".strip()

    print("==== DEBUG SOS ====")
    print("TO:", TWILIO_WHATSAPP_TO)
    print("FROM:", TWILIO_WHATSAPP_FROM)
    print("SID:", (TWILIO_ACCOUNT_SID[:10] + " ...") if TWILIO_ACCOUNT_SID else "")
    print("BASE_URL:", base_url)
    print("===================")

    try:
        msg = client.messages.create(
            body=message,
            from_=TWILIO_WHATSAPP_FROM,
            to=TWILIO_WHATSAPP_TO,
        )
        print("✅ SOS sent:", msg.sid)
    except Exception:
        print("🔥 FULL TWILIO ERROR BELOW 🔥")
        traceback.print_exc()
        raise


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


def _parse_iso_to_utc_naive(value):
    """Parse ISO datetime to naive UTC datetime for Mongo range queries."""
    if not value:
        return None
    try:
        normalized = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except Exception:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.replace(tzinfo=None)


def _extract_detection_labels(detections):
    """Return unique detection labels from a detections payload."""
    labels = []

    if isinstance(detections, list):
        for item in detections:
            if isinstance(item, str):
                label = item.strip()
                if label:
                    labels.append(label)
            elif isinstance(item, dict):
                label = str(item.get("type") or item.get("label") or item.get("name") or item.get("event") or "").strip()
                if label:
                    labels.append(label)
    elif isinstance(detections, dict):
        for k, v in detections.items():
            if v:
                label = str(k).strip()
                if label:
                    labels.append(label)

    seen = set()
    uniq = []
    for l in labels:
        if l in seen:
            continue
        seen.add(l)
        uniq.append(l)
    return uniq


def _parse_event_ts(value):
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return datetime.utcnow()


def _normalize_event_key(trip_id, driver_id, event_type, episode_start_ts):
    return f"{trip_id}|{driver_id}|{event_type}|{episode_start_ts}"


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
            prev_lon = float(prev.get("lng", prev.get("lon", prev.get("longitude", 0))) or 0)
            curr_lat = float(curr.get("lat", curr.get("latitude", 0)) or 0)
            curr_lon = float(curr.get("lng", curr.get("lon", curr.get("longitude", 0))) or 0)
        except (TypeError, ValueError):
            continue

        if prev_lat and prev_lon and curr_lat and curr_lon:
            total_distance += haversine_distance(prev_lat, prev_lon, curr_lat, curr_lon)

    return round(total_distance, 2)


def _parse_datetime_any(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _safe_confidence(value) -> float:
    try:
        v = float(value)
    except Exception:
        return 0.0
    return max(0.0, min(1.0, v))


def compute_emotion_trip_summary(trip: dict, *, trip_end_time: datetime | None = None) -> dict:
    negative_emotions = {"anger", "fear", "sadness", "disgust"}
    ai_events = trip.get("ai_events", []) or []

    points = []
    for evt in ai_events:
        de = evt.get("driver_emotion") or {}
        if not isinstance(de, dict):
            continue

        emotion = str(de.get("driver_emotion") or de.get("emotion") or "").strip().lower()
        if not emotion:
            continue

        ts = _parse_datetime_any(de.get("timestamp")) or _parse_datetime_any(evt.get("timestamp"))
        if ts is None:
            continue

        confidence = _safe_confidence(de.get("confidence"))
        points.append({"timestamp": ts, "emotion": emotion, "confidence": confidence})

    points.sort(key=lambda x: x["timestamp"])

    compressed = []
    for p in points:
        if (not compressed) or (compressed[-1]["emotion"] != p["emotion"]):
            compressed.append(p)

    start_dt = _parse_datetime_any(trip.get("start_time") or trip.get("start"))
    end_dt = _parse_datetime_any(trip_end_time or trip.get("end_time") or trip.get("end"))
    if start_dt is None and compressed:
        start_dt = compressed[0]["timestamp"]
    if end_dt is None:
        end_dt = datetime.now(timezone.utc)
    if start_dt is None:
        start_dt = end_dt

    total_seconds = max(1.0, (end_dt - start_dt).total_seconds())

    durations = {}
    if compressed:
        timeline = [{"timestamp": start_dt, "emotion": compressed[0]["emotion"], "confidence": compressed[0]["confidence"]}] + compressed
        if timeline[0]["timestamp"] > timeline[1]["timestamp"]:
            timeline[0]["timestamp"] = timeline[1]["timestamp"]

        for idx, current in enumerate(timeline):
            t0 = current["timestamp"]
            t1 = timeline[idx + 1]["timestamp"] if idx + 1 < len(timeline) else end_dt
            if t1 < t0:
                continue
            sec = max(0.0, (t1 - t0).total_seconds())
            emo = current["emotion"]
            durations[emo] = durations.get(emo, 0.0) + sec

    confidence_samples = [p["confidence"] for p in compressed]
    avg_conf = (sum(confidence_samples) / len(confidence_samples)) if confidence_samples else 0.0

    negative_seconds = sum(v for k, v in durations.items() if k in negative_emotions)
    negative_ratio = max(0.0, min(1.0, negative_seconds / total_seconds))
    stress_score = max(0.0, min(1.0, 0.7 * negative_ratio + 0.3 * avg_conf))

    dominant_emotion = "unknown"
    if durations:
        dominant_emotion = max(durations.items(), key=lambda kv: kv[1])[0]

    if stress_score >= 0.66:
        stress_level = "HIGH"
    elif stress_score >= 0.33:
        stress_level = "MEDIUM"
    else:
        stress_level = "LOW"

    duration_seconds_by_emotion = {k: round(v, 2) for k, v in durations.items()}
    percentage_by_emotion = {
        k: round((v / total_seconds) * 100.0, 2) for k, v in durations.items()
    }

    return {
        "stress_level": stress_level,
        "negative_ratio": round(negative_ratio, 4),
        "stress_score": round(stress_score, 4),
        "dominant_emotion": dominant_emotion,
        "avg_confidence": round(avg_conf, 4),
        "duration_seconds_by_emotion": duration_seconds_by_emotion,
        "percentage_by_emotion": percentage_by_emotion,
        "total_trip_seconds": round(total_seconds, 2),
    }


@app.get("/")
def health_check():
    return jsonify({"status": "ok", "boot_id": SERVER_BOOT_ID, "boot_at": SERVER_BOOT_AT})


@app.get("/tracking")
def tracking_page():
    return render_template("tracking.html")




@app.post("/trips")
def create_trip():
    """Create a new trip with unique trip ID"""
    try:
        now = datetime.utcnow()

        # Event-driven trip control: ensure there is never more than one ACTIVE trip.
        # If an ACTIVE trip exists, auto-complete it and immediately start a new one.
        trips_collection.update_many(
            {"status": "ACTIVE"},
            {
                "$set": {
                    "status": "COMPLETED",
                    "end_time": now,
                    "end_reason": "auto_end_new_trip",
                }
            },
        )

        # Generate unique trip ID
        trip_id = str(uuid.uuid4())
        
        payload = request.get_json(silent=True) or {}

        # Fallback: if clients start trips without driver fields (or they arrive as null),
        # reuse the most recently stored driver-session details.
        session = _get_driver_session_snapshot()

        # Driver identity
        driver_id = _clean_str(payload.get("driver_id")) or _clean_str(payload.get("license_no")) or _clean_str(session.get("driver_id"))
        if not driver_id:
            return jsonify({"error": "driver_id is required"}), 400

        driver_name = _clean_str(payload.get("driver_name")) or _clean_str(session.get("driver_name")) or "Unknown"
        vehicle_no = _clean_str(payload.get("vehicle_no")) or _clean_str(session.get("vehicle_no")) or "Unknown"
        license_no = _clean_str(payload.get("license_no")) or _clean_str(session.get("license_no")) or driver_id
        
        # Create trip document
        trip = {
            "trip_id": trip_id,
            "driver_id": driver_id,
            "driver_name": driver_name,
            "vehicle_no": vehicle_no,
            "license_no": license_no,
            "start_time": now,
            "status": "ACTIVE",
            "sensor_data": [],  # Initialize empty sensor data array
            "path": []  # Initialize empty path array for GPS points
        }
        
        # Insert into MongoDB
        result = trips_collection.insert_one(trip)

        # Concurrency safety: if any other ACTIVE trips exist (e.g., parallel start requests),
        # auto-complete them so this request finishes with exactly one ACTIVE trip.
        trips_collection.update_many(
            {"status": "ACTIVE", "trip_id": {"$ne": trip_id}},
            {
                "$set": {
                    "status": "COMPLETED",
                    "end_time": now,
                    "end_reason": "auto_end_new_trip",
                }
            },
        )
        
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
            labels = _extract_detection_labels(ai_event.get("detections", []))
            raw_type = str(ai_event.get("event_type") or "").strip()
            is_generic = (not raw_type) or (raw_type in {"DETECTION", "AI Detection", "AI_DETECTION", "Multiple"})
            primary = (", ".join(labels) if len(labels) > 1 else labels[0]) if labels else ("No Detections" if is_generic else raw_type)
            label_text = ", ".join(labels) if labels else "none"
            consolidated_events.append({
                "timestamp": ai_event.get("timestamp"),
                "type": primary,
                "event_type": primary,
                "description": f"Risk: {ai_event.get('risk_level', 'UNKNOWN')} - Detections: {label_text}",
                "details": ai_event.get("reasons", []),
                "risk_level": ai_event.get("risk_level"),
                "detections": ai_event.get("detections", []),
                "event_labels": labels,
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


def _normalize_timestamp(value):
    """Normalize timestamps for JSON/PDF/CSV exports."""
    if value is None:
        return None
    if isinstance(value, datetime):
        # Store as ISO-8601 string.
        return value.isoformat()
    return value


def _build_consolidated_trip_events(trip: dict) -> list[dict]:
    """Build a frontend-friendly events timeline (used by Level-3 exports)."""
    consolidated_events: list[dict] = []

    # Add AI detection events
    for ai_event in trip.get("ai_events", []) or []:
        labels = _extract_detection_labels(ai_event.get("detections", []))
        raw_type = str(ai_event.get("event_type") or "").strip()
        is_generic = (not raw_type) or (raw_type in {"DETECTION", "AI Detection", "AI_DETECTION", "Multiple"})
        primary = (
            (", ".join(labels) if len(labels) > 1 else labels[0])
            if labels
            else ("No Detections" if is_generic else raw_type)
        )
        label_text = ", ".join(labels) if labels else "none"

        consolidated_events.append(
            {
                "timestamp": _normalize_timestamp(ai_event.get("timestamp")),
                "type": primary,
                "event_type": primary,
                "description": f"Risk: {ai_event.get('risk_level', 'UNKNOWN')} - Detections: {label_text}",
                "details": ai_event.get("reasons", []),
                "risk_level": ai_event.get("risk_level"),
                "detections": ai_event.get("detections", []),
                "event_labels": labels,
            }
        )

    # Add SOS events
    for sos_event in trip.get("sos_events", []) or []:
        consolidated_events.append(
            {
                "timestamp": _normalize_timestamp(sos_event.get("timestamp")),
                "type": "SOS Alert",
                "event_type": "SOS",
                "description": f"Emergency SOS triggered from {sos_event.get('source', 'unknown')}",
                "details": sos_event.get("metadata", {}),
                "is_sos": True,
            }
        )

    # Sort by timestamp (ISO strings should sort lexicographically).
    consolidated_events.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return consolidated_events


def _get_trip_or_404(trip_id: str) -> tuple[dict | None, tuple | None]:
    trip = trips_collection.find_one({"trip_id": trip_id})
    if not trip:
        return None, (jsonify({"error": "Trip not found"}), 404)
    return trip, None


def _render_route_png(path: list[dict]) -> bytes:
    """Render route on top of real OpenStreetMap tiles, fallback to local drawing."""
    from PIL import Image, ImageDraw

    width, height = 1000, 500
    tile_size = 256
    line_color = (220, 20, 60)  # crimson

    coords: list[tuple[float, float]] = []  # (lon, lat)
    for pt in path or []:
        lat = pt.get("lat")
        lng = pt.get("lng", pt.get("lon"))
        if lat is None or lng is None:
            continue
        try:
            lat_f = float(lat)
            lng_f = float(lng)
            # Clamp latitude to Web Mercator valid range.
            lat_f = max(-85.0511, min(85.0511, lat_f))
            coords.append((lng_f, lat_f))
        except Exception:
            continue

    def _fallback() -> bytes:
        img = Image.new("RGB", (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        if len(coords) < 2:
            draw.text((20, 20), "No route data available", fill=(0, 0, 0))
        else:
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)

            dx = max(max_x - min_x, 1e-9)
            dy = max(max_y - min_y, 1e-9)

            def project(lng_val: float, lat_val: float) -> tuple[int, int]:
                px = int((lng_val - min_x) / dx * (width - 40) + 20)
                py = int(height - ((lat_val - min_y) / dy * (height - 40) + 20))
                return px, py

            for i in range(1, len(coords)):
                (lng1, lat1) = coords[i - 1]
                (lng2, lat2) = coords[i]
                x1, y1 = project(lng1, lat1)
                x2, y2 = project(lng2, lat2)
                draw.line([(x1, y1), (x2, y2)], fill=line_color, width=4)

            x0, y0 = project(coords[0][0], coords[0][1])
            x1, y1 = project(coords[-1][0], coords[-1][1])
            draw.ellipse((x0 - 6, y0 - 6, x0 + 6, y0 + 6), fill=(0, 180, 0))
            draw.ellipse((x1 - 6, y1 - 6, x1 + 6, y1 + 6), fill=(0, 0, 180))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    if len(coords) < 2:
        return _fallback()

    def lonlat_to_global_px(lon_val: float, lat_val: float, zoom_val: int) -> tuple[float, float]:
        scale = (2 ** zoom_val) * tile_size
        x = (lon_val + 180.0) / 360.0 * scale
        lat_rad = radians(lat_val)
        y = (1.0 - (log(tan(lat_rad) + (1.0 / cos(lat_rad))) / pi)) / 2.0 * scale
        return x, y

    def pick_zoom(min_lon: float, max_lon: float, min_lat: float, max_lat: float) -> int:
        pad = 40
        for z in range(18, 1, -1):
            x1, y1 = lonlat_to_global_px(min_lon, max_lat, z)
            x2, y2 = lonlat_to_global_px(max_lon, min_lat, z)
            span_x = abs(x2 - x1)
            span_y = abs(y2 - y1)
            if span_x <= (width - pad * 2) and span_y <= (height - pad * 2):
                return z
        return 2

    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    zoom = pick_zoom(min_lon, max_lon, min_lat, max_lat)
    center_lon = (min_lon + max_lon) / 2.0
    center_lat = (min_lat + max_lat) / 2.0
    cx, cy = lonlat_to_global_px(center_lon, center_lat, zoom)

    top_left_x = cx - (width / 2.0)
    top_left_y = cy - (height / 2.0)

    canvas = Image.new("RGB", (width, height), (245, 245, 245))
    draw = ImageDraw.Draw(canvas)

    x_start = int(top_left_x // tile_size)
    y_start = int(top_left_y // tile_size)
    x_end = int((top_left_x + width) // tile_size)
    y_end = int((top_left_y + height) // tile_size)

    n = 2 ** zoom
    success_tiles = 0
    for tx in range(x_start, x_end + 1):
        for ty in range(y_start, y_end + 1):
            if ty < 0 or ty >= n:
                continue
            wrapped_tx = tx % n
            url = f"https://tile.openstreetmap.org/{zoom}/{wrapped_tx}/{ty}.png"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "IVS-TripReport/1.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    tile_data = resp.read()
                tile_img = Image.open(io.BytesIO(tile_data)).convert("RGB")
                paste_x = int(tx * tile_size - top_left_x)
                paste_y = int(ty * tile_size - top_left_y)
                canvas.paste(tile_img, (paste_x, paste_y))
                success_tiles += 1
            except Exception:
                continue

    if success_tiles == 0:
        return _fallback()

    # Draw route overlay.
    points: list[tuple[float, float]] = []
    for lon_val, lat_val in coords:
        gx, gy = lonlat_to_global_px(lon_val, lat_val, zoom)
        points.append((gx - top_left_x, gy - top_left_y))

    if len(points) >= 2:
        draw.line(points, fill=line_color, width=4)
        sx, sy = points[0]
        ex, ey = points[-1]
        draw.ellipse((sx - 6, sy - 6, sx + 6, sy + 6), fill=(0, 180, 0))
        draw.ellipse((ex - 6, ey - 6, ex + 6, ey + 6), fill=(0, 0, 180))

    draw.rectangle((0, height - 18, width, height), fill=(255, 255, 255))
    draw.text((8, height - 14), "Map data © OpenStreetMap contributors", fill=(80, 80, 80))

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


@app.get("/trip/<trip_id>/download")
def download_trip_json(trip_id: str):
    """Level-3: download full trip JSON (path + events + timestamps)."""
    try:
        trip, err = _get_trip_or_404(trip_id)
        if err:
            return err

        events = _build_consolidated_trip_events(trip)
        payload = {
            "trip_id": trip.get("trip_id"),
            "driver_id": trip.get("driver_id"),
            "start_time": _normalize_timestamp(trip.get("start_time") or trip.get("start")),
            "end_time": _normalize_timestamp(trip.get("end_time") or trip.get("end")),
            "path": trip.get("path", []) or [],
            "events": events,
            "risk_summary": {
                "risk_level": trip.get("risk_level"),
                "risk_score": trip.get("risk_score"),
                "max_speed": compute_max_speed(trip),
            },
        }
        return jsonify(payload), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/trip/<trip_id>/download_csv")
def download_trip_csv(trip_id: str):
    """Level-3: export path as CSV."""
    try:
        trip, err = _get_trip_or_404(trip_id)
        if err:
            return err

        path = trip.get("path", []) or []
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["lat", "lng", "timestamp"])
        for pt in path:
            writer.writerow(
                [
                    pt.get("lat"),
                    pt.get("lng", pt.get("lon")),
                    pt.get("timestamp"),
                ]
            )

        csv_bytes = buf.getvalue().encode("utf-8")
        return Response(
            csv_bytes,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={trip_id}.csv"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/trip/<trip_id>/map_image")
def download_trip_map_image(trip_id: str):
    """Level-3: download a static PNG map image of the route."""
    try:
        trip, err = _get_trip_or_404(trip_id)
        if err:
            return err

        path = trip.get("path", []) or []
        png_bytes = _render_route_png(path)
        return Response(
            png_bytes,
            mimetype="image/png",
            headers={"Content-Disposition": f"attachment; filename={trip_id}_map.png"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/trip/<trip_id>/report")
def download_trip_report_pdf(trip_id: str):
    """Level-3: generate and download a full PDF report."""
    try:
        trip, err = _get_trip_or_404(trip_id)
        if err:
            return err

        events = _build_consolidated_trip_events(trip)
        path = trip.get("path", []) or []

        # Event counts for the PDF summary.
        drowsiness_count = 0
        yawning_count = 0
        distraction_count = 0
        ai_events_count = 0
        for ai_event in trip.get("ai_events", []) or []:
            ai_events_count += 1
            labels = _extract_detection_labels(ai_event.get("detections", []))
            if "drowsiness" in labels:
                drowsiness_count += 1
            if "yawning" in labels:
                yawning_count += 1
            if "distraction" in labels:
                distraction_count += 1

        sos_count = len(trip.get("sos_events", []) or [])

        peak_risk_level = trip.get("risk_level", "UNKNOWN")
        total_distance_km = compute_trip_distance_km(path)

        png_bytes = _render_route_png(path)
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.utils import ImageReader
        except Exception as e:
            return jsonify({"error": f"reportlab not available: {e}"}), 501

        pdf_buf = io.BytesIO()
        c = canvas.Canvas(pdf_buf, pagesize=A4)
        page_w, page_h = A4

        y = page_h - 60
        c.setFont("Helvetica-Bold", 16)
        c.drawString(60, y, "IVS Trip Report")
        y -= 28

        c.setFont("Helvetica", 11)
        c.drawString(60, y, f"Trip ID: {trip_id}")
        y -= 16
        c.drawString(60, y, f"Driver ID: {trip.get('driver_id')}")
        y -= 16
        c.drawString(60, y, f"Start: {_normalize_timestamp(trip.get('start_time') or trip.get('start'))}")
        y -= 16
        c.drawString(60, y, f"End: {_normalize_timestamp(trip.get('end_time') or trip.get('end'))}")
        y -= 16
        c.drawString(60, y, f"Total Distance (km): {round(total_distance_km, 2)}")
        y -= 16
        c.drawString(60, y, f"Risk Level: {peak_risk_level}")
        y -= 28

        # Event summary.
        c.setFont("Helvetica-Bold", 12)
        c.drawString(60, y, "Event Summary")
        y -= 18
        c.setFont("Helvetica", 11)
        c.drawString(60, y, f"Drowsiness events: {drowsiness_count}")
        y -= 14
        c.drawString(60, y, f"Yawning events: {yawning_count}")
        y -= 14
        c.drawString(60, y, f"Distraction events: {distraction_count}")
        y -= 14
        c.drawString(60, y, f"SOS events: {sos_count}")
        y -= 18
        c.drawString(60, y, f"AI events recorded: {ai_events_count}")
        y -= 28

        # Embed map image.
        try:
            img = ImageReader(io.BytesIO(png_bytes))
            img_w = 420
            img_h = 210
            c.drawImage(img, 60, y - img_h, width=img_w, height=img_h, preserveAspectRatio=True, mask="auto")
            y -= (img_h + 18)
        except Exception:
            y -= 20

        # Timeline (first N to keep page readable).
        c.setFont("Helvetica-Bold", 12)
        c.drawString(60, y, "Recent Events")
        y -= 18
        c.setFont("Helvetica", 9)

        for evt in events[:18]:
            ts = evt.get("timestamp") or ""
            label = evt.get("type") or ""
            line = f"{ts}: {label}"
            # crude line wrap protection
            if y < 50:
                c.showPage()
                y = page_h - 60
                c.setFont("Helvetica", 9)
            c.drawString(60, y, line[:130])
            y -= 12

        c.showPage()
        c.save()

        pdf_bytes = pdf_buf.getvalue()
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={trip_id}_report.pdf"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/trips/<trip_id>/ai-results")
def add_ai_result(trip_id):
    """Receive AI-engine detection/risk result and attach it to trip record."""
    try:
        trip = trips_collection.find_one({"trip_id": trip_id})
        if not trip:
            return jsonify({"error": "Trip not found"}), 404

        if trip.get("status") != "ACTIVE":
            return jsonify(
                {
                    "error": "Trip is not active",
                    "code": "TRIP_NOT_ACTIVE",
                    "status": trip.get("status"),
                }
            ), 409

        payload = request.get_json(silent=True) or {}

        source_raw = str(payload.get("source", "ai_engine")).strip().lower()
        if "mobile" in source_raw:
            source = "mobile_app"
        elif "ai" in source_raw:
            source = "ai_engine"
        else:
            source = source_raw or "ai_engine"

        detections = payload.get("detections", [])
        labels = _extract_detection_labels(detections)
        event_action = str(payload.get("event_action") or "frame").strip().lower()
        event_type = payload.get("event_type")
        if not event_type or event_type in {"DETECTION", "AI Detection", "AI_DETECTION"}:
            # Store a stable primary label; the full list is in event_labels.
            event_type = labels[0] if labels else "DETECTION"

        episode_id = str(payload.get("episode_id") or "").strip() or None
        episode_start_ts = str(payload.get("episode_start_ts") or payload.get("timestamp") or datetime.utcnow().isoformat())
        event_key = str(payload.get("event_key") or "").strip() or None
        driver_id = str((payload.get("metadata") or {}).get("driver", {}).get("driver_id") or trip.get("driver_id") or "unknown_driver")
        if not event_key and event_action == "start":
            event_key = _normalize_event_key(trip_id, driver_id, event_type, episode_start_ts)

        # Always keep trip-level risk summary fresh.
        base_set = {
            "risk_score": payload.get("risk_score"),
            "risk_level": payload.get("risk_level", "UNKNOWN"),
            "last_ai_update": datetime.utcnow(),
        }

        if event_action == "end":
            query = {"trip_id": trip_id}
            if episode_id:
                query["ai_events.episode_id"] = episode_id
            elif event_key:
                query["ai_events.event_key"] = event_key
            else:
                return jsonify({"message": "episode end ignored: missing episode_id/event_key"}), 200

            end_ts = str(payload.get("episode_end_ts") or payload.get("timestamp") or datetime.utcnow().isoformat())
            duration_s = payload.get("duration_s")

            update_doc = {
                "$set": {
                    **base_set,
                    "ai_events.$.end_time": end_ts,
                    "ai_events.$.duration_s": duration_s,
                    "ai_events.$.status": "ended",
                }
            }
            result = trips_collection.update_one(query, update_doc)
            if result.modified_count > 0:
                return jsonify({"message": "AI episode ended", "trip_id": trip_id, "event_type": event_type}), 200
            return jsonify({"message": "AI episode end skipped (not found)", "trip_id": trip_id, "event_type": event_type}), 200

        if event_action == "start" and event_key:
            exists = trips_collection.find_one(
                {"trip_id": trip_id, "ai_events.event_key": event_key},
                {"_id": 1},
            )
            if exists:
                trips_collection.update_one({"trip_id": trip_id}, {"$set": base_set})
                return jsonify({"message": "Duplicate episode ignored", "trip_id": trip_id, "event_type": event_type}), 200

        event = {
            "timestamp": payload.get("timestamp") or datetime.utcnow().isoformat(),
            "start_time": episode_start_ts if event_action == "start" else None,
            "end_time": None,
            "status": "active" if event_action == "start" else "frame",
            "event_action": event_action,
            "event_key": event_key,
            "episode_id": episode_id,
            "event_type": event_type,
            "event_labels": labels,
            "detections": detections,
            "risk_score": payload.get("risk_score"),
            "risk_score_temporal": payload.get("risk_score_temporal"),
            "risk_score_weighted": payload.get("risk_score_weighted"),
            "risk_level": payload.get("risk_level", "UNKNOWN"),
            "risk_level_temporal": payload.get("risk_level_temporal"),
            "risk_level_weighted": payload.get("risk_level_weighted"),
            "reasons": payload.get("reasons", []),
            "sos_triggered": bool(payload.get("sos_triggered", False)),
            "sos_source": payload.get("sos_source"),
            "driver_emotion": payload.get("driver_emotion"),
            "passenger_emotions": payload.get("passenger_emotions", []),
            "metadata": payload.get("metadata", {}),
            "source": source,
        }

        update_doc = {
            "$set": {
                **base_set,
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
            "risk_score": payload.get("risk_score"),
            "source": source,
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
            "risk_level": payload.get("risk_level"),
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

        # After updating DB, send WhatsApp SOS alert
        send_sos_alert(trip)

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
        # Find the trip (accept either trip_id or Mongo _id)
        trip = trips_collection.find_one({"trip_id": trip_id})
        trip_query = {"trip_id": trip_id}
        if not trip:
            try:
                oid = ObjectId(trip_id)
                trip = trips_collection.find_one({"_id": oid})
                trip_query = {"_id": oid}
            except Exception:
                trip = None
        if not trip:
            return jsonify({"error": "Trip not found"}), 404
        
        # Check if trip is still active
        if trip.get("status") != "ACTIVE":
            return jsonify({"error": f"Cannot add location to {trip['status']} trip"}), 400
        
        # Get location data from request
        location_data = request.json
        
        # Validate required fields (speed optional — some clients send lat/lon/timestamp only)
        required_fields = ["latitude", "longitude", "timestamp"]
        for field in required_fields:
            if field not in location_data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Create location point
        location_point = {
            "lat": location_data["latitude"],
            "lng": location_data["longitude"],
            "lon": location_data["longitude"],
            "speed": location_data.get("speed", 0),
            "timestamp": location_data["timestamp"],
        }
        
        # Append location to path array using $push (append, never overwrite)
        result = trips_collection.update_one(
            trip_query,
            {
                "$push": {"path": location_point},
                "$set": {
                    "last_update": datetime.utcnow(),
                    "last_lat": location_data["latitude"],
                    "last_lng": location_data["longitude"],
                }
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
        emotion_summary = compute_emotion_trip_summary(trip, trip_end_time=end_time)
        
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
                    "duration_minutes": duration_minutes,
                    "emotion_summary": emotion_summary,
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
            "emotion_summary": emotion_summary,
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


@app.get("/trips/active-trip/live_map")
def get_active_trip_live_map():
    """Return live map data for the currently active trip."""
    try:
        trip = trips_collection.find_one({"status": "ACTIVE"}, sort=[("start_time", -1)])
        if not trip:
            return jsonify(
                {
                    "trip_active": False,
                    "current_location": None,
                    "path": [],
                }
            ), 200

        path = trip.get("path", []) or []
        current_point = path[-1] if path else {}

        lat = current_point.get("lat")
        lng = current_point.get("lng", current_point.get("lon"))

        start_time = trip.get("start_time")
        if isinstance(start_time, datetime):
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            start_time_iso = start_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            start_time_iso = None

        return jsonify(
            {
                "trip_active": True,
                "current_location": {"lat": lat, "lng": lng} if lat is not None and lng is not None else None,
                "path": path,
                "trip_id": trip.get("trip_id"),
                "trip_start_time": start_time_iso,
            }
        ), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/trips/<trip_id>/live_map")
def get_trip_live_map(trip_id):
    """Live map payload for a specific trip (same shape as active-trip live_map when trip is ACTIVE)."""
    try:
        trip = trips_collection.find_one({"trip_id": trip_id})
        if not trip:
            return jsonify({"error": "Trip not found"}), 404

        active = trip.get("status") == "ACTIVE"
        path = trip.get("path", []) or []
        current_point = path[-1] if path else {}
        lat = current_point.get("lat")
        lng = current_point.get("lng", current_point.get("lon"))

        start_time = trip.get("start_time")
        if isinstance(start_time, datetime):
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            start_time_iso = start_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            start_time_iso = None

        return jsonify(
            {
                "trip_active": active,
                "trip_id": trip.get("trip_id"),
                "trip_start_time": start_time_iso,
                "current_location": {"lat": lat, "lng": lng}
                if active and lat is not None and lng is not None
                else None,
                "path": path,
            }
        ), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/get-location/<trip_id>")
def get_location(trip_id):
    """Return the latest known coordinates for a trip.

    Response shapes:
    - OK: {"status":"OK","lat":<float>,"lon":<float>,"timestamp":<str|null>}
    - NO_DATA: {"status":"NO_DATA","lat":null,"lon":null,"timestamp":null}
    - NOT_FOUND: {"status":"NOT_FOUND","lat":null,"lon":null,"timestamp":null}

    Never returns default/fake coordinates.
    """

    def _to_float(value):
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _timestamp_to_iso(value):
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if isinstance(value, (int, float)):
            try:
                return (
                    datetime.fromtimestamp(float(value), tz=timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
            except Exception:
                return None
        if isinstance(value, str):
            return value
        return None

    def _extract_from_path(path_points):
        for point in reversed(path_points or []):
            lat = _to_float(point.get("lat"))
            lon = _to_float(point.get("lng"))
            if lon is None:
                lon = _to_float(point.get("lon"))
            if lat is not None and lon is not None:
                ts = (
                    point.get("timestamp")
                    or point.get("time")
                    or point.get("ts")
                    or point.get("t")
                )
                return lat, lon, _timestamp_to_iso(ts)
        return None, None, None

    def _extract_from_sensor_data(sensor_rows):
        for row in reversed(sensor_rows or []):
            lat = _to_float(row.get("latitude"))
            lon = _to_float(row.get("longitude"))
            if lon is None:
                lon = _to_float(row.get("lng"))
            if lon is None:
                lon = _to_float(row.get("lon"))
            if lat is None:
                lat = _to_float(row.get("lat"))
            if lat is not None and lon is not None:
                ts = (
                    row.get("timestamp")
                    or row.get("time")
                    or row.get("ts")
                    or row.get("t")
                )
                return lat, lon, _timestamp_to_iso(ts)
        return None, None, None

    try:
        trip = trips_collection.find_one({"trip_id": trip_id})
        if not trip:
            try:
                trip = trips_collection.find_one({"_id": ObjectId(trip_id)})
            except Exception:
                trip = None
        if not trip:
            return jsonify({"status": "NOT_FOUND", "lat": None, "lon": None, "timestamp": None}), 404

        lat, lon, ts = _extract_from_path(trip.get("path", []) or [])
        if lat is None or lon is None:
            lat, lon, ts = _extract_from_sensor_data(trip.get("sensor_data", []) or [])

        if lat is None or lon is None:
            return jsonify({"status": "NO_DATA", "lat": None, "lon": None, "timestamp": None}), 200

        return jsonify({"status": "OK", "lat": lat, "lon": lon, "timestamp": ts}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/sos/<trip_id>")
def sos(trip_id):
    """Send SOS alert for a trip (accepts Mongo _id hex or trip_id)."""
    try:
        trip = None
        try:
            trip = trips_collection.find_one({"_id": ObjectId(trip_id)})
        except Exception:
            trip = None
        if not trip:
            trip = trips_collection.find_one({"trip_id": trip_id})

        if not trip:
            return jsonify({"error": "Trip not found"}), 404

        send_sos_alert(trip)
        return jsonify({"status": "SOS sent"}), 200
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
        
        detections = payload.get("detections", {})
        labels = _extract_detection_labels(detections)
        event_action = str(payload.get("event_action") or "frame").strip().lower()
        episode_id = str(payload.get("episode_id") or "").strip() or None
        event_key = str(payload.get("event_key") or "").strip() or None
        incoming_type_raw = (payload.get("event_type") or "").strip()
        is_sos = bool(payload.get("is_sos", False))
        is_generic_type = (not incoming_type_raw) or (incoming_type_raw in {"DETECTION", "AI Detection", "AI_DETECTION"})

        # Avoid flooding with empty frames - only store if there's actual content
        risk_lvl = str(payload.get("risk_level") or "").upper()
        risk_w = payload.get("risk_score_weighted")
        try:
            risk_w_f = float(risk_w) if risk_w is not None else 0.0
        except (TypeError, ValueError):
            risk_w_f = 0.0
        meaningful_risk = risk_lvl in {"MODERATE", "HIGH", "CRITICAL"} or risk_w_f >= 21.0

        # Reject generic empty frames regardless of risk-level bucket to avoid
        # filling DB with synthetic DETECTION rows that have no actual detections.
        if (not labels) and (not is_sos) and is_generic_type and event_action != "start":
            return jsonify({"message": "No detections; event skipped"}), 200
        
        # Additional strict check: if completely empty and not SOS/high-risk, skip it
        has_meaningful_data = bool(labels) or is_sos or meaningful_risk
        if not has_meaningful_data and is_generic_type:
            return jsonify({"message": "No meaningful data; event skipped"}), 200

        incoming_type = incoming_type_raw
        if is_generic_type:
            # Prefer a stable primary label; keep full list in event_labels.
            incoming_type = labels[0] if labels else "DETECTION"

        source_raw = str(payload.get("source") or payload.get("sos_source") or "ai_engine").strip().lower()
        if "mobile" in source_raw:
            source = "mobile_app"
        elif "ai" in source_raw:
            source = "ai_engine"
        else:
            source = source_raw or "ai_engine"

        if event_action == "end":
            end_ts = payload.get("episode_end_ts") or payload.get("timestamp") or datetime.utcnow().isoformat()
            duration_s = payload.get("duration_s")
            query = {}
            if episode_id:
                query["episode_id"] = episode_id
            elif event_key:
                query["event_key"] = event_key
            else:
                return jsonify({"message": "episode end ignored: missing episode_id/event_key"}), 200

            result = events_collection.update_one(
                query,
                {
                    "$set": {
                        "end_time": end_ts,
                        "duration_s": duration_s,
                        "status": "ended",
                        "received_at": datetime.utcnow(),
                    }
                },
            )
            if result.modified_count > 0:
                return jsonify({"message": "Event episode ended"}), 200
            return jsonify({"message": "Episode end skipped (not found)"}), 200

        if event_action == "start" and event_key:
            exists = events_collection.find_one({"event_key": event_key}, {"_id": 1})
            if exists:
                return jsonify({"message": "Duplicate episode ignored"}), 200

        event = {
            "event_id": str(uuid.uuid4()),
            "trip_id": payload.get("trip_id"),
            "timestamp": payload.get("timestamp") or datetime.utcnow().isoformat(),
            "start_time": payload.get("episode_start_ts") or payload.get("timestamp") or datetime.utcnow().isoformat(),
            "end_time": None,
            "status": "active" if event_action == "start" else "frame",
            "event_action": event_action,
            "episode_id": episode_id,
            "event_key": event_key,
            "event_type": incoming_type,
            "event_labels": labels,
            "detections": detections,
            "risk_score_temporal": payload.get("risk_score_temporal"),
            "risk_score_weighted": payload.get("risk_score_weighted"),
            "risk_level": payload.get("risk_level"),
            "reasons": payload.get("reasons", []),
            "is_sos": is_sos,
            "sos_source": payload.get("sos_source"),
            "driver_emotion": payload.get("driver_emotion"),
            "passenger_emotions": payload.get("passenger_emotions", []),
            "source": source,
            "metadata": payload.get("metadata", {}),
            "received_at": datetime.utcnow()
        }
        
        result = events_collection.insert_one(event)
        
        return jsonify({
            "message": "Event recorded",
            "event_id": event["event_id"],
            "risk_level": event.get("risk_level"),
            "source": source,
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/events")
def get_events():
    """Fetch all events (background detections when no active trip)."""
    try:
        limit = request.args.get("limit", 100, type=int)
        skip = request.args.get("skip", 0, type=int)

        risk_level = request.args.get("risk_level")
        event_type = request.args.get("event_type")
        start = request.args.get("start")
        end = request.args.get("end")
        # Default to including empty records to preserve prior UI behavior.
        # Clients can request include_empty=0 to show only meaningful detections.
        include_empty = str(request.args.get("include_empty", "1")).lower() in {"1", "true", "yes"}

        query = {}
        if risk_level:
            query["risk_level"] = risk_level
        if event_type:
            query["$or"] = [
                {"event_type": event_type},
                {"event_labels": event_type},
                {"detections.type": event_type},
                {"detections": event_type},
            ]

        # By default, suppress empty background frames (no detections) so the list shows actual events.
        if not include_empty:
            non_empty_clause = {
                "$or": [
                    {"detections.0": {"$exists": True}},
                    {"is_sos": True},
                    {"event_type": {"$nin": ["DETECTION", "AI Detection", "AI_DETECTION"]}},
                ]
            }
            if "$and" in query:
                query["$and"].append(non_empty_clause)
            else:
                query["$and"] = [non_empty_clause]

        start_dt = _parse_iso_to_utc_naive(start)
        end_dt = _parse_iso_to_utc_naive(end)
        if start_dt or end_dt:
            ra = {}
            if start_dt:
                ra["$gte"] = start_dt
            if end_dt:
                ra["$lt"] = end_dt
            query["received_at"] = ra

        # Sort by server-side receipt time (datetime) to avoid mixed-type timestamp sorting issues
        # (some older docs may have timestamp stored as string vs datetime).
        # Sort newest first (descending order by received_at, then timestamp)
        events = list(
            events_collection.find(query)
            .sort([("received_at", -1), ("timestamp", -1)])
            .skip(skip)
            .limit(limit)
        )
        
        for event in events:
            event["_id"] = str(event["_id"])

            existing_labels = event.get("event_labels")
            derived_labels = _extract_detection_labels(event.get("detections"))
            labels = existing_labels or derived_labels or []
            event["event_labels"] = labels

            # Ensure every event has a meaningful name in the response payload.
            raw_type = str(event.get("event_type") or "").strip()
            is_generic = (not raw_type) or (raw_type in {"DETECTION", "AI Detection", "AI_DETECTION", "Multiple"})
            if labels:
                event["event_type"] = ", ".join(labels) if len(labels) > 1 else labels[0]
            elif is_generic:
                event["event_type"] = "No Detections"

            event["timestamp"] = to_ist_display(event.get("timestamp"))
            event["received_at"] = to_ist_display(event.get("received_at"))
        
        total_count = events_collection.count_documents(query)
        
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


@app.post("/drivers/<driver_id>/calibration/frames")
def submit_calibration_frames(driver_id):
    """
    Receive calibration frame metrics from AI engine and update driver calibration.
    
    Payload: {
        "calibration_phase": "neutral|eyes_closed|yawning|head_turn",
        "metrics": [{"ear": 0.4, "mar": 0.1, "yaw_angle": 5}, ...]
    }
    """
    try:
        payload = request.get_json(silent=True) or {}
        phase = payload.get("calibration_phase", "neutral")
        metrics_list = payload.get("metrics", [])
        
        if not metrics_list:
            return jsonify({"error": "No metrics provided"}), 400
        
        # Ensure calibration doc exists
        if not get_driver_calibration(driver_id):
            create_driver_calibration(driver_id)
        
        # Map phase to sample fields
        phase_mapping = {
            "neutral": ("head_straight_samples", "ear_open_samples", "mar_closed_samples"),
            "eyes_closed": ("head_straight_samples", "ear_closed_samples", "mar_closed_samples"),
            "yawning": ("head_straight_samples", "ear_open_samples", "mar_open_samples"),
            "head_turn": ("head_turned_samples", "ear_open_samples", "mar_closed_samples"),
        }
        
        if phase not in phase_mapping:
            return jsonify({"error": f"Unknown phase: {phase}"}), 400
        
        head_field, ear_field, mar_field = phase_mapping[phase]
        
        # Extract metrics and add to calibration
        ear_values = []
        mar_values = []
        yaw_values = []
        
        for metric in metrics_list:
            if isinstance(metric, dict):
                try:
                    ear = float(metric.get("ear", 0))
                    mar = float(metric.get("mar", 0))
                    yaw = float(metric.get("yaw_angle", 0))
                    if ear > 0: ear_values.append(ear)
                    if mar > 0: mar_values.append(mar)
                    yaw_values.append(yaw)
                except (TypeError, ValueError):
                    continue
        
        # Update calibration document
        update_doc = {
            "$push": {}
        }
        
        if ear_values:
            update_doc["$push"][ear_field] = {"$each": ear_values}
        if mar_values:
            update_doc["$push"][mar_field] = {"$each": mar_values}
        if yaw_values:
            update_doc["$push"][head_field] = {"$each": yaw_values}
        
        update_doc["$set"] = {
            "calibration_status": "IN_PROGRESS",
            "last_updated": datetime.utcnow().isoformat()
        }
        
        calibration_collection.update_one(
            {"driver_id": driver_id},
            update_doc
        )
        
        return jsonify({
            "message": "Calibration frames received",
            "driver_id": driver_id,
            "phase": phase,
            "frames_added": len(metrics_list)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/drivers/<driver_id>/calibration/compute")
def compute_driver_thresholds(driver_id):
    """
    Compute personalized thresholds from collected calibration samples.
    Called when enough samples have been collected.
    """
    try:
        thresholds = compute_and_store_thresholds(driver_id)
        
        return jsonify({
            "message": "Thresholds computed successfully",
            "driver_id": driver_id,
            "thresholds": thresholds,
            "is_calibrated": True
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