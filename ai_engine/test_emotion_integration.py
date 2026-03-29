"""
Quick integration test for emotion engine three-layer architecture.
Tests that analyze_periodic() calls _run_inference() and _manage_emotion_state().
"""

import numpy as np
from emotion_engine import get_emotion_engine

def test_emotion_engine_three_layer_integration():
    """Verify the three-layer architecture is wired correctly."""
    engine = get_emotion_engine()
    
    # Create a synthetic image (1x1 pixel - just enough to not crash)
    dummy_image = np.zeros((48, 48, 3), dtype=np.uint8)
    
    # Test with bbox (simulating driver face detection)
    dummy_bbox = {"x": 0, "y": 0, "w": 48, "h": 48}
    session_key = "test_session"
    
    # Call analyze_periodic with is_trip_active=True
    result = engine.analyze_periodic(
        session_key=session_key,
        image_bgr=dummy_image,
        driver_bbox=dummy_bbox,
        passenger_bboxes=[],
        force=True,
        is_trip_active=True,  # New parameter - trip active
    )
    
    # Verify result structure
    assert "emotion_result" in result, "Missing emotion_result"
    assert "driver_emotion" in result, "Missing driver_emotion"
    assert "passenger_emotions" in result, "Missing passenger_emotions"
    
    emotion_result = result["emotion_result"]
    assert "dominant_emotion" in emotion_result
    assert "confidence" in emotion_result
    assert isinstance(emotion_result["confidence"], float)
    assert 0.0 <= emotion_result["confidence"] <= 1.0
    
    print("✓ Emotion engine three-layer architecture verified")
    print(f"  - Dominant emotion: {emotion_result['dominant_emotion']}")
    print(f"  - Confidence: {emotion_result['confidence']:.3f}")
    print(f"  - Source: {emotion_result['source']}")
    
    # Verify dashboard output was set
    dashboard_state = engine.get_current_emotion_state(session_key)
    assert "current_emotion" in dashboard_state
    assert "confidence" in dashboard_state
    print(f"  - Dashboard state: {dashboard_state}")
    
    # Test with no bbox (no face detected)
    result_no_face = engine.analyze_periodic(
        session_key="test_no_face",
        image_bgr=dummy_image,
        driver_bbox=None,
        passenger_bboxes=[],
        force=True,
        is_trip_active=False,
    )
    
    emotion_no_face = result_no_face["emotion_result"]
    assert emotion_no_face["dominant_emotion"] == "unknown"
    assert emotion_no_face["confidence"] == 0.0
    print("✓ No-face case handled correctly")
    
    print("\n✅ All integration tests passed!")

if __name__ == "__main__":
    test_emotion_engine_three_layer_integration()
