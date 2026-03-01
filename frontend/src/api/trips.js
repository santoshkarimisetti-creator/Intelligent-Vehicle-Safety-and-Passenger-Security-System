const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:5000'

function computeDistanceKm(trip){
  return trip.distance_km || 0
}

function mapTrip(trip){
  return {
    id: trip.trip_id || trip.id || '',
    driver: trip.driver_id || trip.driver || '',
    start: trip.start_time || trip.start || '',
    end: trip.end_time || trip.end || '',
    durationMinutes: trip.duration_minutes || 0,
    maxSpeed: Number(trip.max_speed ?? trip.maxSpeed ?? 0),
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
  
  // Backend already computes distance_km in /trips endpoint
  return trips.map(mapTrip)
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

export default { getTrips, getTrip }
