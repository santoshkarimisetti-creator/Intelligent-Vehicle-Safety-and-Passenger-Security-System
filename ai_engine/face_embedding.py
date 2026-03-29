"""
Face Embedding Model Module

Handles face embedding extraction using InsightFace or fallback to face_recognition.
"""

import numpy as np
from typing import Optional, List, Dict, Tuple
import cv2

try:
    import insightface
    INSIGHTFACE_AVAILABLE = True
except ImportError:
    INSIGHTFACE_AVAILABLE = False
    print("⚠ InsightFace not available. Attempting face_recognition fallback...")

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False
    print("⚠ face_recognition not available. Face embedding disabled.")

class FaceEmbedding:
    """Extract and manage face embeddings."""
    
    def __init__(self):
        self.model = None
        self.model_type = None
        self.embedding_dim = 512
        self._init_model()
    
    def _init_model(self):
        """Initialize face embedding model."""
        if INSIGHTFACE_AVAILABLE:
            try:
                # InsightFace RetinaFace + ArcFace model
                self.model = insightface.app.FaceAnalysis(
                    name='buffalo_l',  # Large model for best accuracy
                    providers=['CPUProvider']  # Use CPU by default
                )
                self.model.prepare(ctx_id=-1, det_thresh=0.5)
                self.model_type = 'insightface'
                self.embedding_dim = 512
                print("✓ InsightFace model initialized (512D embeddings)")
                return
            except Exception as e:
                print(f"⚠ InsightFace init failed: {e}")
        
        if FACE_RECOGNITION_AVAILABLE:
            try:
                # face_recognition uses dlib's ResNet model
                self.model = 'face_recognition'
                self.model_type = 'face_recognition'
                self.embedding_dim = 128
                print("✓ face_recognition model initialized (128D embeddings)")
                return
            except Exception as e:
                print(f"⚠ face_recognition init failed: {e}")
        
        self.model = None
        self.model_type = None
        print("✗ No face embedding model available")
    
    def extract_embedding(self, image: np.ndarray, face_bbox: Dict) -> Optional[np.ndarray]:
        """
        Extract embedding from a detected face.
        
        Args:
            image: BGR image array (from OpenCV)
            face_bbox: {"x": ..., "y": ..., "w": ..., "h": ...}
        
        Returns:
            embedding: 1D numpy array (512D for InsightFace, 128D for face_recognition)
        """
        if self.model is None:
            return None
        
        if image is None or image.size == 0:
            return None
        
        try:
            x = face_bbox.get('x', 0)
            y = face_bbox.get('y', 0)
            w = face_bbox.get('w', 0)
            h = face_bbox.get('h', 0)
            
            if w <= 0 or h <= 0:
                return None
            
            # Extract face region
            x1 = max(0, x)
            y1 = max(0, y)
            x2 = min(image.shape[1], x + w)
            y2 = min(image.shape[0], y + h)
            
            if x2 <= x1 or y2 <= y1:
                return None
            
            face_image = image[y1:y2, x1:x2].copy()
            
            if self.model_type == 'insightface':
                return self._extract_insightface(face_image)
            elif self.model_type == 'face_recognition':
                return self._extract_face_recognition(face_image)
            
            return None
        
        except Exception as e:
            print(f"Error extracting embedding: {e}")
            return None
    
    def _extract_insightface(self, face_image: np.ndarray) -> Optional[np.ndarray]:
        """Extract embedding using InsightFace."""
        try:
            # InsightFace expects BGR image
            results = self.model.get(face_image)
            if results and len(results) > 0:
                embedding = results[0].embedding
                embedding = embedding / np.linalg.norm(embedding)  # L2 normalize
                return embedding.astype(np.float32)
            return None
        except Exception as e:
            print(f"InsightFace extraction error: {e}")
            return None
    
    def _extract_face_recognition(self, face_image: np.ndarray) -> Optional[np.ndarray]:
        """Extract embedding using face_recognition."""
        try:
            # face_recognition expects RGB image
            rgb_image = cv2.cvtColor(face_image, cv2.COLOR_BGR2RGB)
            face_locations = face_recognition.face_locations(rgb_image, model='hog')
            
            if not face_locations:
                return None
            
            encodings = face_recognition.face_encodings(rgb_image, face_locations)
            if encodings:
                embedding = encodings[0]
                embedding = embedding / np.linalg.norm(embedding)  # L2 normalize
                return embedding.astype(np.float32)
            
            return None
        except Exception as e:
            print(f"face_recognition extraction error: {e}")
            return None
    
    @staticmethod
    def cosine_similarity(embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """
        Calculate cosine similarity between two embeddings.
        
        Returns: float between -1 and 1 (higher = more similar)
        """
        if embedding1 is None or embedding2 is None:
            return 0.0
        
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        embedding1_norm = embedding1 / norm1
        embedding2_norm = embedding2 / norm2
        
        return float(np.dot(embedding1_norm, embedding2_norm))
    
    @staticmethod
    def euclidean_distance(embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """Calculate Euclidean distance between two embeddings."""
        if embedding1 is None or embedding2 is None:
            return float('inf')
        
        return float(np.linalg.norm(embedding1 - embedding2))
    
    def is_same_person(self, embedding1: np.ndarray, embedding2: np.ndarray, threshold: float = 0.6) -> bool:
        """Check if two embeddings represent the same person using cosine similarity."""
        similarity = self.cosine_similarity(embedding1, embedding2)
        return similarity >= threshold
    
    def get_embedding_dim(self) -> int:
        """Get embedding dimension."""
        return self.embedding_dim if self.model else 0
    
    def is_available(self) -> bool:
        """Check if model is available."""
        return self.model is not None


# Global instance
_face_embedding_instance = None

def get_face_embedding() -> FaceEmbedding:
    """Get or create face embedding model instance."""
    global _face_embedding_instance
    if _face_embedding_instance is None:
        _face_embedding_instance = FaceEmbedding()
    return _face_embedding_instance
