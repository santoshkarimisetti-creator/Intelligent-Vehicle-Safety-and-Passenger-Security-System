import numpy as np


def test_emotion_engine_placeholder_cache_reuse():
    import ai_engine.emotion_engine as emotion_module

    eng = emotion_module.EmotionEngine(interval_s=5.0)

    img = np.zeros((100, 100, 3), dtype=np.uint8)
    face_bbox = {"x": 10, "y": 10, "w": 50, "h": 50}

    first = eng.analyze_periodic(
        session_key="trip:test",
        image_bgr=img,
        driver_bbox=face_bbox,
        passenger_bboxes=[],
        force=True,
    )
    assert first["emotion_result"]["dominant_emotion"] == "unknown"
    assert first["reused_cached"] is False

    second = eng.analyze_periodic(
        session_key="trip:test",
        image_bgr=img,
        driver_bbox=face_bbox,
        passenger_bboxes=[],
        force=False,
    )
    assert second["emotion_result"]["dominant_emotion"] == "unknown"
    assert second["reused_cached"] is True

