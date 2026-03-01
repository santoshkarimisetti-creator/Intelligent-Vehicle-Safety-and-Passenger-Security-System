import React from 'react'
import { NavLink } from 'react-router-dom'

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <nav>
        <ul>
          <li>
            <NavLink to="/live" className={({isActive}) => isActive? 'active navlink':'navlink'}>📷 Live Monitoring</NavLink>
          </li>
          <li>
            <NavLink to="/trips" className={({isActive}) => isActive? 'active navlink':'navlink'}>🗺️ Trips</NavLink>
          </li>
          <li>
            <NavLink to="/events" className={({isActive}) => isActive? 'active navlink':'navlink'}>� Detection Events</NavLink>
          </li>
          <li>
            <NavLink to="/events/emergency" className={({isActive}) => isActive? 'active navlink':'navlink'}>🚨 SOS Alerts</NavLink>
          </li>
        </ul>
      </nav>
    </aside>
  )
}

