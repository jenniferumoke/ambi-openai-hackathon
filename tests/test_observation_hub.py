import asyncio
import json

import pytest

from expression_monitor import ObservationMonitor, ObservationSettings
from observation_hub import ObservationHub, log_joint_observations
from proactive_controller import TurnContext
from test_observation import observation


def test_hub_joins_fresh_sources_and_expires_them_independently():
    hub = ObservationHub()
    hub.publish("camera", observed_at=10, expires_at=20, payload={"stable_expression": "confused"}, now=10)
    hub.publish("computer", observed_at=12, expires_at=30, payload={"visible_activity": "Editing code"}, now=12)
    snapshot = hub.snapshot(now=13)
    assert snapshot["pair"] == {"aligned": True, "skew_seconds": 2, "reason": "aligned"}
    assert snapshot["camera"]["status"] == snapshot["computer"]["status"] == "available"
    snapshot = hub.snapshot(now=20)
    assert snapshot["camera"] == {"status": "unavailable", "reason": "expired"}
    assert snapshot["computer"]["status"] == "available"
    assert not snapshot["pair"]["aligned"]


def test_hub_flags_time_skew_without_discarding_individually_fresh_data():
    hub = ObservationHub(max_pair_skew=8)
    hub.publish("computer", observed_at=0, expires_at=30, payload={}, now=0)
    hub.publish("camera", observed_at=12, expires_at=22, payload={}, now=12)
    snapshot = hub.snapshot(now=13)
    assert snapshot["pair"]["reason"] == "observations_too_far_apart"
    assert snapshot["computer"]["status"] == "available"


def test_hub_rejects_expired_future_out_of_order_and_disabled_source_updates():
    hub = ObservationHub(["computer"])
    assert not hub.publish("camera", observed_at=1, expires_at=10, payload={}, now=1)
    assert hub.publish("computer", observed_at=5, expires_at=15, payload={"value": "current"}, now=5)
    for observed, expires, now in [(4, 20, 6), (6, 10, 10), (20, 30, 10), (float("nan"), 30, 10)]:
        assert not hub.publish("computer", observed_at=observed, expires_at=expires, payload={}, now=now)
    hub.unavailable("computer", "capture_failed", now=6)
    assert not hub.publish("computer", observed_at=4, expires_at=20, payload={}, now=7)
    assert hub.snapshot(now=7)["computer"]["reason"] == "capture_failed"
    assert hub.snapshot(now=7)["camera"]["reason"] == "not_enabled"


def test_snapshots_and_bounded_history_cannot_mutate_live_state():
    hub = ObservationHub(history_limit=3)
    payload = {"evidence": ["visible error"]}
    hub.publish("computer", observed_at=0, expires_at=20, payload=payload, now=0)
    payload["evidence"].append("external mutation")
    snapshot = hub.snapshot(now=1)
    snapshot["computer"]["payload"]["evidence"].clear()
    assert hub.snapshot(now=1)["computer"]["payload"] == {"evidence": ["visible error"]}
    for at in range(1, 10):
        hub.publish("computer", observed_at=at, expires_at=at + 20, payload={"value": at}, now=at)
    assert len(hub.history) == 3
    history = hub.history
    history[0]["source"] = "changed"
    assert hub.history[0]["source"] == "computer"


def test_same_observation_refreshes_freshness_without_growing_change_history():
    hub = ObservationHub(["computer"])
    hub.publish("computer", observed_at=0, expires_at=10, payload={"activity": "reading"}, now=0)
    version = hub.version
    hub.publish("computer", observed_at=2, expires_at=12, payload={"activity": "reading"}, now=2)
    assert hub.version > version
    assert len(hub.history) == 1
    assert hub.snapshot(now=11)["computer"]["status"] == "available"


def test_camera_publishes_only_after_existing_three_sample_threshold_and_clears_on_invalidity():
    hub = ObservationHub()
    monitor = ObservationMonitor(None, None, ObservationSettings(), hub=hub)
    for at in (0, 2):
        monitor.filter.observe(observation(at), at)
        monitor._publish_camera(at)
        assert hub.snapshot(now=at)["camera"]["status"] == "unavailable"
    monitor.filter.observe(observation(4), 4)
    monitor._publish_camera(4)
    snapshot = hub.snapshot(now=4)
    assert snapshot["camera"]["payload"]["stable_expression"] == "confused"
    assert snapshot["camera"]["observed_at"] == 4
    assert snapshot["camera"]["expires_at"] == 14
    monitor.filter.clear()
    monitor._publish_camera(5, unavailable_reason="classification_unavailable")
    assert hub.snapshot(now=5)["camera"] == {"status": "unavailable", "reason": "classification_unavailable"}
    assert monitor.settings.threshold == 0.8


async def test_joint_terminal_logger_includes_runtime_but_never_mutates_it():
    hub = ObservationHub(["computer"])
    event = asyncio.Event()
    records = []
    context = TurnContext(user_speaking=True, computer_generation=2)

    def log(name, **data):
        records.append((name, data))
        event.set()

    task = asyncio.create_task(log_joint_observations(hub, log=log, context=lambda: context))
    try:
        async with asyncio.timeout(1):
            await event.wait()
        name, snapshot = records[0]
        assert name == "joint_observation"
        assert snapshot["mode"] == "observation_only"
        assert snapshot["runtime"]["user_speaking"] is True
        assert context == TurnContext(user_speaking=True, computer_generation=2)
        json.dumps(snapshot, allow_nan=False)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_persistent_visible_brow_cues_are_shared_even_when_emotion_remains_uncertain():
    hub = ObservationHub()
    monitor = ObservationMonitor(None, None, ObservationSettings(), hub=hub)
    for at in (0, 2, 4):
        sample = observation(at, confidence=0.65)
        monitor.filter.observe(sample, at)
        monitor.cue_filter.observe(sample, at)
        monitor._publish_camera(at)
        if at < 4:
            assert hub.snapshot(now=at)["camera"]["status"] != "available"
    assert monitor.filter.state is None  # Emotion's original threshold was not relaxed.
    payload = hub.snapshot(now=4)["camera"]["payload"]
    assert payload["stable_expression"] is None
    assert payload["cues"] == ["furrowed_brow"]
    assert payload["interpretation"] == "visible_cues_only"
    assert hub.snapshot(now=14)["camera"]["status"] == "unavailable"
    assert monitor.settings.threshold == 0.8
