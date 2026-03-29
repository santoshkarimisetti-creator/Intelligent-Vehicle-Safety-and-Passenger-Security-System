"""
End-to-end test for the emotion pipeline through app.py
Simulates what happens when a frame arrives at /analyze_frame
"""

import numpy as np
import json
from emotion_engine import get_emotion_engine

def test_end_to_end_emotion_pipeline():
    """Test the complete emotion data flow."""
    print("\n=== End-to-End Emotion Pipeline Test ===\n")
    
    # Step 1: Simulate what happens in _run_slow_analytics()
    print("Step 1: Emotion engine analyzes frame...")
    engine = get_emotion_engine()
    session_key = "trip_abc123"
    
    # Create dummy data
    dummy_image = np.zeros((48, 48, 3), dtype=np.uint8)
    driver_bbox = {"x": 0, "y": 0, "w": 48, "h": 48}
    
    # Call analyze_periodic (now with real three-layer architecture)
    emotion_payload = engine.analyze_periodic(
        session_key=session_key,
        image_bgr=dummy_image,
        driver_bbox=driver_bbox,
        passenger_bboxes=[],
        force=True,
        is_trip_active=True,
    )
    
    print(f"  emotion_result: {emotion_payload['emotion_result']}")
    print(f"  driver_emotion: {emotion_payload['driver_emotion']}")
    
    # Step 2: Verify dashboard state was updated (Layer 3a)
    print("\nStep 2: Verify dashboard state update...")
    dashboard_state = engine.get_current_emotion_state(session_key)
    print(f"  dashboard_state: {dashboard_state}")
    assert dashboard_state["current_emotion"] != "unknown", "Dashboard should have real emotion!"
    assert dashboard_state["confidence"] > 0.0, "Dashboard should have non-zero confidence!"
    
    # Step 3: Simulate what _compute_detection() returns
    print("\nStep 3: Simulate detection_result construction...")
    emotion_result = emotion_payload.get("emotion_result")
    detection_result = {
        "emotion": emotion_result,  # This is what gets set at line 1248 in app.py
        "detections": [],
        "metrics": {},
    }
    
    # Step 4: Simulate what /analyze_frame endpoint does
    print("\nStep 4: Construct /analyze_frame response...")
    emo = (emotion_result or {}) if isinstance(emotion_result, dict) else {}
    driver_emotion_payload = {
        "driver_emotion": str(emo.get("dominant_emotion") or "unknown"),
        "confidence": float(emo.get("confidence") or 0.0),
    }
    
    response_body = {
        "trip_id": "trip_abc123",
        "driver_emotion": driver_emotion_payload,
        "emotion_result": emotion_result,
        "detections": [],
    }
    
    print(f"  Response driver_emotion: {response_body['driver_emotion']}")
    print(f"  Response emotion_result: {response_body['emotion_result']}")
    
    # Step 5: Verify frontend can parse it
    print("\nStep 5: Verify frontend can parse response...")
    # Simulate what LiveMonitoring.jsx does (lines 233-235)
    result = response_body
    emo = result.get("driver_emotion") or result.get("emotion_result") or {}
    emoLabel = str(emo.get("driver_emotion") or emo.get("dominant_emotion") or "unknown")
    emoConf = float(emo.get("confidence") or 0)
    
    print(f"  Frontend reads emotion: {emoLabel}")
    print(f"  Frontend reads confidence: {emoConf:.3f}")
    
    assert emoLabel != "unknown", "❌ Frontend still sees 'unknown'!"
    assert emoConf > 0.0, "❌ Frontend sees 0 confidence!"
    
    print("\n✅ End-to-end flow verified! Dashboard should now show real emotions.")
    print(f"   Emotion: {emoLabel}, Confidence: {emoConf:.1%}")

if __name__ == "__main__":
    test_end_to_end_emotion_pipeline()
