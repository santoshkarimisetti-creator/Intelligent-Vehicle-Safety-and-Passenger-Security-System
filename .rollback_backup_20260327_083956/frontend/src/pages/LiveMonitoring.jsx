import React, {useEffect, useRef, useState} from 'react'
import { subscribeLive } from '../services/liveTelemetry'
import { captureFrame, analyzeFrame, checkAIEngineHealth } from '../services/aiEngineService'
import LiveMap from '../components/LiveMap'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:5000'

export default function LiveMonitoring(){
  const videoRef = useRef(null)
  const audioContextRef = useRef(null)
  const lastBeepAtRef = useRef(0)
  const lastBeepByTypeRef = useRef(new Map())
  const activeDetectionStateRef = useRef({
    drowsiness: false,
    yawning: false,
    distraction: false,
    driver_not_visible: false,
  })
  const soundEndTimeRef = useRef(0)
  const lastInstantEventRef = useRef(null)
  const lastGlobalSoundRef = useRef({ at: 0, type: null })
  const lastEmotionRef = useRef(null)
  const emotionCandidateRef = useRef(null)
  const lastEmotionAlertAtRef = useRef(0)
  const [speed, setSpeed] = useState(45)
  const [state, setState] = useState('ACTIVE')
  const [risk, setRisk] = useState(0)
  const [driverStatus, setDriverStatus] = useState('ALERT')
  const [sos, setSos] = useState(false)
  const [position, setPosition] = useState(null)
  const [distanceKm, setDistanceKm] = useState(0)
  const [tripId, setTripId] = useState(null)
  const [aiEngineStatus, setAIEngineStatus] = useState(false)
  const [detections, setDetections] = useState([])
  const [cvMetrics, setCvMetrics] = useState(null)
  const [smoothedBBox, setSmoothedBBox] = useState(null)
  const [analysisError, setAnalysisError] = useState(null)
  const [driverEmotion, setDriverEmotion] = useState({ driver_emotion: 'unknown', confidence: 0, stress_level: 'LOW' })

  const initAudio = async () => {
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext
      if (!AudioContext) return
      if (!audioContextRef.current) {
        audioContextRef.current = new AudioContext()
      }
      if (audioContextRef.current.state === 'suspended') {
        await audioContextRef.current.resume()
      }
    } catch {
      // ignore audio init failures
    }
  }

  const playBeep = async (level) => {
    try {
      const now = Date.now()
      // Small global spacing; per-type cooldown still applies separately.
      if (now - lastBeepAtRef.current < 1200) return
      lastBeepAtRef.current = now

      await initAudio()
      const ctx = audioContextRef.current
      if (!ctx || ctx.state !== 'running') return

      const osc = ctx.createOscillator()
      const gain = ctx.createGain()

      const freq = level === 'CRITICAL' ? 880 : 660
      osc.type = 'sine'
      osc.frequency.value = freq

      // 3-second alert: ramp up, sustain, ramp down
      gain.gain.setValueAtTime(0.0001, ctx.currentTime)
      gain.gain.exponentialRampToValueAtTime(0.15, ctx.currentTime + 0.05)
      gain.gain.setValueAtTime(0.15, ctx.currentTime + 2.95)
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 3.00)

      osc.connect(gain)
      gain.connect(ctx.destination)

      osc.start(ctx.currentTime)
      osc.stop(ctx.currentTime + 3.00)
    } catch {
      // If audio is blocked, ignore.
    }
  }

  const playDetectionBeep = (key, level = 'HIGH', cooldownMs = 6000) => {
    try {
      const now = Date.now()
      const last = Number(lastBeepByTypeRef.current.get(key) || 0)
      if (now - last < cooldownMs) return
      lastBeepByTypeRef.current.set(key, now)
      playBeep(level)
    } catch {
      // ignore
    }
  }

  const processInstantSound = (instantEvent) => {
    const now = Date.now()
    const prevInstant = lastInstantEventRef.current
    const level = instantEvent === 'driver_not_visible' ? 'CRITICAL' : 'HIGH'

    if (instantEvent && prevInstant !== instantEvent) {
      playDetectionBeep(`instant:${instantEvent}`, level, 800)
      soundEndTimeRef.current = now + 3000
    }

    if (instantEvent) {
      soundEndTimeRef.current = now + 3000
      const key = `instant:loop:${instantEvent}`
      const last = Number(lastBeepByTypeRef.current.get(key) || 0)
      if ((now - last) >= 2500) {
        lastBeepByTypeRef.current.set(key, now)
        playBeep(level)
      }
    } else if (now < soundEndTimeRef.current && prevInstant) {
      const key = `instant:grace:${prevInstant}`
      const last = Number(lastBeepByTypeRef.current.get(key) || 0)
      if ((now - last) >= 2500) {
        lastBeepByTypeRef.current.set(key, now)
        playBeep(prevInstant === 'driver_not_visible' ? 'CRITICAL' : 'HIGH')
      }
    }

    lastInstantEventRef.current = instantEvent || null
  }

  // Smooth face bbox to reduce jitter
  useEffect(() => {
    const bbox = cvMetrics?.face_bbox
    if (!bbox || !cvMetrics?.face_detected) {
      setSmoothedBBox(null)
      return
    }
    const alpha = 0.35
    setSmoothedBBox(prev => {
      if (!prev) return { ...bbox }
      return {
        x: prev.x + (bbox.x - prev.x) * alpha,
        y: prev.y + (bbox.y - prev.y) * alpha,
        w: prev.w + (bbox.w - prev.w) * alpha,
        h: prev.h + (bbox.h - prev.h) * alpha,
      }
    })
  }, [cvMetrics])

  useEffect(()=>{
    const unlockAudio = () => {
      initAudio()
    }

    window.addEventListener('pointerdown', unlockAudio)
    window.addEventListener('keydown', unlockAudio)

    // start webcam
    async function startCam(){
      try{
        const stream = await navigator.mediaDevices.getUserMedia({video:true,audio:false})
        if(videoRef.current) videoRef.current.srcObject = stream
        // getUserMedia is user-driven in most flows; try unlocking audio after permission.
        await initAudio()
      }catch(e){
        console.warn('No camera available', e)
      }
    }
    startCam()

    // Check AI engine health
    checkAIEngineHealth().then(setAIEngineStatus)

    // subscribe to live telemetry only for synthetic speed while backend sensors are unavailable
    const unsub = subscribeLive(data =>{
      setSpeed(data.speed)
      setState(data.state)
    })

    return ()=> {
      window.removeEventListener('pointerdown', unlockAudio)
      window.removeEventListener('keydown', unlockAudio)
      unsub()
    }
  },[])

  // Source map + active trip state from backend (no random mock coordinates).
  useEffect(() => {
    const fetchLiveMap = async () => {
      try {
        const res = await fetch(`${API_BASE}/trips/active-trip/live_map`)
        if (!res.ok) return
        const data = await res.json()
        const active = Boolean(data.trip_active)
        setState(active ? 'ACTIVE' : 'IDLE')
        setTripId(active ? (data.trip_id || null) : null)

        const loc = data.current_location
        if (loc && Number.isFinite(Number(loc.lat)) && Number.isFinite(Number(loc.lng))) {
          setPosition([Number(loc.lat), Number(loc.lng)])
        } else {
          setPosition(null)
        }
      } catch (e) {
        console.warn('Failed to fetch live map data', e)
      }
    }

    fetchLiveMap()
    const interval = setInterval(fetchLiveMap, 5000)
    return () => clearInterval(interval)
  }, [])

  // Fetch live distance from backend
  useEffect(()=>{
    const fetchDistance = async () => {
      try {
        const endpoint = tripId
          ? `${API_BASE}/trips/${encodeURIComponent(tripId)}/distance`
          : `${API_BASE}/trips/active-trip/distance`
        const res = await fetch(endpoint)
        if(res.ok){
          const data = await res.json()
          setDistanceKm(data.distance_km || 0)
        }
      } catch(e) {
        console.warn('Failed to fetch distance', e)
      }
    }

    // Fetch every 5 seconds
    const interval = setInterval(fetchDistance, 5000)
    return () => clearInterval(interval)
  },[tripId])

  // AI Engine Integration: Send frames for analysis
  useEffect(() => {
    if (!aiEngineStatus || !videoRef.current) return

    let inFlight = false

    const analyzeVideoFrame = async () => {
      if (inFlight) return
      inFlight = true
      try {
        const frameData = captureFrame(videoRef.current, {
          maxWidth: 480,
          maxHeight: 360,
          quality: 0.65,
        })
        if (!frameData) return

        const result = await analyzeFrame(frameData, tripId, speed)
        setCvMetrics(result.cv_metrics || null)

        // Always show driver emotion continuously (even if unknown).
        const emo = result.driver_emotion || result.emotion_result || {}
        const emoLabel = String(emo.driver_emotion || emo.dominant_emotion || 'unknown')
        const emoConf = Number(emo.confidence || 0)
        setDriverEmotion({
          driver_emotion: emoLabel,
          confidence: emoConf,
          stress_level: String(emo.stress_level || 'LOW'),
        })

        // Update UI with AI results
        if (result.risk_score_weighted !== undefined) {
          setRisk(result.risk_score_weighted)
        }

        // Always process detections as current-frame only.
        const frameDetections = Array.isArray(result.detections) ? result.detections : []
        setDetections([])
        setDetections(frameDetections)

        const hasByType = {
          drowsiness: frameDetections.some(d => d?.type === 'drowsiness'),
          yawning: frameDetections.some(d => d?.type === 'yawning'),
          distraction: frameDetections.some(d => d?.type === 'distraction'),
          driver_not_visible: frameDetections.some(d => d?.type === 'driver_not_visible'),
        }

        const instantEvent = result.instant_event || null
        if (instantEvent) {
          playDetectionBeep(instantEvent, instantEvent === 'driver_not_visible' ? 'CRITICAL' : 'HIGH', 800)
        }
        processInstantSound(instantEvent)

        // Update driver status based only on current-frame detections.
        if (hasByType.drowsiness) {
          setDriverStatus('DROWSY')
        } else if (hasByType.distraction) {
          setDriverStatus('DISTRACTED')
        } else if (hasByType.driver_not_visible) {
          setDriverStatus('NOT_VISIBLE')
        } else {
          setDriverStatus('ALERT')
        }

        // Sudden emotion change alert (requires confidence + persistence).
        const prev = lastEmotionRef.current
        const now = Date.now()
        const curr = { label: emoLabel, confidence: emoConf }
        if (!prev) {
          lastEmotionRef.current = curr
          emotionCandidateRef.current = null
        } else if (curr.label !== prev.label) {
          const transitions = new Set([
            'neutral->angry',
            'happy->fear',
            'calm->sad',
          ])
          const key = `${prev.label}->${curr.label}`
          const strong = Number(prev.confidence || 0) >= 0.65 && Number(curr.confidence || 0) >= 0.65
          if (strong && transitions.has(key)) {
            const cand = emotionCandidateRef.current
            if (!cand || cand.key !== key) {
              emotionCandidateRef.current = { key, startedAt: now }
            } else if ((now - cand.startedAt) >= 1200 && (now - lastEmotionAlertAtRef.current) >= 15000) {
              lastEmotionAlertAtRef.current = now
              playDetectionBeep(`emo:${key}`, 'HIGH', 15000)
              // accept new emotion as baseline after firing
              lastEmotionRef.current = curr
              emotionCandidateRef.current = null
            }
          } else {
            emotionCandidateRef.current = null
            // update baseline when confidence is decent (prevents flip-flop noise)
            if (Number(curr.confidence || 0) >= 0.55) lastEmotionRef.current = curr
          }
        } else {
          // Same emotion; keep baseline fresh
          lastEmotionRef.current = curr
          emotionCandidateRef.current = null
        }

        // Handle SOS trigger
        if (result.sos_triggered) {
          setSos(true)
          playDetectionBeep('sos', 'CRITICAL', 3000)
          setTimeout(() => setSos(false), 10000) // Clear after 10 seconds
        }

        setAnalysisError(null)
      } catch (error) {
        console.error('Frame analysis error:', error)
        setAnalysisError(error.message)
      } finally {
        inFlight = false
      }
    }

    // Analyze frames frequently to make face-box + detections feel immediate.
    // Throttled by `inFlight` so we never pile up requests.
    const interval = setInterval(analyzeVideoFrame, 250)
    
    return () => clearInterval(interval)
  }, [aiEngineStatus, tripId, speed])

  return (
    <div className="page live">
      {sos && <div className="emergency">EMERGENCY: SOS triggered</div>}
      {analysisError && (
        <div style={{background: '#ffa500', color: '#fff', padding: '8px', marginBottom: '8px', borderRadius: '4px'}}>
          AI Engine: {analysisError}
        </div>
      )}
      <div className="live-grid">
        <div className="card camera">
          <video ref={videoRef} autoPlay playsInline muted />
          {cvMetrics?.face_detected && smoothedBBox && cvMetrics?.image_width > 0 && cvMetrics?.image_height > 0 && (
            <svg
              style={{
                position: 'absolute',
                inset: 0,
                width: '100%',
                height: '100%',
                pointerEvents: 'none',
                transform: 'scaleX(-1)',
                transformOrigin: 'center'
              }}
              viewBox={`0 0 ${cvMetrics.image_width} ${cvMetrics.image_height}`}
              preserveAspectRatio="none"
            >
              {(cvMetrics.faces_meta || []).map((m, idx) => {
                const b = m?.bbox
                if (!Array.isArray(b) || b.length < 4) return null
                const x1 = Number(b[0] || 0)
                const y1 = Number(b[1] || 0)
                const w = Number(b[2] || 0)
                const h = Number(b[3] || 0)
                const x2 = x1 + w
                const y2 = y1 + h
                const corner = Math.max(10, Math.min(w, h) * 0.18)
                const stroke = m?.box_color === 'green' ? '#00c853' : '#ffffff'
                return (
                  <path
                    key={`meta-${idx}`}
                    d={[
                      `M ${x1} ${y1 + corner} V ${y1} H ${x1 + corner}`,
                      `M ${x2 - corner} ${y1} H ${x2} V ${y1 + corner}`,
                      `M ${x2} ${y2 - corner} V ${y2} H ${x2 - corner}`,
                      `M ${x1 + corner} ${y2} H ${x1} V ${y2 - corner}`,
                    ].join(' ')}
                    fill="none"
                    stroke={stroke}
                    strokeWidth={m?.role === 'driver' ? 4 : 3}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                )
              })}
              {(cvMetrics.eye_boxes || []).map((eye, idx) => (
                <g key={`eye-${idx}`}>
                  <circle
                    cx={eye.x + eye.w / 2}
                    cy={eye.y + eye.h / 2}
                    r={Math.max(3, Math.min(eye.w, eye.h) / 5)}
                    fill="none"
                    stroke="#ffe082"
                    strokeWidth="2"
                  />
                </g>
              ))}
            </svg>
          )}
          <div className="speed-overlay">
            <div>Speed: {Math.round(speed)} km/h</div>
            <div className="distance-inline">Distance: {distanceKm.toFixed(2)} km</div>
            {aiEngineStatus && <div style={{fontSize: '10px', marginTop: '4px'}}>🤖 AI: Active</div>}
            {cvMetrics?.faces_detected > 0 && <div style={{fontSize: '10px'}}>Faces: {cvMetrics.faces_detected}</div>}
          </div>
          {detections.length > 0 && (
            <div style={{
              position: 'absolute',
              top: '14px',
              right: '14px',
              background: 'rgba(255,0,0,0.8)',
              color: '#fff',
              padding: '6px 10px',
              borderRadius: '6px',
              fontSize: '11px'
            }}>
              {detections.map((d, i) => (
                <div key={i}>{d.type}: {(d.confidence * 100).toFixed(0)}%</div>
              ))}
            </div>
          )}
          <div className="caption">Live Camera Feed</div>
        </div>

        <div className="card stats">
          <div className="stat"><strong>State</strong><div className="value"><span className="badge blue">{state}</span></div></div>
          <div className="stat"><strong>Risk Score</strong>
            <div className="risk-row">
              <div className="risk-bar"><div className="risk-fill" style={{width: `${risk}%`}} /></div>
              <div className="value">{Math.round(risk)}</div>
            </div>
          </div>
          <div className="stat"><strong>Driver</strong><div className="value"><span className={`badge ${driverStatus==='ALERT'?'green':driverStatus==='DROWSY'?'orange':'red'}`}>{driverStatus}</span></div></div>
          <div className="stat"><strong>Emotion</strong>
            <div className="value">
              <span className="badge blue">
                {driverEmotion.driver_emotion} ({Math.round((driverEmotion.confidence || 0) * 100)}%)
              </span>
            </div>
          </div>
          <div className="stat"><strong>Stress Level</strong>
            <div className="value">
              <span className={`badge ${driverEmotion.stress_level === 'HIGH' ? 'red' : driverEmotion.stress_level === 'MEDIUM' ? 'orange' : 'green'}`}>
                {driverEmotion.stress_level || 'LOW'}
              </span>
            </div>
          </div>
          <div className="stat">
            <strong>AI Engine</strong>
            <div className="value">
              <span className={`badge ${aiEngineStatus ? 'green' : 'red'}`}>
                {aiEngineStatus ? 'Connected' : 'Offline'}
              </span>
            </div>
          </div>
        </div>

        <div className="card map">
          <div style={{height:240}}>
            <LiveMap position={position} />
          </div>
          <div className="caption">Live Map</div>
        </div>
      </div>
    </div>
  )
}
