"""
End-to-end test for landmark engine integration with AI engine API.
Tests that landmark extraction works through the /analyze endpoint.
"""
import requests
import base64
import numpy as np
import cv2
import sys

def test_landmark_integration():
    """Test landmark engine through API endpoint."""
    
    # Create a blank test image
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    
    # Encode to JPEG
    _, buf = cv2.imencode('.jpg', img)
    b64 = base64.b64encode(buf).decode()
    
    # Prepare request
    payload = {
        'image': f'data:image/jpeg;base64,{b64}',
        'trip_id': 'test_landmark_integration',
        'speed': 50.0
    }
    
    print("Testing landmark engine integration...")
    print("Sending request to http://localhost:5001/analyze_frame")
    
    try:
        response = requests.post(
            'http://localhost:5001/analyze_frame',
            json=payload,
            timeout=35
        )
        
        print(f"✓ Response status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"✗ Unexpected status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
        
        data = response.json()
        
        # Check cv_metrics presence
        if 'cv_metrics' not in data:
            print("✗ Missing cv_metrics in response")
            return False
        
        cv_metrics = data['cv_metrics']
        print(f"✓ cv_metrics present")
        
        # Check required fields
        required_fields = ['face_detected', 'ear', 'mar', 'yaw_angle', 'faces_detected']
        for field in required_fields:
            if field not in cv_metrics:
                print(f"✗ Missing field: {field}")
                return False
            print(f"  {field}: {cv_metrics[field]}")
        
        # Verify structure
        if 'face_bbox' in cv_metrics:
            print(f"  face_bbox: {cv_metrics['face_bbox']}")
        
        if 'all_face_boxes' in cv_metrics:
            print(f"  all_face_boxes count: {len(cv_metrics['all_face_boxes'])}")
        
        print("\n✓ Landmark engine integration successful!")
        print(f"  Face detected: {cv_metrics['face_detected']}")
        print(f"  Total faces: {cv_metrics['faces_detected']}")
        
        if cv_metrics['face_detected']:
            print(f"  EAR (Eye Aspect Ratio): {cv_metrics['ear']:.3f}")
            print(f"  MAR (Mouth Aspect Ratio): {cv_metrics['mar']:.3f}")
            print(f"  Head Yaw: {cv_metrics['yaw_angle']:.1f}°")
        else:
            print("  (No face detected in blank test image - expected)")
        
        return True
        
    except requests.exceptions.ConnectionError:
        print("✗ Cannot connect to AI engine at http://localhost:5001")
        print("  Make sure AI engine is running: cd ai_engine && python app.py")
        return False
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_landmark_integration()
    sys.exit(0 if success else 1)
