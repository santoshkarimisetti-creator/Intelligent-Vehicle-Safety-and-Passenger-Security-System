import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import '../styles/events.css'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:5000'

export default function EmergencyEventsPage() {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [pageNum, setPageNum] = useState(1)
  const [pageBlockStart, setPageBlockStart] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const itemsPerPage = 10

  useEffect(() => {
    const fetchEmergencyEvents = async () => {
      try {
        setLoading(true)
        const response = await fetch(`${API_BASE}/events/emergency?limit=${itemsPerPage}&skip=${(pageNum - 1) * itemsPerPage}`)
        if (!response.ok) throw new Error('Failed to fetch emergency events')
        const data = await response.json()
        const eventsList = data.emergency_events || data.events || []
        
        // Sort by timestamp descending (newest first)
        eventsList.sort((a, b) => {
          const aTime = a?.received_at ? new Date(a.received_at).getTime() : 0
          const bTime = b?.received_at ? new Date(b.received_at).getTime() : 0
          return bTime - aTime
        })
        
        setEvents(eventsList)
        setTotalCount(data.total_sos_count || 0)
        setError(null)
      } catch (err) {
        setError(err.message)
        setEvents([])
        setTotalCount(0)
      } finally {
        setLoading(false)
      }
    }
    fetchEmergencyEvents()
  }, [pageNum])

  const totalPages = Math.max(1, Math.ceil((totalCount || 0) / itemsPerPage))
  const pageWindowStart = Math.max(1, pageBlockStart)
  const pageWindowEnd = Math.min(totalPages, pageWindowStart + 9)
  const visiblePages = Array.from(
    { length: Math.max(0, pageWindowEnd - pageWindowStart + 1) },
    (_, i) => pageWindowStart + i,
  )

  useEffect(() => {
    // Align number block only when current page changes.
    const pageAlignedBlockStart = Math.floor((pageNum - 1) / 10) * 10 + 1
    setPageBlockStart((prev) => (prev === pageAlignedBlockStart ? prev : pageAlignedBlockStart))
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
          <div className="sticky-page-nav" role="navigation" aria-label="SOS page navigation">
            <button
              onClick={() => setPageNum(Math.max(1, pageNum - 1))}
              disabled={pageNum === 1}
              className="pagination-btn"
            >
              Prev
            </button>
            <span className="page-info">Page {pageNum} / {totalPages}</span>
            <button
              onClick={() => setPageNum(Math.min(totalPages, pageNum + 1))}
              disabled={pageNum >= totalPages}
              className="pagination-btn"
            >
              Next
            </button>
          </div>

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
                    <Link to={`/trips/${event.trip_id}`} className="action-btn primary">View Trip Details</Link>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="pagination">
            <button 
              onClick={() => setPageBlockStart(Math.max(1, pageWindowStart - 10))}
              disabled={pageWindowStart === 1}
              className="pagination-btn"
            >
              {'<'}
            </button>

            {visiblePages.map(p => (
              <button
                key={p}
                onClick={() => setPageNum(p)}
                disabled={p === pageNum}
                className="pagination-btn pagination-page-btn"
              >
                {p}
              </button>
            ))}
            <button 
              onClick={() => setPageBlockStart(Math.min(totalPages, pageWindowStart + 10))}
              disabled={pageWindowEnd >= totalPages}
              className="pagination-btn"
            >
              {'>'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
