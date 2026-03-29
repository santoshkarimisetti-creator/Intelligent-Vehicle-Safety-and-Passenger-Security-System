"""
ai_engine.alert_engine

Derive user-facing alerts/warnings from detections + risk state with cooldown.

Note:
- This module computes alert triggers; actual audio/UI rendering is handled elsewhere.
- Cooldown prevents repeated warnings from spamming.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple


class AlertEngine:
    def __init__(self) -> None:
        self._cooldown_s_default = float(os.getenv("ALERT_COOLDOWN_SEC", "10"))
        self._occlusion_cooldown_s = float(os.getenv("OCCLUSION_ALERT_COOLDOWN", "3"))
        # (trip_id, alert_key) -> last_emitted_ts (monotonic)
        self._last_emitted: Dict[Tuple[str, str], float] = {}

    def _can_emit(self, trip_id: str, alert_key: str) -> bool:
        now = time.monotonic()
        key = (trip_id, alert_key)
        last = self._last_emitted.get(key)
        cooldown_s = self._cooldown_s_default
        if alert_key in {"camera_blocked", "mouth_occluded"}:
            cooldown_s = self._occlusion_cooldown_s
        if last is None:
            self._last_emitted[key] = now
            return True
        if (now - last) >= cooldown_s:
            self._last_emitted[key] = now
            return True
        return False

    def get_warnings(
        self,
        *,
        trip_id: str,
        detections: Optional[List[Dict[str, Any]]] = None,
        risk_level_weighted: Optional[str] = None,
        sos_triggered: bool = False,
    ) -> List[Dict[str, Any]]:
        detections = detections or []
        types = {str(d.get("type", "")) for d in detections}

        warnings: List[Dict[str, Any]] = []

        def add(alert_key: str, severity: str, message: str, confidence: Optional[float] = None) -> None:
            if not self._can_emit(trip_id, alert_key):
                return
            w: Dict[str, Any] = {
                "type": alert_key,
                "severity": severity,
                "message": message,
            }
            if confidence is not None:
                w["confidence"] = confidence
            warnings.append(w)

        # Detection-based alerts (driver issues).
        if "drowsiness" in types:
            add("drowsiness", "MEDIUM", "Driver drowsiness detected.")
        if "yawning" in types:
            add("yawning", "MEDIUM", "Driver yawning detected.")
        if "distraction" in types:
            add("distraction", "MEDIUM", "Driver distraction / looking away detected.")
        if "driver_not_visible" in types:
            add("driver_not_visible", "HIGH", "Driver face not visible for prolonged duration.")
        if "mouth_occluded" in types:
            add("mouth_occluded", "HIGH", "Driver mouth region appears occluded.")
        if "driver_too_far_from_camera" in types:
            add("driver_too_far_from_camera", "MEDIUM", "Driver appears too far from the monitoring camera.")
        if "camera_blocked" in types:
            add("camera_blocked", "CRITICAL", "Driver monitoring camera appears blocked.")

        # Risk-based alerts.
        if risk_level_weighted == "HIGH":
            add("risk_high", "HIGH", "Overall risk level is HIGH.")
        elif risk_level_weighted == "CRITICAL":
            add("risk_critical", "CRITICAL", "Overall risk level is CRITICAL.")

        # SOS implies emergency (if your UI wants to show a separate alert).
        if sos_triggered:
            add("sos_triggered", "CRITICAL", "SOS triggered; emergency response required.")

        return warnings


_alert_engine_singleton: Optional[AlertEngine] = None


def get_alert_engine() -> AlertEngine:
    global _alert_engine_singleton
    if _alert_engine_singleton is None:
        _alert_engine_singleton = AlertEngine()
    return _alert_engine_singleton

