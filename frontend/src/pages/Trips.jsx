import React, {useMemo, useState, useEffect} from 'react'
import { Link } from 'react-router-dom'
import { getTrips } from '../mockBackend'

export default function Trips(){
  const [query, setQuery] = useState('')
  const [trips, setTrips] = useState([])

  useEffect(()=>{
    let mounted = true
    getTrips().then(data=>{ if(mounted) setTrips(data) })
    return ()=> { mounted = false }
  },[])

  const filtered = useMemo(()=> trips.filter(t=> (
    t.id.toLowerCase().includes(query.toLowerCase()) || t.driver.toLowerCase().includes(query.toLowerCase())
  )),[trips,query])

  return (
    <div className="page trips">
      <div className="list-header">
        <h1>Trips</h1>
        <input className="search" placeholder="Search by Trip or Driver" value={query} onChange={e=>setQuery(e.target.value)} />
      </div>
      <table className="trips-table">
        <thead>
          <tr>
            <th>Trip ID</th>
            <th>Driver ID</th>
            <th>Start Time</th>
            <th>End Time</th>
            <th>Max Speed</th>
            <th>Distance</th>
            <th>Risk Level</th>
            <th>Status</th>
            <th>View Details</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map(t=> (
            <tr key={t.id}>
              <td>{t.id}</td>
              <td>{t.driver}</td>
              <td>{t.start}</td>
              <td>{t.end || '-'}</td>
              <td>{t.maxSpeed}</td>
              <td>{t.distanceKm ? `${t.distanceKm.toFixed(2)} km` : '0 km'}</td>
              <td><span className={`pill ${t.risk.toLowerCase()}`}>{t.risk}</span></td>
              <td>{t.status}</td>
              <td><Link to={`/trips/${t.id}`} className="view-btn">View</Link></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
