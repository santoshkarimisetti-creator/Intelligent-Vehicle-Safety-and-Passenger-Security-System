"""
ai_engine.emotion_engine

DeepFace-based emotion detection wrapper.

Responsibilities:
- Lazy-load DeepFace on first use
- Use `cv_metrics["face_bbox"]` for cropping
- Return a stable emotion result:
  - dominant_emotion
  - confidence
  - probabilities
  - emotion_risk_score in [0, 1]
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import numpy as np

try:
    # DeepFace can be heavy; keep import resilient.
    from deepface import DeepFace  # type: ignore
except Exception:  # pragma: no cover
    DeepFace = None  # type: ignore


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


class EmotionEngine:
    def __init__(self) -> None:
        self._min_interval_ms = float(os.getenv("EMOTION_DETECTION_MIN_INTERVAL_MS", "800"))
        self._last_run_ts = 0.0
        self._last_emotion_result: Optional[Dict[str, Any]] = None

        # Map DeepFace emotions to risk weights (0..1).
        self._emotion_risk_weights: Dict[str, float] = {
            "fear": 0.95,
            "angry": 0.85,
            "sad": 0.75,
            "disgust": 0.85,
            "surprise": 0.55,
            "neutral": 0.15,
            "happy": 0.05,
        }

    def _should_run(self) -> bool:
        now = time.time()
        if self._last_run_ts <= 0:
            return True
        return (now - self._last_run_ts) * 1000.0 >= self._min_interval_ms

    @staticmethod
    def _crop_face(image_bgr: np.ndarray, face_bbox: Optional[Dict[str, Any]]) -> np.ndarray:
        """
        Crop image using face bbox for speed/stability.

        face_bbox expected keys: {x, y, w, h}
        """
        if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
            return image_bgr
        if not face_bbox:
            return image_bgr

        try:
            h, w = image_bgr.shape[:2]
            x = int(float(face_bbox.get("x", 0.0)))
            y = int(float(face_bbox.get("y", 0.0)))
            bw = int(float(face_bbox.get("w", 0.0)))
            bh = int(float(face_bbox.get("h", 0.0)))

            if bw <= 1 or bh <= 1:
                return image_bgr

            # Expand slightly to include context (but clamp to image bounds).
            pad = int(0.08 * max(bw, bh))
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(w, x + bw + pad)
            y2 = min(h, y + bh + pad)

            if x2 <= x1 or y2 <= y1:
                return image_bgr

            return image_bgr[y1:y2, x1:x2]
        except Exception:
            return image_bgr

    @staticmethod
    def _bgr_to_rgb(image_bgr: np.ndarray) -> np.ndarray:
        # OpenCV images are BGR; DeepFace expects RGB for numpy arrays.
        return image_bgr[..., ::-1]

    def predict_emotion(
        self,
        *,
        image_bgr: np.ndarray,
        face_bbox: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Predict dominant emotion and probabilities using DeepFace.
        """
        if not self._should_run():
            if self._last_emotion_result is not None:
                out = dict(self._last_emotion_result)
                out["throttled"] = True
                return out
            return {
                "dominant_emotion": "unknown",
                "confidence": 0.0,
                "probabilities": {},
                "emotion_risk_score": 0.0,
                "throttled": True,
            }

        if DeepFace is None:
            return {
                "dominant_emotion": "unknown",
                "confidence": 0.0,
                "probabilities": {},
                "emotion_risk_score": 0.0,
                "deepface_available": False,
            }

        cropped_bgr = self._crop_face(image_bgr=image_bgr, face_bbox=face_bbox)
        if cropped_bgr is None or getattr(cropped_bgr, "size", 0) == 0:
            return {
                "dominant_emotion": "unknown",
                "confidence": 0.0,
                "probabilities": {},
                "emotion_risk_score": 0.0,
                "crop_failed": True,
            }

        cropped_rgb = self._bgr_to_rgb(cropped_bgr)

        try:
            self._last_run_ts = time.time()
            out = DeepFace.analyze(  # type: ignore[attr-defined]
                cropped_rgb,
                actions=["emotion"],
                enforce_detection=False,
                detector_backend=os.getenv("DEEPFACE_DETECTOR_BACKEND", "opencv"),
            )
        except Exception as e:
            return {
                "dominant_emotion": "unknown",
                "confidence": 0.0,
                "probabilities": {},
                "emotion_risk_score": 0.0,
                "error": str(e),
            }

        # DeepFace can return list (multi-face) or dict.
        if isinstance(out, list) and out:
            out = out[0]
        if not isinstance(out, dict):
            return {
                "dominant_emotion": "unknown",
                "confidence": 0.0,
                "probabilities": {},
                "emotion_risk_score": 0.0,
                "unexpected_output": True,
            }

        probabilities = out.get("emotion") or {}
        if not isinstance(probabilities, dict):
            probabilities = {}

        dominant_emotion = str(out.get("dominant_emotion") or "unknown")
        if dominant_emotion == "unknown" and probabilities:
            dominant_emotion = max(probabilities.keys(), key=lambda k: probabilities.get(k, 0.0))

        try:
            dominant_prob = float(probabilities.get(dominant_emotion, 0.0))
        except Exception:
            dominant_prob = 0.0

        # DeepFace returns emotion probabilities as approx. percentages summing to ~100.
        denom = sum(float(v) for v in probabilities.values()) if probabilities else 0.0
        if denom <= 1e-8:
            emotion_risk_score = 0.0
        else:
            emotion_risk_score = 0.0
            for emo, p in probabilities.items():
                try:
                    p_f = float(p)
                except Exception:
                    continue
                weight = float(self._emotion_risk_weights.get(str(emo), 0.2))
                emotion_risk_score += (p_f / denom) * weight

        # Confidence returned to callers should be in [0, 1].
        confidence = dominant_prob
        # If DeepFace gives percent-like confidence (0..100), normalize.
        if confidence > 1.0:
            confidence = confidence / 100.0

        result = {
            "dominant_emotion": dominant_emotion,
            "confidence": float(_clamp(confidence, 0.0, 1.0)),
            "probabilities": probabilities,
            "emotion_risk_score": float(_clamp(emotion_risk_score, 0.0, 1.0)),
            "throttled": False,
        }

        self._last_emotion_result = dict(result)
        return result


_emotion_engine_singleton: Optional[EmotionEngine] = None


def get_emotion_engine() -> EmotionEngine:
    global _emotion_engine_singleton
    if _emotion_engine_singleton is None:
        _emotion_engine_singleton = EmotionEngine()
    return _emotion_engine_singleton

