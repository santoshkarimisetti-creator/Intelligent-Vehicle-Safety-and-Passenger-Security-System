def test_final_decision_engine_fusion_formula():
    from ai_engine.final_decision_engine import get_final_decision_engine

    engine = get_final_decision_engine()

    risk_result = {"risk_score_weighted": 50.0}
    emotion_result = {"emotion_risk_score": 0.8}

    out = engine.decide(risk_result=risk_result, emotion_result=emotion_result, sos_triggered=False)

    # final_score = (1 - beta) * driver_risk + beta * (emotion_risk * 100)
    # beta=0.15 => 0.85*50 + 0.15*80 = 42.5 + 12 = 54.5
    assert abs(out["risk_score"] - 54.5) < 1e-6
    assert out["risk_score_weighted"] == out["risk_score"]
    assert out["risk_level_weighted"] == "HIGH"
    assert out["risk_level"] == "HIGH"


def test_final_decision_engine_sos_override():
    from ai_engine.final_decision_engine import get_final_decision_engine

    engine = get_final_decision_engine()

    risk_result = {"risk_score_weighted": 20.0}
    emotion_result = {"emotion_risk_score": 0.0}

    out = engine.decide(risk_result=risk_result, emotion_result=emotion_result, sos_triggered=True)
    assert out["risk_score"] == 100.0
    assert out["risk_score_weighted"] == 100.0
    assert out["risk_level_weighted"] == "CRITICAL"
    assert out["risk_level"] == "CRITICAL"

