import numpy as np


def test_emotion_engine_crop_and_risk(monkeypatch):
    # Import module and patch DeepFace with a deterministic fake.
    import ai_engine.emotion_engine as emotion_module

    class FakeDeepFace:
        @staticmethod
        def analyze(img, actions, enforce_detection, detector_backend):
            return {
                "dominant_emotion": "fear",
                "emotion": {
                    "fear": 80,
                    "happy": 5,
                    "neutral": 10,
                    "sad": 3,
                    "angry": 1,
                    "disgust": 1,
                    "surprise": 0,
                },
            }

    monkeypatch.setattr(emotion_module, "DeepFace", FakeDeepFace, raising=False)

    eng = emotion_module.EmotionEngine()
    eng._min_interval_ms = 0  # type: ignore[attr-defined]
    eng._last_run_ts = 0.0  # type: ignore[attr-defined]

    img = np.zeros((100, 100, 3), dtype=np.uint8)
    face_bbox = {"x": 10, "y": 10, "w": 50, "h": 50}

    # Ensure crop uses bbox (with padding) deterministically.
    cropped = eng._crop_face(img, face_bbox)  # type: ignore[attr-defined]
    assert cropped.shape[0] > 40
    assert cropped.shape[1] > 40

    out = eng.predict_emotion(image_bgr=img, face_bbox=face_bbox)
    assert out["dominant_emotion"] == "fear"
    assert abs(out["confidence"] - 0.8) < 1e-6
    assert 0.0 <= out["emotion_risk_score"] <= 1.0
    assert out["emotion_risk_score"] > 0.5

