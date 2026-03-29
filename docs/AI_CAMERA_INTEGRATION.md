# AI Engine Camera Integration

## Overview
The frontend Live Monitoring page is now integrated with the AI engine to analyze camera feed in real-time.

## How It Works

1. **Camera Capture**: The frontend captures frames from the webcam every 2 seconds
2. **Frame Processing**: Frames are converted to base64 and sent to AI engine at `http://localhost:3001/analyze_frame`
3. **AI Analysis**: The AI engine processes frames using OpenCV Haar Cascades to detect:
   - Drowsiness (eye closure)
   - Yawning (mouth opening)
   - Distraction (head position)
   - SOS gestures (open palm held for 2+ seconds)
4. **Real-time Updates**: Results update the UI:
   - Risk score (0-100)
   - Driver status (ALERT/DROWSY/DISTRACTED)
   - Detection overlays on video
   - SOS alerts when triggered

## Setup

### 1. Configure Environment Variables

Create `frontend/.env` file:
```env
VITE_API_BASE=http://localhost:5000
VITE_AI_ENGINE_BASE=http://localhost:3001
```

### 2. Start Services

**Backend:**
```bash
cd backend
python app.py
```

**AI Engine:**
```bash
cd ai_engine
python app.py
```

**Frontend:**
```bash
cd frontend
npm run dev
```

### 3. Start a Trip

Before AI analysis works, you need an active trip:
- Use the Android app to start a trip, OR
- Set `tripId` in LiveMonitoring.jsx (currently defaults to 'active-trip' for demo)

## Features

### Real-time Detection Display
- **Detection Overlay**: Shows detected issues (e.g., "drowsiness: 85%") in top-right corner
- **AI Status Indicator**: Shows "🤖 AI: Active" when engine is connected
- **Connection Status**: Badge shows green (Connected) or red (Offline)

### Driver Status Updates
- **ALERT** (green): No issues detected
- **DROWSY** (orange): Eyes closing detected
- **DISTRACTED** (red): Looking away from road

### Risk Score
- Updated in real-time from 0-100 based on AI analysis
- Uses weighted risk calculation (Task 7)
- Considers temporal patterns and event history

### SOS Detection
- Detects open palm held for 2+ seconds
- Triggers emergency alert displayed at top
- Automatically sends SOS event to backend with `source: "ai_engine"`

## API Endpoints Used

### AI Engine (`http://localhost:3001`)
- `POST /analyze_frame`: Analyze video frame
  - Request: `{trip_id, image (base64), speed}`
  - Response: `{detections, risk_score_weighted, sos_triggered, ...}`
- `GET /health`: Check if AI engine is running

### Backend (`http://localhost:5000`)
- `POST /trips/<trip_id>/ai-results`: Store AI detections
- `POST /trips/<trip_id>/sos`: Store SOS events

## Troubleshooting

### AI Engine Shows "Offline"
- Ensure AI engine is running on port 3001
- Check console for connection errors
- Verify CORS is enabled in AI engine

### No Detections Appearing
- Ensure camera permission is granted
- Check browser console for errors
- Verify active trip exists (tripId is set)

### High CPU Usage
- Adjust frame capture interval in LiveMonitoring.jsx (currently 2000ms)
- Reduce video resolution
- Increase analysis interval

## Performance Notes

- **Frame Rate**: Captures and analyzes every 2 seconds (configurable)
- **Latency**: Typically 200-500ms per analysis
- **CPU Impact**: Moderate - runs in browser and AI engine
- **Network Usage**: ~50-100KB per frame sent to AI engine

## Future Enhancements

- [ ] Add frame skip logic based on speed/risk
- [ ] Implement client-side caching for detections
- [ ] Add visualization of eye/face landmarks
- [ ] Support mobile camera on Android WebView
- [ ] Add detection confidence thresholds
- [ ] Implement detection history timeline
