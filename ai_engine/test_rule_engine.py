#!/usr/bin/env python3
"""
Test Harness for Rule-Based Risk Engine

This script validates the rule-based temporal escalation logic by sending
test sequences to the AI Engine and verifying event counter behavior.
"""

import json
import requests
import time
import sys
from typing import Dict, Any

# Configuration
AI_ENGINE_URL = "http://localhost:5001"
BACKEND_URL = "http://localhost:5000"

def print_header(text: str) -> None:
    """Print a formatted test header."""
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}")

def print_step(num: int, text: str) -> None:
    """Print a test step."""
    print(f"\n[Step {num}] {text}")

def check_health() -> bool:
    """Check if AI Engine is healthy."""
    try:
        response = requests.get(f"{AI_ENGINE_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✓ AI Engine is running")
            return True
    except requests.ConnectionError:
        print("✗ AI Engine not reachable at {AI_ENGINE_URL}")
    return False

def reset_trip(trip_id: str) -> bool:
    """Reset event counters for a trip."""
    try:
        response = requests.post(
            f"{AI_ENGINE_URL}/trips/{trip_id}/counters/reset",
            timeout=5
        )
        if response.status_code == 200:
            print(f"✓ Reset trip {trip_id}")
            return True
    except Exception as e:
        print(f"✗ Failed to reset trip: {e}")
    return False

def get_counters(trip_id: str) -> Dict[str, Any]:
    """Get current event counters for a trip."""
    try:
        response = requests.get(
            f"{AI_ENGINE_URL}/trips/{trip_id}/counters",
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("event_counters", {})
    except Exception as e:
        print(f"✗ Failed to get counters: {e}")
    return {}

def analyze_frame(trip_id: str, signal: Dict[str, Any]) -> Dict[str, Any]:
    """Send a frame analysis request."""
    payload = {"trip_id": trip_id, **signal}
    try:
        response = requests.post(
            f"{AI_ENGINE_URL}/analyze_frame",
            json=payload,
            timeout=5
        )
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"✗ Analysis failed: {e}")
    return {}

def validate_counter(counters: Dict[str, Any], key: str, expected: int) -> bool:
    """Validate that a counter matches expected value."""
    actual = counters.get(key, -1)
    status = "✓" if actual == expected else "✗"
    print(f"{status} {key}: {actual} (expected {expected})")
    return actual == expected

def validate_risk_level(risk_level: str, expected: str) -> bool:
    """Validate risk level."""
    status = "✓" if risk_level == expected else "✗"
    print(f"{status} risk_level: {risk_level} (expected {expected})")
    return risk_level == expected

# ============================================================================
# Test Scenarios
# ============================================================================

def test_scenario_1():
    """TEST 1: Drowsiness Pattern Escalation (Rule 1)"""
    print_header("TEST 1: Drowsiness Pattern Escalation (Rule 1)")
    trip_id = "test_drowsiness_001"
    
    print_step(1, "Reset trip counters")
    reset_trip(trip_id)
    
    print_step(2, "Analyze frame 1 with drowsiness detected")
    response = analyze_frame(trip_id, {"drowsiness": True, "yawning": False, "distraction": False})
    score_1 = response.get("risk_score", 0)
    counters = response.get("event_counters", {})
    print(f"  Risk Score: {score_1:.1f}, Drowsiness Events: {counters.get('drowsiness_events')}")
    
    print_step(3, "Analyze frame 2 with drowsiness detected")
    response = analyze_frame(trip_id, {"drowsiness": True, "yawning": False, "distraction": False})
    score_2 = response.get("risk_score", 0)
    counters = response.get("event_counters", {})
    print(f"  Risk Score: {score_2:.1f}, Drowsiness Events: {counters.get('drowsiness_events')}")
    escalation_2 = score_2 - score_1
    print(f"  Escalation from Frame 1→2: +{escalation_2:.1f} pts (expected ~+10 from Rule 1)")
    
    print_step(4, "Analyze frame 3 with drowsiness detected")
    response = analyze_frame(trip_id, {"drowsiness": True, "yawning": False, "distraction": False})
    score_3 = response.get("risk_score", 0)
    counters = response.get("event_counters", {})
    risk_level = response.get("risk_level", "")
    print(f"  Risk Score: {score_3:.1f}, Drowsiness Events: {counters.get('drowsiness_events')}")
    escalation_3 = score_3 - score_2
    print(f"  Escalation from Frame 2→3: +{escalation_3:.1f} pts (expected ~+10 from Rule 1)")
    
    print_step(5, "Verify final counters")
    final_counters = get_counters(trip_id)
    all_pass = True
    all_pass &= validate_counter(final_counters, "drowsiness_events", 3)
    all_pass &= validate_counter(final_counters, "yawning_events", 0)
    all_pass &= validate_counter(final_counters, "total_frames_analyzed", 3)
    
    print_step(6, "Assessment")
    if all_pass and score_3 > score_2:
        print("✓ TEST 1 PASSED: Rule 1 escalation working correctly")
        return True
    else:
        print("✗ TEST 1 FAILED: Rule 1 escalation not working as expected")
        return False

