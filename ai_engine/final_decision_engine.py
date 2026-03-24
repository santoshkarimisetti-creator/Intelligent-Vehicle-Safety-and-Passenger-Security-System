"""
ai_engine.final_decision_engine

Final decision / fusion logic combining:
- driver risk (continuous)
- emotion risk (continuous support signal)
- SOS override

Outputs:
- risk_score
- risk_score_weighted
- risk_level
- risk_level_weighted
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _risk_level_from_score(score_0_100: float) -> str:
    if score_0_100 >= 76.0:
        return "CRITICAL"
    if score_0_100 >= 51.0:
        return "HIGH"
    if score_0_100 >= 21.0:
        return "MODERATE"
    return "SAFE"


class FinalDecisionEngine:
    def __init__(self, *, beta: float = 0.15) -> None:
        self._beta = float(beta)

    def decide(
        self,
        *,
        risk_result: Dict[str, Any],
        emotion_result: Optional[Dict[str, Any]] = None,
        sos_triggered: bool = False,
    ) -> Dict[str, Any]:
        driver_risk = float(risk_result.get("risk_score_weighted") or 0.0)
        emotion_risk = float((emotion_result or {}).get("emotion_risk_score") or 0.0)

        # If DeepFace isn't available / or we don't have a meaningful emotion estimate,
        # don't reduce the driver risk due to missing emotion signal.
        if not emotion_result:
            emotion_risk = driver_risk / 100.0
        elif emotion_result.get("deepface_available") is False:
            emotion_risk = driver_risk / 100.0
        elif str(emotion_result.get("dominant_emotion") or "unknown") == "unknown":
            emotion_risk = driver_risk / 100.0

        if sos_triggered:
            final_score = 100.0
        else:
            # final_score = (1 - beta) * driver_risk + beta * (emotion_risk * 100)
            final_score = (1.0 - self._beta) * driver_risk + self._beta * (emotion_risk * 100.0)
            final_score = _clamp(final_score, 0.0, 100.0)

        risk_level_weighted = _risk_level_from_score(final_score)
        risk_level = risk_level_weighted

        return {
            "risk_score": round(final_score, 2),
            "risk_score_weighted": round(final_score, 2),
            "risk_level": risk_level,
            "risk_level_weighted": risk_level_weighted,
            "emotion_risk_score": round(emotion_risk, 4),
            "beta": self._beta,
        }


_final_decision_engine_singleton: Optional[FinalDecisionEngine] = None


def get_final_decision_engine() -> FinalDecisionEngine:
    global _final_decision_engine_singleton
    if _final_decision_engine_singleton is None:
        _final_decision_engine_singleton = FinalDecisionEngine(beta=0.15)
    return _final_decision_engine_singleton

