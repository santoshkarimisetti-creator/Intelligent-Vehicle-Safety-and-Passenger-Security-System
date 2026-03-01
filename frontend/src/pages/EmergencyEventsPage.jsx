import React, { useState, useEffect, useRef } from 'react'
import '../styles/events.css'

export default function EmergencyEventsPage() {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [pageNum, setPageNum] = useState(1)
  const itemsPerPage = 10

  const audioContextRef = useRef(null)
  const oscillatorRef = useRef(null)
  const gainNodeRef = useRef(null)
  const alertTimeoutRef = useRef(null)

  // Initialize Web Audio API
  useEffect(() => {
    if (!audioContextRef.current) {
      audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)()
    }
  }, [])

  // Play critical SOS alarm
  const playSOSAlarm = () => {
    if (!audioContextRef.current) return

    // Stop any existing sound
    if (alertTimeoutRef.current) clearTimeout(alertTimeoutRef.current)
    if (oscillatorRef.current) {
      try {
        oscillatorRef.current.stop()
        oscillatorRef.current.disconnect()
      } catch (e) {}
    }
    if (gainNodeRef.current) {
      try {
        gainNodeRef.current.disconnect()
      } catch (e) {}
    }

    const ctx = audioContextRef.current
    let cycleCount = 0

    const playCycle = () => {
      if (cycleCount >= 5) return // Repeat 5 times

      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.connect(gain)
      gain.connect(ctx.destination)

      osc.frequency.setValueAtTime(1500, ctx.currentTime)
      osc.frequency.exponentialRampToValueAtTime(700, ctx.currentTime + 0.4)
      osc.type = 'square'

      gain.gain.setValueAtTime(0.3, ctx.currentTime)
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.4)

      osc.start(ctx.currentTime)
      osc.stop(ctx.currentTime + 0.4)

      cycleCount++
      alertTimeoutRef.current = setTimeout(playCycle, 500)
    }

    playCycle()
  }

  // Play alarm when emergency events appear
  useEffect(() => {
    if (events.length > 0) {
      playSOSAlarm()
    }
  }, [events])

  useEffect(() => {
    const fetchEmergencyEvents = async () => {
      try {
        setLoading(true)
        const response = await fetch(`http://localhost:5000/events/emergency?limit=${itemsPerPage}&skip=${(pageNum - 1) * itemsPerPage}`)
        if (!response.ok) throw new Error('Failed to fetch emergency events')
        const data = await response.json()
        setEvents(data.emergency_events || data.events || [])
        setError(null)
      } catch (err) {
        setError(err.message)
        setEvents([])
      } finally {
        setLoading(false)
      }
    }
    fetchEmergencyEvents()
  }, [pageNum])

  const formatTimestamp = (ts) => {
    if (!ts) return 'Unknown'
    
    // If already formatted with IST, just return it
    if (typeof ts === 'string' && ts.includes('IST')) {
      return ts
    }
    
    try {
      const dateObj = new Date(ts)
      if (isNaN(dateObj.getTime())) {
        return ts
      }
      return dateObj.toLocaleString('en-IN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true
      })
    } catch (e) {
      return ts
    }
  }

  return (
    <div className="page emergency-events">
      <div className="emergency-header">
        <div className="emergency-title">
          <span className="emergency-icon">🚨</span>
          <h1>SOS Events</h1>
        </div>
        <p className="subtitle">Emergency alerts triggered</p>
      </div>

      {loading && <div className="loading">Loading emergency events...</div>}
      {error && <div className="error">Error: {error}</div>}

      {!loading && events.length === 0 && (
        <div className="no-data">No SOS events recorded</div>
      )}

      {!loading && events.length > 0 && (
        <>
          <div className="emergency-list">
            {events.map(event => (
              <div key={event._id} className="emergency-card">
                <div className="emergency-card-header">
                  <div className="sos-indicator">🚨 SOS TRIGGERED</div>
                  <span className="timestamp">{formatTimestamp(event.timestamp)}</span>
                </div>

                <div className="emergency-details">
                  {event.trip_id && (
                    <p className="trip-info"><strong>Trip ID:</strong> {event.trip_id}</p>
                  )}
                  
                  {event.driver_id && (
                    <p className="driver-info"><strong>Driver ID:</strong> {event.driver_id}</p>
                  )}

                  {event.message && (
                    <p className="sos-message"><strong>Alert:</strong> {event.message}</p>
                  )}

                  {event.source && (
                    <p className="source-info"><strong>Source:</strong> {event.source}</p>
                  )}

                  {event.location && (event.location.latitude || event.location.longitude) && (
                    <div className="location-info">
                      <strong>Location:</strong>
                      <div className="coordinates">
                        <span>Lat: {event.location.latitude?.toFixed(5) || 'N/A'}</span>
                        <span>Lon: {event.location.longitude?.toFixed(5) || 'N/A'}</span>
                      </div>
                    </div>
                  )}

                  {event.vehicle_info && (
                    <div className="vehicle-info">
                      <strong>Vehicle:</strong> {event.vehicle_info}
                    </div>
                  )}

                  {event.detections && Object.keys(event.detections).length > 0 && (
                    <div className="detections-info">
                      <strong>Detections at SOS Time:</strong>
                      <ul>
                        {Object.entries(event.detections).map(([key, val]) => (
                          <li key={key}>
                            {key}: <span className="value">{val}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {event.risk_score_weighted && (
                    <div className="risk-info">
                      <strong>Risk Score at SOS:</strong> {event.risk_score_weighted.toFixed(2)}/100
                    </div>
                  )}
                </div>

                <div className="emergency-actions">
                  {event.trip_id && (
                    <a href={`/#/trips/${event.trip_id}`} className="action-btn primary">View Trip Details</a>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="pagination">
            <button 
              onClick={() => setPageNum(Math.max(1, pageNum - 1))}
              disabled={pageNum === 1}
              className="pagination-btn"
            >
              Previous
            </button>
            <span className="page-info">Page {pageNum}</span>
            <button 
              onClick={() => setPageNum(pageNum + 1)}
              disabled={events.length < itemsPerPage}
              className="pagination-btn"
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  )
}
