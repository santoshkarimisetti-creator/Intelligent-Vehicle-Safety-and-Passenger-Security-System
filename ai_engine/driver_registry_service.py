import base64
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    from pymongo import MongoClient
except Exception:  # pragma: no cover
    MongoClient = None  # type: ignore

from face_recognition_service import get_face_recognition_service


@dataclass(frozen=True)
class DriverRegistrationResult:
    driver_id: str
    samples_used: int
    embedding_dim: int


class DriverRegistryService:
    def __init__(
        self,
        mongo_uri: Optional[str] = None,
        mongo_db: Optional[str] = None,
        drivers_collection: str = "drivers",
        connect_timeout_ms: int = 1500,
    ) -> None:
        self._mongo_uri = mongo_uri or os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        if mongo_db:
            self._mongo_db = mongo_db
        else:
            db_env = os.getenv("DB_NAME")
            if db_env and str(db_env).upper() == "IVSPS":
                self._mongo_db = "IVSPS"
            else:
                self._mongo_db = os.getenv("MONGO_DB", "IVS")
        self._drivers_collection_name = drivers_collection
        self._connect_timeout_ms = connect_timeout_ms

    def register_driver_from_images(
        self,
        *,
        driver_id: str,
        images_bgr: List[np.ndarray],
        min_samples: int = 1,
    ) -> DriverRegistrationResult:
        if not driver_id:
            raise ValueError("driver_id is required")
        if not images_bgr:
            raise ValueError("images_bgr must contain at least one image")

        embeddings: List[np.ndarray] = []
        face_service = get_face_recognition_service()

        for image in images_bgr:
            faces = face_service.extract_face_embeddings(image)
            if not faces:
                continue

            # Pick the largest face by area for this image.
            best_bbox, best_emb = max(
                faces,
                key=lambda pair: float(max(0, pair[0].get("w", 0))) * float(max(0, pair[0].get("h", 0))),
            )
            embeddings.append(np.asarray(best_emb, dtype=np.float32).reshape(-1))

        if len(embeddings) < min_samples:
            raise ValueError(
                f"Not enough usable samples: got {len(embeddings)}, need {min_samples}"
            )

        avg = np.mean(np.stack(embeddings, axis=0), axis=0)
        norm = float(np.linalg.norm(avg))
        if norm > 0:
            avg = avg / norm

        self._upsert_embedding(driver_id=driver_id, embedding=avg)
        return DriverRegistrationResult(
            driver_id=driver_id, samples_used=len(embeddings), embedding_dim=int(avg.shape[0])
        )

    def _upsert_embedding(self, *, driver_id: str, embedding: np.ndarray) -> None:
        if MongoClient is None:
            raise RuntimeError(
                "pymongo is not available; cannot store driver embedding in MongoDB"
            )

        client = MongoClient(
            self._mongo_uri,
            serverSelectionTimeoutMS=self._connect_timeout_ms,
            connectTimeoutMS=self._connect_timeout_ms,
            socketTimeoutMS=self._connect_timeout_ms,
        )
        # Fail fast if Mongo is unreachable.
        client.admin.command("ping")

        db = client[self._mongo_db]
        coll = db[self._drivers_collection_name]

        now = datetime.now(timezone.utc)
        doc: Dict[str, Any] = {
            "driver_id": driver_id,
            "embedding": embedding.astype(float).tolist(),
            "embedding_dim": int(embedding.shape[0]),
            "embedding_updated_at": now,
        }

        coll.update_one({"driver_id": driver_id}, {"$set": doc}, upsert=True)


_driver_registry_singleton: Optional[DriverRegistryService] = None


def get_driver_registry_service() -> DriverRegistryService:
    global _driver_registry_singleton
    if _driver_registry_singleton is None:
        _driver_registry_singleton = DriverRegistryService()
    return _driver_registry_singleton


def decode_base64_image_to_bgr(image_b64: str) -> np.ndarray:
    if not image_b64:
        raise ValueError("image is empty")

    # allow 'data:image/jpeg;base64,...'
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    raw = base64.b64decode(image_b64)
    npbuf = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(npbuf, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode image")
    return img
