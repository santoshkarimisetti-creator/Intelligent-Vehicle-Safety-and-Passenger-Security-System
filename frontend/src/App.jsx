import React, { useEffect, useState } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import LiveMonitoring from './pages/LiveMonitoring'
import Trips from './pages/Trips'
import TripDetail from './pages/TripDetail'
import EventsPage from './pages/EventsPage'
import EmergencyEventsPage from './pages/EmergencyEventsPage'
import DriverSetup from './pages/DriverSetup'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:5000'
const BOOT_ID_KEY = 'ivs_backend_boot_id'

function clearDriverSetup() {
  try {
    localStorage.removeItem('driver_name')
    localStorage.removeItem('vehicle_no')
    localStorage.removeItem('license_no')
  } catch {
    // ignore
  }
}

function hasDriverDetails() {
  try {
    const isValid = (value) => {
      if (value == null) return false
      const s = String(value).trim()
      if (!s) return false
      const lowered = s.toLowerCase()
      return lowered !== 'null' && lowered !== 'none' && lowered !== 'undefined'
    }

    const driverName = localStorage.getItem('driver_name')
    const vehicleNo = localStorage.getItem('vehicle_no')
    const licenseNo = localStorage.getItem('license_no')
    return Boolean(isValid(driverName) && isValid(vehicleNo) && isValid(licenseNo))
  } catch {
    return false
  }
}

function LoadingScreen() {
  return (
    <div className="page">
      <h1>Loading…</h1>
      <div className="caption">Checking backend session…</div>
    </div>
  )
}

function RequireDriverSetup({ bootStatus, ready, children }) {
  const location = useLocation()
  if (bootStatus === 'checking') return <LoadingScreen />
  if (!ready) return <Navigate to="/setup" replace state={{ from: location.pathname }} />
  return children
}

export default function App() {
  const location = useLocation()
  const [bootStatus, setBootStatus] = useState('checking')

  useEffect(() => {
    let cancelled = false

    const run = async () => {
      try {
        const res = await fetch(`${API_BASE}/`, { cache: 'no-store' })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json().catch(() => ({}))
        const bootId = String(data?.boot_id || '')
        if (!bootId) throw new Error('Missing boot_id')

        const prevBootId = localStorage.getItem(BOOT_ID_KEY)
        if (prevBootId && prevBootId !== bootId) {
          clearDriverSetup()
        }
        localStorage.setItem(BOOT_ID_KEY, bootId)

        if (!cancelled) setBootStatus('ok')
      } catch {
        // Backend is down/unreachable -> force setup and clear prior session.
        try {
          localStorage.removeItem(BOOT_ID_KEY)
        } catch {
          // ignore
        }
        clearDriverSetup()
        if (!cancelled) setBootStatus('down')
      }
    }

    run()
    return () => {
      cancelled = true
    }
  }, [])

  const setupDone = bootStatus === 'ok' && hasDriverDetails()
  const showShell = setupDone && location.pathname !== '/setup'

  return (
    <div className="app-root">
      {showShell ? <Sidebar /> : null}
      <div className="main-area">
        {showShell ? <Header /> : null}
        <main className="content">
          <Routes>
            <Route
              path="/"
              element={
                bootStatus === 'checking'
                  ? <LoadingScreen />
                  : <Navigate to={setupDone ? '/live' : '/setup'} replace />
              }
            />
            <Route path="/setup" element={<DriverSetup />} />

            <Route
              path="/live"
              element={
                <RequireDriverSetup bootStatus={bootStatus} ready={setupDone}>
                  <LiveMonitoring />
                </RequireDriverSetup>
              }
            />
            <Route
              path="/trips"
              element={
                <RequireDriverSetup bootStatus={bootStatus} ready={setupDone}>
                  <Trips />
                </RequireDriverSetup>
              }
            />
            <Route
              path="/trips/:id"
              element={
                <RequireDriverSetup bootStatus={bootStatus} ready={setupDone}>
                  <TripDetail />
                </RequireDriverSetup>
              }
            />
            <Route
              path="/events"
              element={
                <RequireDriverSetup bootStatus={bootStatus} ready={setupDone}>
                  <EventsPage />
                </RequireDriverSetup>
              }
            />
            <Route
              path="/events/emergency"
              element={
                <RequireDriverSetup bootStatus={bootStatus} ready={setupDone}>
                  <EmergencyEventsPage />
                </RequireDriverSetup>
              }
            />

            <Route path="*" element={<Navigate to={setupDone ? '/live' : '/setup'} replace />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
