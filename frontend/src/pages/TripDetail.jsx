import React, {useEffect, useMemo, useState} from 'react'
import { useParams, Link } from 'react-router-dom'
import MapReplay from '../components/MapReplay'
import { getTrip } from '../api/trips'

export default function TripDetail(){
  const { id } = useParams()
  const [trip, setTrip] = useState(null)
  const [path, setPath] = useState([])
  const [events, setEvents] = useState([])
  const [error, setError] = useState('')

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
            <li>Max Speed: {trip?.maxSpeed ?? '-'}</li>
            <li>Risk Level: {trip?.risk || 'Unknown'}</li>
          </ul>
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
