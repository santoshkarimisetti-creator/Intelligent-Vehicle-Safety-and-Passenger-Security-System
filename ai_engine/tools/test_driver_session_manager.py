"""Sanity tests for DriverSessionManager identity locking.

Run:
  python -m ai_engine.tools.test_driver_session_manager
"""

from ai_engine.driver_session_manager import DriverSessionManager


def test_driver_session_manager_identity_locking() -> None:
    mgr = DriverSessionManager(
        backend_base_url="http://invalid",  # avoid network
        thresholds_ttl_s=9999,
        session_ttl_s=9999,
        default_thresholds={"ear_drowsiness": 0.25, "mar_yawning": 0.6, "head_turn": 25},
    )

    # Before lock, uses fallback
    sess, changed, prev = mgr.observe_identity(
        session_key="trip1",
        fallback_driver_id="fallback",
        identity_driver_id=None,
        identity_confidence=0.0,
        identity_matched=False,
        now=1.0,
    )
    assert sess.active_driver_id == "fallback"
    assert not sess.locked
    assert changed is False

    # First match locks to driverA
    sess, changed, prev = mgr.observe_identity(
        session_key="trip1",
        fallback_driver_id="fallback",
        identity_driver_id="driverA",
        identity_confidence=0.9,
        identity_matched=True,
        now=2.0,
    )
    assert sess.locked is True
    assert sess.active_driver_id == "driverA"
    assert changed is True
    assert prev == "fallback"

    # Later match of different driver should be ignored
    sess, changed, prev = mgr.observe_identity(
        session_key="trip1",
        fallback_driver_id="fallback",
        identity_driver_id="driverB",
        identity_confidence=0.95,
        identity_matched=True,
        now=3.0,
    )
    assert sess.active_driver_id == "driverA"
    assert sess.locked_driver_id == "driverA"
    assert changed is False

    # Even if fallback changes, still locked
    sess, changed, prev = mgr.observe_identity(
        session_key="trip1",
        fallback_driver_id="fallback2",
        identity_driver_id=None,
        identity_confidence=0.0,
        identity_matched=False,
        now=4.0,
    )
    assert sess.active_driver_id == "driverA"
    assert changed is False

    mgr.reset_session(session_key="trip1")
    sess, changed, prev = mgr.observe_identity(
        session_key="trip1",
        fallback_driver_id="fallback2",
        identity_driver_id=None,
        identity_confidence=0.0,
        identity_matched=False,
        now=5.0,
    )
    assert sess.active_driver_id == "fallback2"


def main() -> None:
    test_driver_session_manager_identity_locking()


if __name__ == "__main__":
    main()
