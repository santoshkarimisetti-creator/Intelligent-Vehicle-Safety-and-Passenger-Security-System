import React, { useState, useRef, useEffect } from 'react'

/**
 * SoundAlerts Component
 * Manages audio alerts for different risk levels
 * - SAFE (0-20): No sound
 * - MODERATE (21-50): Warning beep (500ms)
 * - HIGH (51-75): Urgent alert (pulsing)
 * - CRITICAL (76-100): Continuous alarm
 */

export default function SoundAlerts({ riskLevel = 'SAFE', isActive = true }) {
  const [muted, setMuted] = useState(false)
  const audioContextRef = useRef(null)
  const oscillatorRef = useRef(null)
  const gainNodeRef = useRef(null)
  const currentAlertRef = useRef(null)

  // Initialize Web Audio API
  useEffect(() => {
    if (!audioContextRef.current) {
      audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)()
    }
  }, [])

  // Stop any active sound
  const stopSound = () => {
    if (currentAlertRef.current) {
      clearTimeout(currentAlertRef.current)
      currentAlertRef.current = null
    }

    if (oscillatorRef.current) {
      try {
        oscillatorRef.current.stop()
        oscillatorRef.current.disconnect()
      } catch (e) {
        // Already stopped
      }
      oscillatorRef.current = null
    }

    if (gainNodeRef.current) {
      try {
        gainNodeRef.current.disconnect()
      } catch (e) {
        // Already disconnected
      }
      gainNodeRef.current = null
    }
  }

  // Play warning beep (MODERATE)
  const playWarningBeep = () => {
    if (muted || !isActive || !audioContextRef.current) return

    stopSound()

    const ctx = audioContextRef.current
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()

    osc.connect(gain)
    gain.connect(ctx.destination)

    osc.frequency.value = 800
    osc.type = 'sine'

    gain.gain.setValueAtTime(0.3, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.5)

    osc.start(ctx.currentTime)
    osc.stop(ctx.currentTime + 0.5)

    oscillatorRef.current = osc
    gainNodeRef.current = gain
  }

  // Play urgent pulsing alert (HIGH)
  const playUrgentAlert = () => {
    if (muted || !isActive || !audioContextRef.current) return

    stopSound()

    const ctx = audioContextRef.current
    let pulseCount = 0
    const maxPulses = 5

    const playPulse = () => {
      if (pulseCount >= maxPulses) {
        pulseCount = 0
        currentAlertRef.current = setTimeout(playPulse, 1000) // Repeat after 1 second
        return
      }

      const osc = ctx.createOscillator()
      const gain = ctx.createGain()

      osc.connect(gain)
      gain.connect(ctx.destination)

      osc.frequency.value = 1000
      osc.type = 'square'

      gain.gain.setValueAtTime(0.2, ctx.currentTime)
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.15)

      osc.start(ctx.currentTime)
      osc.stop(ctx.currentTime + 0.15)

      pulseCount++
      currentAlertRef.current = setTimeout(playPulse, 200)
    }

    playPulse()
  }

  // Play continuous alarm (CRITICAL)
  const playCriticalAlarm = () => {
    if (muted || !isActive || !audioContextRef.current) return

    stopSound()

    const ctx = audioContextRef.current

    const playAlarmCycle = () => {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()

      osc.connect(gain)
      gain.connect(ctx.destination)

      osc.frequency.setValueAtTime(1200, ctx.currentTime)
      osc.frequency.exponentialRampToValueAtTime(800, ctx.currentTime + 0.3)
      osc.type = 'square'

      gain.gain.setValueAtTime(0.25, ctx.currentTime)
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3)

      osc.start(ctx.currentTime)
      osc.stop(ctx.currentTime + 0.3)

      currentAlertRef.current = setTimeout(playAlarmCycle, 400)
    }

    playAlarmCycle()
  }

  // Trigger sound based on risk level
  useEffect(() => {
    if (!isActive) {
      stopSound()
      return
    }

    switch (riskLevel) {
      case 'MODERATE':
        playWarningBeep()
        break
      case 'HIGH':
        playUrgentAlert()
        break
      case 'CRITICAL':
        playCriticalAlarm()
        break
      default:
        stopSound()
    }

    return () => {
      // Cleanup on unmount
      stopSound()
    }
  }, [riskLevel, muted, isActive])

  const getAlertText = () => {
    switch (riskLevel) {
      case 'SAFE':
        return 'All Clear'
      case 'MODERATE':
        return 'Warning ⚠️'
      case 'HIGH':
        return 'Alert 🔴'
      case 'CRITICAL':
        return 'Critical 🚨'
      default:
        return 'Unknown'
    }
  }

  const getAlertColor = () => {
    switch (riskLevel) {
      case 'SAFE':
        return '#4caf50'
      case 'MODERATE':
        return '#ff9800'
      case 'HIGH':
        return '#f44336'
      case 'CRITICAL':
        return '#8b0000'
      default:
        return '#999'
    }
  }

  return (
    <div className="sound-alerts" style={{ borderLeft: `4px solid ${getAlertColor()}` }}>
      <div className="alert-status">
        <span className="status-light" style={{ backgroundColor: getAlertColor() }}></span>
        <span className="status-text">{getAlertText()}</span>
      </div>
      <button
        onClick={() => setMuted(!muted)}
        className={`mute-btn ${muted ? 'muted' : ''}`}
        title={muted ? 'Unmute alerts' : 'Mute alerts'}
      >
        {muted ? '🔇' : '🔊'}
      </button>
    </div>
  )
}
