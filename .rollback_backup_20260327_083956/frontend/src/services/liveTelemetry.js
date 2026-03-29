export function subscribeLive(cb){
  let lat = 37.7749, lon = -122.4194, speed = 0, risk = 10
  let driverStatus = 'ALERT'
  let state = 'IDLE'

  const t = setInterval(()=>{
    const dLat = (Math.random()-0.5) * 0.0005
    const dLon = (Math.random()-0.5) * 0.0005
    lat += dLat
    lon += dLon

    speed = Math.max(0, speed + (Math.random()-0.5)*6)
    state = speed > 5 ? 'ACTIVE' : 'IDLE'
    risk = Math.min(100, Math.max(0, risk + (Math.random()-0.5)*6))

    if(risk > 60) driverStatus = 'DROWSY'
    else if(risk > 30) driverStatus = 'YAWNING'
    else driverStatus = 'ALERT'

    cb({
      speed: Math.round(speed),
      lat,
      lon,
      state,
      risk: Math.round(risk),
      driverStatus,
      timestamp: Date.now()
    })
  }, 1500)

  return () => clearInterval(t)
}

export default { subscribeLive }
