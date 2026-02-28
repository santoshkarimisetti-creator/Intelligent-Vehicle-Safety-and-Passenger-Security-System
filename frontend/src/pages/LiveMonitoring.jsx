import React, {useEffect, useRef, useState} from 'react'
import { subscribeLive } from '../services/liveTelemetry'
import LiveMap from '../components/LiveMap'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:5000'

export default function LiveMonitoring(){
  const videoRef = useRef(null)
  const [speed, setSpeed] = useState(45)
  const [state, setState] = useState('ACTIVE')
  const [risk, setRisk] = useState(12)
  const [driverStatus, setDriverStatus] = useState('ALERT')
  const [sos, setSos] = useState(false)
  const [position, setPosition] = useState(null)
  const [distanceKm, setDistanceKm] = useState(0)
  const [tripId, setTripId] = useState(null)

  useEffect(()=>{
    // start webcam
    async function startCam(){
      try{
        const stream = await navigator.mediaDevices.getUserMedia({video:true,audio:false})
        if(videoRef.current) videoRef.current.srcObject = stream
      }catch(e){
        console.warn('No camera available', e)
      }
    }
    startCam()

    // subscribe to live telemetry (mock) so you can see speed/map without backend
    const unsub = subscribeLive(data =>{
      setSpeed(data.speed)
      setRisk(data.risk)
      setState(data.state)
      setDriverStatus(data.driverStatus)
      if(data.lat && data.lon){
        setPosition([data.lat, data.lon])
        // Set a dummy trip ID for demo (in real app, use actual trip ID)
        if(!tripId) setTripId('active-trip')
      }
    })

    return ()=> unsub()
  },[tripId])

  // Fetch live distance from backend
  useEffect(()=>{
    if(!tripId) return
    
    const fetchDistance = async () => {
      try {
        const res = await fetch(`${API_BASE}/trips/${encodeURIComponent(tripId)}/distance`)
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

  return (
    <div className="page live">
      {sos && <div className="emergency">EMERGENCY: SOS triggered</div>}
      <div className="live-grid">
        <div className="card camera">
          <video ref={videoRef} autoPlay playsInline muted />
          <div className="speed-overlay">
            <div>Speed: {Math.round(speed)} km/h</div>
            <div className="distance-inline">Distance: {distanceKm.toFixed(2)} km</div>
          </div>
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
