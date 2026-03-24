"""
ai_engine.driver_profile_engine

Thin adapter around existing driver/session + thresholds logic.

This keeps the codebase modular without forcing a large refactor.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from driver_session_manager import get_driver_session_manager


def get_driver_profile(
    *,
    session_key: str,
    fallback_driver_id: str,
    identity_driver_id: Optional[str],
    identity_confidence: float,
    identity_matched: bool,
) -> Dict[str, Any]:
    """
    Returns:
    - active_driver_id
    - thresholds (personalized, cached)
    - driver_changed
    - previous_driver_id
    - session_export (debug info)
    """
    session_mgr = get_driver_session_manager()
    sess, driver_changed, previous_driver = session_mgr.observe_identity(
        session_key=session_key,
        fallback_driver_id=fallback_driver_id,
        identity_driver_id=identity_driver_id,
        identity_confidence=identity_confidence,
        identity_matched=identity_matched,
    )
    thresholds = session_mgr.get_thresholds(
        session_key=session_key,
        driver_id=sess.active_driver_id,
    )
    return {
        "active_driver_id": sess.active_driver_id,
        "thresholds": thresholds,
        "driver_changed": bool(driver_changed),
        "previous_driver_id": previous_driver,
        "session_export": session_mgr.export_session(session_key=session_key),
    }

