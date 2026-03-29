"""ai_engine.face_recognition_service

Identity (face recognition) layer.

Responsibilities:
- Load face detector + face embedding model
- Generate an embedding per detected face
- Compare embeddings against stored driver embeddings
- Return best `driver_id` + `confidence`

This module intentionally does not do risk scoring, SOS logic, or backend I/O.
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from dataclasses import dataclass
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    from pymongo import MongoClient
except Exception:  # pragma: no cover
    MongoClient = None  # type: ignore


@dataclass(frozen=True)
class IdentityResult:
    driver_id: Optional[str]
    confidence: float
    matched: bool


def _clamp01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def _bbox_iou_xywh(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    try:
        ax1 = float(a.get("x", 0.0))
        ay1 = float(a.get("y", 0.0))
        ax2 = ax1 + float(a.get("w", 0.0))
        ay2 = ay1 + float(a.get("h", 0.0))

        bx1 = float(b.get("x", 0.0))
        by1 = float(b.get("y", 0.0))
        bx2 = bx1 + float(b.get("w", 0.0))
        by2 = by1 + float(b.get("h", 0.0))

        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)

        iw = max(0.0, ix2 - ix1)
        ih = max(0.0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0.0:
            return 0.0

        area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        union = area_a + area_b - inter
        if union <= 0.0:
            return 0.0
        return float(inter / union)
    except Exception:
        return 0.0


class FaceRecognitionService:
    """Face recognition using OpenCV's YuNet + SFace.

    Notes:
    - Models are loaded lazily and cached.
    - Driver embeddings are read from MongoDB (preferred) with JSON file fallback.

    Driver embeddings JSON formats accepted:
    1) {"driverA": [..embedding floats..], "driverB": [..]}
    2) {"driverA": {"embedding": [..], ...}, ...}
    """

    # OpenCV Zoo model URLs
    _YUNET_URL = (
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
        "face_detection_yunet_2023mar.onnx"
    )
    _SFACE_URL = (
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/"
        "face_recognition_sface_2021dec.onnx"
    )

    def __init__(self):
        self.available = False
        self._detector: Optional[Any] = None
        self._recognizer: Optional[Any] = None

        self._mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        self._mongo_db = os.getenv("MONGO_DB", "ivs_db")
        self._mongo_drivers_collection = os.getenv("MONGO_DRIVERS_COLLECTION", "drivers")
        self._mongo_connect_timeout_ms = int(os.getenv("MONGO_CONNECT_TIMEOUT_MS", "1500"))
        self._embeddings_cache_ttl_s = float(os.getenv("DRIVER_EMBEDDINGS_CACHE_TTL", "30"))
        self._embeddings_cache: Optional[Dict[str, np.ndarray]] = None
        self._embeddings_cache_at: float = 0.0

        self._models_dir = os.getenv(
            "AI_ENGINE_MODELS_DIR",
            os.path.join(os.path.dirname(__file__), "models"),
        )
        self._driver_embeddings_path = os.getenv(
            "DRIVER_EMBEDDINGS_PATH",
            os.path.join(os.path.dirname(__file__), "driver_embeddings.json"),
        )

        # Check if OpenCV provides these APIs (opencv-contrib style)
        self.available = hasattr(cv2, "FaceDetectorYN") and hasattr(cv2, "FaceRecognizerSF")

    def _ensure_models(self) -> Tuple[str, str]:
        os.makedirs(self._models_dir, exist_ok=True)

        yunet_path = os.path.join(self._models_dir, "face_detection_yunet_2023mar.onnx")
        sface_path = os.path.join(self._models_dir, "face_recognition_sface_2021dec.onnx")

        if not os.path.exists(yunet_path):
            self._download(self._YUNET_URL, yunet_path)
        if not os.path.exists(sface_path):
            self._download(self._SFACE_URL, sface_path)

        return yunet_path, sface_path

    @staticmethod
    def _download(url: str, dst: str) -> None:
        tmp_dir = tempfile.gettempdir()
        tmp_path = os.path.join(tmp_dir, os.path.basename(dst) + ".tmp")
        urllib.request.urlretrieve(url, tmp_path)
        os.replace(tmp_path, dst)

    def _ensure_initialized(self, input_w: int, input_h: int) -> bool:
        if not self.available:
            return False

        if self._detector is not None and self._recognizer is not None:
            # Update input size if supported
            try:
                if hasattr(self._detector, "setInputSize"):
                    self._detector.setInputSize((int(input_w), int(input_h)))
            except Exception:
                pass
            return True

        try:
            yunet_path, sface_path = self._ensure_models()

            # Create detector
            self._detector = cv2.FaceDetectorYN.create(
                yunet_path,
                "",
                (int(input_w), int(input_h)),
                0.9,
                0.3,
                5000,
            )

            # Create recognizer
            self._recognizer = cv2.FaceRecognizerSF.create(sface_path, "")

            return True
        except Exception as e:
            print(f"⚠ FaceRecognitionService init failed: {e}")
            self._detector = None
            self._recognizer = None
            return False

    def _load_driver_embeddings(self) -> Dict[str, np.ndarray]:
        # Small TTL cache to avoid DB/file reads on every frame.
        now = float(time.time())
        if (
            self._embeddings_cache is not None
            and self._embeddings_cache_ttl_s > 0
            and (now - self._embeddings_cache_at) < self._embeddings_cache_ttl_s
        ):
            return self._embeddings_cache

        embeddings = self._load_driver_embeddings_from_mongo()
        if not embeddings:
            embeddings = self._load_driver_embeddings_from_json()

        self._embeddings_cache = embeddings
        self._embeddings_cache_at = now
        return embeddings

    def _load_driver_embeddings_from_mongo(self) -> Dict[str, np.ndarray]:
        if MongoClient is None:
            return {}

        try:
            client = MongoClient(
                self._mongo_uri,
                serverSelectionTimeoutMS=self._mongo_connect_timeout_ms,
                connectTimeoutMS=self._mongo_connect_timeout_ms,
                socketTimeoutMS=self._mongo_connect_timeout_ms,
            )
            client.admin.command("ping")

            db = client[self._mongo_db]
            coll = db[self._mongo_drivers_collection]

            docs = coll.find({"embedding": {"$exists": True}, "driver_id": {"$exists": True}})
            result: Dict[str, np.ndarray] = {}
            for doc in docs:
                driver_id = str(doc.get("driver_id") or "").strip()
                emb_list = doc.get("embedding")
                if not driver_id or not isinstance(emb_list, list) or len(emb_list) == 0:
                    continue

                arr = np.asarray(emb_list, dtype=np.float32).reshape(1, -1)
                result[driver_id] = arr
            return result
        except Exception:
            return {}

    def _load_driver_embeddings_from_json(self) -> Dict[str, np.ndarray]:
        if not os.path.exists(self._driver_embeddings_path):
            return {}

        try:
            with open(self._driver_embeddings_path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            return {}

        embeddings: Dict[str, np.ndarray] = {}

        if isinstance(data, dict):
            for driver_id, value in data.items():
                emb_list = None
                if isinstance(value, dict) and "embedding" in value:
                    emb_list = value.get("embedding")
                elif isinstance(value, list):
                    emb_list = value

                if not emb_list:
                    continue

                try:
                    arr = np.asarray(emb_list, dtype=np.float32)
                    if arr.ndim == 1:
                        arr = arr.reshape(1, -1)
                    embeddings[str(driver_id)] = arr
                except Exception:
                    continue

        return embeddings

    def extract_face_embeddings(self, image_bgr: np.ndarray) -> List[Tuple[Dict[str, int], np.ndarray]]:
        """Detect faces and return [(bbox_xywh, embedding), ...]."""
        if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
            return []

        h, w = image_bgr.shape[:2]
        if not self._ensure_initialized(w, h):
            return []

        assert self._detector is not None
        assert self._recognizer is not None

        # YuNet expects BGR image
        try:
            _, faces = self._detector.detect(image_bgr)
        except Exception:
            return []

        if faces is None or len(faces) == 0:
            return []

        results: List[Tuple[Dict[str, int], np.ndarray]] = []

        for row in faces:
            # row shape: [15]
            x, y, bw, bh = [float(row[i]) for i in range(4)]
            bbox = {"x": int(x), "y": int(y), "w": int(bw), "h": int(bh)}

            try:
                aligned = self._recognizer.alignCrop(image_bgr, row)
                feat = self._recognizer.feature(aligned)
                feat = np.asarray(feat, dtype=np.float32)
                if feat.ndim == 1:
                    feat = feat.reshape(1, -1)
                results.append((bbox, feat))
            except Exception:
                continue

        return results

    def identify_driver(
        self,
        image_bgr: np.ndarray,
        target_face_bbox: Optional[Dict[str, Any]] = None,
        min_confidence: float = 0.55,
    ) -> IdentityResult:
        """Identify the driver for an image.

        If `target_face_bbox` is provided, picks the detected face with highest IoU.
        Otherwise picks the highest-confidence match over all faces.
        """
        driver_embeddings = self._load_driver_embeddings()
        if not driver_embeddings:
            return IdentityResult(driver_id=None, confidence=0.0, matched=False)

        faces = self.extract_face_embeddings(image_bgr)
        if not faces:
            return IdentityResult(driver_id=None, confidence=0.0, matched=False)

        # Optionally select a single face first (closest to the vision primary face)
        if target_face_bbox:
            best_iou = -1.0
            best_face: Optional[Tuple[Dict[str, int], np.ndarray]] = None
            for bbox, emb in faces:
                iou = _bbox_iou_xywh(target_face_bbox, bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_face = (bbox, emb)
            if best_face is not None:
                faces = [best_face]

        best_driver: Optional[str] = None
        best_score: float = -1.0

        for _, query_emb in faces:
            for driver_id, known_emb in driver_embeddings.items():
                score = self._cosine_similarity(query_emb, known_emb)
                if score > best_score:
                    best_score = score
                    best_driver = driver_id

        confidence = _clamp01((best_score + 1.0) / 2.0) if best_score <= 1.0 else _clamp01(best_score)
        matched = bool(best_driver) and confidence >= float(min_confidence)

        return IdentityResult(driver_id=best_driver if matched else None, confidence=confidence, matched=matched)

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity for 1xD vectors."""
        try:
            a = np.asarray(a, dtype=np.float32).reshape(-1)
            b = np.asarray(b, dtype=np.float32).reshape(-1)
            denom = (np.linalg.norm(a) * np.linalg.norm(b))
            if denom <= 1e-8:
                return 0.0
            return float(np.dot(a, b) / denom)
        except Exception:
            return 0.0


_face_recognition_service: Optional[FaceRecognitionService] = None


def get_face_recognition_service() -> FaceRecognitionService:
    global _face_recognition_service
    if _face_recognition_service is None:
        _face_recognition_service = FaceRecognitionService()
    return _face_recognition_service
