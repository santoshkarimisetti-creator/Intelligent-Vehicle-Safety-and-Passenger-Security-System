"""
Backend Face Embeddings Management

Store and retrieve face embeddings per driver for recognition.
"""

from datetime import datetime
from pymongo import MongoClient
import uuid
from typing import Dict, List, Optional, Any

# MongoDB setup
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "ivs_db"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
embeddings_collection = db["driver_embeddings"]

# Create index for fast lookup
embeddings_collection.create_index("driver_id", unique=False)
embeddings_collection.create_index("driver_name", unique=False)


def store_driver_embedding(driver_id: str, driver_name: str, embedding: List[float], model_type: str = "insightface") -> Dict[str, Any]:
    """
    Store face embedding for a driver.
    
    Args:
        driver_id: Unique driver identifier
        driver_name: Driver's name
        embedding: 1D array of embedding values (128D or 512D)
        model_type: Type of model used ('insightface' or 'face_recognition')
    
    Returns:
        Stored document
    """
    embedding_doc = {
        "driver_id": driver_id,
        "driver_name": driver_name,
        "embedding": embedding,  # Store as list for JSON compatibility
        "embedding_dim": len(embedding),
        "model_type": model_type,
        "stored_at": datetime.utcnow().isoformat(),
        "is_active": True
    }
    
    # Update or insert
    result = embeddings_collection.update_one(
        {"driver_id": driver_id},
        {"$set": embedding_doc},
        upsert=True
    )
    
    embedding_doc["_id"] = str(result.upserted_id or result.matched_id)
    return embedding_doc


def get_driver_embeddings(driver_id: str) -> Optional[Dict[str, Any]]:
    """
    Get face embedding for a driver.
    
    Returns:
        Document with embedding, or None if not found
    """
    doc = embeddings_collection.find_one(
        {"driver_id": driver_id, "is_active": True}
    )
    
    if doc:
        doc["_id"] = str(doc["_id"])
    
    return doc


def get_all_driver_embeddings(limit: int = 1000) -> List[Dict[str, Any]]:
    """
    Get all stored driver embeddings.
    
    Returns:
        List of embedding documents
    """
    docs = list(embeddings_collection.find({"is_active": True}).limit(limit))
    
    for doc in docs:
        doc["_id"] = str(doc["_id"])
    
    return docs


def delete_driver_embedding(driver_id: str) -> bool:
    """
    Delete/deactivate driver embedding.
    
    Returns:
        True if updated, False if not found
    """
    result = embeddings_collection.update_one(
        {"driver_id": driver_id},
        {"$set": {"is_active": False}}
    )
    
    return result.matched_count > 0


def update_driver_info(driver_id: str, driver_name: str) -> bool:
    """Update driver name for embeddings."""
    result = embeddings_collection.update_one(
        {"driver_id": driver_id},
        {"$set": {"driver_name": driver_name, "updated_at": datetime.utcnow().isoformat()}}
    )
    
    return result.modified_count > 0


def clear_all_embeddings() -> int:
    """Clear all embeddings (for testing). Returns count deleted."""
    result = embeddings_collection.delete_many({})
    return result.deleted_count
