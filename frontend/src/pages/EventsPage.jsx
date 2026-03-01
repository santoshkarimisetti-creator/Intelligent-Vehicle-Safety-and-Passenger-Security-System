import React, { useState, useEffect, useMemo, useRef } from 'react'
import '../styles/events.css'

export default function EventsPage() {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedRiskLevel, setSelectedRiskLevel] = useState('')
  const [selectedEventType, setSelectedEventType] = useState('')
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

  // Play sound alert based on risk level
  const playAlert = (level) => {
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

    switch (level) {
      case 'MODERATE': {
        // Warning beep
        const osc = ctx.createOscillator()
        const gain = ctx.createGain()
        osc.connect(gain)
        gain.connect(ctx.destination)
        osc.frequency.value = 800
        osc.type = 'sine'
        gain.gain.setValueAtTime(0.3, ctx.currentTime)
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.5)
        osc.start(ctx.currentTime)
        osc.stop(ctx.currentTime + 0.5)
        oscillatorRef.current = osc
        break
      }
      case 'HIGH': {
        // Pulsing alert (3 pulses)
        let pulseCount = 0
        const playPulse = () => {
          if (pulseCount >= 3) return
          const osc = ctx.createOscillator()
          const gain = ctx.createGain()
          osc.connect(gain)
          gain.connect(ctx.destination)
          osc.frequency.value = 1000
          osc.type = 'square'
          gain.gain.setValueAtTime(0.2, ctx.currentTime)
          gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.15)
          osc.start(ctx.currentTime)
          osc.stop(ctx.currentTime + 0.15)
          pulseCount++
          alertTimeoutRef.current = setTimeout(playPulse, 200)
        }
        playPulse()
        break
      }
      case 'CRITICAL': {
        // Continuous alarm (3 cycles)
        let cycleCount = 0
        const playCycle = () => {
          if (cycleCount >= 3) return
          const osc = ctx.createOscillator()
          const gain = ctx.createGain()
          osc.connect(gain)
          gain.connect(ctx.destination)
          osc.frequency.setValueAtTime(1200, ctx.currentTime)
          osc.frequency.exponentialRampToValueAtTime(800, ctx.currentTime + 0.3)
          osc.type = 'square'
          gain.gain.setValueAtTime(0.25, ctx.currentTime)
          gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3)
          osc.start(ctx.currentTime)
          osc.stop(ctx.currentTime + 0.3)
          cycleCount++
          alertTimeoutRef.current = setTimeout(playCycle, 400)
        }
        playCycle()
        break
      }
      default:
        break
    }
  }

  // Trigger sound when high-risk event appears
  useEffect(() => {
    if (events.length > 0) {
      const highestRisk = events[0]?.risk_level
      if (highestRisk === 'HIGH' || highestRisk === 'CRITICAL') {
        playAlert(highestRisk)
      } else if (highestRisk === 'MODERATE') {
        playAlert('MODERATE')
      }
    }
  }, [events])

  useEffect(() => {
    const fetchEvents = async () => {
      try {
        setLoading(true)
        const response = await fetch(`http://localhost:5000/events?limit=${itemsPerPage}&skip=${(pageNum - 1) * itemsPerPage}`)
        if (!response.ok) throw new Error('Failed to fetch events')
        const data = await response.json()
        setEvents(data.events || [])
        setError(null)
      } catch (err) {
        setError(err.message)
        setEvents([])
      } finally {
        setLoading(false)
      }
    }
    fetchEvents()
  }, [pageNum])

  const filtered = useMemo(() => {
    let result = events

    if (selectedRiskLevel) {
      result = result.filter(e => e.risk_level === selectedRiskLevel)
    }

    if (selectedEventType) {
      result = result.filter(e => e.event_type === selectedEventType)
    }

    return result
  }, [events, selectedRiskLevel, selectedEventType])

  const eventTypes = [...new Set(events.map(e => e.event_type).filter(Boolean))]
  const riskLevels = ['SAFE', 'MODERATE', 'HIGH', 'CRITICAL']

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

  const getRiskColor = (level) => {
    switch(level) {
      case 'SAFE': return '#4caf50'
      case 'MODERATE': return '#ff9800'
      case 'HIGH': return '#f44336'
      case 'CRITICAL': return '#8b0000'
      default: return '#999'
    }
  }

  return (
    <div className="page events">
      <div className="list-header">
        <h1>Detection Events</h1>
        <p className="subtitle">All background monitoring detections</p>
      </div>

      <div className="events-filters">
        <select 
          value={selectedRiskLevel} 
          onChange={e => {
            setSelectedRiskLevel(e.target.value)
            setPageNum(1)
          }}
          className="filter-select"
        >
          <option value="">All Risk Levels</option>
          {riskLevels.map(level => (
            <option key={level} value={level}>{level}</option>
          ))}
        </select>

        <select 
          value={selectedEventType} 
          onChange={e => {
            setSelectedEventType(e.target.value)
            setPageNum(1)
          }}
          className="filter-select"
        >
          <option value="">All Event Types</option>
          {eventTypes.map(type => (
            <option key={type} value={type}>{type}</option>
          ))}
        </select>
      </div>

      {loading && <div className="loading">Loading events...</div>}
      {error && <div className="error">Error: {error}</div>}

      {!loading && filtered.length === 0 && (
        <div className="no-data">No events found</div>
      )}

      {!loading && filtered.length > 0 && (
        <>
          <div className="events-list">
            {filtered.map(event => (
              <div key={event._id} className="event-card">
                <div className="event-header">
                  <h3>{event.event_type || 'Unknown Event'}</h3>
                  <span 
                    className="risk-badge" 
                    style={{ backgroundColor: getRiskColor(event.risk_level) }}
                  >
                    {event.risk_level || 'N/A'}
                  </span>
                </div>

                <div className="event-details">
                  <p><strong>Timestamp:</strong> {formatTimestamp(event.timestamp)}</p>
                  <p><strong>Risk Score (Weighted):</strong> {event.risk_score_weighted?.toFixed(2) || 'N/A'}</p>
                  {event.risk_score_temporal && (
                    <p><strong>Risk Score (Temporal):</strong> {event.risk_score_temporal.toFixed(2)}</p>
                  )}
                </div>

                {event.detections && Object.keys(event.detections).length > 0 && (
                  <div className="event-detections">
                    <strong>Detections:</strong>
                    <ul>
                      {Object.entries(event.detections).map(([key, val]) => (
                        <li key={key}>
                          {key}: <span className="detection-value">{val}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {event.location && (
                  <div className="event-location">
                    <strong>Location:</strong> {event.location.latitude?.toFixed(5)}, {event.location.longitude?.toFixed(5)}
                  </div>
                )}
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
              disabled={filtered.length < itemsPerPage}
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
