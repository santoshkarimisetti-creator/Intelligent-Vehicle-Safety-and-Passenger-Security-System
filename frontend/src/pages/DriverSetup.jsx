import React, { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:5000'

export default function DriverSetup() {
  const navigate = useNavigate()
  const location = useLocation()

  const [driverName, setDriverName] = useState('')
  const [vehicleNo, setVehicleNo] = useState('')
  const [licenseNo, setLicenseNo] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const from = location.state?.from || '/live'

  const saveLocal = (name, vehicle, license) => {
    localStorage.setItem('driver_name', name)
    localStorage.setItem('vehicle_no', vehicle)
    localStorage.setItem('license_no', license)
  }

  const saveBackendSession = async (name, vehicle, license) => {
    // Best-effort: if backend is reachable, store session driver details.
    // This is used as a fallback when trips are created without driver fields.
    const res = await fetch(`${API_BASE}/driver-session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        driver_name: name,
        vehicle_no: vehicle,
        license_no: license,
        driver_id: license,
      }),
    })
    if (!res.ok) {
      const text = await res.text().catch(() => '')
      throw new Error(text || `Failed to store session (HTTP ${res.status})`)
    }
  }

  const onSubmit = async (e) => {
    e.preventDefault()
    setError(null)

    const name = String(driverName || '').trim()
    const vehicle = String(vehicleNo || '').trim()
    const license = String(licenseNo || '').trim()

    if (!name || !vehicle || !license) {
      setError('All fields are required.')
      return
    }

    try {
      setSubmitting(true)
      saveLocal(name, vehicle, license)
      await saveBackendSession(name, vehicle, license)
      navigate(from, { replace: true })
    } catch (err) {
      setSubmitting(false)
      setError(err?.message || 'Failed to start session')
    }
  }

  return (
    <div className="page" style={{ maxWidth: 720 }}>
      <h1>Driver Setup</h1>
      <div className="caption">Enter driver details to start a session.</div>

      <div className="card" style={{ marginTop: 12 }}>
        <form onSubmit={onSubmit}>
          <div style={{ display: 'grid', gap: 10 }}>
            <label style={{ fontSize: 12, color: '#526070' }}>
              Driver Name
              <input
                value={driverName}
                onChange={(e) => setDriverName(e.target.value)}
                className="search"
                style={{ width: '100%', marginTop: 6 }}
                autoComplete="name"
                required
              />
            </label>

            <label style={{ fontSize: 12, color: '#526070' }}>
              Vehicle Number
              <input
                value={vehicleNo}
                onChange={(e) => setVehicleNo(e.target.value)}
                className="search"
                style={{ width: '100%', marginTop: 6 }}
                autoComplete="off"
                required
              />
            </label>

            <label style={{ fontSize: 12, color: '#526070' }}>
              License Number
              <input
                value={licenseNo}
                onChange={(e) => setLicenseNo(e.target.value)}
                className="search"
                style={{ width: '100%', marginTop: 6 }}
                autoComplete="off"
                required
              />
            </label>

            <button
              type="submit"
              className="view-btn"
              style={{ width: '100%', padding: '10px 12px', textAlign: 'center', border: 0, cursor: 'pointer' }}
              disabled={submitting}
            >
              {submitting ? 'Starting…' : 'Start Session'}
            </button>

            {error ? (
              <div style={{ color: '#b71c1c', fontSize: 12, whiteSpace: 'pre-wrap' }}>{error}</div>
            ) : null}
          </div>
        </form>
      </div>
    </div>
  )
}
