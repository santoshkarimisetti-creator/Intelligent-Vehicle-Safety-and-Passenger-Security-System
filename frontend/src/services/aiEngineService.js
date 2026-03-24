// Default AI engine port is defined in ai_engine/app.py (AI_ENGINE_PORT, default 5001).
const AI_ENGINE_BASE = import.meta.env.VITE_AI_ENGINE_BASE || 'http://localhost:5001'

/**
 * Capture frame from video element and convert to base64
 */
export function captureFrame(videoElement, options = {}) {
  if (!videoElement || videoElement.videoWidth === 0) {
    return null
  }

  const {
    maxWidth = 480,
    maxHeight = 360,
    quality = 0.65,
  } = options

  const srcW = videoElement.videoWidth
  const srcH = videoElement.videoHeight

  // Downscale frames before sending to the AI engine to reduce latency and bandwidth.
  const scale = Math.min(1, maxWidth / srcW, maxHeight / srcH)
  const dstW = Math.max(1, Math.round(srcW * scale))
  const dstH = Math.max(1, Math.round(srcH * scale))

  const canvas = document.createElement('canvas')
  canvas.width = dstW
  canvas.height = dstH
  
  const ctx = canvas.getContext('2d')
  ctx.drawImage(videoElement, 0, 0, dstW, dstH)
  
  // Get base64 image data (remove "data:image/jpeg;base64," prefix)
  const q = Math.max(0.2, Math.min(0.95, Number(quality) || 0.65))
  const dataURL = canvas.toDataURL('image/jpeg', q)
  const base64Data = dataURL.split(',')[1]
  
  return base64Data
}

/**
 * Send frame to AI engine for analysis
 */
export async function analyzeFrame(frameData, tripId, speed = 0) {
  try {
    const response = await fetch(`${AI_ENGINE_BASE}/analyze_frame`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        trip_id: tripId,
        image: frameData,
        frame_id: Date.now(),
        input_type: 'webcam',
        speed: speed,
      })
    })

    if (!response.ok) {
      throw new Error(`AI engine returned ${response.status}`)
    }

    const result = await response.json()
    return result
  } catch (error) {
    console.error('AI engine analysis failed:', error)
    throw error
  }
}

/**
 * Check AI engine health
 */
export async function checkAIEngineHealth() {
  try {
    const response = await fetch(`${AI_ENGINE_BASE}/health`)
    return response.ok
  } catch {
    return false
  }
}

export default { captureFrame, analyzeFrame, checkAIEngineHealth }
