import React, {useEffect, useState} from 'react'

export default function Header(){
  const [now, setNow] = useState(new Date())

  useEffect(()=>{
    const t = setInterval(()=> setNow(new Date()), 1000)
    return ()=> clearInterval(t)
  },[])

  return (
    <header className="app-header">
      <div className="header-right">
        <div className="status-badge">Monitoring: <span className="badge green">ACTIVE</span></div>
        <div className="now">{now.toLocaleString()}</div>
      </div>
    </header>
  )
}
