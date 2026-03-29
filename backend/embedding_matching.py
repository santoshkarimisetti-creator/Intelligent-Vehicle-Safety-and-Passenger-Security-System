"""
Face Embedding Matching Service

Compare candidate embeddings against stored driver embeddings.
"""

from typing import Dict, List, Optional, Tuple
import numpy as np
from embedding_storage import get_driver_embeddings, get_all_driver_embeddings


def cosine_similarity(embedding1: List[float], embedding2: List[float]) -> float:
    """
    Compute cosine similarity between two embeddings.
    
    Returns:
        Score in range [-1, 1], where 1 = identical, 0 = orthogonal, -1 = opposite
    """
    emb1 = np.array(embedding1)
    emb2 = np.array(embedding2)
    
    # Normalize
    norm1 = np.linalg.norm(emb1)
    norm2 = np.linalg.norm(emb2)
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    emb1_norm = emb1 / norm1
    emb2_norm = emb2 / norm2
    
    return float(np.dot(emb1_norm, emb2_norm))


def euclidean_distance(embedding1: List[float], embedding2: List[float]) -> float:
    """
    Compute Euclidean distance between two embeddings.
    
    Returns:
        Distance value (0 = identical)
    """
    emb1 = np.array(embedding1)
    emb2 = np.array(embedding2)
    return float(np.linalg.norm(emb1 - emb2))


def find_best_match(candidate_embedding: List[float], 
                   candidates: Optional[List[Dict]] = None,
                   similarity_threshold: float = 0.6,
                   use_distance: bool = False) -> Optional[Dict[str, any]]:
    """
    Find the best matching driver for a candidate embedding.
    
    Args:
        candidate_embedding: The embedding to match
        candidates: List of stored embeddings. If None, fetches all from DB.
        similarity_threshold: Minimum cosine similarity (or max distance if use_distance=True)
        use_distance: If True, use euclidean distance instead of cosine similarity
    
    Returns:
        {
            "driver_id": str,
            "driver_name": str,
            "similarity": float or distance: float,
            "is_known": bool,
            "confidence": float (0-100)
        }
        or None if no good match found
    """
    if candidates is None:
        candidates = get_all_driver_embeddings()
    
    if not candidates:
        return None
    
    best_match = None
    best_score = -2.0 if not use_distance else float('inf')
    
    for candidate in candidates:
        stored_embedding = candidate.get("embedding", [])
        
        if not stored_embedding:
            continue
        
        if use_distance:
            score = euclidean_distance(candidate_embedding, stored_embedding)
            is_better = score < best_score
        else:
            score = cosine_similarity(candidate_embedding, stored_embedding)
            is_better = score > best_score
        
        if is_better:
            best_score = score
            best_match = candidate
    
    # Apply threshold
    if best_match is None:
        return None
    
    if use_distance:
        is_known = best_score <= similarity_threshold
        confidence = max(0, 100 * (1 - best_score))  # Distance: lower is better
    else:
        is_known = best_score >= similarity_threshold
        confidence = max(0, 100 * best_score)  # Similarity: higher is better
    
    return {
        "driver_id": best_match.get("driver_id"),
        "driver_name": best_match.get("driver_name"),
        "similarity": best_score if not use_distance else None,
        "distance": best_score if use_distance else None,
        "is_known": is_known,
        "confidence": round(confidence, 1),
        "model_type": best_match.get("model_type", "unknown")
    }


def match_all_candidates(candidate_embedding: List[float], 
                        candidates: Optional[List[Dict]] = None,
                        max_results: int = 5) -> List[Dict]:
    """
    Find all potential matches ranked by similarity.
    
    Returns:
        List of matches sorted by best to worst match
    """
    if candidates is None:
        candidates = get_all_driver_embeddings()
    
    if not candidates:
        return []
    
    matches = []
    
    for candidate in candidates:
        stored_embedding = candidate.get("embedding", [])
        
        if not stored_embedding:
            continue
        
        score = cosine_similarity(candidate_embedding, stored_embedding)
        confidence = max(0, 100 * score)
        
        matches.append({
            "driver_id": candidate.get("driver_id"),
            "driver_name": candidate.get("driver_name"),
            "similarity": score,
            "confidence": round(confidence, 1),
            "model_type": candidate.get("model_type", "unknown")
        })
    
    # Sort by similarity (best first)
    matches.sort(key=lambda x: x["similarity"], reverse=True)
    
    return matches[:max_results]


def verify_driver(driver_id: str, candidate_embedding: List[float], 
                 threshold: float = 0.6) -> Dict[str, any]:
    """
    Verify if a candidate embedding matches a specific driver.
    
    Args:
        driver_id: Expected driver ID
        candidate_embedding: Embedding to verify
        threshold: Minimum similarity for verification
    
    Returns:
        {
            "driver_id": str,
            "verified": bool,
            "similarity": float,
            "confidence": float (0-100)
        }
    """
    stored_doc = get_driver_embeddings(driver_id)
    
    if not stored_doc:
        return {
            "driver_id": driver_id,
            "verified": False,
            "similarity": 0,
            "confidence": 0,
            "reason": "No embedding found for driver"
        }
    
    stored_embedding = stored_doc.get("embedding", [])
    if not stored_embedding:
        return {
            "driver_id": driver_id,
            "verified": False,
            "similarity": 0,
            "confidence": 0,
            "reason": "Stored embedding corrupted"
        }
    
    similarity = cosine_similarity(candidate_embedding, stored_embedding)
    confidence = max(0, 100 * similarity)
    verified = similarity >= threshold
    
    return {
        "driver_id": driver_id,
        "verified": verified,
        "similarity": round(similarity, 4),
        "confidence": round(confidence, 1),
        "threshold": threshold,
        "driver_name": stored_doc.get("driver_name", "Unknown")
    }
