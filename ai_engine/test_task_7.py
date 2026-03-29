#!/usr/bin/env python3
"""Quick test for Task 7 - Composite Weighted Risk Formula"""

import requests
import json

AI_ENGINE = "http://localhost:5001"

def test_weighted_risk():
    print("\n=== Testing Task 7: Weighted Risk Formula ===\n")
    
    # Test case 1: High distraction (w3=0.35)
    print("[Test 1] High distraction only")
    payload = {
        "trip_id": "weighted_test_1",
        "drowsiness": False,
        "yawning": False,
        "distraction": True,
        "speed": 50
    }
    resp = requests.post(f"{AI_ENGINE}/analyze_frame", json=payload).json()
    print(f"  Weighted Score: {resp.get('risk_score_weighted')} (Expected: ~35, w3=0.35*100)")
    print(f"  Weighted Level: {resp.get('risk_level_weighted')} (Expected: MODERATE)")
    
    # Test case 2: High drowsiness (w2=0.30)
    print("\n[Test 2] Drowsiness only")
    payload = {
        "trip_id": "weighted_test_2",
        "drowsiness": True,
        "yawning": False,
        "distraction": False,
        "speed": 50
    }
    resp = requests.post(f"{AI_ENGINE}/analyze_frame", json=payload).json()
    print(f"  Weighted Score: {resp.get('risk_score_weighted')} (Expected: ~30, w2=0.30*100)")
    print(f"  Weighted Level: {resp.get('risk_level_weighted')} (Expected: MODERATE)")
    
    # Test case 3: High speed (w1=0.25)
    print("\n[Test 3] High speed only (100 km/h, normalized to 0.83)")
    payload = {
        "trip_id": "weighted_test_3",
        "drowsiness": False,
        "yawning": False,
        "distraction": False,
        "speed": 100
    }
    resp = requests.post(f"{AI_ENGINE}/analyze_frame", json=payload).json()
    print(f"  Weighted Score: {resp.get('risk_score_weighted')} (Expected: ~21, w1=0.25*83)")
    print(f"  Weighted Level: {resp.get('risk_level_weighted')} (Expected: MODERATE)")
    
    # Test case 4: All dangers (should compound)
    print("\n[Test 4] All dangers at once (drowsy + distracted + fast + yawning)")
    payload = {
        "trip_id": "weighted_test_4",
        "drowsiness": True,
        "yawning": True,
        "distraction": True,
        "speed": 120
    }
    resp = requests.post(f"{AI_ENGINE}/analyze_frame", json=payload).json()
    score = resp.get('risk_score_weighted')
    print(f"  Weighted Score: {score} (Expected: ~100)")
    print(f"  Weighted Level: {resp.get('risk_level_weighted')} (Expected: CRITICAL)")
    print(f"  Component Breakdown: {resp.get('weighted_breakdown')}")
    
    # Test case 5: Safe driving
    print("\n[Test 5] Safe driving (all normal)")
    payload = {
        "trip_id": "weighted_test_5",
        "drowsiness": False,
        "yawning": False,
        "distraction": False,
        "speed": 30
    }
    resp = requests.post(f"{AI_ENGINE}/analyze_frame", json=payload).json()
    print(f"  Weighted Score: {resp.get('risk_score_weighted')} (Expected: ~0)")
    print(f"  Weighted Level: {resp.get('risk_level_weighted')} (Expected: SAFE)")
    
    print("\n✓ Task 7 tests complete\n")

if __name__ == "__main__":
    try:
        test_weighted_risk()
    except Exception as e:
        print(f"✗ Error: {e}")
        print("Make sure AI Engine is running on localhost:5001")