def test_scenario_2():
    """TEST 2: Yawning Pattern Escalation (Rule 2)"""
    print_header("TEST 2: Yawning Pattern Escalation (Rule 2)")
    trip_id = "test_yawning_001"
    
    print_step(1, "Reset trip counters")
    reset_trip(trip_id)
    
    scores = []
    for frame_num in range(1, 5):
        print_step(frame_num + 1, f"Analyze frame {frame_num} with yawning detected")
        response = analyze_frame(trip_id, {"drowsiness": False, "yawning": True, "distraction": False})
        score = response.get("risk_score", 0)
        counters = response.get("event_counters", {})
        scores.append(score)
        print(f"  Risk Score: {score:.1f}, Yawning Events: {counters.get('yawning_events')}")
    
    print_step(6, "Verify counters")
    final_counters = get_counters(trip_id)
    all_pass = True
    all_pass &= validate_counter(final_counters, "yawning_events", 4)
    
    print_step(7, "Check escalation")
    escalation = scores[3] - scores[2]
    print(f"  Escalation at frame 4: +{escalation:.1f} pts (expected ~+15 from Rule 2)")
    
    if all_pass and escalation >= 10:
        print("✓ TEST 2 PASSED: Rule 2 escalation working correctly")
        return True
    else:
        print("✗ TEST 2 FAILED: Rule 2 escalation not working as expected")
        return False

def test_scenario_3():
    """TEST 3: Distraction Pattern Escalation (Rule 3)"""
    print_header("TEST 3: Distraction Pattern Escalation (Rule 3)")
    trip_id = "test_distraction_001"
    
    print_step(1, "Reset trip counters")
    reset_trip(trip_id)
    
    scores = []
    for frame_num in range(1, 6):
        print_step(frame_num + 1, f"Analyze frame {frame_num} with distraction detected")
        response = analyze_frame(trip_id, {"drowsiness": False, "yawning": False, "distraction": True})
        score = response.get("risk_score", 0)
        counters = response.get("event_counters", {})
        scores.append(score)
        print(f"  Risk Score: {score:.1f}, Looking Away: {counters.get('looking_away_events')}")
    
    print_step(7, "Verify counters")
    final_counters = get_counters(trip_id)
    all_pass = True
    all_pass &= validate_counter(final_counters, "looking_away_events", 5)
    
    print_step(8, "Check escalation")
    escalation = scores[4] - scores[3]  # frame 5 vs frame 4
    print(f"  Escalation at frame 5: +{escalation:.1f} pts (expected ~+25 from Rule 3)")
    
    if all_pass and escalation >= 15:
        print("✓ TEST 3 PASSED: Rule 3 escalation working correctly")
        return True
    else:
        print("✗ TEST 3 FAILED: Rule 3 escalation not working as expected")
        return False

