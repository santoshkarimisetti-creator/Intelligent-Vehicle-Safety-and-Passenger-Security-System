"""ai_engine.landmark_engine

Vision-only face landmark extraction.

- Uses MediaPipe FaceLandmarker (FaceMesh-style 468 landmarks)
- Computes EAR (eye aspect ratio), MAR (mouth aspect ratio), and head pose (yaw/pitch/roll)
- Exposes a small API for callers to get clean frame-level metrics

This module intentionally contains *only* vision processing. Risk scoring, SOS logic,
and backend I/O belong elsewhere.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    mp = None  # type: ignore[assignment]
    python = None  # type: ignore[assignment]
    vision = None  # type: ignore[assignment]
    print("⚠ MediaPipe not installed. Install with: pip install mediapipe")


@dataclass
class FaceMetrics:
    """Container for extracted face metrics."""
    face_id: int
    face_bbox: Dict[str, float]  # {x, y, w, h, confidence}
    landmarks_3d: List[List[float]]  # 468 landmarks in 3D (x, y, z)
    landmarks_2d: List[List[float]]  # 468 landmarks in 2D (x, y)
    ear_left: float  # Eye Aspect Ratio (left eye)
    ear_right: float  # Eye Aspect Ratio (right eye)
    ear_avg: float  # Average EAR
    mar: float  # Mouth Aspect Ratio
    head_yaw: float  # Head rotation left/right (degrees)
    head_pitch: float  # Head rotation up/down (degrees)
    head_roll: float  # Head tilt (degrees)
    is_frontal: bool  # True if facing camera
    confidence: float  # Detection confidence [0, 1]
    landmark_count: int  # Number of landmarks produced for this face
    landmark_ratio: float  # landmark_count / expected_landmarks
    mouth_center: List[float]  # [x, y] in pixel coordinates
    mouth_area_ratio: float  # mouth bbox area / face bbox area
    mouth_landmark_ratio: float  # valid mouth landmarks / expected mouth landmarks
    eye_distance_px: float  # distance between eye-corner landmarks


class LandmarkEngine:
    """
    Vision processing module for face landmark extraction.
    Uses MediaPipe FaceMesh for robust, fast landmark detection.
    """

    def __init__(self):
        """Initialize MediaPipe FaceLandmarker."""
        self.facemesh = None
        self.initialized = False

        if not MEDIAPIPE_AVAILABLE:
            print("⚠ MediaPipe not available")
            return

        try:
            model_path = self._ensure_model_file()

            base_options = python.BaseOptions(model_asset_path=model_path)
            options = vision.FaceLandmarkerOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.IMAGE,
                num_faces=6,
                min_face_detection_confidence=0.45,
                min_face_presence_confidence=0.45,
                min_tracking_confidence=0.45,
            )
            self.facemesh = vision.FaceLandmarker.create_from_options(options)
            self.initialized = True
            self._expected_landmarks = int(os.getenv("FACE_LANDMARK_EXPECTED", "468"))
            self._min_landmark_ratio = float(os.getenv("FACE_LANDMARK_MIN_RATIO", "0.45"))
            print("✓ MediaPipe FaceLandmarker initialized")
        except Exception as e:
            print(f"⚠ Failed to initialize FaceLandmarker: {e}")
    
    def _ensure_model_file(self) -> str:
        """Return a usable `face_landmarker.task` path.

        Preference order:
        1) Workspace-local model (checked into repo): `ai_engine/face_landmarker.task`
        2) Cached temp-dir model
        3) Download into temp-dir (last resort)
        """
        # 1) Prefer the repo-local model (no network dependency)
        local_path = os.path.join(os.path.dirname(__file__), "face_landmarker.task")
        if os.path.exists(local_path):
            return local_path

        # 2) Temp cache
        model_path = os.path.join(tempfile.gettempdir(), "face_landmarker.task")
        if os.path.exists(model_path):
            return model_path

        # 3) Download as last resort
        import urllib.request

        model_url = (
            "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
            "face_landmarker/float16/1/face_landmarker.task"
        )
        print(f"Downloading face landmarker model to {model_path}...")
        urllib.request.urlretrieve(model_url, model_path)
        print("✓ Model downloaded")
        return model_path

    def process_frame(self, image: np.ndarray) -> Dict[str, Any]:
        """Return the primary-driver face metrics for a single frame.

        Output shape is intentionally stable for callers (API + frontend overlays):
        {
          face_detected: bool,
          landmarks_detected: bool,
          ear: float,
          mar: float,
          yaw_angle: float,
          pitch_angle: float,
          roll_angle: float,
          faces_detected: int,
          face_bbox: {x,y,w,h} | None,
          eye_boxes: [{x,y,w,h}, ...],
          all_face_boxes: [{x,y,w,h}, ...],
          image_width: int,
          image_height: int
        }
        """
        if image is None or getattr(image, "size", 0) == 0:
            return {
                "face_detected": False,
                "landmarks_detected": False,
                "ear": 0.0,
                "mar": 0.0,
                "yaw_angle": 0.0,
                "pitch_angle": 0.0,
                "roll_angle": 0.0,
                "faces_detected": 0,
                "face_bbox": None,
                "eye_boxes": [],
                "all_face_boxes": [],
                "driver_landmark_count": 0,
                "driver_landmark_ratio": 0.0,
                "face_presence_confidence": 0.0,
                "face_area_ratio": 0.0,
                "mouth_center": [0.0, 0.0],
                "mouth_area_ratio": 0.0,
                "mouth_landmark_ratio": 0.0,
                "eye_distance_norm": 0.0,
                "image_width": 0,
                "image_height": 0,
            }

        image_height, image_width = image.shape[:2]
        face_metrics_list = self.extract_landmarks(image)
        if not face_metrics_list:
            return {
                "face_detected": False,
                "landmarks_detected": False,
                "ear": 0.0,
                "mar": 0.0,
                "yaw_angle": 0.0,
                "pitch_angle": 0.0,
                "roll_angle": 0.0,
                "faces_detected": 0,
                "face_bbox": None,
                "eye_boxes": [],
                "all_face_boxes": [],
                "driver_landmark_count": 0,
                "driver_landmark_ratio": 0.0,
                "face_presence_confidence": 0.0,
                "face_area_ratio": 0.0,
                "mouth_center": [0.0, 0.0],
                "mouth_area_ratio": 0.0,
                "mouth_landmark_ratio": 0.0,
                "eye_distance_norm": 0.0,
                "image_width": int(image_width),
                "image_height": int(image_height),
            }

        # Multi-person monitoring (max 6 faces).
        # Keep existing outputs for the selected "driver" face so downstream logic remains stable.
        MAX_FACES = 6

        image_center_x = image_width / 2.0
        candidates: List[Dict[str, Any]] = []

        for metrics in face_metrics_list:
            bbox = metrics.face_bbox
            face_box = {
                "x": int(bbox.get("x", 0.0)),
                "y": int(bbox.get("y", 0.0)),
                "w": int(bbox.get("w", 0.0)),
                "h": int(bbox.get("h", 0.0)),
            }
            area = float(face_box["w"] * face_box["h"])
            center_x = face_box["x"] + (face_box["w"] / 2.0)
            center_distance_norm = abs(center_x - image_center_x) / max(1.0, float(image_center_x))

            eye_boxes = self._eye_boxes_from_landmarks(metrics.landmarks_2d)
            candidates.append(
                {
                    "center_distance_norm": float(center_distance_norm),
                    "area": float(area),
                    "ear": float(metrics.ear_avg),
                    "mar": float(metrics.mar),
                    "yaw_angle": float(metrics.head_yaw),
                    "pitch_angle": float(metrics.head_pitch),
                    "roll_angle": float(metrics.head_roll),
                    "eyes_detected": 2 if metrics.is_frontal else 1,
                    "face_bbox": face_box,
                    "eye_boxes": eye_boxes,
                    "is_frontal": bool(metrics.is_frontal),
                    "landmark_count": int(getattr(metrics, "landmark_count", 0)),
                    "landmark_ratio": float(getattr(metrics, "landmark_ratio", 1.0)),
                    "mouth_center": list(getattr(metrics, "mouth_center", [0.0, 0.0])),
                    "mouth_area_ratio": float(getattr(metrics, "mouth_area_ratio", 0.0)),
                    "mouth_landmark_ratio": float(getattr(metrics, "mouth_landmark_ratio", 0.0)),
                    "eye_distance_px": float(getattr(metrics, "eye_distance_px", 0.0)),
                }
            )

        if not candidates:
            return {
                "face_detected": False,
                "landmarks_detected": False,
                "ear": 0.0,
                "mar": 0.0,
                "yaw_angle": 0.0,
                "pitch_angle": 0.0,
                "roll_angle": 0.0,
                "faces_detected": 0,
                "face_bbox": None,
                "eye_boxes": [],
                "all_face_boxes": [],
                "driver_landmark_count": 0,
                "driver_landmark_ratio": 0.0,
                "face_presence_confidence": 0.0,
                "face_area_ratio": 0.0,
                "mouth_center": [0.0, 0.0],
                "mouth_area_ratio": 0.0,
                "mouth_landmark_ratio": 0.0,
                "eye_distance_norm": 0.0,
                "image_width": int(image_width),
                "image_height": int(image_height),
            }

        # Driver selection: prefer faces near horizontal center; among those, prefer largest box.
        # If none are central enough, fall back to closest-to-center then largest (tie-break).
        half_w = max(float(image_width) / 2.0, 1.0)
        center_band_px = 0.22 * half_w  # ~central 44% of frame width
        in_center_band = [
            c
            for c in candidates
            if abs((c["face_bbox"]["x"] + c["face_bbox"]["w"] / 2.0) - image_center_x)
            <= center_band_px
        ]
        if in_center_band:
            driver = max(in_center_band, key=lambda c: c["area"])
        else:
            driver = sorted(
                candidates,
                key=lambda c: (c["center_distance_norm"], -c["area"]),
            )[0]

        # Keep up to MAX_FACES total. Passengers are largest remaining boxes.
        remaining = [c for c in candidates if c is not driver]
        remaining_sorted = sorted(remaining, key=lambda c: c["area"], reverse=True)
        kept = [driver] + remaining_sorted[: max(0, MAX_FACES - 1)]

        faces_meta: List[Dict[str, Any]] = []
        all_face_boxes: List[Dict[str, int]] = []

        for c in kept:
            bbox = c["face_bbox"]
            role = "driver" if c is driver else "passenger"
            box_color = "green" if role == "driver" else "white"
            faces_meta.append(
                {
                    "bbox": [bbox["x"], bbox["y"], bbox["w"], bbox["h"]],
                    "role": role,
                    "box_color": box_color,
                }
            )
            all_face_boxes.append(
                {
                    "x": int(bbox["x"]),
                    "y": int(bbox["y"]),
                    "w": int(bbox["w"]),
                    "h": int(bbox["h"]),
                }
            )

        face_area_ratio = float(driver["face_bbox"]["w"] * driver["face_bbox"]["h"]) / max(1.0, float(image_width * image_height))
        eye_distance_norm = float(driver.get("eye_distance_px", 0.0)) / max(1.0, float(image_width))
        face_presence_conf = min(
            1.0,
            max(
                0.0,
                0.45 * float(driver.get("landmark_ratio", 1.0))
                + 0.25 * min(1.0, face_area_ratio / 0.08)
                + 0.20 * min(1.0, eye_distance_norm / 0.08)
                + 0.10 * (1.0 if bool(driver.get("is_frontal", False)) else 0.7),
            ),
        )

        return {
            "face_detected": True,
            "landmarks_detected": True,
            "ear": round(driver["ear"], 3),
            "mar": round(driver["mar"], 3),
            "yaw_angle": round(driver["yaw_angle"], 2),
            "pitch_angle": round(driver["pitch_angle"], 2),
            "roll_angle": round(driver["roll_angle"], 2),
            "eyes_detected": driver["eyes_detected"],
            "faces_detected": len(all_face_boxes),
            "face_bbox": driver["face_bbox"],
            "eye_boxes": driver["eye_boxes"],
            "all_face_boxes": all_face_boxes,
            "driver_landmark_count": int(driver.get("landmark_count", 0)),
            "driver_landmark_ratio": round(float(driver.get("landmark_ratio", 1.0)), 3),
            "face_presence_confidence": round(float(face_presence_conf), 3),
            "face_area_ratio": round(float(face_area_ratio), 4),
            "mouth_center": [
                round(float(driver.get("mouth_center", [0.0, 0.0])[0]), 2),
                round(float(driver.get("mouth_center", [0.0, 0.0])[1]), 2),
            ],
            "mouth_area_ratio": round(float(driver.get("mouth_area_ratio", 0.0)), 4),
            "mouth_landmark_ratio": round(float(driver.get("mouth_landmark_ratio", 0.0)), 3),
            "eye_distance_norm": round(float(eye_distance_norm), 4),
            # Per-face metadata for UI overlays and passenger logic.
            "faces_meta": faces_meta,
            "image_width": int(image_width),
            "image_height": int(image_height),
        }

    def extract_landmarks(self, image: np.ndarray) -> List[FaceMetrics]:
        """
        Extract landmarks from image.

        Args:
            image: BGR image from OpenCV

        Returns:
            List of FaceMetrics for each detected face
        """
        if not self.initialized or self.facemesh is None:
            return []

        if image is None or image.size == 0:
            return []

        try:
            # Convert BGR to RGB for MediaPipe
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            h, w = rgb_image.shape[:2]

            # Convert numpy array to MediaPipe Image
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)

            # Run face landmark detection
            results = self.facemesh.detect(mp_image)

            if not results.face_landmarks or len(results.face_landmarks) == 0:
                return []

            faces_metrics = []
            for face_id, face_landmarks in enumerate(results.face_landmarks):
                # Extract landmarks - face_landmarks is a list of NormalizedLandmark objects
                landmarks_3d = []
                landmarks_2d = []

                for landmark in face_landmarks:
                    landmarks_3d.append([landmark.x, landmark.y, landmark.z])
                    landmarks_2d.append([landmark.x * w, landmark.y * h])

                landmark_count = int(len(landmarks_2d))
                expected = max(1, int(getattr(self, "_expected_landmarks", 468)))
                landmark_ratio = float(landmark_count / float(expected))
                if landmark_ratio < float(getattr(self, "_min_landmark_ratio", 0.70)):
                    # Skip low-integrity landmark sets.
                    continue

                landmarks_3d = np.array(landmarks_3d)
                landmarks_2d = np.array(landmarks_2d)

                # Compute metrics
                ear_left = self._compute_ear(landmarks_2d, side="left")
                ear_right = self._compute_ear(landmarks_2d, side="right")
                ear_avg = (ear_left + ear_right) / 2.0

                mar = self._compute_mar(landmarks_2d)

                head_yaw, head_pitch, head_roll = self._compute_head_pose(
                    landmarks_2d=landmarks_2d,
                    img_w=w,
                    img_h=h,
                )

                # Compute bounding box
                face_bbox = self._get_face_bbox(landmarks_2d, w, h)
                face_box_int = {
                    "x": int(face_bbox.get("x", 0.0)),
                    "y": int(face_bbox.get("y", 0.0)),
                    "w": int(face_bbox.get("w", 0.0)),
                    "h": int(face_bbox.get("h", 0.0)),
                }
                mouth_stats = self._mouth_stats_from_landmarks(landmarks_2d.tolist(), face_box_int)
                eye_distance_px = self._eye_distance_from_landmarks(landmarks_2d.tolist())

                # Determine if frontal
                is_frontal = abs(head_yaw) < 30 and abs(head_pitch) < 30 and abs(head_roll) < 20

                metrics = FaceMetrics(
                    face_id=face_id,
                    face_bbox=face_bbox,
                    landmarks_3d=landmarks_3d.tolist(),
                    landmarks_2d=landmarks_2d.tolist(),
                    ear_left=round(ear_left, 3),
                    ear_right=round(ear_right, 3),
                    ear_avg=round(ear_avg, 3),
                    mar=round(mar, 3),
                    head_yaw=round(head_yaw, 2),
                    head_pitch=round(head_pitch, 2),
                    head_roll=round(head_roll, 2),
                    is_frontal=is_frontal,
                    confidence=1.0,  # MediaPipe doesn't return per-face confidence
                    landmark_count=landmark_count,
                    landmark_ratio=round(landmark_ratio, 3),
                    mouth_center=[
                        float(mouth_stats.get("center", [0.0, 0.0])[0]),
                        float(mouth_stats.get("center", [0.0, 0.0])[1]),
                    ],
                    mouth_area_ratio=round(float(mouth_stats.get("area_ratio", 0.0)), 4),
                    mouth_landmark_ratio=round(float(mouth_stats.get("landmark_ratio", 0.0)), 3),
                    eye_distance_px=round(float(eye_distance_px), 2),
                )

                faces_metrics.append(metrics)

            return faces_metrics

        except Exception as e:
            print(f"⚠ Error in landmark extraction: {e}")
            return []

    @staticmethod
    def _compute_ear(landmarks: np.ndarray, side: str = "left") -> float:
        """
        Compute Eye Aspect Ratio (EAR).

        EAR = (||p2 - p6|| + ||p3 - p5||) / (2 * ||p1 - p4||)

        Lower EAR = eyes closing/closed
        Higher EAR = eyes open
        """
        if side == "left":
            # Left eye landmarks: 33, 160, 158, 133, 153, 144
            eye_indices = [33, 160, 158, 133, 153, 144]
        else:
            # Right eye landmarks: 362, 385, 387, 263, 373, 380
            eye_indices = [362, 385, 387, 263, 373, 380]

        try:
            points = landmarks[eye_indices]

            # Vertical distances
            vertical_1 = np.linalg.norm(points[1] - points[5])
            vertical_2 = np.linalg.norm(points[2] - points[4])

            # Horizontal distance
            horizontal = np.linalg.norm(points[0] - points[3])

            # Compute EAR
            ear = (vertical_1 + vertical_2) / (2.0 * horizontal) if horizontal > 0 else 0.0
            return float(ear)
        except Exception as e:
            print(f"⚠ Error computing EAR ({side}): {e}")
            return 0.35  # Default: eyes open

    @staticmethod
    def _compute_mar(landmarks: np.ndarray) -> float:
        """
        Compute Mouth Aspect Ratio (MAR).

        MAR = (||p2 - p8|| + ||p3 - p7|| + ||p4 - p6||) / (3 * ||p1 - p5||)

        Lower MAR = mouth closed
        Higher MAR = mouth open/yawning
        """
        try:
            # Use a stable, scale-invariant ratio:
            # MAR = lip_opening / mouth_width
            # lip_opening: inner upper (13) to inner lower (14)
            # mouth_width: left corner (61) to right corner (291)
            upper_inner = landmarks[13]
            lower_inner = landmarks[14]
            left_corner = landmarks[61]
            right_corner = landmarks[291]

            lip_opening = np.linalg.norm(upper_inner - lower_inner)
            mouth_width = np.linalg.norm(left_corner - right_corner)
            if mouth_width <= 1e-6:
                return 0.0
            return float(lip_opening / mouth_width)
        except Exception as e:
            print(f"⚠ Error computing MAR: {e}")
            return 0.0

    @staticmethod
    def _compute_head_pose(
        landmarks_2d: np.ndarray,
        img_w: int,
        img_h: int,
    ) -> Tuple[float, float, float]:
        """
        Compute head pose (yaw, pitch, roll) from 3D landmarks.

        Uses 6-point PnP solver with 3D face model points.
        Returns angles in degrees.
        """
        try:
            # 3D model points (generic face model, millimeters)
            # Commonly used in head-pose examples; absolute scale doesn't matter for angles.
            model_points = np.array(
                [
                    (0.0, 0.0, 0.0),  # Nose tip
                    (0.0, -330.0, -65.0),  # Chin
                    (-225.0, 170.0, -135.0),  # Left eye outer corner
                    (225.0, 170.0, -135.0),  # Right eye outer corner
                    (-150.0, -150.0, -125.0),  # Left mouth corner
                    (150.0, -150.0, -125.0),  # Right mouth corner
                ],
                dtype=np.float64,
            )

            # 2D image points from MediaPipe FaceMesh indices
            # nose: 1, chin: 152, left eye: 33, right eye: 263, mouth corners: 61, 291
            image_points = np.array(
                [
                    landmarks_2d[1],
                    landmarks_2d[152],
                    landmarks_2d[33],
                    landmarks_2d[263],
                    landmarks_2d[61],
                    landmarks_2d[291],
                ],
                dtype=np.float64,
            )

            focal_length = float(img_w)
            center = (float(img_w) / 2.0, float(img_h) / 2.0)
            camera_matrix = np.array(
                [[focal_length, 0.0, center[0]], [0.0, focal_length, center[1]], [0.0, 0.0, 1.0]],
                dtype=np.float64,
            )
            dist_coeffs = np.zeros((4, 1), dtype=np.float64)

            success, rvec, tvec = cv2.solvePnP(
                model_points,
                image_points,
                camera_matrix,
                dist_coeffs,
                flags=cv2.SOLVEPNP_ITERATIVE,
            )
            if not success:
                return 0.0, 0.0, 0.0

            rotation_matrix, _ = cv2.Rodrigues(rvec)
            yaw, pitch, roll = LandmarkEngine._rotation_matrix_to_euler(rotation_matrix)
            return float(yaw), float(pitch), float(roll)

        except Exception as e:
            print(f"⚠ Error computing head pose: {e}")
            return 0.0, 0.0, 0.0

    @staticmethod
    def _rotation_matrix_to_euler(rotation_matrix: np.ndarray) -> Tuple[float, float, float]:
        """Convert rotation matrix to yaw/pitch/roll in degrees.

        Convention used:
        - yaw:   rotation around Y axis (left/right)
        - pitch: rotation around X axis (up/down)
        - roll:  rotation around Z axis (tilt)
        """
        r = rotation_matrix
        sy = float(np.sqrt((r[0, 0] * r[0, 0]) + (r[1, 0] * r[1, 0])))
        singular = sy < 1e-6

        if not singular:
            pitch = float(np.arctan2(r[2, 1], r[2, 2]))
            yaw = float(np.arctan2(-r[2, 0], sy))
            roll = float(np.arctan2(r[1, 0], r[0, 0]))
        else:
            pitch = float(np.arctan2(-r[1, 2], r[1, 1]))
            yaw = float(np.arctan2(-r[2, 0], sy))
            roll = 0.0

        return (np.degrees(yaw), np.degrees(pitch), np.degrees(roll))

    @staticmethod
    def _eye_boxes_from_landmarks(landmarks_2d: List[List[float]] | List[Tuple[float, float]]) -> List[Dict[str, int]]:
        if not landmarks_2d:
            return []

        def _bbox_for_indices(indices: List[int]) -> Optional[Dict[str, int]]:
            pts = [landmarks_2d[i] for i in indices if i < len(landmarks_2d)]
            if not pts:
                return None
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
            x_min, y_min = min(xs), min(ys)
            w, h = (max(xs) - x_min), (max(ys) - y_min)
            if w <= 0 or h <= 0:
                return None
            return {"x": int(x_min), "y": int(y_min), "w": int(w), "h": int(h)}

        left = _bbox_for_indices([33, 160, 158, 133, 153, 144])
        right = _bbox_for_indices([362, 385, 387, 263, 373, 380])
        boxes: List[Dict[str, int]] = []
        if left:
            boxes.append(left)
        if right:
            boxes.append(right)
        return boxes

    @staticmethod
    def _eye_distance_from_landmarks(landmarks_2d: List[List[float]] | List[Tuple[float, float]]) -> float:
        try:
            if len(landmarks_2d) <= 263:
                return 0.0
            left = landmarks_2d[33]
            right = landmarks_2d[263]
            dx = float(left[0]) - float(right[0])
            dy = float(left[1]) - float(right[1])
            return float((dx * dx + dy * dy) ** 0.5)
        except Exception:
            return 0.0

    @staticmethod
    def _mouth_stats_from_landmarks(
        landmarks_2d: List[List[float]] | List[Tuple[float, float]],
        face_bbox: Dict[str, int],
    ) -> Dict[str, Any]:
        mouth_idx = [61, 291, 78, 308, 13, 14, 0, 17, 82, 312, 87, 317, 95, 324, 88, 318]
        pts: List[Tuple[float, float]] = []
        valid = 0

        for idx in mouth_idx:
            if idx >= len(landmarks_2d):
                continue
            p = landmarks_2d[idx]
            try:
                x = float(p[0])
                y = float(p[1])
            except Exception:
                continue
            pts.append((x, y))
            if np.isfinite(x) and np.isfinite(y):
                valid += 1

        if not pts:
            return {"center": [0.0, 0.0], "area_ratio": 0.0, "landmark_ratio": 0.0}

        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)

        width = max(0.0, float(x_max - x_min))
        height = max(0.0, float(y_max - y_min))
        cx = float((x_min + x_max) / 2.0)
        cy = float((y_min + y_max) / 2.0)

        face_w = max(1.0, float(face_bbox.get("w", 1)))
        face_h = max(1.0, float(face_bbox.get("h", 1)))
        area_ratio = float((width * height) / max(1.0, face_w * face_h))
        landmark_ratio = float(valid / max(1, len(mouth_idx)))
        return {
            "center": [cx, cy],
            "area_ratio": area_ratio,
            "landmark_ratio": landmark_ratio,
        }

    @staticmethod
    def _get_face_bbox(
        landmarks_2d: np.ndarray, img_w: int, img_h: int
    ) -> Dict[str, float]:
        """
        Compute bounding box from landmarks.
        """
        try:
            x_coords = landmarks_2d[:, 0]
            y_coords = landmarks_2d[:, 1]

            x_min = float(np.clip(np.min(x_coords), 0, img_w))
            x_max = float(np.clip(np.max(x_coords), 0, img_w))
            y_min = float(np.clip(np.min(y_coords), 0, img_h))
            y_max = float(np.clip(np.max(y_coords), 0, img_h))

            w = x_max - x_min
            h = y_max - y_min

            return {
                "x": x_min,
                "y": y_min,
                "w": w,
                "h": h,
                "confidence": 1.0,
            }
        except Exception as e:
            print(f"⚠ Error computing bounding box: {e}")
            return {"x": 0, "y": 0, "w": 0, "h": 0, "confidence": 0.0}


# Singleton instance
_landmark_engine: Optional[LandmarkEngine] = None


def get_landmark_engine() -> LandmarkEngine:
    """Get or create landmark engine singleton."""
    global _landmark_engine
    if _landmark_engine is None:
        _landmark_engine = LandmarkEngine()
    return _landmark_engine


def extract_landmarks(image: np.ndarray) -> List[FaceMetrics]:
    """Extract landmarks from image using singleton engine."""
    engine = get_landmark_engine()
    return engine.extract_landmarks(image)
