import React, {useMemo, useState, useEffect} from 'react'
import { Link } from 'react-router-dom'
import { getTrips } from '../api/trips'

export default function Trips(){
  const [query, setQuery] = useState('')
  const [selectedDate, setSelectedDate] = useState('')
  const [trips, setTrips] = useState([])

  useEffect(()=>{
    let mounted = true
    getTrips().then(data=>{ if(mounted) setTrips(data) })
    return ()=> { mounted = false }
  },[])

  const getDateKey = (value) => {
    if(!value) return ''

    const raw = String(value).trim()
    const datePart = raw.split(',')[0]?.trim() || ''

    const ddmmyyyy = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(datePart)
    if(ddmmyyyy){
      const [, dd, mm, yyyy] = ddmmyyyy
      return `${yyyy}-${mm}-${dd}`
    }

    const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(raw)
    if(iso){
      const [, yyyy, mm, dd] = iso
      return `${yyyy}-${mm}-${dd}`
    }

    return ''
  }

  const filtered = useMemo(()=> trips.filter(t=> {
    const matchesQuery = t.id.toLowerCase().includes(query.toLowerCase()) || t.driver.toLowerCase().includes(query.toLowerCase())
    if(!matchesQuery) return false
    if(!selectedDate) return true
    return getDateKey(t.start) === selectedDate
  }),[trips,query,selectedDate])

  return (
    <div className="page trips">
      <div className="list-header">
        <h1>Trips</h1>
        <div className="header-filters">
          <input className="search" placeholder="Search by Trip or Driver" value={query} onChange={e=>setQuery(e.target.value)} />
          <input type="date" className="search" value={selectedDate} onChange={e=>setSelectedDate(e.target.value)} />
        </div>
      </div>
      <table className="trips-table">
        <thead>
          <tr>
            <th>S.No</th>
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
          {filtered.map((t, index)=> (
            <tr key={t.id}>
              <td>{index + 1}</td>
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
