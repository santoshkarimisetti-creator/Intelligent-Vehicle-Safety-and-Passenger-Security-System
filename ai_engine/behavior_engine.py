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
    yaw_ema: Optional[float] = None
    yawn_peak_mar: float = 0.0
    yawn_mar_series: Deque[float] = field(default_factory=deque)

    no_face_start_ts: Optional[float] = None
    too_far_start_ts: Optional[float] = None
    mouth_occluded_start_ts: Optional[float] = None
    mouth_area_baseline_ema: Optional[float] = None
    prev_mouth_center: Optional[Tuple[float, float]] = None
    prev_yaw_stable: Optional[float] = None
    blink_active: bool = False
    blink_start_ts: Optional[float] = None
    blink_timestamps: Deque[float] = field(default_factory=deque)
    baseline_learning_start_ts: Optional[float] = None

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
            # Distraction must be near-immediate for safety.
            "distraction": 1,
        }

        # Store a time-based version so activation can adapt to the real sampling rate.
        base_fps = max(self._assumed_fps, 1.0)
        self._min_consecutive_s: Dict[str, float] = {
            k: max(0.0, float(v) / base_fps) for k, v in self._min_consecutive_frames.items()
        }

        self._min_duration_s = min_duration_s or {
            "drowsiness": 0.45,
            "yawning": 0.25,
            "distraction": 0.0,
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
        self._blink_event_min_s = float(os.getenv("BLINK_EVENT_MIN_SECONDS", "0.05"))
        self._blink_event_max_s = float(os.getenv("BLINK_EVENT_MAX_SECONDS", "0.8"))
        self._blink_window_s = float(os.getenv("BLINK_WINDOW_SECONDS", "60.0"))
        self._face_missing_warn_s = float(os.getenv("FACE_MISSING_WARN_SECONDS", "2.0"))
        self._driver_not_visible_after_s = float(os.getenv("DRIVER_NOT_VISIBLE_AFTER_S", "3.0"))
        self._camera_blocked_crit_s = float(os.getenv("CAMERA_BLOCKED_CRITICAL_SECONDS", "5.0"))
        self._too_far_warn_s = float(os.getenv("TOO_FAR_WARN_SECONDS", "2.0"))
        self._min_face_presence_conf = float(os.getenv("MIN_FACE_PRESENCE_CONF", "0.5"))
        self._min_landmark_ratio = float(os.getenv("MIN_LANDMARK_RATIO", "0.7"))
        self._too_far_face_area_ratio = float(os.getenv("TOO_FAR_FACE_AREA_RATIO", "0.018"))
        self._too_far_eye_distance_norm = float(os.getenv("TOO_FAR_EYE_DISTANCE_NORM", "0.055"))
        self._baseline_learning_s = float(os.getenv("BASELINE_LEARNING_SECONDS", "10.0"))
        self._yaw_ema_alpha = float(os.getenv("YAW_EMA_ALPHA", "0.3"))
        self._mouth_occluded_warn_s = float(os.getenv("MOUTH_OCCLUDED_WARN_SECONDS", "1.0"))
        self._mouth_occluded_drop_ratio = float(os.getenv("MOUTH_OCCLUDED_DROP_RATIO", "0.22"))
        self._mouth_visibility_min_ratio = float(os.getenv("MOUTH_VISIBILITY_MIN_RATIO", "0.40"))
        self._mouth_jump_thresh = float(os.getenv("MOUTH_JUMP_THRESHOLD", "0.06"))
        self._mar_noise_occlusion_var = float(os.getenv("MAR_NOISE_OCCLUSION_VAR", "0.03"))
        self._occlusion_alert_cooldown_s = float(os.getenv("OCCLUSION_ALERT_COOLDOWN", "3.0"))
        # Distraction defaults tuned for earlier, stable triggering in real driving scenes.
        self._distraction_min_s = float(os.getenv("DISTRACTION_MIN_SECONDS", "0.6"))
        self._distraction_yaw_trigger_deg = float(os.getenv("DISTRACTION_YAW_TRIGGER_DEG", "45.0"))
        self._distraction_yaw_avg_frames = max(1, int(os.getenv("DISTRACTION_YAW_AVG_FRAMES", "3")))
        self._distraction_ear_gate_factor = float(os.getenv("DISTRACTION_EAR_GATE_FACTOR", "0.3"))

        # Yawning pattern tuning: sustained open-mouth + peak requirement.
        self._yawning_min_s = float(os.getenv("YAWNING_MIN_SECONDS", "0.9"))
        self._yawning_mar_scale = float(os.getenv("YAWNING_MAR_THRESHOLD_SCALE", "1.10"))
        self._yawning_peak_scale = float(os.getenv("YAWNING_PEAK_THRESHOLD_SCALE", "1.30"))
        self._yawning_mar_avg_frames = max(1, int(os.getenv("YAWNING_MAR_AVG_FRAMES", "5")))
        self._yawning_open_abs = float(os.getenv("YAWNING_OPEN_THRESHOLD_ABS", "0.58"))
        self._yawning_peak_abs = float(os.getenv("YAWNING_PEAK_THRESHOLD_ABS", "0.70"))
        self._yawning_ear_gate_factor = float(os.getenv("YAWNING_EAR_GATE_FACTOR", "0.97"))
        self._yawning_strong_peak_margin = float(os.getenv("YAWNING_STRONG_PEAK_MARGIN", "1.10"))
        self._yawning_open_release_scale = float(os.getenv("YAWNING_OPEN_RELEASE_SCALE", "0.97"))
        self._yawning_var_window = max(5, int(os.getenv("YAWNING_VARIANCE_WINDOW", "10")))
        self._yawning_max_variance = float(os.getenv("YAWNING_MAX_VARIANCE", "0.012"))
        self._yawning_max_step = float(os.getenv("YAWNING_MAX_STEP", "0.10"))
        self._yawning_min_rise_ratio = float(os.getenv("YAWNING_MIN_RISE_RATIO", "0.6"))

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

        state = self._drivers.get(driver_id)
        if state is None:
            state = _DriverBehaviorState()
            self._drivers[driver_id] = state
        state.last_seen_ts = now
        if state.baseline_learning_start_ts is None:
            state.baseline_learning_start_ts = now

        face_presence_conf = float(cv_metrics.get("face_presence_confidence", 1.0) or 0.0)
        landmark_ratio = float(cv_metrics.get("driver_landmark_ratio", 1.0) or 0.0)
        face_area_ratio = float(cv_metrics.get("face_area_ratio", 0.0) or 0.0)
        eye_distance_norm = float(cv_metrics.get("eye_distance_norm", 0.0) or 0.0)
        mouth_area_ratio = float(cv_metrics.get("mouth_area_ratio", 0.0) or 0.0)
        mouth_landmark_ratio = float(cv_metrics.get("mouth_landmark_ratio", 1.0) or 0.0)
        mouth_center_raw = cv_metrics.get("mouth_center", [0.0, 0.0])
        mouth_center = (
            float(mouth_center_raw[0]) if isinstance(mouth_center_raw, (list, tuple)) and len(mouth_center_raw) >= 2 else 0.0,
            float(mouth_center_raw[1]) if isinstance(mouth_center_raw, (list, tuple)) and len(mouth_center_raw) >= 2 else 0.0,
        )

        face_detected = bool(cv_metrics.get("face_detected"))
        low_quality_face = (face_presence_conf < self._min_face_presence_conf)

        # Fixed identity visibility (preferred): app.py provides the driver's last-seen age
        # based on periodic matching against a single calibration encoding.
        unseen_s_raw = cv_metrics.get("driver_last_seen_s_ago")
        if unseen_s_raw is not None:
            try:
                unseen_s = max(0.0, float(unseen_s_raw))
            except (TypeError, ValueError):
                unseen_s = 0.0

            if unseen_s >= float(self._driver_not_visible_after_s):
                self._clear_for_no_face(driver_id=driver_id, st=state, now=now)
                return {
                    "detections": [
                        {
                            "type": "driver_not_visible",
                            "confidence": 1.0,
                            "source": "behavior_engine",
                            "metric": "driver_last_seen_s_ago",
                            "value": round(float(unseen_s), 2),
                            "threshold": round(float(self._driver_not_visible_after_s), 2),
                            "duration_s": round(float(unseen_s), 2),
                        }
                    ],
                    "smoothed_metrics": {
                        "ear": 0.0,
                        "mar": 0.0,
                        "yaw_angle": 0.0,
                    },
                    "raw_scores": {
                        "eyes_closed_score": 0.0,
                        "head_off_road_score": 0.0,
                        "yawning_score": 0.0,
                    },
                }

            # Within grace window (< 3s since last match): do not emit driver_not_visible,
            # but also do not run temporal behavior scoring if the face isn't reliably detected.
            if (not face_detected) or low_quality_face:
                self._clear_for_no_face(driver_id=driver_id, st=state, now=now)
                return {
                    "detections": [],
                    "smoothed_metrics": {
                        "ear": 0.0,
                        "mar": 0.0,
                        "yaw_angle": 0.0,
                    },
                    "raw_scores": {
                        "eyes_closed_score": 0.0,
                        "head_off_road_score": 0.0,
                        "yawning_score": 0.0,
                    },
                }
        distance_ok_score = 0.0
        if face_area_ratio > 0.0:
            distance_ok_score += 0.6 * min(1.0, face_area_ratio / max(self._too_far_face_area_ratio, 1e-6))
        if eye_distance_norm > 0.0:
            distance_ok_score += 0.4 * min(1.0, eye_distance_norm / max(self._too_far_eye_distance_norm, 1e-6))
        too_far_face = face_detected and (distance_ok_score < 1.0)

        if (not face_detected) or low_quality_face:
            if state.no_face_start_ts is None:
                state.no_face_start_ts = now
            no_face_duration_s = max(0.0, now - float(state.no_face_start_ts))

            if too_far_face:
                if state.too_far_start_ts is None:
                    state.too_far_start_ts = now
            else:
                state.too_far_start_ts = None

            too_far_dur = max(0.0, now - float(state.too_far_start_ts)) if state.too_far_start_ts else 0.0

            self._clear_for_no_face(driver_id=driver_id, st=state, now=now)
            blink_count_60s, blink_rate_per_min = self._blink_stats(state=state, now=now)

            detections: List[Dict[str, Any]] = []
            if no_face_duration_s >= self._face_missing_warn_s:
                detections.append(
                    {
                        "type": "driver_not_visible",
                        "confidence": round(min(1.0, no_face_duration_s / max(self._face_missing_warn_s, 1e-6)), 3),
                        "source": "behavior_engine",
                        "metric": "face_visible",
                        "value": 0,
                        "threshold": 1,
                        "duration_s": round(no_face_duration_s, 2),
                    }
                )
            if too_far_dur >= self._too_far_warn_s:
                detections.append(
                    {
                        "type": "driver_too_far_from_camera",
                        "confidence": round(min(1.0, too_far_dur / max(self._too_far_warn_s, 1e-6)), 3),
                        "source": "behavior_engine",
                        "metric": "face_area_ratio",
                        "value": round(float(face_area_ratio), 4),
                        "threshold": round(float(self._too_far_face_area_ratio), 4),
                        "duration_s": round(too_far_dur, 2),
                    }
                )
            if no_face_duration_s >= self._camera_blocked_crit_s:
                detections.append(
                    {
                        "type": "camera_blocked",
                        "confidence": 1.0,
                        "source": "behavior_engine",
                        "metric": "no_face_duration_s",
                        "value": round(no_face_duration_s, 2),
                        "threshold": round(float(self._camera_blocked_crit_s), 2),
                        "duration_s": round(no_face_duration_s, 2),
                    }
                )

            detections = self._apply_detection_priority(detections)

            return {
                "detections": detections,
                "smoothed_metrics": {
                    "no_face_duration_s": round(no_face_duration_s, 2),
                    "face_presence_confidence": round(float(face_presence_conf), 3),
                    "driver_landmark_ratio": round(float(landmark_ratio), 3),
                    "face_area_ratio": round(float(face_area_ratio), 4),
                    "eye_distance_norm": round(float(eye_distance_norm), 4),
                    "mouth_area_ratio": round(float(mouth_area_ratio), 4),
                    "mouth_landmark_ratio": round(float(mouth_landmark_ratio), 3),
                    "blink_count_60s": int(blink_count_60s),
                    "blink_rate_per_min": round(float(blink_rate_per_min), 2),
                },
                "raw_scores": {
                    "eyes_closed_score": 0.0,
                    "head_off_road_score": 0.0,
                    "yawning_score": 0.0,
                },
                "message": "Face not detected or low-quality landmarks",
            }
        state.no_face_start_ts = None
        if too_far_face:
            if state.too_far_start_ts is None:
                state.too_far_start_ts = now
        else:
            state.too_far_start_ts = None

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
        state.buffer.append((now, ear, mar, yaw_abs))
        self._trim_buffer(state.buffer, now)

        effective_fps = self._estimate_fps(state.buffer, now)

        smoothed = self._compute_smoothed(state.buffer, now)
        ear_s = smoothed.get("ear", ear)
        mar_s = smoothed.get("mar", mar)
        yaw_s = smoothed.get("yaw_abs", yaw_abs)
        state.yaw_ema = self._ema(state.yaw_ema, float(yaw_s), alpha=self._yaw_ema_alpha)
        yaw_stable = float(state.yaw_ema if state.yaw_ema is not None else yaw_s)

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
            and yaw_stable < (head_thr * 0.7)
            and pitch < max(8.0, pitch_thr * 0.8)
            and roll < max(8.0, roll_thr * 0.8)
        )
        in_baseline_warmup = (now - float(state.baseline_learning_start_ts or now)) <= self._baseline_learning_s
        if neutral_candidate:
            alpha = 0.22 if in_baseline_warmup else 0.10
            state.ear_baseline_ema = self._ema(state.ear_baseline_ema, ear_eval, alpha=alpha)
            state.mar_baseline_ema = self._ema(state.mar_baseline_ema, mar_eval, alpha=alpha)
            state.yaw_baseline_ema = self._ema(state.yaw_baseline_ema, yaw_stable, alpha=alpha)
            if mouth_area_ratio > 0:
                state.mouth_area_baseline_ema = self._ema(state.mouth_area_baseline_ema, mouth_area_ratio, alpha=alpha)

        # Blend calibrated thresholds with current-session baselines.
        if state.ear_baseline_ema is not None:
            ear_dyn = max(0.10, min(0.30, state.ear_baseline_ema * 0.70))
            ear_thr = 0.2 * ear_thr + 0.8 * ear_dyn
        if state.mar_baseline_ema is not None:
            mar_dyn = max(0.45, min(0.90, state.mar_baseline_ema * 1.80))
            mar_thr = 0.2 * mar_thr + 0.8 * mar_dyn
        if state.yaw_baseline_ema is not None:
            head_dyn = max(10.0, min(50.0, state.yaw_baseline_ema + max(8.0, head_thr * 0.45)))
            head_thr = 0.7 * head_thr + 0.3 * head_dyn

        # Update consecutive counters based on SMOOTHED values
        mar_yawn_open_thr = max(float(mar_thr) * float(self._yawning_mar_scale), float(self._yawning_open_abs))
        mar_yawn_peak_thr = max(float(mar_thr) * float(self._yawning_peak_scale), float(self._yawning_peak_abs))
        mar_recent_yawn = self._recent_moving_average(
            state.buffer,
            index=2,
            last_n=self._yawning_mar_avg_frames,
            fallback=float(mar_eval),
        )

        ear_low = ear_eval > 0 and ear_eval < ear_thr
        mar_high = mar_recent_yawn > mar_yawn_open_thr
        mar_clear = mar_recent_yawn < (mar_yawn_open_thr * self._yawning_open_release_scale)
        # Require large head rotation for distraction to avoid false positives.
        yaw_activation_thr = max(float(head_thr), float(self._distraction_yaw_trigger_deg))
        pitch_activation_thr = max(float(pitch_thr), 16.0)
        roll_activation_thr = max(float(roll_thr), 16.0)

        # Smooth yaw across a short recent frame window to reduce jitter around threshold.
        yaw_recent = self._recent_moving_average(
            state.buffer,
            index=3,
            last_n=self._distraction_yaw_avg_frames,
            fallback=float(yaw_stable),
        )

        # Distraction activation is yaw-dominant, using short-window smoothing.
        yaw_high = yaw_recent >= yaw_activation_thr
        distraction_high = yaw_high

        state.consec_ear_low = (state.consec_ear_low + 1) if ear_low else 0
        state.consec_mar_high = (state.consec_mar_high + 1) if mar_high else 0
        state.consec_yaw_high = (state.consec_yaw_high + 1) if distraction_high else 0
        self._update_blink_state(state=state, ear_low=ear_low, now=now)
        blink_count_60s, blink_rate_per_min = self._blink_stats(state=state, now=now)

        ear_low_s, state.ear_low_start_ts = self._condition_duration_s(state.ear_low_start_ts, ear_low, now)
        if mar_high:
            if state.mar_high_start_ts is None:
                state.mar_high_start_ts = now
            mar_high_s = max(0.0, now - float(state.mar_high_start_ts))
        elif mar_clear:
            mar_high_s = 0.0
            state.mar_high_start_ts = None
        else:
            mar_high_s = max(0.0, now - float(state.mar_high_start_ts)) if state.mar_high_start_ts is not None else 0.0
        yaw_high_s, state.yaw_high_start_ts = self._condition_duration_s(state.yaw_high_start_ts, distraction_high, now)
        yawning_candidate_active = mar_high or (state.mar_high_start_ts is not None)

        if mar_high:
            state.yawn_peak_mar = max(float(state.yawn_peak_mar), float(mar_recent_yawn))
            state.yawn_mar_series.append(float(mar_recent_yawn))
            while len(state.yawn_mar_series) > self._yawning_var_window:
                state.yawn_mar_series.popleft()
        elif not state.yawning.active:
            state.yawn_peak_mar = 0.0
            state.yawn_mar_series.clear()

        detections: List[Dict[str, Any]] = []

        # Mouth occlusion checks: keep strict/simple signals only.
        mouth_drop_ratio = None
        mouth_occluded_now = False
        if not yawning_candidate_active:
            if state.mouth_area_baseline_ema and state.mouth_area_baseline_ema > 1e-6 and mouth_area_ratio > 0:
                mouth_drop_ratio = float(mouth_area_ratio / state.mouth_area_baseline_ema)
                if mouth_drop_ratio < self._mouth_occluded_drop_ratio:
                    mouth_occluded_now = True
            if mouth_landmark_ratio < self._mouth_visibility_min_ratio:
                mouth_occluded_now = True

            mouth_jump = 0.0
            if state.prev_mouth_center is not None:
                dx = float(mouth_center[0] - state.prev_mouth_center[0])
                dy = float(mouth_center[1] - state.prev_mouth_center[1])
                mouth_jump = ((dx * dx + dy * dy) ** 0.5) / max(1.0, float(cv_metrics.get("image_width", 1)))
                face_stable = (
                    (state.prev_yaw_stable is not None)
                    and (abs(float(yaw_stable) - float(state.prev_yaw_stable)) < 4.0)
                    and (face_presence_conf >= self._min_face_presence_conf)
                )
                if face_stable and mouth_jump > self._mouth_jump_thresh:
                    mouth_occluded_now = True

        if mouth_occluded_now:
            if state.mouth_occluded_start_ts is None:
                state.mouth_occluded_start_ts = now
        else:
            state.mouth_occluded_start_ts = None

        mouth_occluded_dur = max(0.0, now - float(state.mouth_occluded_start_ts)) if state.mouth_occluded_start_ts else 0.0
        if mouth_occluded_dur >= self._mouth_occluded_warn_s:
            detections.append(
                {
                    "type": "mouth_occluded",
                    "confidence": round(min(1.0, mouth_occluded_dur / max(self._mouth_occluded_warn_s, 1e-6)), 3),
                    "source": "behavior_engine",
                    "metric": "mouth_visibility",
                    "value": round(float(mouth_landmark_ratio), 3),
                    "threshold": round(float(self._mouth_visibility_min_ratio), 3),
                    "duration_s": round(mouth_occluded_dur, 2),
                }
            )

        if state.too_far_start_ts is not None:
            too_far_dur = max(0.0, now - float(state.too_far_start_ts))
            if too_far_dur >= self._too_far_warn_s:
                detections.append(
                    {
                        "type": "driver_too_far_from_camera",
                        "confidence": round(min(1.0, too_far_dur / max(self._too_far_warn_s, 1e-6)), 3),
                        "source": "behavior_engine",
                        "metric": "face_area_ratio",
                        "value": round(float(face_area_ratio), 4),
                        "threshold": round(float(self._too_far_face_area_ratio), 4),
                        "duration_s": round(too_far_dur, 2),
                    }
                )

        # Drowsiness
        # Blink filtering: ignore short eye-closure dips under blink threshold.
        drowsy_gate_s = max(float(self._blink_ignore_s), float(self._min_duration_s.get("drowsiness", 0.0) or 0.0))
        mouth_clearly_open = mar_recent_yawn >= mar_yawn_open_thr
        if yawning_candidate_active:
            state.ear_low_start_ts = None
            state.consec_ear_low = 0
            ear_low_s = 0.0
        ear_low_for_drowsy = ear_low and (not yawning_candidate_active)

        if (not mouth_clearly_open) and self._should_activate(driver_id, "drowsiness", ear_low_s if ear_low_for_drowsy else 0.0, now, min_required_s=drowsy_gate_s):
            self._activate_episode(state.drowsy, now)
        if (mouth_clearly_open or yawning_candidate_active) and state.drowsy.active:
            self._end_episode(driver_id, "drowsiness", state.drowsy, now)
        if state.drowsy.active and not ear_low_for_drowsy:
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
        yawning_peak_ok = float(state.yawn_peak_mar) >= float(mar_yawn_peak_thr)
        yawning_eye_ok = ear_eval < (ear_thr * self._yawning_ear_gate_factor)
        yawning_strong_peak = float(state.yawn_peak_mar) >= (float(mar_yawn_peak_thr) * float(self._yawning_strong_peak_margin))
        yawning_eye_or_strong = yawning_eye_ok or yawning_strong_peak
        if self._should_activate(driver_id, "yawning", mar_high_s, now, min_required_s=self._yawning_min_s) and yawning_peak_ok and yawning_eye_or_strong and (not mouth_occluded_now):
            self._activate_episode(state.yawning, now)
        if state.yawning.active and not mar_high:
            self._end_episode(driver_id, "yawning", state.yawning, now)
            state.yawn_peak_mar = 0.0
            state.yawn_mar_series.clear()
        if state.yawning.active:
            conf = self._confidence_high(mar_recent_yawn, mar_yawn_open_thr)
            detections.append(
                {
                    "type": "yawning",
                    "confidence": round(conf, 3),
                    "source": "behavior_engine",
                    "metric": "mar",
                    "value": round(float(mar_recent_yawn), 4),
                    "threshold": round(float(mar_yawn_open_thr), 4),
                    "duration_s": round(self._episode_duration(state.yawning, now), 2),
                }
            )

        # Priority rule: if yawning is active, suppress drowsiness label for that frame.
        if any(d.get("type") == "yawning" for d in detections):
            detections = [d for d in detections if d.get("type") != "drowsiness"]

        # Distraction / looking away: only if head yaw is high AND eyes are not closed.
        # This prevents closed-eye events from being misclassified as distraction.
        distraction_condition = yaw_high_s > 0 and ear_eval > (ear_thr * self._distraction_ear_gate_factor)
        if self._should_activate(driver_id, "distraction", yaw_high_s, now, min_required_s=self._distraction_min_s) and distraction_condition:
            self._activate_episode(state.distraction, now)

        # End distraction when yaw returns near forward view.
        distraction_clear = (
            yaw_abs < (yaw_activation_thr * 0.45)
            and ear_eval > (ear_thr * 0.8)  # also ensure eyes not closed when clearing
        )
        if state.distraction.active and distraction_clear:
            self._end_episode(driver_id, "distraction", state.distraction, now)
        if state.distraction.active:
            yaw_score = self._score_high(yaw_recent, max(1.0, yaw_activation_thr))
            conf = yaw_score
            metric_name = "yaw_angle"
            metric_value = float(yaw_recent)
            metric_threshold = float(yaw_activation_thr)

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

            state.prev_mouth_center = mouth_center
            state.prev_yaw_stable = float(yaw_stable)

            detections = self._apply_detection_priority(detections)

        head_score = max(
            self._score_high(yaw_recent, max(1.0, yaw_activation_thr)),
            self._score_high(pitch, max(1.0, pitch_activation_thr)),
            self._score_high(roll, max(1.0, roll_activation_thr)),
        )

        raw_scores = {
            "eyes_closed_score": self._score_low(ear_eval, ear_thr),
            "head_off_road_score": head_score,
            "yawning_score": self._score_high(mar_recent_yawn, max(1e-3, mar_yawn_open_thr)),
        }

        return {
            "detections": detections,
            "smoothed_metrics": {
                "ear": float(ear_s),
                "mar": float(mar_s),
                "mar_yawning_avg": float(mar_recent_yawn),
                "yaw_angle": float(yaw_stable),
                "yaw_angle_ema": float(yaw_stable),
                "yaw_distraction_avg": float(yaw_recent),
                "effective_fps": float(effective_fps),
                "buffer_len": int(len(state.buffer)),
                "pitch_angle": float(pitch),
                "roll_angle": float(roll),
                "yawn_peak_mar": float(state.yawn_peak_mar),
                "blink_count_60s": int(blink_count_60s),
                "blink_rate_per_min": round(float(blink_rate_per_min), 2),
                "face_presence_confidence": round(float(face_presence_conf), 3),
                "driver_landmark_ratio": round(float(landmark_ratio), 3),
                "face_area_ratio": round(float(face_area_ratio), 4),
                "eye_distance_norm": round(float(eye_distance_norm), 4),
                "mouth_area_ratio": round(float(mouth_area_ratio), 4),
                "mouth_landmark_ratio": round(float(mouth_landmark_ratio), 3),
                "mouth_center": [round(float(mouth_center[0]), 2), round(float(mouth_center[1]), 2)],
                "thresholds_effective": {
                    "ear_drowsiness": round(float(ear_thr), 4),
                    "mar_yawning": round(float(mar_thr), 4),
                    "mar_yawning_open": round(float(mar_yawn_open_thr), 4),
                    "mar_yawning_peak": round(float(mar_yawn_peak_thr), 4),
                    "yawning_ear_gate": round(float(ear_thr * self._yawning_ear_gate_factor), 4),
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
        st.yawn_peak_mar = 0.0
        st.yawn_mar_series.clear()
        st.yaw_ema = None
        st.no_face_start_ts = None
        st.too_far_start_ts = None
        st.mouth_occluded_start_ts = None
        st.mouth_area_baseline_ema = None
        st.prev_mouth_center = None
        st.prev_yaw_stable = None
        st.blink_active = False
        st.blink_start_ts = None
        st.blink_timestamps.clear()
        st.baseline_learning_start_ts = None
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

    @staticmethod
    def _recent_moving_average(
        buf: Deque[Tuple[float, float, float, float]],
        *,
        index: int,
        last_n: int,
        fallback: float,
    ) -> float:
        if not buf:
            return float(fallback)
        n = max(1, int(last_n))
        vals = [row[index] for row in list(buf)[-n:]]
        if not vals:
            return float(fallback)
        return float(sum(vals) / float(len(vals)))

    @staticmethod
    def _yawning_pattern_ok(
        mar_series: Deque[float],
        *,
        max_variance: float,
        max_step: float,
        min_rise_ratio: float,
    ) -> bool:
        vals = list(mar_series)
        if len(vals) < 5:
            return False

        mean = float(sum(vals) / len(vals))
        var = float(sum((v - mean) * (v - mean) for v in vals) / len(vals))
        if var > float(max_variance):
            return False

        deltas = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
        if not deltas:
            return False
        rise_ratio = sum(1 for d in deltas if d >= 0.0) / float(len(deltas))
        if rise_ratio < float(min_rise_ratio):
            return False
        if max(deltas) > float(max_step):
            return False

        return True

    @staticmethod
    def _variance(values: List[float]) -> float:
        if not values:
            return 0.0
        m = float(sum(values) / len(values))
        return float(sum((v - m) * (v - m) for v in values) / len(values))

    def _apply_detection_priority(self, detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not detections:
            return detections

        occlusion_types = {"camera_blocked", "mouth_occluded"}
        severe_face_quality_types = {"camera_blocked", "driver_not_visible"}
        types = {str(d.get("type", "")) for d in detections}
        if types & severe_face_quality_types:
            # Suppress yawning/drowsiness only when overall face quality is poor.
            detections = [d for d in detections if str(d.get("type", "")) not in {"yawning", "drowsiness"}]

        priority_rank = {
            "camera_blocked": 0,
            "mouth_occluded": 1,
            "distraction": 2,
            "driver_not_visible": 3,
            "yawning": 4,
            "drowsiness": 5,
            "driver_too_far_from_camera": 6,
        }

        now = time.time()
        filtered: List[Dict[str, Any]] = []
        for d in detections:
            t = str(d.get("type", ""))
            if t in occlusion_types:
                last = float(self._last_end_ts.get(("__occlusion__", t), 0.0) or 0.0)
                if (now - last) < self._occlusion_alert_cooldown_s:
                    continue
                self._last_end_ts[("__occlusion__", t)] = now
            filtered.append(d)

        return sorted(filtered, key=lambda d: priority_rank.get(str(d.get("type", "")), 99))

    def _clear_for_no_face(self, *, driver_id: str, st: _DriverBehaviorState, now: float) -> None:
        st.buffer.clear()
        st.consec_ear_low = 0
        st.consec_mar_high = 0
        st.consec_yaw_high = 0
        st.ear_low_start_ts = None
        st.mar_high_start_ts = None
        st.yaw_high_start_ts = None
        st.yawn_peak_mar = 0.0
        st.yawn_mar_series.clear()
        st.yaw_ema = None
        st.mouth_occluded_start_ts = None
        st.prev_mouth_center = None
        st.prev_yaw_stable = None
        if st.blink_active:
            st.blink_active = False
            st.blink_start_ts = None
        if st.drowsy.active:
            self._end_episode(driver_id, "drowsiness", st.drowsy, now)
        if st.yawning.active:
            self._end_episode(driver_id, "yawning", st.yawning, now)
        if st.distraction.active:
            self._end_episode(driver_id, "distraction", st.distraction, now)

    def _update_blink_state(self, *, state: _DriverBehaviorState, ear_low: bool, now: float) -> None:
        if ear_low:
            if not state.blink_active:
                state.blink_active = True
                state.blink_start_ts = now
            return

        if not state.blink_active:
            return

        dur = max(0.0, now - float(state.blink_start_ts or now))
        if self._blink_event_min_s <= dur <= self._blink_event_max_s:
            state.blink_timestamps.append(now)
        state.blink_active = False
        state.blink_start_ts = None

    def _blink_stats(self, *, state: _DriverBehaviorState, now: float) -> Tuple[int, float]:
        cutoff = now - self._blink_window_s
        while state.blink_timestamps and state.blink_timestamps[0] < cutoff:
            state.blink_timestamps.popleft()
        count = int(len(state.blink_timestamps))
        rate = (count / max(self._blink_window_s, 1e-6)) * 60.0
        return count, float(rate)

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
