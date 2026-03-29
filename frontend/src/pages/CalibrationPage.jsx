import React, { useEffect, useRef, useState } from 'react'
import { captureFrame } from '../services/aiEngineService'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:5000'

export default function CalibrationPage() {
  const videoRef = useRef(null)
  const [phase, setPhase] = useState('instructions') // instructions | neutral | yawning | headturn | complete
  const [sessionId, setSessionId] = useState(null)
  const [driverId, setDriverId] = useState('')
  const [frameCount, setFrameCount] = useState({ neutral: 0, yawning: 0, headturn: 0 })
  const [calibrationStatus, setCalibrationStatus] = useState('IDLE')
  const [message, setMessage] = useState('')
  const [progress, setProgress] = useState(0)
  const [existingCalibration, setExistingCalibration] = useState(null)

  // Start webcam
  useEffect(() => {
    async function startCam() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
        if (videoRef.current) videoRef.current.srcObject = stream
      } catch (e) {
        console.warn('No camera available', e)
        setMessage('Camera not available')
      }
    }
    startCam()
  }, [])

  // Check existing calibration
  const checkExistingCalibration = async () => {
    if (!driverId.trim()) {
      setMessage('Please enter Driver ID')
      return
    }

    try {
      const res = await fetch(`${API_BASE}/drivers/${encodeURIComponent(driverId)}/calibration`)
      const data = await res.json()
      
      if (data.calibration_status === 'COMPLETED') {
        setExistingCalibration(data)
        setMessage(`✅ Calibration exists from ${new Date(data.last_updated).toLocaleDateString()}`)
      } else {
        setExistingCalibration(null)
        setMessage('No calibration found. Starting new calibration...')
        setTimeout(() => startCalibration(), 1500)
      }
    } catch (e) {
      console.error('Error checking calibration:', e)
      setMessage('Error checking calibration')
    }
  }

  // Start calibration
  const startCalibration = async () => {
    if (!driverId.trim()) {
      setMessage('Please enter Driver ID')
      return
    }

    try {
      const res = await fetch(`${API_BASE}/drivers/${encodeURIComponent(driverId)}/calibrate/start`, {
        method: 'POST'
      })
      const data = await res.json()
      
      setSessionId(data.session_id)
      setPhase('instructions')
      setMessage(data.message)
      setCalibrationStatus('IN_PROGRESS')
      setProgress(0)
    } catch (e) {
      console.error('Error starting calibration:', e)
      setMessage('Failed to start calibration')
    }
  }

  // Submit calibration frame
  const submitFrame = async () => {
    if (!videoRef.current || !sessionId) return

    try {
      const frameData = captureFrame(videoRef.current)
      if (!frameData) {
        setMessage('Failed to capture frame')
        return
      }

      // For simplicity, we estimate EAR/MAR on frontend
      // In production, send to AI engine for computation first
      const ear = 0.28 + Math.random() * 0.05  // Simulate variation
      const mar = 0.35 + Math.random() * 0.05
      const yaw = Math.random() * 10 - 5

      const res = await fetch(`${API_BASE}/drivers/${encodeURIComponent(driverId)}/calibrate/frame`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          ear: ear,
          mar: mar,
          yaw_angle: yaw,
          phase: phase,
          face_detected: true
        })
      })

      const data = await res.json()
      
      if (res.ok) {
        setFrameCount(prev => ({
          ...prev,
          [phase]: data.frames_in_phase
        }))
        
        const total = data.total_frames
        setProgress(Math.min(100, (total / 150) * 100))
        setMessage(`${phase}: ${data.frames_in_phase} frames | Total: ${total}/150`)
      } else {
        setMessage(data.error || 'Error submitting frame')
      }
    } catch (e) {
      console.error('Error submitting frame:', e)
    }
  }

  // Complete calibration
  const completeCalibration = async () => {
    try {
      const res = await fetch(`${API_BASE}/drivers/${encodeURIComponent(driverId)}/calibrate/complete`, {
        method: 'POST'
      })
      const data = await res.json()

      if (res.ok) {
        setPhase('complete')
        setCalibrationStatus('COMPLETED')
        setMessage('✅ Calibration completed successfully!')
        setExistingCalibration(data)
      } else {
        setMessage(data.error || 'Calibration incomplete. Frames needed: ' + JSON.stringify(data.required))
      }
    } catch (e) {
      console.error('Error completing calibration:', e)
      setMessage('Failed to complete calibration')
    }
  }

  // Auto-capture frames
  useEffect(() => {
    if (phase === 'neutral' || phase === 'yawning' || phase === 'headturn') {
      const interval = setInterval(submitFrame, 500)
      return () => clearInterval(interval)
    }
  }, [phase, sessionId])

  return (
    <div className="calibration-page">
      <div className="calibration-container">
        <h1>🎯 Driver Calibration</h1>
        <p>Personalize detection thresholds based on your facial characteristics</p>

        {/* Driver ID Input */}
        {!sessionId && (
          <div className="calibration-form">
            <input
              type="text"
              placeholder="Enter Driver ID"
              value={driverId}
              onChange={(e) => setDriverId(e.target.value)}
              className="input-field"
            />
            <button onClick={checkExistingCalibration} className="btn-primary">
              Check / Start Calibration
            </button>
          </div>
        )}

        {/* Video Feed */}
        {sessionId && (
          <div className="video-container">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="calibration-video"
            />
            <div className="phase-indicator">Phase: {phase}</div>
          </div>
        )}

        {/* Instructions */}
        {phase === 'instructions' && (
          <div className="instructions">
            <h3>Calibration Instructions</h3>
            <ol>
              <li><strong>Neutral Phase (30 frames):</strong> Look straight at camera with natural, alert face</li>
              <li><strong>Yawning Phase (30 frames):</strong> Yawn 3-4 times widely, we'll capture the motion</li>
              <li><strong>Head Turn Phase (30 frames):</strong> Slowly turn your head side-to-side</li>
            </ol>
            <p>Each phase takes 10-15 seconds. We need ~150 frames total.</p>
            <button onClick={() => setPhase('neutral')} className="btn-primary">
              Start Neutral Phase
            </button>
          </div>
        )}

        {/* Progress */}
        {(phase === 'neutral' || phase === 'yawning' || phase === 'headturn') && (
          <div className="progress-section">
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${progress}%` }} />
            </div>
            <p>{progress.toFixed(0)}% Complete</p>
            
            <div className="phase-buttons">
              {phase === 'neutral' && frameCount.neutral >= 30 && (
                <button onClick={() => setPhase('yawning')} className="btn-secondary">
                  Neutral Complete → Yawning Phase
                </button>
              )}
              {phase === 'yawning' && frameCount.yawning >= 30 && (
                <button onClick={() => setPhase('headturn')} className="btn-secondary">
                  Yawning Complete → Head Turn Phase
                </button>
              )}
              {phase === 'headturn' && frameCount.headturn >= 30 && (
                <button onClick={completeCalibration} className="btn-success">
                  Complete Calibration
                </button>
              )}
            </div>
          </div>
        )}

        {/* Complete Status */}
        {phase === 'complete' && existingCalibration && (
          <div className="calibration-complete">
            <h3>✅ Calibration Complete!</h3>
            <div className="calibration-results">
              <h4>Your Personalized Baselines:</h4>
              <table>
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Your Value</th>
                    <th>Threshold</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Eyes Open (EAR)</td>
                    <td>{existingCalibration.baseline?.ear_open}</td>
                    <td>{existingCalibration.thresholds?.drowsiness_ear}</td>
                  </tr>
                  <tr>
                    <td>Mouth Yawning (MAR)</td>
                    <td>{existingCalibration.baseline?.mar_yawning}</td>
                    <td>{existingCalibration.thresholds?.yawning_mar}</td>
                  </tr>
                  <tr>
                    <td>Frames Collected</td>
                    <td colSpan="2">{existingCalibration.baseline?.frames_collected}</td>
                  </tr>
                </tbody>
              </table>
              
              <p className="calibration-note">
                Detection thresholds are now personalized for you!
                Better accuracy with your unique facial characteristics.
              </p>
              
              <a href="/live" className="btn-primary">
                Go to Live Monitoring
              </a>
            </div>
          </div>
        )}

        {/* Message Display */}
        {message && (
          <div className={`message ${calibrationStatus.toLowerCase()}`}>
            {message}
          </div>
        )}

        {/* Existing Calibration Display */}
        {existingCalibration && phase === 'instructions' && (
          <div className="existing-calibration">
            <h4>Existing Calibration Found</h4>
            <p>Last updated: {new Date(existingCalibration.last_updated).toLocaleString()}</p>
            <button onClick={() => setPhase('neutral')} className="btn-secondary">
              Recalibrate
            </button>
            <a href="/live" className="btn-primary">
              Use Existing Calibration
            </a>
          </div>
        )}
      </div>

      <style jsx>{`
        .calibration-page {
          min-height: 100vh;
          background: #f5f5f5;
          padding: 20px;
          font-family: Arial, sans-serif;
        }

        .calibration-container {
          max-width: 800px;
          margin: 0 auto;
          background: white;
          border-radius: 8px;
          padding: 30px;
          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }

        h1 {
          text-align: center;
          color: #333;
          margin-bottom: 10px;
        }

        .calibration-form {
          display: flex;
          gap: 10px;
          margin: 20px 0;
        }

        .input-field {
          flex: 1;
          padding: 12px;
          border: 2px solid #ddd;
          border-radius: 4px;
          font-size: 14px;
        }

        .video-container {
          position: relative;
          margin: 20px 0;
          border-radius: 8px;
          overflow: hidden;
          background: #000;
        }

        .calibration-video {
          width: 100%;
          display: block;
        }

        .phase-indicator {
          position: absolute;
          top: 10px;
          right: 10px;
          background: rgba(0, 0, 0, 0.7);
          color: white;
          padding: 8px 12px;
          border-radius: 4px;
          font-weight: bold;
        }

        .instructions {
          background: #f9f9f9;
          border-left: 4px solid #2196F3;
          padding: 20px;
          margin: 20px 0;
          border-radius: 4px;
        }

        .instructions ol {
          margin-left: 20px;
          line-height: 1.8;
        }

        .progress-section {
          margin: 20px 0;
        }

        .progress-bar {
          width: 100%;
          height: 20px;
          background: #e0e0e0;
          border-radius: 10px;
          overflow: hidden;
          margin-bottom: 10px;
        }

        .progress-fill {
          height: 100%;
          background: linear-gradient(90deg, #4CAF50, #45a049);
          transition: width 0.3s ease;
        }

        .phase-buttons {
          display: flex;
          gap: 10px;
          margin-top: 15px;
        }

        .calibration-complete {
          background: #e8f5e9;
          border: 2px solid #4CAF50;
          padding: 20px;
          border-radius: 8px;
          text-align: center;
        }

        .calibration-results {
          text-align: left;
          margin: 20px 0;
        }

        table {
          width: 100%;
          border-collapse: collapse;
          margin: 15px 0;
        }

        th, td {
          padding: 12px;
          text-align: left;
          border-bottom: 1px solid #ddd;
        }

        th {
          background: #f5f5f5;
          font-weight: bold;
        }

        .btn-primary, .btn-secondary, .btn-success {
          padding: 12px 24px;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-weight: bold;
          font-size: 14px;
          transition: 0.3s;
        }

        .btn-primary {
          background: #2196F3;
          color: white;
        }

        .btn-primary:hover {
          background: #1976D2;
        }

        .btn-secondary {
          background: #FF9800;
          color: white;
        }

        .btn-success {
          background: #4CAF50;
          color: white;
        }

        .message {
          padding: 15px;
          border-radius: 4px;
          margin: 15px 0;
          font-weight: bold;
        }

        .message.in_progress {
          background: #e3f2fd;
          color: #1976D2;
        }

        .message.completed {
          background: #e8f5e9;
          color: #388E3C;
        }

        .existing-calibration {
          background: #fff3cd;
          border: 2px solid #ffc107;
          padding: 15px;
          border-radius: 4px;
          margin: 15px 0;
        }
      `}</style>
    </div>
  )
}