def test_scenario_4():
    """TEST 4: Critical Combo Escalation (Rule 4)"""
    print_header("TEST 4: Critical Combo Escalation (Rule 4)")
    trip_id = "test_combo_001"
    
    print_step(1, "Reset trip counters")
    reset_trip(trip_id)
    
    print_step(2, "Analyze frame 1: Drowsiness + Normal Speed")
    response = analyze_frame(trip_id, {"drowsiness": True, "speed": 75, "speed_limit": 80})
    score_1 = response.get("risk_score", 0)
    counters_1 = response.get("event_counters", {})
    print(f"  Risk Score: {score_1:.1f}, Drowsiness: {counters_1.get('drowsiness_events')}, Overspeed: {counters_1.get('overspeed_count')}")
    
    print_step(3, "Analyze frame 2: Drowsiness + Overspeed (Rule 4 should trigger)")
    response = analyze_frame(trip_id, {"drowsiness": True, "speed": 90, "speed_limit": 80})
    score_2 = response.get("risk_score", 0)
    counters_2 = response.get("event_counters", {})
    reasons = response.get("reasons", [])
    print(f"  Risk Score: {score_2:.1f}, Drowsiness: {counters_2.get('drowsiness_events')}, Overspeed: {counters_2.get('overspeed_count')}")
    print(f"  Reasons: {reasons}")
    escalation = score_2 - score_1
    print(f"  Escalation: +{escalation:.1f} pts (expected ~+20+ from Rule 4)")
    
    print_step(4, "Verify final counters")
    final_counters = get_counters(trip_id)
    all_pass = True
    all_pass &= validate_counter(final_counters, "drowsiness_events", 2)
    all_pass &= validate_counter(final_counters, "overspeed_count", 1)
    
    if all_pass and escalation >= 15:
        print("✓ TEST 4 PASSED: Rule 4 (critical combo) escalation working correctly")
        return True
    else:
        print("✗ TEST 4 FAILED: Rule 4 escalation not working as expected")
        return False

def test_scenario_5():
    """TEST 5: State Persistence Across Multiple Calls"""
    print_header("TEST 5: State Persistence Across Multiple Calls")
    trip_id = "test_persistence_001"
    
    print_step(1, "Reset trip counters")
    reset_trip(trip_id)
    
    print_step(2, "Call 1: Analyze frame with drowsiness")
    response1 = analyze_frame(trip_id, {"drowsiness": True, "yawning": False, "distraction": False})
    counters1 = response1.get("event_counters", {})
    print(f"  Drowsiness: {counters1.get('drowsiness_events')}, Yawning: {counters1.get('yawning_events')}")
    
    print_step(3, "Call 2: Analyze frame with yawning (different issue)")
    response2 = analyze_frame(trip_id, {"drowsiness": False, "yawning": True, "distraction": False})
    counters2 = response2.get("event_counters", {})
    print(f"  Drowsiness: {counters2.get('drowsiness_events')}, Yawning: {counters2.get('yawning_events')}")
    
    print_step(4, "GET /counters to verify both counters present")
    final_counters = get_counters(trip_id)
    all_pass = True
    all_pass &= validate_counter(final_counters, "drowsiness_events", 1)
    all_pass &= validate_counter(final_counters, "yawning_events", 1)
    
    if all_pass:
        print("✓ TEST 5 PASSED: State persistent across multiple calls")
        return True
    else:
        print("✗ TEST 5 FAILED: State not persisting correctly")
        return False

# ============================================================================
# Main
# ============================================================================

def main():
    """Run all test scenarios."""
    print("\n" + "="*70)
    print("    Rule-Based Risk Engine Test Harness")
    print("="*70)
    
    print("\nChecking AI Engine health...")
    if not check_health():
        print("\n⚠ AI Engine is not running. Start it with:")
        print("  cd d:\\Projects\\IVS\\ai_engine && python app.py")
        sys.exit(1)
    
    print("\nRunning test scenarios...")
    results = []
    
    try:
        results.append(("Scenario 1: Drowsiness Escalation", test_scenario_1()))
        time.sleep(1)
        
        results.append(("Scenario 2: Yawning Escalation", test_scenario_2()))
        time.sleep(1)
        
        results.append(("Scenario 3: Distraction Escalation", test_scenario_3()))
        time.sleep(1)
        
        results.append(("Scenario 4: Critical Combo", test_scenario_4()))
        time.sleep(1)
        
        results.append(("Scenario 5: State Persistence", test_scenario_5()))
    except KeyboardInterrupt:
        print("\n⚠ Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n⚠ Test execution error: {e}")
        sys.exit(1)
    
    # Summary
    print("\n" + "="*70)
    print("    TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All tests passed! Rule-based engine is working correctly.")
        sys.exit(0)
    else:
        print(f"\n✗ {total - passed} test(s) failed. Review above for details.")
        sys.exit(1)

if __name__ == "__main__":
    main()
