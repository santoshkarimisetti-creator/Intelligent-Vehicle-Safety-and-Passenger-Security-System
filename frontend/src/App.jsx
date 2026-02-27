import React from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import LiveMonitoring from './pages/LiveMonitoring'
import Trips from './pages/Trips'
import TripDetail from './pages/TripDetail'

export default function App() {
  return (
    <div className="app-root">
      <Sidebar />
      <div className="main-area">
        <Header />
        <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/live" replace />} />
          <Route path="/live" element={<LiveMonitoring />} />
          <Route path="/trips" element={<Trips />} />
          <Route path="/trips/:id" element={<TripDetail />} />
          <Route path="/events" element={<Trips />} />
        </Routes>
        </main>
      </div>
    </div>
  )
}
