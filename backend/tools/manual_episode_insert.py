"""Manual backend insert sanity check.

Posts a synthetic AI episode (start + end) to the backend so you can confirm
MongoDB inserts/updates work even if the AI engine is not generating episodes.

Usage (PowerShell):
  py backend/tools/manual_episode_insert.py --mode events
  py backend/tools/manual_episode_insert.py --mode trip --driver-id test_driver
  py backend/tools/manual_episode_insert.py --mode both --driver-id test_driver

Defaults assume backend is running at http://localhost:5000.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_post_json(url: str, payload: Dict[str, Any], timeout_s: float = 8.0) -> Tuple[int, Dict[str, Any] | str]:
    body = json.dumps(payload).encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=float(timeout_s)) as resp:
            status = int(getattr(resp, "status", 200))
            raw = resp.read()
        if raw:
            try:
                return status, json.loads(raw.decode("utf-8"))
            except Exception:
                return status, raw.decode("utf-8", errors="replace")
        return status, {}
    except HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        msg: Dict[str, Any] | str
        if raw:
            try:
                msg = json.loads(raw.decode("utf-8"))
            except Exception:
                msg = raw.decode("utf-8", errors="replace")
        else:
            msg = str(exc)
        return int(exc.code), msg
    except URLError as exc:
        return 0, f"URLError: {exc}"


def _create_trip(backend: str, driver_id: str) -> str:
    url = f"{backend.rstrip('/')}/trips"
    status, data = _http_post_json(url, {"driver_id": driver_id})
    if status not in (200, 201):
        raise RuntimeError(f"Trip create failed: status={status} body={data}")
    if not isinstance(data, dict) or not data.get("trip_id"):
        raise RuntimeError(f"Trip create returned unexpected payload: {data}")
    return str(data["trip_id"])


def _episode_payloads(*, trip_id: str, event_type: str, duration_s: float = 1.6) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    episode_id = str(uuid.uuid4())
    start_ts = _iso_now()
    # Give end a slightly later timestamp so the duration makes sense.
    end_ts = datetime.now(timezone.utc).timestamp() + max(0.2, float(duration_s))
    end_iso = datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat()

    event_key = f"{trip_id}|manual|{event_type}|{start_ts}"

    start_payload: Dict[str, Any] = {
        "trip_id": trip_id,
        "timestamp": start_ts,
        "source": "manual_debug",
        "event_action": "start",
        "event_type": event_type,
        "event_key": event_key,
        "episode_id": episode_id,
        "episode_start_ts": start_ts,
        "detections": [
            {
                "type": event_type,
                "confidence": 0.99,
                "source": "manual_debug",
                "duration_s": float(duration_s),
            }
        ],
        "risk_score_weighted": 42.0,
        "risk_level": "HIGH",
        "reasons": ["manual episode insert sanity check"],
        "metadata": {"manual": True},
    }

    end_payload: Dict[str, Any] = {
        "trip_id": trip_id,
        "timestamp": end_iso,
        "source": "manual_debug",
        "event_action": "end",
        "event_type": event_type,
        "event_key": event_key,
        "episode_id": episode_id,
        "episode_start_ts": start_ts,
        "episode_end_ts": end_iso,
        "duration_s": float(duration_s),
        "detections": [],
        "risk_score_weighted": 42.0,
        "risk_level": "HIGH",
        "reasons": ["manual episode insert sanity check"],
        "metadata": {"manual": True},
    }

    return start_payload, end_payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="http://localhost:5000", help="Backend base URL")
    ap.add_argument("--mode", choices=["events", "trip", "both"], default="events")
    ap.add_argument("--driver-id", default="manual_driver", help="Used only when mode includes trip")
    ap.add_argument("--trip-id", default=None, help="Optional existing trip_id for mode=trip/both")
    ap.add_argument("--event-type", default="yawning", help="Episode event type")
    ap.add_argument("--duration-s", type=float, default=1.6, help="Episode duration")
    args = ap.parse_args()

    backend = str(args.backend)
    mode = str(args.mode)

    if mode in {"trip", "both"}:
        trip_id = str(args.trip_id) if args.trip_id else _create_trip(backend, str(args.driver_id))
        print(f"[manual] trip_id={trip_id}")
    else:
        # /events still accepts trip_id; it’s useful for correlation.
        trip_id = str(args.trip_id or f"idle-{uuid.uuid4()}")
        print(f"[manual] using trip_id={trip_id} (events mode)")

    start_payload, end_payload = _episode_payloads(
        trip_id=trip_id,
        event_type=str(args.event_type),
        duration_s=float(args.duration_s),
    )

    if mode in {"events", "both"}:
        url = f"{backend.rstrip('/')}/events"
        st, body = _http_post_json(url, start_payload)
        print(f"[manual] POST /events start -> status={st} body={body}")
        time.sleep(0.25)
        st, body = _http_post_json(url, end_payload)
        print(f"[manual] POST /events end   -> status={st} body={body}")

    if mode in {"trip", "both"}:
        url = f"{backend.rstrip('/')}/trips/{trip_id}/ai-results"
        st, body = _http_post_json(url, start_payload)
        print(f"[manual] POST /trips/<id>/ai-results start -> status={st} body={body}")
        time.sleep(0.25)
        st, body = _http_post_json(url, end_payload)
        print(f"[manual] POST /trips/<id>/ai-results end   -> status={st} body={body}")

    print("[manual] done")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[manual] cancelled")
        raise
