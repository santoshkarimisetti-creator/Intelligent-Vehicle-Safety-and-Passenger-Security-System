"""Sanity tests for BehaviorEngine temporal triggering.

Run:
  python -m ai_engine.tools.test_behavior_engine
"""

from ai_engine.behavior_engine import BehaviorEngine


def test_behavior_engine_temporal_triggering() -> None:
    eng = BehaviorEngine(
        assumed_fps=10.0,
        buffer_seconds=2.0,
        smoothing_seconds=0.2,
        min_consecutive_frames={"drowsiness": 5, "yawning": 3, "distraction": 4},
        min_duration_s={"drowsiness": 0.0, "yawning": 0.0, "distraction": 0.0},
        cooldown_s={"drowsiness": 0.0, "yawning": 0.0, "distraction": 0.0},
        driver_ttl_s=9999,
    )

    thr = {"ear_drowsiness": 0.2, "mar_yawning": 0.6, "head_turn": 25}
    driver_id = "d1"

    # 4 low-ear frames -> should NOT trigger yet
    for i in range(4):
        out = eng.update(
            driver_id=driver_id,
            cv_metrics={"face_detected": True, "ear": 0.15, "mar": 0.3, "yaw_angle": 0.0},
            thresholds=thr,
            ts=1000.0 + i * 0.1,
        )
        assert not any(d["type"] == "drowsiness" for d in out["detections"])

    # 5th consecutive -> triggers
    out = eng.update(
        driver_id=driver_id,
        cv_metrics={"face_detected": True, "ear": 0.15, "mar": 0.3, "yaw_angle": 0.0},
        thresholds=thr,
        ts=1000.4,
    )
    assert any(d["type"] == "drowsiness" for d in out["detections"])

    # Yawning needs 3
    for i in range(2):
        out = eng.update(
            driver_id=driver_id,
            cv_metrics={"face_detected": True, "ear": 0.3, "mar": 0.8, "yaw_angle": 0.0},
            thresholds=thr,
            ts=2000.0 + i * 0.1,
        )
        assert not any(d["type"] == "yawning" for d in out["detections"])

    out = eng.update(
        driver_id=driver_id,
        cv_metrics={"face_detected": True, "ear": 0.3, "mar": 0.8, "yaw_angle": 0.0},
        thresholds=thr,
        ts=2000.2,
    )
    assert any(d["type"] == "yawning" for d in out["detections"])


def main() -> None:
    test_behavior_engine_temporal_triggering()

    # Distraction needs 4
    for i in range(3):
        out = eng.update(
            driver_id=driver_id,
            cv_metrics={"face_detected": True, "ear": 0.3, "mar": 0.3, "yaw_angle": 40.0},
            thresholds=thr,
            ts=3000.0 + i * 0.1,
        )
        assert not any(d["type"] == "distraction" for d in out["detections"])

    out = eng.update(
        driver_id=driver_id,
        cv_metrics={"face_detected": True, "ear": 0.3, "mar": 0.3, "yaw_angle": 40.0},
        thresholds=thr,
        ts=3000.3,
    )
    assert any(d["type"] == "distraction" for d in out["detections"])

    print("OK behavior_engine temporal triggering")


if __name__ == "__main__":
    main()
