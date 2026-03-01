const AI_ENGINE_BASE = import.meta.env.VITE_AI_ENGINE_BASE || 'http://localhost:3001'

/**
 * Capture frame from video element and convert to base64
 */
export function captureFrame(videoElement) {
  if (!videoElement || videoElement.videoWidth === 0) {
    return null
  }

  const canvas = document.createElement('canvas')
  canvas.width = videoElement.videoWidth
  canvas.height = videoElement.videoHeight
  
  const ctx = canvas.getContext('2d')
  ctx.drawImage(videoElement, 0, 0, canvas.width, canvas.height)
  
  // Get base64 image data (remove "data:image/jpeg;base64," prefix)
  const dataURL = canvas.toDataURL('image/jpeg', 0.8)
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
