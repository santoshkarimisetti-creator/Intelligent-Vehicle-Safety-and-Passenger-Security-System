import React, {useMemo} from 'react'
import { MapContainer, TileLayer, Polyline, Marker, Popup } from 'react-leaflet'
import L from 'leaflet'

const startIcon = new L.Icon({
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  iconSize: [25,41],
  iconAnchor: [12,41]
})

export default function MapReplay({points}){
  // points: [{lat,lon,risk,timestamp}]
  const filteredPoints = useMemo(()=>{
    if(!points || points.length === 0) return []
    const toRad = value => (value * Math.PI) / 180
    const distanceMeters = (a, b) => {
      const r = 6371000
      const dLat = toRad(b.lat - a.lat)
      const dLon = toRad(b.lon - a.lon)
      const lat1 = toRad(a.lat)
      const lat2 = toRad(b.lat)
      const sinDLat = Math.sin(dLat / 2)
      const sinDLon = Math.sin(dLon / 2)
      const h = sinDLat * sinDLat + Math.cos(lat1) * Math.cos(lat2) * sinDLon * sinDLon
      return 2 * r * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h))
    }
    const bearingDeg = (a, b) => {
      const lat1 = toRad(a.lat)
      const lat2 = toRad(b.lat)
      const dLon = toRad(b.lon - a.lon)
      const y = Math.sin(dLon) * Math.cos(lat2)
      const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon)
      const brng = Math.atan2(y, x)
      return (brng * 180 / Math.PI + 360) % 360
    }

    const result = [points[0]]
    let lastBearing = null
    for(let i = 1; i < points.length; i++){
      const prev = result[result.length - 1]
      const current = points[i]
      const dist = distanceMeters(prev, current)
      const bearing = bearingDeg(prev, current)
      let deviation = 0
      if(lastBearing !== null){
        const diff = Math.abs(bearing - lastBearing)
        deviation = Math.min(diff, 360 - diff)
      }

      if(dist > 5 || deviation >= 45){
        result.push(current)
        lastBearing = bearing
      }
    }
    return result
  },[points])

  const center = useMemo(()=> filteredPoints.length? [filteredPoints[0].lat, filteredPoints[0].lon] : [0,0], [filteredPoints])

  // split into segments grouped by risk class
  const segments = useMemo(()=>{
    if(!filteredPoints || filteredPoints.length<2) return []
    const hasRisk = filteredPoints.some(p => Number.isFinite(p.risk))
    if(!hasRisk){
      return [{pts: filteredPoints.slice(), cls: 'neutral'}]
    }
    const segs = []
    let cur = [filteredPoints[0]]
    for(let i=1;i<filteredPoints.length;i++){
      const prev = filteredPoints[i-1]
      const p = filteredPoints[i]
      // if risk changes classification, split
      const prevClass = prev.risk >= 60? 'high' : prev.risk >= 30? 'moderate':'safe'
      const curClass = p.risk >= 60? 'high' : p.risk >= 30? 'moderate':'safe'
      cur.push(p)
      if(curClass !== prevClass){
        segs.push({pts: cur.slice(), cls: prevClass})
        cur = [p]
      }
    }
    segs.push({pts: cur, cls: (cur[cur.length-1].risk>=60? 'high': cur[cur.length-1].risk>=30? 'moderate':'safe')})
    return segs
  },[filteredPoints])

  const colorFor = cls => cls==='high'? '#c62828' : cls==='moderate'? '#f57c00' : cls==='neutral'? '#1565c0' : '#2e7d32'

  return (
    <MapContainer center={center} zoom={13} style={{height:'100%',borderRadius:8}}>
      <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      {segments.map((s,i)=> (
        <Polyline key={i} positions={s.pts.map(p=>[p.lat,p.lon])} pathOptions={{color: colorFor(s.cls), weight:5, opacity:0.9}} />
      ))}
      {filteredPoints && filteredPoints.length>0 && (
        <>
          <Marker position={[filteredPoints[0].lat, filteredPoints[0].lon]} icon={startIcon}>
            <Popup>Start</Popup>
          </Marker>
          <Marker position={[filteredPoints[filteredPoints.length-1].lat, filteredPoints[filteredPoints.length-1].lon]} icon={startIcon}>
            <Popup>End</Popup>
          </Marker>
        </>
      )}
    </MapContainer>
  )
}
