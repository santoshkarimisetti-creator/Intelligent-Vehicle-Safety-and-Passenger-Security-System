import React, { useState, useEffect, useMemo } from 'react'
import '../styles/events.css'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:5000'

export default function EventsPage() {
  const [events, setEvents] = useState([])
  const [eventTypeOptions, setEventTypeOptions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedRiskLevel, setSelectedRiskLevel] = useState('')
  const [selectedEventType, setSelectedEventType] = useState('')
  const [datePreset, setDatePreset] = useState('') // '', 'today', 'yesterday', 'custom'
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [pageNum, setPageNum] = useState(1)
  const [pageBlockStart, setPageBlockStart] = useState(1)
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

        const optionsParams = new URLSearchParams({
          limit: '500',
          skip: '0',
        })
        if (selectedRiskLevel) optionsParams.set('risk_level', selectedRiskLevel)
        if (start) optionsParams.set('start', start.toISOString())
        if (end) optionsParams.set('end', end.toISOString())

        const [response, optionsResponse] = await Promise.all([
          fetch(`${API_BASE}/events?${params.toString()}`),
          fetch(`${API_BASE}/events?${optionsParams.toString()}`),
        ])

        if (!response.ok) throw new Error('Failed to fetch events')
        if (!optionsResponse.ok) throw new Error('Failed to fetch event type options')

        const data = await response.json()
        const optionsData = await optionsResponse.json()
        const list = Array.isArray(data.events) ? data.events.slice() : []
        list.sort((a, b) => {
          const at = a?.received_at ? new Date(a.received_at).getTime() : (a?.timestamp ? new Date(a.timestamp).getTime() : 0)
          const bt = b?.received_at ? new Date(b.received_at).getTime() : (b?.timestamp ? new Date(b.timestamp).getTime() : 0)
          return bt - at
        })

        const sourceForOptions = Array.isArray(optionsData.events) ? optionsData.events : []
        const optionSet = new Set()
        for (const ev of sourceForOptions) {
          const label = String((ev?.event_label || ev?.event_type || '')).trim()
          if (label) optionSet.add(label)
        }

        // Keep currently selected option visible even if temporarily not in current result window.
        if (selectedEventType) optionSet.add(selectedEventType)

        setEvents(list)
        setEventTypeOptions(Array.from(optionSet).sort((a, b) => a.localeCompare(b)))
        setTotalCount(data.total_count || 0)
        setError(null)
      } catch (err) {
        setError(err.message)
        setEvents([])
        setEventTypeOptions([])
        setTotalCount(0)
      } finally {
        setLoading(false)
      }
    }
    fetchEvents()
  }, [pageNum, selectedRiskLevel, selectedEventType, datePreset, fromDate, toDate])

  const getEventLabel = (event) => {
    return String(event?.event_label || event?.event_type || 'Detection')
  }

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
            setPageBlockStart(1)
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
            setPageBlockStart(1)
          }}
          className="filter-select"
        >
          <option value="">All Event Types</option>
          {eventTypeOptions.map(type => (
            <option key={type} value={type}>{type}</option>
          ))}
        </select>

        <select
          value={datePreset}
          onChange={e => {
            setDatePreset(e.target.value)
            setPageNum(1)
            setPageBlockStart(1)
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
                setPageBlockStart(1)
              }}
              className="filter-select"
            />
            <input
              type="date"
              value={toDate}
              onChange={e => {
                setToDate(e.target.value)
                setPageNum(1)
                setPageBlockStart(1)
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
          <div className="sticky-page-nav" role="navigation" aria-label="Events page navigation">
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
                  <p><strong>Start Time:</strong> {formatTimestamp(event.start_time)}</p>
                  <p><strong>End Time:</strong> {formatTimestamp(event.end_time)}</p>
                  <p><strong>Risk Score:</strong> {event.risk_score != null ? Number(event.risk_score).toFixed(2) : 'N/A'}</p>
                  <p><strong>Emotion:</strong> {event.emotion || 'unknown'}</p>
                  <p><strong>Confidence:</strong> {event.confidence != null ? Number(event.confidence).toFixed(2) : 'N/A'}</p>
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
