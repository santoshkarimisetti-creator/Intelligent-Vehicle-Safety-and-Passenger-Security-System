import React, {useEffect, useMemo, useState} from 'react'
import { useParams, Link } from 'react-router-dom'
import MapReplay from '../components/MapReplay'
import { getTrip } from '../api/trips'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:5000'

function parseTimestampMs(value) {
  if (!value) return null
  const raw = String(value).trim()
  if (!raw) return null

  // Native parse handles ISO inputs.
  const nativeMs = new Date(raw).getTime()
  if (Number.isFinite(nativeMs)) return nativeMs

  // Handle backend display format: DD/MM/YYYY, hh:mm:ss AM IST
  const cleaned = raw.replace(' IST', '').trim()
  const m = cleaned.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4}),\s*(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)$/i)
  if (!m) return null

  const day = Number(m[1])
  const month = Number(m[2]) - 1
  const year = Number(m[3])
  let hour = Number(m[4])
  const minute = Number(m[5])
  const second = Number(m[6])
  const ampm = String(m[7]).toUpperCase()

  if (ampm === 'PM' && hour < 12) hour += 12
  if (ampm === 'AM' && hour === 12) hour = 0

  // Interpret parsed values as IST (+05:30) then convert to UTC epoch.
  const utcMs = Date.UTC(year, month, day, hour - 5, minute - 30, second)
  return Number.isFinite(utcMs) ? utcMs : null
}

