"""
Quick test to verify landmark engine integration works correctly.
"""
import cv2
import numpy as np
import base64
from landmark_engine import get_landmark_engine

# Create a simple test image (640x480 black canvas)
test_image = np.zeros((480, 640, 3), dtype=np.uint8)

# Draw a simple face-like pattern
cv2.circle(test_image, (320, 240), 100, (255, 255, 255), 2)  # Face outline
cv2.circle(test_image, (280, 220), 10, (255, 255, 255), -1)  # Left eye
cv2.circle(test_image, (360, 220), 10, (255, 255, 255), -1)  # Right eye
cv2.ellipse(test_image, (320, 270), (40, 20), 0, 0, 180, (255, 255, 255), 2)  # Mouth

print("Testing landmark engine...")
engine = get_landmark_engine()

if not engine.initialized:
    print("✗ Landmark engine not initialized")
    exit(1)

print(f"✓ Landmark engine initialized: {engine.initialized}")

# Test landmark extraction
results = engine.extract_landmarks(test_image)
print(f"  Faces detected: {len(results)}")

if len(results) == 0:
    print("  ℹ No faces detected (expected for simple drawing)")
else:
    for i, face in enumerate(results):
        print(f"  Face {i}: EAR={face.ear_avg:.3f}, MAR={face.mar:.3f}, Yaw={face.head_yaw:.1f}°")

print("\n✓ Landmark engine integration test completed")
