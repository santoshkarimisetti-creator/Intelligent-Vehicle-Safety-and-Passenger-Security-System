"""Quick sanity checks for CalibrationEngine threshold computation.

Run:
  python -m ai_engine.tools.test_calibration_engine

This is not a full integration test; it validates the stats logic.
"""

from ai_engine.calibration_engine import CalibrationEngine, CalibrationPhase


def _make_metrics(*, ear: float, mar: float, yaw: float) -> dict:
    return {
        "face_detected": True,
        "ear": ear,
        "mar": mar,
        "yaw_angle": yaw,
    }


def test_calibration_engine_threshold_computation() -> None:
    engine = CalibrationEngine(
        phase_requirements={
            CalibrationPhase.NEUTRAL: engine_req(5),
            CalibrationPhase.EYES_CLOSED: engine_req(5),
            CalibrationPhase.YAWNING: engine_req(5),
            CalibrationPhase.HEAD_TURN: engine_req(5),
        },
        session_ttl_s=9999,
    )

    driver_id = "driver_test"
    engine.start(driver_id=driver_id)

    for _ in range(5):
        engine.add_metrics(driver_id=driver_id, metrics=_make_metrics(ear=0.30, mar=0.35, yaw=1.0), phase=CalibrationPhase.NEUTRAL)
    for _ in range(5):
        engine.add_metrics(driver_id=driver_id, metrics=_make_metrics(ear=0.12, mar=0.35, yaw=1.0), phase=CalibrationPhase.EYES_CLOSED)
    for _ in range(5):
        engine.add_metrics(driver_id=driver_id, metrics=_make_metrics(ear=0.30, mar=0.85, yaw=1.0), phase=CalibrationPhase.YAWNING)
    for _ in range(5):
        engine.add_metrics(driver_id=driver_id, metrics=_make_metrics(ear=0.30, mar=0.35, yaw=30.0), phase=CalibrationPhase.HEAD_TURN)

    thresholds, baseline = engine.compute_thresholds(driver_id=driver_id)

    assert 0.12 < thresholds["ear_drowsiness"] < 0.30
    assert 0.35 < thresholds["mar_yawning"] < 0.85
    assert 15.0 <= thresholds["head_turn"] <= 45.0

    assert isinstance(baseline, dict)


def engine_req(frames_needed: int):
    from ai_engine.calibration_engine import PhaseRequirements

    return PhaseRequirements(frames_needed=frames_needed)


def main() -> None:
    test_calibration_engine_threshold_computation()


if __name__ == "__main__":
    main()
