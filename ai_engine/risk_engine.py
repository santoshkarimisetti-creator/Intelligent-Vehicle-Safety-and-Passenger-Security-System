"""ai_engine.risk_engine

Risk scoring engine.

Separation of concerns:
- Inputs: behavior events (detections) + optional raw_scores + speed
- Outputs: weighted risk score + levels + per-trip counters
- Does NOT extract face metrics (EAR/MAR/yaw) from frames

This keeps risk logic independent from vision and temporal behavior detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _risk_level_temporal(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 35:
        return "MEDIUM"
    return "LOW"


def _risk_level_weighted(score: float) -> str:
    if score >= 76:
        return "CRITICAL"
    if score >= 51:
        return "HIGH"
    if score >= 21:
        return "MODERATE"
    return "SAFE"


def _fatigue_level(score: float) -> str:
    if score >= 75:
        return "SEVERE"
    if score >= 50:
        return "HIGH"
    if score >= 25:
        return "MODERATE"
    return "LOW"


@dataclass
class TripCounters:
    drowsiness_events: int = 0
    yawning_events: int = 0
    looking_away_events: int = 0
    overspeed_count: int = 0
    total_frames_analyzed: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "drowsiness_events": int(self.drowsiness_events),
            "yawning_events": int(self.yawning_events),
            "looking_away_events": int(self.looking_away_events),
            "overspeed_count": int(self.overspeed_count),
            "total_frames_analyzed": int(self.total_frames_analyzed),
        }


class RiskEngine:
    """Stateful per-trip risk scoring (counters + composite scores)."""

    def __init__(
        self,
        *,
        speed_limit_kmh: float = 80.0,
        speed_norm_cap_kmh: float = 120.0,
        weights: Optional[Dict[str, float]] = None,
    ) -> None:
        self._speed_limit_kmh = float(speed_limit_kmh)
        self._speed_norm_cap_kmh = float(speed_norm_cap_kmh)

        # w1 overspeed, w2 drowsiness, w3 distraction, w4 yawning
        self._weights = weights or {
            "w1_overspeed": 0.25,
            "w2_drowsiness": 0.30,
            "w3_distraction": 0.35,
            "w4_yawning": 0.10,
        }

        self._counters: Dict[str, TripCounters] = {}

    def get_trip_counters(self, *, trip_id: str) -> Dict[str, int]:
        return self._get_or_create(trip_id).as_dict()

    def reset_trip(self, *, trip_id: str) -> None:
        if trip_id in self._counters:
            del self._counters[trip_id]

    def compute(
        self,
        *,
        trip_id: str,
        detections: List[Dict[str, Any]],
        speed_kmh: float,
        raw_scores: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Compute temporal + weighted risk from behavior events.

        `detections`: output of behavior_engine (types: drowsiness/yawning/distraction)
        `raw_scores`: optional {eyes_closed_score, head_off_road_score, yawning_score} in 0..1.
                     If omitted, derives scores from detection confidences.
        """
        counters = self._get_or_create(trip_id)

        # Update counters from current frame events
        counters.total_frames_analyzed += 1

        speed = max(0.0, float(speed_kmh or 0.0))
        if speed > self._speed_limit_kmh:
            counters.overspeed_count += 1

        # Increment event counters once per frame per event type
        types = {str(d.get("type", "")) for d in (detections or [])}
        driver_not_visible = "driver_not_visible" in types
        if "drowsiness" in types:
            counters.drowsiness_events += 1
        if "yawning" in types or "fatigue_yawn" in types:
            counters.yawning_events += 1
        if "distraction" in types or "looking_away" in types:
            counters.looking_away_events += 1

        # Scores for formulas
        scores = self._resolve_scores(detections=detections, raw_scores=raw_scores)
        eyes_closed_score = _clamp(_to_float(scores.get("eyes_closed_score"), 0.0), 0.0, 1.0)
        head_off_road_score = _clamp(_to_float(scores.get("head_off_road_score"), 0.0), 0.0, 1.0)
        yawning_score = _clamp(_to_float(scores.get("yawning_score"), 0.0), 0.0, 1.0)

        # Reduce false positives from isolated low-confidence spikes.
        if counters.drowsiness_events <= 1 and eyes_closed_score < 0.35:
            eyes_closed_score *= 0.6
        if counters.looking_away_events <= 1 and head_off_road_score < 0.30:
            head_off_road_score *= 0.6
        if counters.yawning_events <= 1 and yawning_score < 0.35:
            yawning_score *= 0.6

        # Temporal score (rule-based escalation)
        base_score = (
            eyes_closed_score * 45.0
            + head_off_road_score * 30.0
            + yawning_score * 15.0
            + min(speed, self._speed_norm_cap_kmh) / max(self._speed_norm_cap_kmh, 1.0) * 10.0
        )

        # Escalation rules based on accumulated events
        if counters.drowsiness_events >= 3:
            base_score += 20.0
        elif counters.drowsiness_events >= 2:
            base_score += 10.0

        if counters.yawning_events >= 4:
            base_score += 15.0
        elif counters.yawning_events >= 2:
            base_score += 5.0

        if counters.looking_away_events >= 5:
            base_score += 25.0
        elif counters.looking_away_events >= 3:
            base_score += 15.0

        if counters.overspeed_count > 0:
            overspeed_ratio = counters.overspeed_count / max(counters.total_frames_analyzed, 1)
            if overspeed_ratio > 0.5 and (counters.drowsiness_events > 0 or counters.yawning_events > 0):
                base_score += 20.0

        temporal_score = _clamp(float(base_score), 0.0, 100.0)

        reasons: List[str] = []
        if driver_not_visible:
            reasons.append("driver_not_visible")
        if eyes_closed_score >= 0.6:
            reasons.append("high_eye_closure")
        if head_off_road_score >= 0.5:
            reasons.append("driver_distraction")
        if yawning_score >= 0.55:
            reasons.append("frequent_yawning")
        if speed >= self._speed_limit_kmh:
            reasons.append("elevated_speed")

        if counters.drowsiness_events >= 3:
            reasons.append("repeated_drowsiness")
        if counters.looking_away_events >= 3:
            reasons.append("persistent_distraction")
        if counters.overspeed_count > 3:
            reasons.append("continuous_speeding")

        weighted = self._compute_weighted(
            speed_kmh=speed,
            eyes_closed_score=eyes_closed_score,
            head_off_road_score=head_off_road_score,
            yawning_score=yawning_score,
        )

        # Policy override: driver face not visible should always be treated as HIGH risk.
        # The UI/backend expects `risk_level` to align with the weighted score, so we apply
        # a score floor rather than only overriding the label.
        if driver_not_visible:
            temporal_score = max(float(temporal_score), 60.0)
            weighted_score = max(float(weighted.get("risk_score_weighted") or 0.0), 51.0)
            weighted["risk_score_weighted"] = round(weighted_score, 2)
            weighted["risk_level_weighted"] = _risk_level_weighted(weighted_score)

        fatigue_score = _clamp(
            (
                0.55 * eyes_closed_score
                + 0.25 * yawning_score
                + 0.10 * min(1.0, counters.drowsiness_events / 3.0)
                + 0.10 * min(1.0, counters.yawning_events / 4.0)
            ) * 100.0,
            0.0,
            100.0,
        )

        recommended_level = weighted["risk_level_weighted"]

        return {
            "risk_score_temporal": round(temporal_score, 2),
            "risk_level_temporal": _risk_level_temporal(temporal_score),
            "risk_score_weighted": weighted["risk_score_weighted"],
            "risk_level_weighted": weighted["risk_level_weighted"],
            "risk_level": recommended_level,
            "reasons": reasons,
            "fatigue_score": round(float(fatigue_score), 2),
            "fatigue_level": _fatigue_level(float(fatigue_score)),
            "event_counters": counters.as_dict(),
            "weighted_breakdown": weighted["weighted_breakdown"],
            "weights": weighted["weights"],
        }

    def _get_or_create(self, trip_id: str) -> TripCounters:
        if trip_id not in self._counters:
            self._counters[trip_id] = TripCounters()
        return self._counters[trip_id]

    @staticmethod
    def _resolve_scores(
        *,
        detections: List[Dict[str, Any]],
        raw_scores: Optional[Dict[str, Any]],
    ) -> Dict[str, float]:
        # If provided, trust raw_scores from behavior layer
        if isinstance(raw_scores, dict) and raw_scores:
            return {
                "eyes_closed_score": _to_float(raw_scores.get("eyes_closed_score"), 0.0),
                "head_off_road_score": _to_float(raw_scores.get("head_off_road_score"), 0.0),
                "yawning_score": _to_float(raw_scores.get("yawning_score"), 0.0),
            }

        # Otherwise derive from event confidences
        by_type: Dict[str, float] = {}
        for d in detections or []:
            t = str(d.get("type", ""))
            c = _to_float(d.get("confidence"), 0.0)
            if c > by_type.get(t, 0.0):
                by_type[t] = c

        return {
            "eyes_closed_score": _clamp(by_type.get("drowsiness", 0.0), 0.0, 1.0),
            "head_off_road_score": _clamp(by_type.get("distraction", 0.0), 0.0, 1.0),
            "yawning_score": _clamp(
                max(by_type.get("yawning", 0.0), by_type.get("fatigue_yawn", 0.0)),
                0.0,
                1.0,
            ),
        }

    def _compute_weighted(
        self,
        *,
        speed_kmh: float,
        eyes_closed_score: float,
        head_off_road_score: float,
        yawning_score: float,
    ) -> Dict[str, Any]:
        speed = max(0.0, float(speed_kmh or 0.0))
        speed_normalized = min(1.0, speed / max(self._speed_norm_cap_kmh, 1.0))

        w1 = float(self._weights.get("w1_overspeed", 0.25))
        w2 = float(self._weights.get("w2_drowsiness", 0.30))
        w3 = float(self._weights.get("w3_distraction", 0.35))
        w4 = float(self._weights.get("w4_yawning", 0.10))

        weighted_score = (
            w1 * speed_normalized * 100.0
            + w2 * eyes_closed_score * 100.0
            + w3 * head_off_road_score * 100.0
            + w4 * yawning_score * 100.0
        )
        weighted_score = _clamp(weighted_score, 0.0, 100.0)

        return {
            "risk_score_weighted": round(weighted_score, 2),
            "risk_level_weighted": _risk_level_weighted(weighted_score),
            "weighted_breakdown": {
                "overspeed_component": round(w1 * speed_normalized * 100.0, 2),
                "drowsiness_component": round(w2 * eyes_closed_score * 100.0, 2),
                "distraction_component": round(w3 * head_off_road_score * 100.0, 2),
                "yawning_component": round(w4 * yawning_score * 100.0, 2),
            },
            "weights": {
                "w1_overspeed": w1,
                "w2_drowsiness": w2,
                "w3_distraction": w3,
                "w4_yawning": w4,
            },
        }


_risk_engine_singleton: Optional[RiskEngine] = None


def get_risk_engine() -> RiskEngine:
    global _risk_engine_singleton
    if _risk_engine_singleton is None:
        _risk_engine_singleton = RiskEngine()
    return _risk_engine_singleton
