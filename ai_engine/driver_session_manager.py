"""ai_engine.driver_session_manager

Session management for identity + personalization.

Responsibilities:
- Lock driver identity when a confident match occurs
- Prevent identity switching mid-session
- Load and cache thresholds for the active driver
- Detect driver changes (e.g., when a lock is first established) so callers can reset state

A "session" is keyed by `session_key` (typically `trip_id`).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.request import Request, urlopen


@dataclass
class DriverSession:
    session_key: str
    active_driver_id: str

    started_at: float = 0.0

    locked: bool = False
    locked_driver_id: Optional[str] = None
    locked_confidence: float = 0.0
    locked_at: Optional[float] = None

    thresholds: Optional[Dict[str, float]] = None
    thresholds_loaded_at: float = 0.0

    last_seen_at: float = 0.0

    # Identity visibility tracking (fixed identity per session)
    frame_counter: int = 0
    last_driver_seen_at: float = 0.0

    # Fixed driver encoding captured during calibration (stored on driver:{driver_id} session)
    driver_encoding: Optional[list[float]] = None


class DriverSessionManager:
    def __init__(
        self,
        *,
        backend_base_url: Optional[str] = None,
        thresholds_ttl_s: float = 300.0,
        session_ttl_s: float = 30 * 60,
        default_thresholds: Optional[Dict[str, float]] = None,
    ) -> None:
        self._backend_base_url = backend_base_url or os.getenv(
            "BACKEND_BASE_URL", "http://localhost:5000"
        )
        self._thresholds_ttl_s = float(os.getenv("THRESHOLD_CACHE_TTL", str(thresholds_ttl_s)))
        self._session_ttl_s = float(os.getenv("DRIVER_SESSION_TTL", str(session_ttl_s)))

        self._default_thresholds = default_thresholds or {
            "ear_drowsiness": float(os.getenv("DEFAULT_EAR_THRESH", "0.20")),
            "mar_yawning": float(os.getenv("DEFAULT_MAR_THRESH", "0.08")),  # FaceMesh MAR scale: 0.0-0.4 typical 0.03-0.10
            "head_turn": float(os.getenv("DEFAULT_HEAD_TURN_THRESH", "20")),
        }

        self._sessions: Dict[str, DriverSession] = {}

    def tick_frame(
        self,
        *,
        session_key: str,
        fallback_driver_id: str,
        now: Optional[float] = None,
    ) -> DriverSession:
        ts = float(now if now is not None else time.time())
        self._expire_old(ts)

        sess = self._sessions.get(session_key)
        if sess is None:
            sess = DriverSession(
                session_key=session_key,
                active_driver_id=fallback_driver_id,
                started_at=ts,
                last_seen_at=ts,
                last_driver_seen_at=0.0,
                frame_counter=0,
            )
            self._sessions[session_key] = sess

        if not float(getattr(sess, "started_at", 0.0) or 0.0):
            sess.started_at = ts

        sess.last_seen_at = ts
        sess.frame_counter = int(sess.frame_counter) + 1
        return sess

    def update_last_driver_seen(
        self,
        *,
        session_key: str,
        fallback_driver_id: str,
        now: Optional[float] = None,
    ) -> float:
        ts = float(now if now is not None else time.time())
        self._expire_old(ts)

        sess = self._sessions.get(session_key)
        if sess is None:
            sess = DriverSession(
                session_key=session_key,
                active_driver_id=fallback_driver_id,
                started_at=ts,
                last_seen_at=ts,
                last_driver_seen_at=ts,
            )
            self._sessions[session_key] = sess
        if not float(getattr(sess, "started_at", 0.0) or 0.0):
            sess.started_at = ts
        sess.last_seen_at = ts
        sess.last_driver_seen_at = ts
        return ts

    def get_last_driver_seen(
        self,
        *,
        session_key: str,
    ) -> float:
        sess = self._sessions.get(session_key)
        if sess is None:
            return 0.0
        return float(sess.last_driver_seen_at or 0.0)

    def set_driver_encoding(
        self,
        *,
        driver_id: str,
        encoding: list[float],
        now: Optional[float] = None,
    ) -> bool:
        """Store a single fixed driver encoding for this process lifetime.

        Stored under the synthetic session_key `driver:{driver_id}` so it can be
        reused across trips without ever reassigning identity.

        Returns True when encoding was set, False if one already existed.
        """
        ts = float(now if now is not None else time.time())
        self._expire_old(ts)

        key = f"driver:{str(driver_id)}"
        sess = self._sessions.get(key)
        if sess is None:
            sess = DriverSession(session_key=key, active_driver_id=str(driver_id), last_seen_at=ts)
            self._sessions[key] = sess

        sess.last_seen_at = ts
        if sess.driver_encoding is not None:
            return False

        sess.driver_encoding = list(encoding)
        # Seed last seen for the driver-level session.
        sess.last_driver_seen_at = ts
        return True

    def get_driver_encoding(self, *, driver_id: str) -> Optional[list[float]]:
        sess = self._sessions.get(f"driver:{str(driver_id)}")
        if sess is None:
            return None
        return sess.driver_encoding

    def observe_identity(
        self,
        *,
        session_key: str,
        fallback_driver_id: str,
        identity_driver_id: Optional[str],
        identity_confidence: float,
        identity_matched: bool,
        now: Optional[float] = None,
    ) -> Tuple[DriverSession, bool, Optional[str]]:
        """Update session with latest identity observation.

        Returns: (session, driver_changed, previous_driver_id)
        - driver_changed becomes True when active_driver_id changes (e.g. first time identity locks)
        """
        ts = float(now if now is not None else time.time())
        self._expire_old(ts)

        sess = self._sessions.get(session_key)
        if sess is None:
            sess = DriverSession(
                session_key=session_key,
                active_driver_id=fallback_driver_id,
                last_seen_at=ts,
            )
            self._sessions[session_key] = sess

        sess.last_seen_at = ts

        previous = sess.active_driver_id

        # Lock identity on first confident match
        if not sess.locked and identity_matched and identity_driver_id:
            sess.locked = True
            sess.locked_driver_id = str(identity_driver_id)
            sess.locked_confidence = float(identity_confidence)
            sess.locked_at = ts
            sess.active_driver_id = sess.locked_driver_id
            # Force re-load thresholds for the now-locked driver.
            sess.thresholds = None
            sess.thresholds_loaded_at = 0.0

        # If locked, never switch.
        if sess.locked and sess.locked_driver_id:
            sess.active_driver_id = sess.locked_driver_id
        else:
            # Not locked: keep fallback stable
            sess.active_driver_id = fallback_driver_id

        driver_changed = sess.active_driver_id != previous
        return sess, driver_changed, previous if driver_changed else None

    def get_thresholds(
        self,
        *,
        session_key: str,
        driver_id: str,
        now: Optional[float] = None,
    ) -> Dict[str, float]:
        ts = float(now if now is not None else time.time())
        sess = self._sessions.get(session_key)
        if sess is None:
            sess = DriverSession(session_key=session_key, active_driver_id=driver_id, last_seen_at=ts)
            self._sessions[session_key] = sess

        sess.last_seen_at = ts

        if sess.thresholds and (ts - sess.thresholds_loaded_at) < self._thresholds_ttl_s:
            return sess.thresholds

        thresholds = self._fetch_thresholds_from_backend(driver_id)
        sess.thresholds = thresholds
        sess.thresholds_loaded_at = ts
        return thresholds

    def reset_session(self, *, session_key: str) -> None:
        if session_key in self._sessions:
            del self._sessions[session_key]

    def export_session(self, *, session_key: str) -> Optional[Dict[str, Any]]:
        sess = self._sessions.get(session_key)
        if sess is None:
            return None
        return {
            "session_key": sess.session_key,
            "active_driver_id": sess.active_driver_id,
            "locked": bool(sess.locked),
            "locked_driver_id": sess.locked_driver_id,
            "locked_confidence": round(float(sess.locked_confidence), 3),
            "thresholds_loaded": bool(sess.thresholds is not None),
        }

    def _fetch_thresholds_from_backend(self, driver_id: str) -> Dict[str, float]:
        try:
            endpoint = f"{self._backend_base_url.rstrip('/')}/drivers/{driver_id}/thresholds"
            with urlopen(Request(endpoint, method="GET"), timeout=2) as response:
                if getattr(response, "status", 200) == 200:
                    data = json.load(response) or {}
                    thresholds = data.get("thresholds", {}) or {}
                    return {
                        "ear_drowsiness": float(thresholds.get("ear_drowsiness", self._default_thresholds["ear_drowsiness"])),
                        "mar_yawning": float(thresholds.get("mar_yawning", self._default_thresholds["mar_yawning"])),
                        "head_turn": float(thresholds.get("head_turn", self._default_thresholds["head_turn"])),
                    }
        except Exception:
            pass

        return dict(self._default_thresholds)

    def _expire_old(self, now: float) -> None:
        if self._session_ttl_s <= 0:
            return
        expired = [k for k, s in self._sessions.items() if (now - s.last_seen_at) > self._session_ttl_s]
        for k in expired:
            del self._sessions[k]


_driver_session_manager_singleton: Optional[DriverSessionManager] = None


def get_driver_session_manager() -> DriverSessionManager:
    global _driver_session_manager_singleton
    if _driver_session_manager_singleton is None:
        _driver_session_manager_singleton = DriverSessionManager()
    return _driver_session_manager_singleton