function sameDayEpoch(msA, msB) {
  const a = new Date(msA)
  const b = new Date(msB)
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

export default function TripDetail(){
  const { id } = useParams()
  const [trip, setTrip] = useState(null)
  const [path, setPath] = useState([])
  const [events, setEvents] = useState([])
  const [error, setError] = useState('')
  const [downloading, setDownloading] = useState(false)
  const [eventTypeFilter, setEventTypeFilter] = useState('ALL')
  const [dateFilterMode, setDateFilterMode] = useState('ALL')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')

  useEffect(()=>{
    let mounted = true
    setError('')
    getTrip(id)
      .then(data => {
        if(!mounted) return
        setTrip(data.trip)
        setPath(data.path)
        setEvents(Array.isArray(data.events) ? data.events : [])
      })
      .catch(e => {
        if(!mounted) return
        setError('Unable to load trip data.')
        console.warn(e)
      })
    return ()=> { mounted = false }
  },[id])

  const sortedPath = useMemo(()=>{
    return path.slice().sort((a,b)=>{
      const at = a.timestamp ? new Date(a.timestamp).getTime() : 0
      const bt = b.timestamp ? new Date(b.timestamp).getTime() : 0
      return at - bt
    })
  },[path])

  const normalizedEvents = useMemo(()=>{
    return events.map((evt, index) => {
      const ts = evt.timestamp || evt.ts || evt.time || ''
      const type = evt.type || evt.event_type || evt.label || 'Activity'
      const desc = evt.description || evt.desc || evt.details || ''
      const tsMs = parseTimestampMs(ts)
      const labels = Array.isArray(evt.event_labels) ? evt.event_labels : []
      const detectionTypes = Array.isArray(evt.detections)
        ? evt.detections
          .map((d) => (d && typeof d === 'object' ? String(d.type || d.label || '').trim() : ''))
          .filter(Boolean)
        : []
      const rawTypeParts = String(type)
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean)
      const typeTokens = Array.from(
        new Set([...rawTypeParts, ...labels, ...detectionTypes].map((t) => String(t).trim().toLowerCase()).filter(Boolean))
      )
      return {
        id: evt.id || `${type}-${index}`,
        ts,
        tsMs,
        type,
        typeKey: String(type || 'Activity').trim().toLowerCase(),
        typeTokens,
        desc,
      }
    })
  },[events])

  const eventTypeOptions = useMemo(()=>{
    const uniq = new Map()
    normalizedEvents.forEach((evt) => {
      const candidates = Array.isArray(evt.typeTokens) && evt.typeTokens.length > 0
        ? evt.typeTokens
        : [String(evt.type || '').trim().toLowerCase()]

      candidates.forEach((key) => {
        const normalized = String(key || '').trim().toLowerCase()
        if (!normalized) return
        if (!uniq.has(normalized)) {
          uniq.set(normalized, normalized.replace(/_/g, ' ').replace(/\b\w/g, (ch) => ch.toUpperCase()))
        }
      })
    })
    return Array.from(uniq.values()).sort((a, b) => a.localeCompare(b))
  }, [normalizedEvents])

  const filteredEvents = useMemo(() => {
    const now = Date.now()
    let startMs = null
    let endMs = null

    if (dateFilterMode === 'TODAY') {
      startMs = new Date(new Date().getFullYear(), new Date().getMonth(), new Date().getDate()).getTime()
      endMs = now + 1
    } else if (dateFilterMode === 'LAST_24H') {
      startMs = now - (24 * 60 * 60 * 1000)
      endMs = now + 1
    } else if (dateFilterMode === 'LAST_7D') {
      startMs = now - (7 * 24 * 60 * 60 * 1000)
      endMs = now + 1
    } else if (dateFilterMode === 'CUSTOM') {
      startMs = customStart ? parseTimestampMs(customStart) : null
      endMs = customEnd ? parseTimestampMs(customEnd) : null
      if (endMs != null) {
        endMs += 1000
      }
    }

    return normalizedEvents.filter((evt) => {
      if (eventTypeFilter !== 'ALL') {
        const wanted = String(eventTypeFilter).trim().toLowerCase()
        const tokens = Array.isArray(evt.typeTokens) ? evt.typeTokens : [evt.typeKey]
        if (!tokens.includes(wanted)) {
          return false
        }
      }

      if (dateFilterMode === 'ALL') {
        return true
      }

      if (evt.tsMs == null) {
        return false
      }

      if (dateFilterMode === 'TODAY') {
        return sameDayEpoch(evt.tsMs, now)
      }

      if (startMs != null && evt.tsMs < startMs) {
        return false
      }
      if (endMs != null && evt.tsMs > endMs) {
        return false
      }
      return true
    })
  }, [normalizedEvents, eventTypeFilter, dateFilterMode, customStart, customEnd])

  const downloadReportPdf = async () => {
    if (!id || downloading) return
    setDownloading(true)
    try {
      const res = await fetch(`${API_BASE}/trip/${encodeURIComponent(id)}/report`)
      const contentType = String(res.headers.get('content-type') || '').toLowerCase()

      if (!res.ok || !contentType.includes('application/pdf')) {
        let message = `Download failed (${res.status})`
        try {
          if (contentType.includes('application/json')) {
            const body = await res.json()
            message = body?.error || body?.message || message
          } else {
            const text = await res.text()
            if (text) message = text.slice(0, 200)
          }
        } catch {
          // keep default message
        }
        throw new Error(message)
      }

      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${id}_report.pdf`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (e) {
      console.warn(e)
      setError(e?.message ? `Unable to download report: ${e.message}` : 'Unable to download report.')
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="page trip-detail">
      <h1>Trip {id}</h1>
      <div className="detail-grid">
        <section className="card fullmap">
          {error && <div>{error}</div>}
          {!error && sortedPath.length === 0 && <div>No path data available for this trip.</div>}
          {!error && sortedPath.length > 0 && <MapReplay points={sortedPath} />}
        </section>

        <section className="card stats">
          <h3>Trip Summary</h3>
          <ul>
            <li>Trip ID: {trip?.id || id || '-'}</li>
            <li>Driver ID: {trip?.driver || '-'}</li>
            <li>Status: {trip?.status || '-'}</li>
            <li>
            Start Time: {trip?.start || '-'}
          </li>
          <li>
            End Time: {trip?.end || '-'}
          </li>
            <li>Distance: {trip?.distanceKm ? `${trip.distanceKm} km` : '-'}</li>
            <li>Max Speed: {trip?.maxSpeed ?? '-'}</li>
            <li>Risk Level: {trip?.risk || 'Unknown'}</li>
          </ul>
          <div style={{marginTop: 12}}>
            <button
              className="action-btn primary"
              onClick={downloadReportPdf}
              disabled={downloading}
            >
              {downloading ? 'Downloading…' : 'Download Report'}
            </button>
          </div>
        </section>

        <section className="card alerts">
          <h3>Activities & Alerts</h3>
          {normalizedEvents.length === 0 && <div>No activity recorded for this trip.</div>}
          {normalizedEvents.length > 0 && (
            <div className="alerts-filters">
              <label>
                Event Type
                <select value={eventTypeFilter} onChange={(e) => setEventTypeFilter(e.target.value)}>
                  <option value="ALL">All Types</option>
                  {eventTypeOptions.map((type) => (
                    <option key={type} value={type}>{type}</option>
                  ))}
                </select>
              </label>

              <label>
                Date Filter
                <select value={dateFilterMode} onChange={(e) => setDateFilterMode(e.target.value)}>
                  <option value="ALL">All Dates</option>
                  <option value="TODAY">Today</option>
                  <option value="LAST_24H">Last 24 Hours</option>
                  <option value="LAST_7D">Last 7 Days</option>
                  <option value="CUSTOM">Custom Range</option>
                </select>
              </label>

              {dateFilterMode === 'CUSTOM' && (
                <>
                  <label>
                    From
                    <input
                      type="datetime-local"
                      value={customStart}
                      onChange={(e) => setCustomStart(e.target.value)}
                    />
                  </label>
                  <label>
                    To
                    <input
                      type="datetime-local"
                      value={customEnd}
                      onChange={(e) => setCustomEnd(e.target.value)}
                    />
                  </label>
                </>
              )}

              <div className="alerts-filter-meta">
                Showing {filteredEvents.length} of {normalizedEvents.length}
              </div>
            </div>
          )}
          {filteredEvents.length > 0 && (
            <table>
              <thead>
                <tr><th>Timestamp</th><th>Type</th><th>Description</th></tr>
              </thead>
              <tbody>
                {filteredEvents.map(e => (
                  <tr key={e.id}>
                    <td>{e.ts || '-'}</td>
                    <td>{e.type}</td>
                    <td>{e.desc || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {normalizedEvents.length > 0 && filteredEvents.length === 0 && (
            <div>No events match the selected filters.</div>
          )}
        </section>
      </div>

      <div className="actions"><Link to="/trips">← Back</Link></div>
    </div>
  )
}
