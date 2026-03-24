"""ai_engine.behavior_engine

Temporal behavior detection (stateful).

This replaces single-frame thresholding with per-driver temporal logic:
- Per-driver rolling frame buffer
- Moving averages / smoothing
- Consecutive-frame counters
- Duration tracking (episodes)

Inputs:
- cv_metrics: {face_detected, ear, mar, yaw_angle, ...}
- thresholds: {ear_drowsiness, mar_yawning, head_turn}

Outputs:
- detections: list of current active behaviors (drowsiness/yawning/distraction)
- smoothed_metrics: ear/mar/yaw_angle after temporal smoothing
- raw_scores: stable 0..1 scores for risk computation
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple


@dataclass
class _Episode:
    active: bool = False
    start_ts: Optional[float] = None
    last_ts: Optional[float] = None


@dataclass
class _DriverBehaviorState:
    buffer: Deque[Tuple[float, float, float, float]] = field(default_factory=deque)  # (ts, ear, mar, yaw_abs)

    consec_ear_low: int = 0
    consec_mar_high: int = 0
    consec_yaw_high: int = 0

    drowsy: _Episode = field(default_factory=_Episode)
    yawning: _Episode = field(default_factory=_Episode)
    distraction: _Episode = field(default_factory=_Episode)

    ear_low_start_ts: Optional[float] = None
    mar_high_start_ts: Optional[float] = None
    yaw_high_start_ts: Optional[float] = None

    ear_baseline_ema: Optional[float] = None
    mar_baseline_ema: Optional[float] = None
    yaw_baseline_ema: Optional[float] = None

    last_seen_ts: float = 0.0


class BehaviorEngine:
    def __init__(
        self,
        *,
        buffer_seconds: float = 2.0,
        smoothing_seconds: float = 0.6,
        min_consecutive_frames: Optional[Dict[str, int]] = None,
        min_duration_s: Optional[Dict[str, float]] = None,
        cooldown_s: Optional[Dict[str, float]] = None,
        driver_ttl_s: float = 20 * 60,
        assumed_fps: float = 15.0,
    ) -> None:
        self._buffer_seconds = float(buffer_seconds)
        self._smoothing_seconds = float(smoothing_seconds)
        self._assumed_fps = float(assumed_fps)

        self._min_consecutive_frames = min_consecutive_frames or {
            "drowsiness": int(round(0.6 * self._assumed_fps)),  # ~0.6s
            "yawning": int(round(0.3 * self._assumed_fps)),  # ~0.3s
            "distraction": int(round(0.5 * self._assumed_fps)),  # ~0.5s
        }

        # Store a time-based version so activation can adapt to the real sampling rate.
        base_fps = max(self._assumed_fps, 1.0)
        self._min_consecutive_s: Dict[str, float] = {
            k: max(0.0, float(v) / base_fps) for k, v in self._min_consecutive_frames.items()
        }

        self._min_duration_s = min_duration_s or {
            "drowsiness": 0.45,
            "yawning": 0.25,
            "distraction": 0.45,
        }

        # Prevent back-to-back yawning/distraction spikes from duplicating immediately.
        self._cooldown_s = cooldown_s or {
            "drowsiness": 0.0,
            "yawning": 1.0,
            "distraction": 0.5,
        }

        self._driver_ttl_s = float(driver_ttl_s)
        self._drivers: Dict[str, _DriverBehaviorState] = {}

        # Ignore short low-EAR dips as normal blinks.
        self._blink_ignore_s = float(os.getenv("BLINK_IGNORE_SECONDS", "0.5"))
        self._distraction_min_s = float(os.getenv("DISTRACTION_MIN_SECONDS", "5.0"))

        # Extra head-pose thresholds to reduce false positives from yaw-only jitter.
        self._default_pitch_turn = float(os.getenv("DEFAULT_HEAD_PITCH_THRESH", "18"))
        self._default_roll_turn = float(os.getenv("DEFAULT_HEAD_ROLL_THRESH", "17"))

        # Track last end time for cooldown
        self._last_end_ts: Dict[Tuple[str, str], float] = {}  # (driver_id, event_type) -> ts

    def update(
        self,
        *,
        driver_id: str,
        cv_metrics: Dict[str, Any],
        thresholds: Dict[str, float],
        ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Update per-driver state and return current detections."""
        now = float(ts if ts is not None else time.time())
        self._expire_old_drivers(now)

        face_detected = bool(cv_metrics.get("face_detected"))
        if not face_detected:
            self._reset_driver(driver_id, now)
            return {
                "detections": [],
                "smoothed_metrics": {},
                "raw_scores": {
                    "eyes_closed_score": 0.0,
                    "head_off_road_score": 0.0,
                    "yawning_score": 0.0,
                },
                "message": "No face detected",
            }

        try:
            ear = float(cv_metrics.get("ear", 0.0) or 0.0)
            mar = float(cv_metrics.get("mar", 0.0) or 0.0)
            yaw = float(cv_metrics.get("yaw_angle", 0.0) or 0.0)
            pitch = abs(float(cv_metrics.get("pitch_angle", 0.0) or 0.0))
            roll = abs(float(cv_metrics.get("roll_angle", 0.0) or 0.0))
        except Exception:
            return {
                "detections": [],
                "smoothed_metrics": {},
                "raw_scores": {
                    "eyes_closed_score": 0.0,
                    "head_off_road_score": 0.0,
                    "yawning_score": 0.0,
                },
                "message": "Invalid metrics",
            }

        yaw_abs = abs(yaw)
        state = self._drivers.get(driver_id)
        if state is None:
            state = _DriverBehaviorState()
            self._drivers[driver_id] = state

        state.last_seen_ts = now
        state.buffer.append((now, ear, mar, yaw_abs))
        self._trim_buffer(state.buffer, now)

        effective_fps = self._estimate_fps(state.buffer, now)

        smoothed = self._compute_smoothed(state.buffer, now)
        ear_s = smoothed.get("ear", ear)
        mar_s = smoothed.get("mar", mar)
        yaw_s = smoothed.get("yaw_abs", yaw_abs)

        # Be conservative for misses:
        # - drowsiness: use lower EAR of raw vs smoothed
        # - yawning: use higher MAR of raw vs smoothed
        ear_eval = min(float(ear_s), float(ear))
        mar_eval = max(float(mar_s), float(mar))

        # Defaults match FaceMesh scale + driver_session defaults (MAR ~0.03–0.10 baseline).
        ear_thr = float(thresholds.get("ear_drowsiness", 0.20) or 0.20)
        mar_thr = float(thresholds.get("mar_yawning", 0.08) or 0.08)
        head_thr = float(thresholds.get("head_turn", 20.0) or 20.0)
        pitch_thr = float(thresholds.get("head_pitch", self._default_pitch_turn) or self._default_pitch_turn)
        roll_thr = float(thresholds.get("head_roll", self._default_roll_turn) or self._default_roll_turn)

        # Adaptive baseline update from likely-neutral windows.
        neutral_candidate = (
            ear_eval > ear_thr
            and mar_eval < mar_thr
            and yaw_s < (head_thr * 0.7)
            and pitch < max(8.0, pitch_thr * 0.8)
            and roll < max(8.0, roll_thr * 0.8)
        )
        if neutral_candidate:
            state.ear_baseline_ema = self._ema(state.ear_baseline_ema, ear_eval, alpha=0.12)
            state.mar_baseline_ema = self._ema(state.mar_baseline_ema, mar_eval, alpha=0.12)
            state.yaw_baseline_ema = self._ema(state.yaw_baseline_ema, yaw_s, alpha=0.12)

        # Blend calibrated thresholds with current-session baselines.
        if state.ear_baseline_ema is not None:
            ear_dyn = max(0.14, min(0.33, state.ear_baseline_ema * 0.82))
            ear_thr = 0.55 * ear_thr + 0.45 * ear_dyn
        if state.mar_baseline_ema is not None:
            mar_dyn = max(0.05, min(0.20, state.mar_baseline_ema * 2.10))
            mar_thr = 0.7 * mar_thr + 0.3 * mar_dyn
        if state.yaw_baseline_ema is not None:
            head_dyn = max(10.0, min(50.0, state.yaw_baseline_ema + max(8.0, head_thr * 0.45)))
            head_thr = 0.7 * head_thr + 0.3 * head_dyn

        # Update consecutive counters based on SMOOTHED values
        ear_low = ear_eval > 0 and ear_eval < ear_thr
        mar_high = mar_eval > mar_thr
        yaw_high = yaw_s > head_thr
        pose_high = pitch > pitch_thr or roll > roll_thr
        distraction_high = yaw_high or pose_high

        state.consec_ear_low = (state.consec_ear_low + 1) if ear_low else 0
        state.consec_mar_high = (state.consec_mar_high + 1) if mar_high else 0
        state.consec_yaw_high = (state.consec_yaw_high + 1) if distraction_high else 0

        ear_low_s, state.ear_low_start_ts = self._condition_duration_s(state.ear_low_start_ts, ear_low, now)
        mar_high_s, state.mar_high_start_ts = self._condition_duration_s(state.mar_high_start_ts, mar_high, now)
        yaw_high_s, state.yaw_high_start_ts = self._condition_duration_s(state.yaw_high_start_ts, distraction_high, now)

        detections: List[Dict[str, Any]] = []

        # Drowsiness
        # Blink filtering: ignore short eye-closure dips under blink threshold.
        drowsy_gate_s = max(float(self._blink_ignore_s), float(self._min_duration_s.get("drowsiness", 0.0) or 0.0))
        if self._should_activate(driver_id, "drowsiness", ear_low_s, now, min_required_s=drowsy_gate_s):
            self._activate_episode(state.drowsy, now)
        if state.drowsy.active and not ear_low:
            self._end_episode(driver_id, "drowsiness", state.drowsy, now)
        if state.drowsy.active:
            conf = self._confidence_low(ear_eval, ear_thr)
            detections.append(
                {
                    "type": "drowsiness",
                    "confidence": round(conf, 3),
                    "source": "behavior_engine",
                    "metric": "ear",
                    "value": round(float(ear_eval), 4),
                    "threshold": round(float(ear_thr), 4),
                    "duration_s": round(self._episode_duration(state.drowsy, now), 2),
                }
            )

        # Yawning
        if self._should_activate(driver_id, "yawning", mar_high_s, now):
            self._activate_episode(state.yawning, now)
        if state.yawning.active and not mar_high:
            self._end_episode(driver_id, "yawning", state.yawning, now)
        if state.yawning.active:
            conf = self._confidence_high(mar_eval, mar_thr)
            detections.append(
                {
                    "type": "yawning",
                    "confidence": round(conf, 3),
                    "source": "behavior_engine",
                    "metric": "mar",
                    "value": round(float(mar_eval), 4),
                    "threshold": round(float(mar_thr), 4),
                    "duration_s": round(self._episode_duration(state.yawning, now), 2),
                }
            )

        # Distraction / looking away: only if head pose is high AND eyes are not closed.
        # This prevents closed-eye events from being misclassified as distraction.
        distraction_condition = yaw_high_s > 0 and ear_eval > (ear_thr * 0.5)
        if self._should_activate(driver_id, "distraction", yaw_high_s, now, min_required_s=self._distraction_min_s) and distraction_condition:
            self._activate_episode(state.distraction, now)

        # End distraction only when clearly back to safe head pose (stricter hysteresis).
        # Use 0.6x threshold to avoid lingering distraction or false closed-eye misclassification.
        distraction_clear = (
            yaw_abs < (head_thr * 0.6)
            and pitch < (pitch_thr * 0.6)
            and roll < (roll_thr * 0.6)
            and ear_eval > (ear_thr * 0.8)  # also ensure eyes not closed when clearing
        )
        if state.distraction.active and distraction_clear:
            self._end_episode(driver_id, "distraction", state.distraction, now)
        if state.distraction.active:
            yaw_score = self._score_high(yaw_s, max(1.0, head_thr))
            pitch_score = self._score_high(pitch, max(1.0, pitch_thr))
            roll_score = self._score_high(roll, max(1.0, roll_thr))
            conf = max(yaw_score, pitch_score, roll_score)

            if yaw_score >= pitch_score and yaw_score >= roll_score:
                metric_name = "yaw_angle"
                metric_value = float(yaw_s)
                metric_threshold = float(head_thr)
            elif pitch_score >= roll_score:
                metric_name = "pitch_angle"
                metric_value = float(pitch)
                metric_threshold = float(pitch_thr)
            else:
                metric_name = "roll_angle"
                metric_value = float(roll)
                metric_threshold = float(roll_thr)

            detections.append(
                {
                    "type": "distraction",
                    "confidence": round(conf, 3),
                    "source": "behavior_engine",
                    "metric": metric_name,
                    "value": round(metric_value, 3),
                    "threshold": round(metric_threshold, 3),
                    "duration_s": round(self._episode_duration(state.distraction, now), 2),
                }
            )

        head_score = max(
            self._score_high(yaw_s, max(1.0, head_thr)),
            self._score_high(pitch, max(1.0, pitch_thr)),
            self._score_high(roll, max(1.0, roll_thr)),
        )

        raw_scores = {
            "eyes_closed_score": self._score_low(ear_eval, ear_thr),
            "head_off_road_score": head_score,
            "yawning_score": self._score_high(mar_eval, max(1e-3, mar_thr)),
        }

        return {
            "detections": detections,
            "smoothed_metrics": {
                "ear": float(ear_s),
                "mar": float(mar_s),
                "yaw_angle": float(yaw_s),
                "effective_fps": float(effective_fps),
                "buffer_len": int(len(state.buffer)),
                "pitch_angle": float(pitch),
                "roll_angle": float(roll),
                "thresholds_effective": {
                    "ear_drowsiness": round(float(ear_thr), 4),
                    "mar_yawning": round(float(mar_thr), 4),
                    "head_turn": round(float(head_thr), 3),
                    "head_pitch": round(float(pitch_thr), 3),
                    "head_roll": round(float(roll_thr), 3),
                },
            },
            "raw_scores": raw_scores,
        }

    def reset_driver(self, *, driver_id: str, ts: Optional[float] = None) -> None:
        """Clear all temporal state for a driver."""
        now = float(ts if ts is not None else time.time())
        self._reset_driver(driver_id, now)

    def reset_all(self) -> None:
        """Clear all drivers' temporal state."""
        self._drivers.clear()
        self._last_end_ts.clear()

    def _expire_old_drivers(self, now: float) -> None:
        if self._driver_ttl_s <= 0:
            return
        expired = [
            driver_id
            for driver_id, st in self._drivers.items()
            if (now - st.last_seen_ts) > self._driver_ttl_s
        ]
        for driver_id in expired:
            del self._drivers[driver_id]

    def _reset_driver(self, driver_id: str, now: float) -> None:
        st = self._drivers.get(driver_id)
        if st is None:
            return
        st.buffer.clear()
        st.consec_ear_low = 0
        st.consec_mar_high = 0
        st.consec_yaw_high = 0
        st.ear_low_start_ts = None
        st.mar_high_start_ts = None
        st.yaw_high_start_ts = None
        if st.drowsy.active:
            self._end_episode(driver_id, "drowsiness", st.drowsy, now)
        if st.yawning.active:
            self._end_episode(driver_id, "yawning", st.yawning, now)
        if st.distraction.active:
            self._end_episode(driver_id, "distraction", st.distraction, now)

    def _trim_buffer(self, buf: Deque[Tuple[float, float, float, float]], now: float) -> None:
        cutoff = now - self._buffer_seconds
        while buf and buf[0][0] < cutoff:
            buf.popleft()

    def _compute_smoothed(self, buf: Deque[Tuple[float, float, float, float]], now: float) -> Dict[str, float]:
        if not buf:
            return {}
        cutoff = now - self._smoothing_seconds
        vals = [(ear, mar, yaw) for (ts, ear, mar, yaw) in buf if ts >= cutoff]
        if not vals:
            # Fall back to last sample
            _, ear, mar, yaw = buf[-1]
            return {"ear": ear, "mar": mar, "yaw_abs": yaw}

        ears = [v[0] for v in vals]
        mars = [v[1] for v in vals]
        yaws = [v[2] for v in vals]

        # median is robust to spikes
        return {
            "ear": float(_median(ears)),
            "mar": float(_median(mars)),
            "yaw_abs": float(_median(yaws)),
        }

    def _should_activate(
        self,
        driver_id: str,
        event_type: str,
        active_duration_s: float,
        now: float,
        min_required_s: Optional[float] = None,
    ) -> bool:
        # Time-based gate: robust across variable frame rates.
        min_consec_s = float(self._min_consecutive_s.get(event_type, 0.0) or 0.0)
        min_dur = float(self._min_duration_s.get(event_type, 0.0) or 0.0)
        required_s = max(min_consec_s, min_dur)
        if min_required_s is not None:
            required_s = max(required_s, float(min_required_s))
        if active_duration_s < required_s:
            return False

        cooldown = float(self._cooldown_s.get(event_type, 0.0) or 0.0)
        last_end = float(self._last_end_ts.get((driver_id, event_type), 0.0) or 0.0)
        if cooldown > 0 and (now - last_end) < cooldown:
            return False

        return True

    @staticmethod
    def _condition_duration_s(start_ts: Optional[float], is_active: bool, now: float) -> Tuple[float, Optional[float]]:
        if not is_active:
            return 0.0, None
        if start_ts is None:
            start_ts = now
        return max(0.0, now - start_ts), start_ts

    @staticmethod
    def _ema(prev: Optional[float], value: float, alpha: float) -> float:
        if prev is None:
            return float(value)
        a = max(0.01, min(1.0, float(alpha)))
        return float((1.0 - a) * prev + a * value)

    def _estimate_fps(self, buf: Deque[Tuple[float, float, float, float]], now: float) -> float:
        """Estimate effective fps from recent timestamps.

        This allows the engine to behave similarly across clients (mobile/web) that
        sample at different cadences.
        """
        if len(buf) < 3:
            return float(self._assumed_fps)

        # Use a short window so changes in cadence converge quickly.
        window_s = 1.2
        cutoff = now - window_s
        ts = [t for (t, _, _, _) in buf if t >= cutoff]
        if len(ts) < 3:
            return float(self._assumed_fps)

        dts: List[float] = []
        for i in range(1, len(ts)):
            dt = float(ts[i] - ts[i - 1])
            if dt <= 0:
                continue
            dts.append(dt)

        if not dts:
            return float(self._assumed_fps)

        dt_med = _median(dts)
        if dt_med <= 1e-6:
            return float(self._assumed_fps)

        fps = 1.0 / dt_med
        return float(max(1.0, min(30.0, fps)))

    @staticmethod
    def _activate_episode(ep: _Episode, now: float) -> None:
        if ep.active:
            ep.last_ts = now
            return
        ep.active = True
        ep.start_ts = now
        ep.last_ts = now

    def _end_episode(self, driver_id: str, event_type: str, ep: _Episode, now: float) -> None:
        if not ep.active:
            return
        ep.active = False
        ep.last_ts = now
        self._last_end_ts[(driver_id, event_type)] = now

    @staticmethod
    def _episode_duration(ep: _Episode, now: float) -> float:
        if not ep.active or ep.start_ts is None:
            return 0.0
        return max(0.0, float(now - ep.start_ts))

    @staticmethod
    def _confidence_low(value: float, thr: float) -> float:
        if thr <= 1e-8:
            return 0.0
        # value smaller than thr => higher confidence
        return max(0.0, min(1.0, 1.0 - (value / thr)))

    @staticmethod
    def _confidence_high(value: float, thr: float) -> float:
        if thr <= 1e-8:
            return 0.0
        # value larger than thr => higher confidence
        return max(0.0, min(1.0, (value - thr) / max(thr, 1e-6)))

    @staticmethod
    def _score_low(value: float, thr: float) -> float:
        # 0 when above threshold; approaches 1 as value approaches 0
        if value >= thr:
            return 0.0
        if thr <= 1e-8:
            return 0.0
        return max(0.0, min(1.0, 1.0 - (value / thr)))

    @staticmethod
    def _score_high(value: float, thr: float) -> float:
        # 0 at/below threshold; increases with magnitude
        if value <= thr:
            return 0.0
        # scale so that 2x threshold ~= 1.0
        return max(0.0, min(1.0, (value - thr) / max(thr, 1e-6)))


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    values_sorted = sorted(values)
    mid = len(values_sorted) // 2
    if len(values_sorted) % 2 == 1:
        return float(values_sorted[mid])
    return float((values_sorted[mid - 1] + values_sorted[mid]) / 2.0)


_behavior_engine_singleton: Optional[BehaviorEngine] = None


def get_behavior_engine() -> BehaviorEngine:
    global _behavior_engine_singleton
    if _behavior_engine_singleton is None:
        _behavior_engine_singleton = BehaviorEngine()
    return _behavior_engine_singleton
