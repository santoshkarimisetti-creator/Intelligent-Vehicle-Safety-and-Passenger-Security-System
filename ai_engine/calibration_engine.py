"""ai_engine.calibration_engine

Structured, phase-based driver calibration.

Goals:
- Centralize calibration logic (phases, sample collection, threshold computation)
- Compute personalized thresholds from real landmark metrics (EAR/MAR/yaw)
- Freeze thresholds per driver by persisting to MongoDB (same DB as backend)

Phases:
- NEUTRAL: eyes open, mouth closed, head straight
- EYES_CLOSED: eyes closed naturally
- YAWNING: yawning / mouth wide open
- HEAD_TURN: head turned left/right

This engine is intentionally UI-agnostic: callers drive the phase progression
(explicitly or via `auto_advance=True`).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    from pymongo import MongoClient
except Exception:  # pragma: no cover
    MongoClient = None  # type: ignore


class CalibrationPhase(str, Enum):
    NEUTRAL = "neutral"
    EYES_CLOSED = "eyes_closed"
    YAWNING = "yawning"
    HEAD_TURN = "head_turn"
    COMPLETE = "complete"


DEFAULT_PHASE_ORDER: Tuple[CalibrationPhase, ...] = (
    CalibrationPhase.NEUTRAL,
    CalibrationPhase.EYES_CLOSED,
    CalibrationPhase.YAWNING,
    CalibrationPhase.HEAD_TURN,
)


@dataclass(frozen=True)
class PhaseRequirements:
    frames_needed: int


@dataclass
class CalibrationSession:
    driver_id: str
    current_phase: CalibrationPhase
    frames_by_phase: Dict[CalibrationPhase, List[Dict[str, float]]]
    started_at: float
    last_seen_at: float


@dataclass(frozen=True)
class CalibrationProgress:
    driver_id: str
    current_phase: CalibrationPhase
    frames_collected: Dict[str, int]
    frames_needed: Dict[str, int]
    is_complete: bool
    thresholds: Optional[Dict[str, float]] = None
    baseline: Optional[Dict[str, float]] = None


class CalibrationEngine:
    def __init__(
        self,
        *,
        phase_requirements: Optional[Dict[CalibrationPhase, PhaseRequirements]] = None,
        session_ttl_s: float = 20 * 60,
        mongo_uri: Optional[str] = None,
        mongo_db: Optional[str] = None,
        mongo_collection: Optional[str] = None,
        mongo_connect_timeout_ms: int = 1500,
    ) -> None:
        self._phase_requirements = phase_requirements or {
            CalibrationPhase.NEUTRAL: PhaseRequirements(frames_needed=int(os.getenv("CALIB_NEUTRAL_FRAMES", "30"))),
            CalibrationPhase.EYES_CLOSED: PhaseRequirements(frames_needed=int(os.getenv("CALIB_EYES_CLOSED_FRAMES", "20"))),
            CalibrationPhase.YAWNING: PhaseRequirements(frames_needed=int(os.getenv("CALIB_YAWNING_FRAMES", "20"))),
            CalibrationPhase.HEAD_TURN: PhaseRequirements(frames_needed=int(os.getenv("CALIB_HEAD_TURN_FRAMES", "20"))),
        }
        self._session_ttl_s = float(os.getenv("CALIB_SESSION_TTL", str(session_ttl_s)))

        self._mongo_uri = mongo_uri or os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        if mongo_db:
            self._mongo_db = mongo_db
        else:
            # Connect to existing database with records
            self._mongo_db = os.getenv("MONGO_DB", "ivs_db")
        self._mongo_collection = mongo_collection or os.getenv(
            "MONGO_CALIBRATION_COLLECTION", "driver_calibrations"
        )
        self._mongo_connect_timeout_ms = int(
            os.getenv("MONGO_CONNECT_TIMEOUT_MS", str(mongo_connect_timeout_ms))
        )

        self._sessions: Dict[str, CalibrationSession] = {}

    def start(self, *, driver_id: str, phase: CalibrationPhase = CalibrationPhase.NEUTRAL) -> CalibrationProgress:
        now = time.time()
        session = CalibrationSession(
            driver_id=driver_id,
            current_phase=phase,
            frames_by_phase={p: [] for p in DEFAULT_PHASE_ORDER},
            started_at=now,
            last_seen_at=now,
        )
        self._sessions[driver_id] = session
        return self.get_progress(driver_id=driver_id)

    def reset(self, *, driver_id: str) -> CalibrationProgress:
        if driver_id in self._sessions:
            del self._sessions[driver_id]
        return self.start(driver_id=driver_id)

    def set_phase(self, *, driver_id: str, phase: CalibrationPhase) -> CalibrationProgress:
        session = self._get_or_create_session(driver_id)
        session.current_phase = phase
        session.last_seen_at = time.time()
        return self.get_progress(driver_id=driver_id)

    def add_metrics(
        self,
        *,
        driver_id: str,
        metrics: Dict[str, Any],
        phase: Optional[CalibrationPhase] = None,
        auto_advance: bool = True,
    ) -> CalibrationProgress:
        self._expire_old_sessions()

        session = self._get_or_create_session(driver_id)
        session.last_seen_at = time.time()

        active_phase = phase or session.current_phase
        if active_phase == CalibrationPhase.COMPLETE:
            return self.get_progress(driver_id=driver_id)

        sample = self._extract_sample(metrics)
        if sample is None:
            return self.get_progress(driver_id=driver_id)

        session.frames_by_phase.setdefault(active_phase, []).append(sample)

        if auto_advance and self._is_phase_complete(session, active_phase):
            next_phase = self._next_phase(active_phase)
            session.current_phase = next_phase

        # If all phases complete, compute thresholds but don't persist unless asked.
        progress = self.get_progress(driver_id=driver_id)
        if progress.is_complete:
            thresholds, baseline = self.compute_thresholds(driver_id=driver_id)
            return CalibrationProgress(
                driver_id=driver_id,
                current_phase=CalibrationPhase.COMPLETE,
                frames_collected=progress.frames_collected,
                frames_needed=progress.frames_needed,
                is_complete=True,
                thresholds=thresholds,
                baseline=baseline,
            )

        return progress

    def compute_thresholds(self, *, driver_id: str) -> Tuple[Dict[str, float], Dict[str, float]]:
        session = self._sessions.get(driver_id)
        if session is None:
            raise ValueError("Calibration session not found")

        neutral = session.frames_by_phase.get(CalibrationPhase.NEUTRAL, [])
        closed = session.frames_by_phase.get(CalibrationPhase.EYES_CLOSED, [])
        yawning = session.frames_by_phase.get(CalibrationPhase.YAWNING, [])
        head_turn = session.frames_by_phase.get(CalibrationPhase.HEAD_TURN, [])

        if len(neutral) < self._phase_requirements[CalibrationPhase.NEUTRAL].frames_needed:
            raise ValueError("Insufficient NEUTRAL samples")
        if len(closed) < self._phase_requirements[CalibrationPhase.EYES_CLOSED].frames_needed:
            raise ValueError("Insufficient EYES_CLOSED samples")
        if len(yawning) < self._phase_requirements[CalibrationPhase.YAWNING].frames_needed:
            raise ValueError("Insufficient YAWNING samples")
        if len(head_turn) < self._phase_requirements[CalibrationPhase.HEAD_TURN].frames_needed:
            raise ValueError("Insufficient HEAD_TURN samples")

        neutral_ear = np.asarray([s["ear"] for s in neutral], dtype=np.float32)
        closed_ear = np.asarray([s["ear"] for s in closed], dtype=np.float32)

        neutral_mar = np.asarray([s["mar"] for s in neutral], dtype=np.float32)
        yawning_mar = np.asarray([s["mar"] for s in yawning], dtype=np.float32)

        neutral_yaw_abs = np.asarray([abs(s["yaw"]) for s in neutral], dtype=np.float32)
        turned_yaw_abs = np.asarray([abs(s["yaw"]) for s in head_turn], dtype=np.float32)

        ear_open_med = float(np.median(neutral_ear))
        ear_closed_med = float(np.median(closed_ear))
        if ear_open_med <= ear_closed_med:
            raise ValueError("Invalid EAR calibration: neutral <= closed")

        mar_neutral_med = float(np.median(neutral_mar))
        mar_yawn_med = float(np.median(yawning_mar))
        if mar_yawn_med <= mar_neutral_med:
            raise ValueError("Invalid MAR calibration: yawning <= neutral")

        # Thresholds as separation midpoints, with conservative clamps.
        ear_thr = float((ear_open_med + ear_closed_med) / 2.0)
        ear_thr = float(np.clip(ear_thr, ear_closed_med, ear_open_med))

        mar_thr = float((mar_neutral_med + mar_yawn_med) / 2.0)
        mar_thr = float(np.clip(mar_thr, mar_neutral_med, mar_yawn_med))

        neutral_yaw_p95 = float(np.percentile(neutral_yaw_abs, 95))
        turned_yaw_p05 = float(np.percentile(turned_yaw_abs, 5))

        head_thr = float((neutral_yaw_p95 + turned_yaw_p05) / 2.0)
        head_thr = float(np.clip(head_thr, 15.0, 45.0))

        thresholds = {
            "ear_drowsiness": round(ear_thr, 3),
            "mar_yawning": round(mar_thr, 3),
            "head_turn": round(head_thr, 1),
        }

        baseline = {
            "ear_open_median": round(ear_open_med, 3),
            "ear_closed_median": round(ear_closed_med, 3),
            "mar_neutral_median": round(mar_neutral_med, 3),
            "mar_yawn_median": round(mar_yawn_med, 3),
            "neutral_yaw_abs_p95": round(neutral_yaw_p95, 2),
            "turned_yaw_abs_p05": round(turned_yaw_p05, 2),
            "frames_total": int(
                len(neutral) + len(closed) + len(yawning) + len(head_turn)
            ),
        }

        return thresholds, baseline

    def freeze_thresholds(self, *, driver_id: str) -> Dict[str, Any]:
        thresholds, baseline = self.compute_thresholds(driver_id=driver_id)
        self._persist_to_mongo(driver_id=driver_id, thresholds=thresholds, baseline=baseline)
        return {
            "driver_id": driver_id,
            "status": "COMPLETED",
            "thresholds": thresholds,
            "baseline": baseline,
        }

    def get_progress(self, *, driver_id: str) -> CalibrationProgress:
        self._expire_old_sessions()
        session = self._sessions.get(driver_id)
        if session is None:
            # Not started yet.
            frames_needed = {p.value: r.frames_needed for p, r in self._phase_requirements.items()}
            return CalibrationProgress(
                driver_id=driver_id,
                current_phase=CalibrationPhase.NEUTRAL,
                frames_collected={p.value: 0 for p in DEFAULT_PHASE_ORDER},
                frames_needed=frames_needed,
                is_complete=False,
            )

        frames_collected = {
            p.value: len(session.frames_by_phase.get(p, [])) for p in DEFAULT_PHASE_ORDER
        }
        frames_needed = {p.value: r.frames_needed for p, r in self._phase_requirements.items()}
        is_complete = all(
            frames_collected.get(p.value, 0) >= self._phase_requirements[p].frames_needed
            for p in DEFAULT_PHASE_ORDER
        )

        return CalibrationProgress(
            driver_id=driver_id,
            current_phase=session.current_phase if not is_complete else CalibrationPhase.COMPLETE,
            frames_collected=frames_collected,
            frames_needed=frames_needed,
            is_complete=is_complete,
        )

    @staticmethod
    def phase_instructions(phase: CalibrationPhase) -> str:
        if phase == CalibrationPhase.NEUTRAL:
            return "Look straight ahead with neutral face. Eyes open, mouth closed."
        if phase == CalibrationPhase.EYES_CLOSED:
            return "Close your eyes naturally (no squinting) and hold."
        if phase == CalibrationPhase.YAWNING:
            return "Yawn widely a few times (mouth open)."
        if phase == CalibrationPhase.HEAD_TURN:
            return "Turn your head left/right slowly while keeping eyes open."
        return "Calibration complete."

    def _extract_sample(self, metrics: Dict[str, Any]) -> Optional[Dict[str, float]]:
        if not metrics or not bool(metrics.get("face_detected")):
            return None

        try:
            ear = float(metrics.get("ear", 0.0))
            mar = float(metrics.get("mar", 0.0))
            yaw = float(metrics.get("yaw_angle", 0.0))
        except Exception:
            return None

        # Reject zero/invalid metrics.
        if ear <= 0.0 or mar <= 0.0:
            return None

        return {"ear": ear, "mar": mar, "yaw": yaw}

    def _is_phase_complete(self, session: CalibrationSession, phase: CalibrationPhase) -> bool:
        needed = self._phase_requirements.get(phase)
        if needed is None:
            return True
        return len(session.frames_by_phase.get(phase, [])) >= needed.frames_needed

    @staticmethod
    def _next_phase(phase: CalibrationPhase) -> CalibrationPhase:
        try:
            idx = DEFAULT_PHASE_ORDER.index(phase)
        except ValueError:
            return CalibrationPhase.NEUTRAL
        if idx >= len(DEFAULT_PHASE_ORDER) - 1:
            return CalibrationPhase.COMPLETE
        return DEFAULT_PHASE_ORDER[idx + 1]

    def _get_or_create_session(self, driver_id: str) -> CalibrationSession:
        session = self._sessions.get(driver_id)
        if session is None:
            now = time.time()
            session = CalibrationSession(
                driver_id=driver_id,
                current_phase=CalibrationPhase.NEUTRAL,
                frames_by_phase={p: [] for p in DEFAULT_PHASE_ORDER},
                started_at=now,
                last_seen_at=now,
            )
            self._sessions[driver_id] = session
        return session

    def _expire_old_sessions(self) -> None:
        if self._session_ttl_s <= 0:
            return
        now = time.time()
        expired = [
            driver_id
            for driver_id, session in self._sessions.items()
            if (now - session.last_seen_at) > self._session_ttl_s
        ]
        for driver_id in expired:
            del self._sessions[driver_id]

    def _persist_to_mongo(
        self,
        *,
        driver_id: str,
        thresholds: Dict[str, float],
        baseline: Dict[str, float],
    ) -> None:
        if MongoClient is None:
            raise RuntimeError("pymongo is not available; cannot persist calibration")

        client = MongoClient(
            self._mongo_uri,
            serverSelectionTimeoutMS=self._mongo_connect_timeout_ms,
            connectTimeoutMS=self._mongo_connect_timeout_ms,
            socketTimeoutMS=self._mongo_connect_timeout_ms,
        )
        client.admin.command("ping")

        db = client[self._mongo_db]
        coll = db[self._mongo_collection]

        now = datetime.now(timezone.utc)
        update = {
            "$setOnInsert": {
                "created_at": now.isoformat(),
                "calibration_frames_needed": int(
                    sum(self._phase_requirements[p].frames_needed for p in DEFAULT_PHASE_ORDER)
                ),
            },
            "$set": {
                "driver_id": driver_id,
                "thresholds": thresholds,
                "baseline": baseline,
                "calibration_status": "COMPLETED",
                "is_calibrated": True,
                "frames_collected": int(baseline.get("frames_total", 0) or 0),
                "last_updated": now.isoformat(),
            }
        }

        coll.update_one({"driver_id": driver_id}, update, upsert=True)


_calibration_engine_singleton: Optional[CalibrationEngine] = None


def get_calibration_engine() -> CalibrationEngine:
    global _calibration_engine_singleton
    if _calibration_engine_singleton is None:
        _calibration_engine_singleton = CalibrationEngine()
    return _calibration_engine_singleton
