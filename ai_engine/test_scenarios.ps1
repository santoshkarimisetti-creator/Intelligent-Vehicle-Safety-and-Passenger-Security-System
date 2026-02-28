@echo off
REM Test scenarios for Rule-Based Risk Engine (Windows PowerShell version)
REM Run individual tests with: powershell -File test_scenarios.ps1 -Scenario scenario_1

param(
    [string]$Scenario = "help"
)

$ErrorActionPreference = "Stop"
$AI_ENGINE = "http://localhost:5001"
$TRIP_ID = "test_$(Get-Date -Format 'yyyyMMddHHmmss')"

Write-Host "Test Trip ID: $TRIP_ID" -ForegroundColor Cyan
Write-Host "AI Engine URL: $AI_ENGINE" -ForegroundColor Cyan

function Print-Header([string]$Text) {
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Yellow
    Write-Host "  $Text" -ForegroundColor Yellow
    Write-Host "==========================================" -ForegroundColor Yellow
}

function Print-Step([string]$Text) {
    Write-Host "[STEP] $Text" -ForegroundColor Cyan
}

function Print-Success([string]$Text) {
    Write-Host "✓ $Text" -ForegroundColor Green
}

function Print-Error([string]$Text) {
    Write-Host "✗ $Text" -ForegroundColor Red
}

function Check-Health {
    Print-Step "Checking AI Engine health..."
    try {
        $Response = Invoke-WebRequest -Uri "$AI_ENGINE/health" -ErrorAction Stop
        if ($Response.StatusCode -eq 200) {
            Print-Success "AI Engine is running"
            return $true
        }
    } catch {
        Print-Error "AI Engine not responding: $_"
        return $false
    }
}

function Reset-Trip([string]$TRIP) {
    Print-Step "Resetting trip $TRIP..."
    $Response = Invoke-WebRequest -Uri "$AI_ENGINE/trips/$TRIP/counters/reset" -Method Post -ErrorAction Stop
    Write-Host ($Response.Content | ConvertFrom-Json | ConvertTo-Json -Depth 10)
}

function Get-Counters([string]$TRIP) {
    Print-Step "Getting counters for trip $TRIP..."
    $Response = Invoke-WebRequest -Uri "$AI_ENGINE/trips/$TRIP/counters" -ErrorAction Stop
    $Data = $Response.Content | ConvertFrom-Json
    Write-Host ($Data.event_counters | ConvertTo-Json -Depth 10)
}

