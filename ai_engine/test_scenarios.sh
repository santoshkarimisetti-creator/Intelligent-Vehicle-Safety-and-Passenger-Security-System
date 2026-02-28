#!/usr/bin/env bash
# Test scenarios for Rule-Based Risk Engine
# Run individual tests with: bash test_scenarios.sh scenario_1

# Configuration
AI_ENGINE="http://localhost:5001"
TRIP_ID="test_$(date +%s)"

echo "Test Trip ID: $TRIP_ID"
echo "AI Engine URL: $AI_ENGINE"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

function print_header() {
    echo ""
    echo "=========================================="
    echo "  $1"
    echo "=========================================="
}

function print_step() {
    echo -e "${YELLOW}[STEP] $1${NC}"
}

function print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

function print_error() {
    echo -e "${RED}✗ $1${NC}"
}

function check_health() {
    print_step "Checking AI Engine health..."
    RESPONSE=$(curl -s "$AI_ENGINE/health" -w "\n%{http_code}")
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    
    if [ "$HTTP_CODE" = "200" ]; then
        print_success "AI Engine is running"
        return 0
    else
        print_error "AI Engine not responding (HTTP $HTTP_CODE)"
        return 1
    fi
}

function reset_trip() {
    local TRIP=$1
    print_step "Resetting trip $TRIP..."
    RESPONSE=$(curl -s -X POST "$AI_ENGINE/trips/$TRIP/counters/reset" -H "Content-Type: application/json")
    echo "$RESPONSE" | jq '.'
}

function get_counters() {
    local TRIP=$1
    print_step "Getting counters for trip $TRIP..."
    RESPONSE=$(curl -s -X GET "$AI_ENGINE/trips/$TRIP/counters")
    echo "$RESPONSE" | jq '.event_counters'
}

