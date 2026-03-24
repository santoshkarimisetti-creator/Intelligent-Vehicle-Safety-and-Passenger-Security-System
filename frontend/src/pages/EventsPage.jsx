import React, { useState, useEffect, useMemo } from 'react'
import '../styles/events.css'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:5000'

export default function EventsPage() {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedRiskLevel, setSelectedRiskLevel] = useState('')
  const [selectedEventType, setSelectedEventType] = useState('')
  const [datePreset, setDatePreset] = useState('') // '', 'today', 'yesterday', 'custom'
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [pageNum, setPageNum] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const itemsPerPage = 10

  useEffect(() => {
    const fetchEvents = async () => {
      try {
        setLoading(true)

        const params = new URLSearchParams({
          limit: String(itemsPerPage),
          skip: String((pageNum - 1) * itemsPerPage),
        })

        if (selectedRiskLevel) params.set('risk_level', selectedRiskLevel)
        if (selectedEventType) params.set('event_type', selectedEventType)

        const now = new Date()
        const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate())

        let start = null
        let end = null
        if (datePreset === 'today') {
          start = startOfDay(now)
          end = new Date(start)
          end.setDate(end.getDate() + 1)
        } else if (datePreset === 'yesterday') {
          start = startOfDay(now)
          start.setDate(start.getDate() - 1)
          end = new Date(start)
          end.setDate(end.getDate() + 1)
        } else if (datePreset === 'custom' && fromDate) {
          start = new Date(`${fromDate}T00:00:00`)
          if (toDate) {
            end = new Date(`${toDate}T00:00:00`)
            end.setDate(end.getDate() + 1)
          } else {
            end = new Date(start)
            end.setDate(end.getDate() + 1)
          }
        }
        if (start) params.set('start', start.toISOString())
        if (end) params.set('end', end.toISOString())

        const response = await fetch(`${API_BASE}/events?${params.toString()}`)
        if (!response.ok) throw new Error('Failed to fetch events')
        const data = await response.json()
        const list = Array.isArray(data.events) ? data.events.slice() : []
        list.sort((a, b) => {
          const at = a?.received_at ? new Date(a.received_at).getTime() : (a?.timestamp ? new Date(a.timestamp).getTime() : 0)
          const bt = b?.received_at ? new Date(b.received_at).getTime() : (b?.timestamp ? new Date(b.timestamp).getTime() : 0)
          return bt - at
        })
        setEvents(list)
        setTotalCount(data.total_count || 0)
        setError(null)
      } catch (err) {
        setError(err.message)
        setEvents([])
        setTotalCount(0)
      } finally {
        setLoading(false)
      }
    }
    fetchEvents()
  }, [pageNum, selectedRiskLevel, selectedEventType, datePreset, fromDate, toDate])

  const _extractLabels = (event) => {
    const detections = event?.event_labels || event?.detections
    const labels = []

    if (Array.isArray(detections)) {
      for (const d of detections) {
        if (typeof d === 'string') {
          if (d.trim()) labels.push(d.trim())
        } else if (d && typeof d === 'object') {
          const label = d.type || d.label || d.name || d.event
          if (label) labels.push(String(label))
        }
      }
    } else if (detections && typeof detections === 'object') {
      for (const [k, v] of Object.entries(detections)) {
        if (v) labels.push(k)
      }
    }

    return [...new Set(labels.filter(Boolean))]
  }

  const getEventLabel = (event) => {
    const raw = (event?.event_type || '').trim()
    const labels = _extractLabels(event)

    // If we have multiple labels, always prefer showing them.
    if (labels.length > 1) return labels.join(', ')

    // If backend gave a meaningful type, use it.
    if (raw && raw !== 'DETECTION' && raw !== 'AI Detection') return raw

    const uniq = labels
    if (uniq.length === 1) return uniq[0]
    return 'Detection'
  }

  const eventTypes = useMemo(() => {
    const labels = []
    for (const e of events) {
      for (const l of _extractLabels(e)) labels.push(l)
    }
    return [...new Set(labels.filter(Boolean))]
  }, [events])

  const totalPages = Math.max(1, Math.ceil((totalCount || 0) / itemsPerPage))
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

        <select
          value={datePreset}
          onChange={e => {
            setDatePreset(e.target.value)
            setPageNum(1)
          }}
          className="filter-select"
        >
          <option value="">All Dates</option>
          <option value="today">Today</option>
          <option value="yesterday">Yesterday</option>
          <option value="custom">Custom</option>
        </select>

        {datePreset === 'custom' && (
          <>
            <input
              type="date"
              value={fromDate}
              onChange={e => {
                setFromDate(e.target.value)
                setPageNum(1)
              }}
              className="filter-select"
            />
            <input
              type="date"
              value={toDate}
              onChange={e => {
                setToDate(e.target.value)
                setPageNum(1)
              }}
              className="filter-select"
            />
          </>
        )}
      </div>

      {loading && <div className="loading">Loading events...</div>}
      {error && <div className="error">Error: {error}</div>}

      {!loading && events.length === 0 && (
        <div className="no-data">No events found</div>
      )}

      {!loading && events.length > 0 && (
        <>
          <div className="events-list">
            {events.map(event => (
              <div key={event._id} className="event-card">
                <div className="event-header">
                  <h3>{getEventLabel(event)}</h3>
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

                {event.detections && ((Array.isArray(event.detections) && event.detections.length > 0) || (!Array.isArray(event.detections) && Object.keys(event.detections).length > 0)) && (
                  <div className="event-detections">
                    <strong>Detections:</strong>
                    <ul>
                      {Array.isArray(event.detections)
                        ? event.detections.map((d, idx) => {
                            if (typeof d === 'string') {
                              return (
                                <li key={`${d}-${idx}`}>
                                  {d}
                                </li>
                              )
                            }
                            return (
                              <li key={`${d?.type || 'detection'}-${idx}`}>
                                {d?.type || 'unknown'}: <span className="detection-value">{d?.confidence != null ? `${Math.round(d.confidence * 100)}%` : 'N/A'}</span>
                              </li>
                            )
                          })
                        : Object.entries(event.detections).map(([key, val]) => (
                            <li key={key}>
                              {key}: <span className="detection-value">{typeof val === 'object' ? JSON.stringify(val) : String(val)}</span>
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
            <span className="page-info">Page {pageNum} / {totalPages}</span>

            {Array.from({ length: totalPages }, (_, i) => i + 1).map(p => (
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
              onClick={() => setPageNum(pageNum + 1)}
              disabled={pageNum >= totalPages}
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