function Analyze-Frame(
    [string]$TRIP,
    [bool]$drowsy = $false,
    [bool]$yawn = $false,
    [bool]$distract = $false,
    [int]$speed = 75
) {
    $Payload = @{
        trip_id = $TRIP
        drowsiness = $drowsy
        yawning = $yawn
        distraction = $distract
        speed = $speed
        speed_limit = 80
    } | ConvertTo-Json
    
    $Response = Invoke-WebRequest -Uri "$AI_ENGINE/analyze_frame" -Method Post `
        -ContentType "application/json" `
        -Body $Payload `
        -ErrorAction Stop
    
    $Data = $Response.Content | ConvertFrom-Json
    $Output = @{
        risk_score = $Data.risk_score
        risk_level = $Data.risk_level
        event_counters = $Data.event_counters
    }
    Write-Host ($Output | ConvertTo-Json -Depth 10)
}

function Scenario-1 {
    Print-Header "SCENARIO 1: Drowsiness Pattern Escalation (Rule 1)"
    
    Reset-Trip $TRIP_ID
    
    for ($i = 1; $i -le 3; $i++) {
        Print-Step "Analyzing drowsiness frame $i..."
        Analyze-Frame $TRIP_ID $true $false $false 75
        Start-Sleep -Milliseconds 500
    }
    
    Print-Step "Final counters:"
    Get-Counters $TRIP_ID
    
    Write-Host ""
    Write-Host "Expected: drowsiness_events=3, risk escalation at frame 2 (+10) and frame 3 (+20)" -ForegroundColor Yellow
}

function Scenario-2 {
    Print-Header "SCENARIO 2: Yawning Pattern Escalation (Rule 2)"
    
    Reset-Trip $TRIP_ID
    
    for ($i = 1; $i -le 4; $i++) {
        Print-Step "Analyzing yawning frame $i..."
        Analyze-Frame $TRIP_ID $false $true $false 75
        Start-Sleep -Milliseconds 500
    }
    
    Print-Step "Final counters:"
    Get-Counters $TRIP_ID
    
    Write-Host ""
    Write-Host "Expected: yawning_events=4, risk escalation at frame 2 (+5) and frame 4 (+15)" -ForegroundColor Yellow
}

function Scenario-3 {
    Print-Header "SCENARIO 3: Distraction Pattern Escalation (Rule 3)"
    
    Reset-Trip $TRIP_ID
    
    for ($i = 1; $i -le 5; $i++) {
        Print-Step "Analyzing distraction frame $i..."
        Analyze-Frame $TRIP_ID $false $false $true 75
        Start-Sleep -Milliseconds 500
    }
    
    Print-Step "Final counters:"
    Get-Counters $TRIP_ID
    
    Write-Host ""
    Write-Host "Expected: looking_away_events=5, risk escalation at frame 3 (+15) and frame 5 (+25)" -ForegroundColor Yellow
}

function Scenario-4 {
    Print-Header "SCENARIO 4: Critical Combo Escalation (Rule 4)"
    
    Reset-Trip $TRIP_ID
    
    Print-Step "Frame 1: Drowsiness with normal speed (75 km/h)..."
    Analyze-Frame $TRIP_ID $true $false $false 75
    Start-Sleep -Milliseconds 500
    
    Print-Step "Frame 2: Drowsiness WITH excessive speed (90 km/h)..."
    Analyze-Frame $TRIP_ID $true $false $false 90
    Start-Sleep -Milliseconds 500
    
    Print-Step "Final counters:"
    Get-Counters $TRIP_ID
    
    Write-Host ""
    Write-Host "Expected: drowsiness_events=2, overspeed_count=1, Rule 4 escalation (+20) at frame 2" -ForegroundColor Yellow
}

function Scenario-5 {
    Print-Header "SCENARIO 5: State Persistence Across Multiple Calls"
    
    Reset-Trip $TRIP_ID
    
    Print-Step "Call 1: Send drowsiness detection..."
    $Resp1 = Invoke-WebRequest -Uri "$AI_ENGINE/analyze_frame" -Method Post `
        -ContentType "application/json" `
        -Body (@{trip_id=$TRIP_ID; drowsiness=$true; yawning=$false; distraction=$false; speed=75; speed_limit=80} | ConvertTo-Json) `
        -ErrorAction Stop | Select-Object -ExpandProperty Content | ConvertFrom-Json
    
    Write-Host "  Drowsiness events after call 1: $($Resp1.event_counters.drowsiness_events)"
    
    Start-Sleep -Milliseconds 500
    
    Print-Step "Call 2: Send yawning detection (different signal)..."
    $Resp2 = Invoke-WebRequest -Uri "$AI_ENGINE/analyze_frame" -Method Post `
        -ContentType "application/json" `
        -Body (@{trip_id=$TRIP_ID; drowsiness=$false; yawning=$true; distraction=$false; speed=75; speed_limit=80} | ConvertTo-Json) `
        -ErrorAction Stop | Select-Object -ExpandProperty Content | ConvertFrom-Json
    
    Write-Host "  Drowsiness events after call 2: $($Resp2.event_counters.drowsiness_events)"
    Write-Host "  Yawning events after call 2: $($Resp2.event_counters.yawning_events)"
    
    Start-Sleep -Milliseconds 500
    
    Print-Step "Final counters via GET endpoint:"
    Get-Counters $TRIP_ID
    
    Write-Host ""
    Write-Host "Expected: Both drowsiness_events=1 and yawning_events=1 persistent in state" -ForegroundColor Yellow
}

function Scenario-Combo {
    Print-Header "SCENARIO: Mixed Pattern Detection (All Issues)"
    
    Reset-Trip $TRIP_ID
    
    Print-Step "Frame 1: Drowsiness..."
    Analyze-Frame $TRIP_ID $true $false $false 75
    Start-Sleep -Milliseconds 500
    
    Print-Step "Frame 2: Drowsiness + Yawning..."
    Analyze-Frame $TRIP_ID $true $true $false 75
    Start-Sleep -Milliseconds 500
    
    Print-Step "Frame 3: Drowsiness + Yawning + Distraction..."
    Analyze-Frame $TRIP_ID $true $true $true 75
    Start-Sleep -Milliseconds 500
    
    Print-Step "Frame 4: All issues + Overspeed (90 km/h)..."
    Analyze-Frame $TRIP_ID $true $true $true 90
    Start-Sleep -Milliseconds 500
    
    Print-Step "Final counters:"
    Get-Counters $TRIP_ID
    
    Write-Host ""
    Write-Host "Expected: All counters incremented, multiple rules triggering, score escalating to CRITICAL" -ForegroundColor Yellow
}

function Show-Help {
    Write-Host @"
Usage: powershell -File test_scenarios.ps1 -Scenario <scenario_name>

Available scenarios:
  scenario_1    - Drowsiness pattern escalation (Rule 1)
  scenario_2    - Yawning pattern escalation (Rule 2)
  scenario_3    - Distraction pattern escalation (Rule 3)
  scenario_4    - Critical combo escalation (Rule 4)
  scenario_5    - State persistence verification
  combo         - Mixed pattern detection test
  help          - Show this message

Examples:
  powershell -File test_scenarios.ps1 -Scenario scenario_1   # Run drowsiness test
  powershell -File test_scenarios.ps1 -Scenario combo        # Run mixed pattern test

Note: Ensure AI Engine is running on localhost:5001
Change-Location d:\Projects\IVS\ai_engine; python app.py
"@
}

# Main
if (-not (Check-Health)) {
    Print-Error "AI Engine is not running!"
    Write-Host "Start it with: cd d:\Projects\IVS\ai_engine; python app.py" -ForegroundColor Yellow
    exit 1
}

switch ($Scenario.ToLower()) {
    "scenario_1" { Scenario-1 }
    "scenario_2" { Scenario-2 }
    "scenario_3" { Scenario-3 }
    "scenario_4" { Scenario-4 }
    "scenario_5" { Scenario-5 }
    "combo" { Scenario-Combo }
    "help" { Show-Help }
    default { 
        Print-Error "Unknown scenario: $Scenario"
        Show-Help
        exit 1
    }
}

Print-Success "Scenario complete"
