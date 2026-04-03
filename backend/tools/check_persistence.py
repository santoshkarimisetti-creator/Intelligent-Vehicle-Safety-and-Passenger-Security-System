"""backend.tools.check_persistence

Quick sanity-check to see where AI persistence is landing for a given trip_id.

Usage:
  python backend/tools/check_persistence.py --trip-id <uuid>

It prints:
- whether a trip document exists
- its status
- ai_events count
- events collection count filtered by trip_id

This script is read-only.
"""

from __future__ import annotations

import argparse

from pymongo import MongoClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trip-id", required=True)
    parser.add_argument("--mongo", default="mongodb://localhost:27017/")
    parser.add_argument("--db", default="ivs_db")
    args = parser.parse_args()

    trip_id = str(args.trip_id).strip()
    if not trip_id:
        raise SystemExit("trip_id is required")

    client = MongoClient(str(args.mongo))
    db = client[str(args.db)]

    trips = db["trips"]
    events = db["events"]

    trip = trips.find_one({"trip_id": trip_id})
    if not trip:
        print(f"trip: NOT FOUND (trip_id={trip_id})")
    else:
        status = trip.get("status")
        ai_events = trip.get("ai_events", []) or []
        print(f"trip: FOUND status={status} ai_events={len(ai_events)}")

    ev_count = events.count_documents({"trip_id": trip_id})
    print(f"events: count(trip_id={trip_id}) = {ev_count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
