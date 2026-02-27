// Backend API helpers for trips and live telemetry.

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:5000'

function formatDate(value){
  if(!value) return ''
  const date = new Date(value)
  if(Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString()
}

function computeMaxSpeed(trip){
  const points = Array.isArray(trip.sensor_data) ? trip.sensor_data : []
  let maxSpeed = 0
  points.forEach(p => {
    const speed = Number(p.speed)
    if(Number.isFinite(speed)) maxSpeed = Math.max(maxSpeed, speed)
  })
  return maxSpeed
}

function computeDistanceKm(trip){
  // Distance is now fetched from backend endpoint, not computed here
  return trip.distance_km || 0
}

function mapTrip(trip){
  return {
    id: trip.trip_id || trip.id || '',
    driver: trip.driver_id || trip.driver || '',
    start: formatDate(trip.start_time || trip.start),
    end: formatDate(trip.end_time || trip.end),
    maxSpeed: computeMaxSpeed(trip),
    distanceKm: computeDistanceKm(trip),
    risk: trip.risk_level || trip.risk || 'Unknown',
    status: trip.status || 'Unknown',
  }
}

export async function getTrips(){
  const res = await fetch(`${API_BASE}/trips`)
  if(!res.ok) throw new Error('Failed to fetch trips')
  const data = await res.json()
  const trips = Array.isArray(data.trips) ? data.trips : []
  
  // Fetch distance for each trip
  const tripsWithDistance = await Promise.all(trips.map(async trip => {
    try {
      const distRes = await fetch(`${API_BASE}/trips/${encodeURIComponent(trip.trip_id)}/distance`)
      if(distRes.ok){
        const distData = await distRes.json()
        trip.distance_km = distData.distance_km || 0
      }
    } catch(e) {
      console.warn(`Failed to fetch distance for trip ${trip.trip_id}`, e)
      trip.distance_km = 0
    }
    return trip
  }))
  
  return tripsWithDistance.map(mapTrip)
}

export async function getTrip(id){
  const res = await fetch(`${API_BASE}/trips/${encodeURIComponent(id)}`)
  if(!res.ok) throw new Error('Failed to fetch trip')
  const trip = await res.json()
  const path = Array.isArray(trip.path) ? trip.path : []
  const events = Array.isArray(trip.events) ? trip.events : []
  return {
    trip: mapTrip(trip),
    path: path.map(p => ({
      lat: Number(p.lat),
      lon: Number(p.lon),
      timestamp: p.timestamp
    })).filter(p => Number.isFinite(p.lat) && Number.isFinite(p.lon)),
    events
  }
}

// Live telemetry simulator: emits an object {speed, lat, lon, state, risk, driverStatus, timestamp}
export function subscribeLive(cb){
  let lat = 37.7749, lon = -122.4194, speed = 0, risk = 10
  let driverStatus = 'ALERT'
  let state = 'IDLE'

  const t = setInterval(()=>{
    // random walk position
    const dLat = (Math.random()-0.5) * 0.0005
    const dLon = (Math.random()-0.5) * 0.0005
    lat += dLat; lon += dLon
    // vary speed
    speed = Math.max(0, speed + (Math.random()-0.5)*6)
    // set state and risk
    state = speed > 5 ? 'ACTIVE' : 'IDLE'
    risk = Math.min(100, Math.max(0, risk + (Math.random()-0.5)*6))
    if(risk>60) driverStatus = 'DROWSY'
    else if(risk>30) driverStatus = 'YAWNING'
    else driverStatus = 'ALERT'

    cb({speed: Math.round(speed), lat, lon, state, risk: Math.round(risk), driverStatus, timestamp: Date.now()})
  }, 1500)

  // return unsubscribe
  return () => clearInterval(t)
}

export default { getTrips, getTrip, subscribeLive }