function analyze_frame() {
    local TRIP=$1
    local DROWSY=${2:-false}
    local YAWN=${3:-false}
    local DISTRACT=${4:-false}
    local SPEED=${5:-75}
    
    local PAYLOAD=$(cat <<EOF
{
  "trip_id": "$TRIP",
  "drowsiness": $DROWSY,
  "yawning": $YAWN,
  "distraction": $DISTRACT,
  "speed": $SPEED,
  "speed_limit": 80
}
EOF
)
    
    RESPONSE=$(curl -s -X POST "$AI_ENGINE/analyze_frame" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD")
    
    echo "$RESPONSE" | jq '{risk_score: .risk_score, risk_level: .risk_level, event_counters: .event_counters}'
}

# Test Scenarios
function scenario_1() {
    print_header "SCENARIO 1: Drowsiness Pattern Escalation (Rule 1)"
    
    reset_trip "$TRIP_ID"
    
    for i in {1..3}; do
        print_step "Analyzing drowsiness frame $i..."
        analyze_frame "$TRIP_ID" "true" "false" "false" "75"
        sleep 0.5
    done
    
    print_step "Final counters:"
    get_counters "$TRIP_ID"
    
    echo ""
    echo "Expected: drowsiness_events=3, risk escalation at frame 2 (+10) and frame 3 (+20)"
}

function scenario_2() {
    print_header "SCENARIO 2: Yawning Pattern Escalation (Rule 2)"
    
    reset_trip "$TRIP_ID"
    
    for i in {1..4}; do
        print_step "Analyzing yawning frame $i..."
        analyze_frame "$TRIP_ID" "false" "true" "false" "75"
        sleep 0.5
    done
    
    print_step "Final counters:"
    get_counters "$TRIP_ID"
    
    echo ""
    echo "Expected: yawning_events=4, risk escalation at frame 2 (+5) and frame 4 (+15)"
}

function scenario_3() {
    print_header "SCENARIO 3: Distraction Pattern Escalation (Rule 3)"
    
    reset_trip "$TRIP_ID"
    
    for i in {1..5}; do
        print_step "Analyzing distraction frame $i..."
        analyze_frame "$TRIP_ID" "false" "false" "true" "75"
        sleep 0.5
    done
    
    print_step "Final counters:"
    get_counters "$TRIP_ID"
    
    echo ""
    echo "Expected: looking_away_events=5, risk escalation at frame 3 (+15) and frame 5 (+25)"
}

function scenario_4() {
    print_header "SCENARIO 4: Critical Combo Escalation (Rule 4)"
    
    reset_trip "$TRIP_ID"
    
    print_step "Frame 1: Drowsiness with normal speed (75 km/h)..."
    analyze_frame "$TRIP_ID" "true" "false" "false" "75"
    sleep 0.5
    
    print_step "Frame 2: Drowsiness WITH excessive speed (90 km/h)..."
    analyze_frame "$TRIP_ID" "true" "false" "false" "90"
    sleep 0.5
    
    print_step "Final counters:"
    get_counters "$TRIP_ID"
    
    echo ""
    echo "Expected: drowsiness_events=2, overspeed_count=1, Rule 4 escalation (+20) at frame 2"
}

function scenario_5() {
    print_header "SCENARIO 5: State Persistence Across Multiple Calls"
    
    reset_trip "$TRIP_ID"
    
    print_step "Call 1: Send drowsiness detection..."
    RESP1=$(analyze_frame "$TRIP_ID" "true" "false" "false" "75")
    DROWSY1=$(echo "$RESP1" | jq '.event_counters.drowsiness_events')
    echo "  Drowsiness events after call 1: $DROWSY1"
    
    sleep 0.5
    
    print_step "Call 2: Send yawning detection (different signal)..."
    RESP2=$(analyze_frame "$TRIP_ID" "false" "true" "false" "75")
    DROWSY2=$(echo "$RESP2" | jq '.event_counters.drowsiness_events')
    YAWN2=$(echo "$RESP2" | jq '.event_counters.yawning_events')
    echo "  Drowsiness events after call 2: $DROWSY2"
    echo "  Yawning events after call 2: $YAWN2"
    
    sleep 0.5
    
    print_step "Final counters via GET endpoint:"
    FINAL=$(get_counters "$TRIP_ID")
    echo "$FINAL"
    
    echo ""
    echo "Expected: Both drowsiness_events=1 and yawning_events=1 persistent in state"
}

function scenario_combo() {
    print_header "SCENARIO: Mixed Pattern Detection (All Issues)"
    
    reset_trip "$TRIP_ID"
    
    print_step "Frame 1: Drowsiness..."
    analyze_frame "$TRIP_ID" "true" "false" "false" "75"
    sleep 0.5
    
    print_step "Frame 2: Drowsiness + Yawning..."
    analyze_frame "$TRIP_ID" "true" "true" "false" "75"
    sleep 0.5
    
    print_step "Frame 3: Drowsiness + Yawning + Distraction..."
    analyze_frame "$TRIP_ID" "true" "true" "true" "75"
    sleep 0.5
    
    print_step "Frame 4: All issues + Overspeed (90 km/h)..."
    analyze_frame "$TRIP_ID" "true" "true" "true" "90"
    sleep 0.5
    
    print_step "Final counters:"
    get_counters "$TRIP_ID"
    
    echo ""
    echo "Expected: All counters incremented, multiple rules triggerring, score escalating to CRITICAL"
}

function show_help() {
    cat <<EOF
Usage: bash test_scenarios.sh [scenario]

Available scenarios:
  scenario_1    - Drowsiness pattern escalation (Rule 1)
  scenario_2    - Yawning pattern escalation (Rule 2)
  scenario_3    - Distraction pattern escalation (Rule 3)
  scenario_4    - Critical combo escalation (Rule 4)
  scenario_5    - State persistence verification
  combo         - Mixed pattern detection test
  help          - Show this message

Examples:
  bash test_scenarios.sh scenario_1   # Run drowsiness test
  bash test_scenarios.sh combo        # Run mixed pattern test

Note: Ensure AI Engine is running on localhost:5001
EOF
}

# Main
if ! check_health; then
    print_error "AI Engine is not running!"
    echo "Start it with: cd d:\\Projects\\IVS\\ai_engine && python app.py"
    exit 1
fi

case "${1:-help}" in
    scenario_1) scenario_1 ;;
    scenario_2) scenario_2 ;;
    scenario_3) scenario_3 ;;
    scenario_4) scenario_4 ;;
    scenario_5) scenario_5 ;;
    combo) scenario_combo ;;
    help) show_help ;;
    *) print_error "Unknown scenario: $1"; show_help; exit 1 ;;
esac

print_success "Scenario complete"
