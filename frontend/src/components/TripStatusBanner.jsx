import React from 'react'

function pad2(n) {
  return String(Math.max(0, Number(n) || 0)).padStart(2, '0')
}

function formatHMS(totalSeconds) {
  const s = Math.max(0, Math.floor(Number(totalSeconds) || 0))
  const hours = Math.floor(s / 3600)
  const minutes = Math.floor((s % 3600) / 60)
  const seconds = s % 60

  if (hours > 0) return `${hours}:${pad2(minutes)}:${pad2(seconds)}`
  return `${pad2(minutes)}:${pad2(seconds)}`
}

export default function TripStatusBanner({ type, elapsedSeconds }) {
  let className = 'trip-banner blue'
  let label = 'No active trip'
  let showTimer = false

  if (type === 'TRIP_STARTED') {
    className = 'trip-banner green'
    label = 'Trip started'
    showTimer = true
  } else if (type === 'TRIP_ACTIVE') {
    className = 'trip-banner green'
    label = 'Trip active'
    showTimer = true
  } else if (type === 'TRIP_ENDED') {
    className = 'trip-banner red'
    label = 'Trip ended'
    showTimer = false
  }

  return (
    <div className={className} role="status" aria-live="polite">
      <div className="trip-banner-left">{label}</div>
      {showTimer && (
        <div className="trip-banner-right">
          <span className="trip-banner-timer">{formatHMS(elapsedSeconds)}</span>
        </div>
      )}
    </div>
  )
}
