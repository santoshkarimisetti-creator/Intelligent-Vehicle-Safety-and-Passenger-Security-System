"""ai_engine.emotion_engine - Three-Layer Emotion Recognition Architecture

Layer 1: Emotion Inference
  - Always runs every 5 seconds
  - Crops driver face and runs ONNX model
  - Returns raw emotion + confidence
  - Independent of trip state

Layer 2: Emotion State Manager  
  - Routes inference results to three outputs
  - Tracks state for DB/dashboard/alerts
  - Detects emotion changes and dangerous transitions
  
Layer 3: Three Output Channels
  - Dashboard: Live emotion display (memory-based, real-time)
  - Database: Trip-dependent storage (only on change, trip-active only)
  - Stress Alerts: Dangerous transition detection (trip-independent)
"""

from __future__ import annotations

import time
from collections import Counter, deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

import cv2
import numpy as np
import onnxruntime as ort


def default_emotion_result() -> Dict[str, Any]:
    return {
        "dominant_emotion": "unknown",
        "confidence": 0.0,
        "stress_level": "LOW",
        "emotion_risk_score": 0.0,
        "source": "emotion_placeholder",
        "model": None,
        "pending_model_integration": True,
    }


class EmotionEngine:
    def __init__(self, *, interval_s: float = 5.0, model_path: str = "models/emotion_model.onnx", debug: bool = False) -> None:
        self._interval_s = max(0.5, float(interval_s))
        self._last_by_session: Dict[str, float] = {}
        self._cache_by_session: Dict[str, Dict[str, Any]] = {}
        self._emotion_timeline_by_session: Dict[str, List[Dict[str, Any]]] = {}
        self.debug = debug

        # Layer 2: Emotion State Manager tracking
        self._current_emotion_state_by_session: Dict[str, Dict[str, Any]] = {}  # For dashboard
        self._last_db_emotion_by_session: Dict[str, str] = {}  # For DB change detection
        self._last_stress_emotion_by_session: Dict[str, str] = {}  # For stress alert tracking
        self._last_stress_alert_ts_by_session: Dict[str, float] = {}  # Cooldown tracking
        self._emotion_buffer_by_session: Dict[str, deque[str]] = {}  # Last-3 smoothing buffer

        # Stress detection configuration
        self.stress_emotions = {"anger", "fear", "sadness", "disgust"}
        self._stress_alert_cooldown_s = 10.0
        self.stress_alert_callback: Optional[callable] = None  # Override to handle alerts

        self._model_path = str(model_path)
        self._session: Optional[ort.InferenceSession] = None
        self._input_name: Optional[str] = None

        self.emotions = [
            "neutral",
            "happiness",
            "surprise",
            "sadness",
            "anger",
            "disgust",
            "fear",
            "contempt",
        ]

    def _resolve_model_path(self) -> str:
        p = Path(self._model_path)
        if p.is_absolute():
            return str(p)
        return str((Path(__file__).resolve().parent / p).resolve())

    def _ensure_model_session(self) -> None:
        if self._session is not None and self._input_name:
            return

        model_path = self._resolve_model_path()
        self._session = ort.InferenceSession(model_path)
        self._input_name = self._session.get_inputs()[0].name

        if self.debug:
            print("Input name:", self._session.get_inputs()[0].name)
            print("Input shape:", self._session.get_inputs()[0].shape)
            print("Output name:", self._session.get_outputs()[0].name)
            print("Output shape:", self._session.get_outputs()[0].shape)

            print("Model Inputs:")
            for inp in self._session.get_inputs():
                print(inp.name, inp.shape, inp.type)

            print("\nModel Outputs:")
            for out in self._session.get_outputs():
                print(out.name, out.shape, out.type)

    def predict(self, face_img: np.ndarray, debug_viz: bool = False) -> tuple[str, float]:
        if face_img is None or getattr(face_img, "size", 0) == 0:
            raise ValueError("face_img is empty")

        self._ensure_model_session()
        assert self._session is not None
        assert self._input_name is not None

        model_input_shape = self._session.get_inputs()[0].shape
        if self.debug or debug_viz:
            print("\n" + "="*60)
            print("🔍 EMOTION MODEL DEBUG")
            print("="*60)
            print(f"Model expects input shape: {model_input_shape}")
            print(f"Input name: {self._input_name}")

        target_h = 64
        target_w = 64
        if len(model_input_shape) >= 4:
            h_raw = model_input_shape[2]
            w_raw = model_input_shape[3]
            if isinstance(h_raw, int) and h_raw > 0:
                target_h = int(h_raw)
            if isinstance(w_raw, int) and w_raw > 0:
                target_w = int(w_raw)

        if self.debug or debug_viz:
            print(f"Target shape: H={target_h}, W={target_w}")
            print(f"Input face shape (before resize): {face_img.shape}")

        # Step 1: Resize to target dimensions
        face = cv2.resize(face_img, (target_w, target_h))
        
        if self.debug or debug_viz:
            print(f"\n📸 Face resized to ({target_w}x{target_h})")
            print(f"  Pixel range: [{face.min()}, {face.max()}]")
            print(f"  Mean pixel value: {face.mean():.1f}")

        # Step 2: Convert to grayscale (CRITICAL - must match model expectations)
        face = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
        
        if self.debug or debug_viz:
            print(f"\n✓ Converted to grayscale")
            print(f"  Shape after grayscale: {face.shape}")
            print(f"  Pixel range: [{face.min()}, {face.max()}]")

        # Step 3: Convert to float32 but DO NOT normalize (model expects raw 0-255)
        face = face.astype(np.float32)
        
        if self.debug or debug_viz:
            print(f"\n✓ Converted to float32 (no normalization)")
            print(f"  Shape: {face.shape}")
            print(f"  Min: {face.min():.1f}, Max: {face.max():.1f}, Mean: {face.mean():.1f}")
            print(f"  ⚠️ NOTE: Keeping raw pixel values 0-255 (NOT normalized)")

        # Step 4: Add channel dimension [H, W] → [1, H, W]
        face = np.expand_dims(face, axis=0)
        
        if self.debug or debug_viz:
            print(f"\n✓ Added channel dimension")
            print(f"  Shape: {face.shape}")

        # Step 5: Add batch dimension [1, H, W] → [1, 1, H, W]
        face = np.expand_dims(face, axis=0)
        
        if self.debug or debug_viz:
            print(f"\n✓ Added batch dimension")
            print(f"  Final shape: {face.shape}")
            print(f"  Expected shape: {model_input_shape}")
            print(f"  Match: {face.shape == tuple(model_input_shape)}")

        # Step 6: Run inference
        if self.debug or debug_viz:
            print(f"\n🚀 Running inference...")
        
        outputs = self._session.run(None, {self._input_name: face})

        # Step 7: Check raw output distribution
        logits = outputs[0][0]
        if self.debug or debug_viz:
            print(f"\n📊 Raw logits from model:")
            print(f"  {logits}")
            print(f"  Min: {logits.min():.4f}, Max: {logits.max():.4f}, Std: {np.std(logits):.4f}")

        # Convert logits to probabilities using stable softmax
        exp_scores = np.exp(logits - np.max(logits))
        probs = exp_scores / exp_scores.sum()
        
        if self.debug or debug_viz:
            print(f"\n📈 Softmax probabilities:")
            for idx, (emotion, prob) in enumerate(zip(self.emotions, probs)):
                print(f"  {emotion:12}: {prob:.4f}")

        emotion_index = int(np.argmax(probs))
        emotion_label = self.emotions[emotion_index]
        confidence = float(probs[emotion_index])
        
        if self.debug or debug_viz:
            print(f"\n✅ Result: {emotion_label} ({confidence:.1%})")
            print("="*60 + "\n")
        
        return emotion_label, confidence

    def _due(self, session_key: str, now: float) -> bool:
        last = float(self._last_by_session.get(session_key, 0.0) or 0.0)
        return (now - last) >= self._interval_s

    # ═════════════════════════════════════════════════════════
    # LAYER 1: Emotion Inference (Always Runs)
    # ═════════════════════════════════════════════════════════

    def _run_inference(
        self,
        *,
        image_bgr: np.ndarray,
        driver_bbox: Optional[Dict[str, Any]],
        timestamp: float,
    ) -> Dict[str, Any]:
        """Layer 1: Run emotion inference. Always executes regardless of trip state."""
        if not driver_bbox:
            return {
                "emotion": "unknown",
                "confidence": 0.0,
                "driver_face_present": False,
                "timestamp": timestamp,
            }

        try:
            face_crop = self._crop_driver_face(
                image_bgr=image_bgr,
                driver_bbox=driver_bbox,
            )
            if face_crop is None or face_crop.size == 0:
                return {
                    "emotion": "unknown",
                    "confidence": 0.0,
                    "driver_face_present": False,
                    "timestamp": timestamp,
                }
            if face_crop.shape[0] < 30 or face_crop.shape[1] < 30:
                return {
                    "emotion": "unknown",
                    "confidence": 0.0,
                    "driver_face_present": False,
                    "timestamp": timestamp,
                }

            emotion, confidence = self.predict(face_crop)
            return {
                "emotion": emotion,
                "confidence": confidence,
                "driver_face_present": True,
                "timestamp": timestamp,
            }
        except Exception as e:
            if self.debug:
                print(f"Error in emotion inference: {e}")
            return {
                "emotion": "unknown",
                "confidence": 0.0,
                "driver_face_present": bool(driver_bbox),
                "timestamp": timestamp,
            }

    def _crop_driver_face(
        self,
        *,
        image_bgr: np.ndarray,
        driver_bbox: Dict[str, Any],
    ) -> np.ndarray:
        """Crop driver face into a square centered on bounding box with boundary clamping."""
        x = int(driver_bbox.get("x", 0))
        y = int(driver_bbox.get("y", 0))
        w = int(driver_bbox.get("w", 0))
        h = int(driver_bbox.get("h", 0))

        # Create square crop centered on the face
        size = max(w, h)
        center_x = x + w // 2
        center_y = y + h // 2

        new_x = int(center_x - size // 2)
        new_y = int(center_y - size // 2)

        # Clamp boundaries to frame dimensions
        img_h, img_w = image_bgr.shape[:2]
        new_x = max(0, min(new_x, img_w - 1))
        new_y = max(0, min(new_y, img_h - 1))
        new_x2 = min(new_x + size, img_w)
        new_y2 = min(new_y + size, img_h)

        face_crop = image_bgr[new_y:new_y2, new_x:new_x2]
        return face_crop

    # ═════════════════════════════════════════════════════════
    # LAYER 2: Emotion State Manager (Routes to 3 Outputs)
    # ═════════════════════════════════════════════════════════

    def _smooth_emotion(self, session_key: str, new_emotion: str) -> str:
        buffer = self._emotion_buffer_by_session.setdefault(session_key, deque(maxlen=3))
        buffer.append(new_emotion)
        return Counter(buffer).most_common(1)[0][0]

    def _stress_level_for_emotion(self, emotion: str) -> str:
        if emotion in {"anger", "fear"}:
            return "HIGH"
        if emotion in {"sadness", "disgust"}:
            return "MEDIUM"
        return "LOW"

    def _should_store_emotion_to_db(
        self,
        session_key: str,
        new_emotion: str,
        is_trip_active: bool,
    ) -> bool:
        """Check if emotion should be stored to DB: changed AND trip active."""
        if not is_trip_active:
            return False
        last_emotion = self._last_db_emotion_by_session.get(session_key)
        return last_emotion != new_emotion

    def _should_trigger_stress_alert(
        self,
        session_key: str,
        new_emotion: str,
        timestamp: float,
    ) -> bool:
        """Check if dangerous emotion transition occurred (independent of trip state)."""
        prev_emotion = self._last_stress_emotion_by_session.get(session_key, "unknown")
        last_alert_ts = float(self._last_stress_alert_ts_by_session.get(session_key, 0.0) or 0.0)

        # Trigger alert if transitioning INTO a stress emotion from a non-stress emotion
        if (
            prev_emotion not in self.stress_emotions
            and new_emotion in self.stress_emotions
            and (timestamp - last_alert_ts) > self._stress_alert_cooldown_s
        ):
            return True

        return False

    def _manage_emotion_state(
        self,
        *,
        session_key: str,
        inference_result: Dict[str, Any],
        is_trip_active: bool,
    ) -> Dict[str, Any]:
        """Layer 2: Manage emotion state and route to three outputs."""
        raw_emotion = inference_result["emotion"]
        confidence = inference_result["confidence"]
        timestamp = inference_result["timestamp"]
        driver_face_present = inference_result["driver_face_present"]
        emotion = self._smooth_emotion(session_key, raw_emotion)
        stress_level = self._stress_level_for_emotion(emotion)

        # Layer 3a: Dashboard Output (always update)
        self._output_to_dashboard(
            session_key=session_key,
            emotion=emotion,
            confidence=confidence,
            stress_level=stress_level,
            timestamp=timestamp,
        )

        # Layer 3b: Database Output (only if trip active and emotion changed)
        if self._should_store_emotion_to_db(session_key, emotion, is_trip_active):
            self._output_to_database(
                session_key=session_key,
                emotion=emotion,
                confidence=confidence,
                timestamp=timestamp,
            )
            self._last_db_emotion_by_session[session_key] = emotion

        # Layer 3c: Stress Alert Output (independent of trip state)
        if self._should_trigger_stress_alert(session_key, emotion, timestamp):
            self._output_stress_alert(
                session_key=session_key,
                emotion=emotion,
                confidence=confidence,
                timestamp=timestamp,
            )
            self._last_stress_alert_ts_by_session[session_key] = timestamp
        self._last_stress_emotion_by_session[session_key] = emotion

        # Append to timeline
        if session_key not in self._emotion_timeline_by_session:
            self._emotion_timeline_by_session[session_key] = []
        self._emotion_timeline_by_session[session_key].append({
            "timestamp": timestamp,
            "emotion": emotion,
            "confidence": confidence,
        })

        return {
            "dominant_emotion": emotion,
            "raw_emotion": raw_emotion,
            "confidence": confidence,
            "stress_level": stress_level,
            "source": "emotion_model" if driver_face_present else "emotion_placeholder",
            "model": "emotion-ferplus-8" if driver_face_present else None,
            "pending_model_integration": False,
            "driver_face_present": driver_face_present,
            "timestamp": timestamp,
        }

    # ═════════════════════════════════════════════════════════
    # LAYER 3: Three Output Channels
    # ═════════════════════════════════════════════════════════

    def _output_to_dashboard(
        self,
        *,
        session_key: str,
        emotion: str,
        confidence: float,
        stress_level: str,
        timestamp: float,
    ) -> None:
        """Layer 3a: Update current emotion state for dashboard (memory-based)."""
        self._current_emotion_state_by_session[session_key] = {
            "current_emotion": emotion,
            "confidence": confidence,
            "stress_level": stress_level,
            "emotion_updated_at": timestamp,
        }

    def _output_to_database(
        self,
        *,
        session_key: str,
        emotion: str,
        confidence: float,
        timestamp: float,
    ) -> None:
        """Layer 3b: Store emotion to database (trip-dependent, change-based)."""
        # This method will be called only when:
        # 1. Trip is active
        # 2. Emotion changed from last stored value
        # Actual DB insertion logic would be implemented by the app layer.
        # For now, log the intent if in debug mode.
        if self.debug:
            print(f"[{session_key}] DB STORE: emotion={emotion}, conf={confidence:.2f}, ts={timestamp}")

    def _output_stress_alert(
        self,
        *,
        session_key: str,
        emotion: str,
        confidence: float,
        timestamp: float,
    ) -> None:
        """Layer 3c: Trigger stress alert for dangerous emotion transitions (trip-independent)."""
        # This runs independently of trip state
        if self.stress_alert_callback:
            self.stress_alert_callback(
                session_key=session_key,
                emotion=emotion,
                confidence=confidence,
                timestamp=timestamp,
            )
        else:
            # Default: log the alert
            if self.debug:
                print(f"[{session_key}] STRESS ALERT: {emotion} (conf={confidence:.2f})")

    def get_current_emotion_state(
        self,
        session_key: str,
    ) -> Dict[str, Any]:
        """Get current emotion state for dashboard display."""
        return self._current_emotion_state_by_session.get(
            session_key,
            {
                "current_emotion": "unknown",
                "confidence": 0.0,
                "stress_level": "LOW",
                "emotion_updated_at": 0.0,
            },
        )

    def _analyze_driver_placeholder(
        self,
        *,
        image_bgr: np.ndarray,
        driver_bbox: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Kept for backwards compatibility only."""
        result = default_emotion_result()
        result["driver_face_present"] = bool(driver_bbox)
        return result

    def _analyze_passengers_placeholder(
        self,
        *,
        passenger_bboxes: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for idx, pb in enumerate(passenger_bboxes or []):
            out.append(
                {
                    "passenger_index": idx,
                    "bbox": pb,
                    "dominant_emotion": "unknown",
                    "confidence": 0.0,
                    "source": "emotion_placeholder",
                }
            )
        return out

    def analyze_periodic(
        self,
        *,
        session_key: str,
        image_bgr: np.ndarray,
        driver_bbox: Optional[Dict[str, Any]],
        passenger_bboxes: Optional[List[Dict[str, Any]]] = None,
        force: bool = False,
        is_trip_active: bool = False,
    ) -> Dict[str, Any]:
        now = time.time()
        if (not force) and (not self._due(session_key, now)):
            cached = self._cache_by_session.get(session_key)
            if cached is not None:
                out = dict(cached)
                out["reused_cached"] = True
                return out

        # Layer 1: Run ONNX inference
        inference_result = self._run_inference(
            image_bgr=image_bgr,
            driver_bbox=driver_bbox,
            timestamp=now,
        )

        # Layer 2: Route to three outputs (dashboard, database, stress alerts)
        driver_emotion = self._manage_emotion_state(
            session_key=session_key,
            inference_result=inference_result,
            is_trip_active=is_trip_active,
        )

        # Analyze passengers (placeholder for now)
        passenger_emotions = self._analyze_passengers_placeholder(
            passenger_bboxes=passenger_bboxes,
        )

        # Get emotion timeline for this session
        emotion_timeline = self._emotion_timeline_by_session.get(session_key, [])

        result = {
            "emotion_result": driver_emotion,
            "driver_emotion": {
                "driver_emotion": str(driver_emotion.get("dominant_emotion") or "unknown"),
                "confidence": float(driver_emotion.get("confidence") or 0.0),
                "stress_level": str(driver_emotion.get("stress_level") or "LOW"),
                "source": driver_emotion.get("source", "emotion_placeholder"),
            },
            "passenger_emotions": passenger_emotions,
            "emotion_timeline": emotion_timeline,
            "analyzed_at": now,
            "reused_cached": False,
        }

        self._last_by_session[session_key] = now
        self._cache_by_session[session_key] = dict(result)
        return result


_emotion_engine_singleton: Optional[EmotionEngine] = None


def get_emotion_engine() -> EmotionEngine:
    global _emotion_engine_singleton
    if _emotion_engine_singleton is None:
        _emotion_engine_singleton = EmotionEngine(interval_s=5.0, debug=False)
    return _emotion_engine_singleton