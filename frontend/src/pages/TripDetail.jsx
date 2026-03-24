import React, {useEffect, useMemo, useState} from 'react'
import { useParams, Link } from 'react-router-dom'
import MapReplay from '../components/MapReplay'
import { getTrip } from '../api/trips'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:5000'

export default function TripDetail(){
  const { id } = useParams()
  const [trip, setTrip] = useState(null)
  const [path, setPath] = useState([])
  const [events, setEvents] = useState([])
  const [error, setError] = useState('')
  const [downloading, setDownloading] = useState(false)

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
      return { id: evt.id || `${type}-${index}`, ts, type, desc }
    })
  },[events])

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
            <table>
              <thead>
                <tr><th>Timestamp</th><th>Type</th><th>Description</th></tr>
              </thead>
              <tbody>
                {normalizedEvents.map(e => (
                  <tr key={e.id}>
                    <td>{e.ts || '-'}</td>
                    <td>{e.type}</td>
                    <td>{e.desc || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      <div className="actions"><Link to="/trips">← Back</Link></div>
    </div>
  )
}
