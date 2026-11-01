import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from observation_hub import ObservationHub
from proactive_controller import TurnContext
from proactive_realtime import ProactiveRealtimeModel
from proactive_voice import NotificationPolicy, ProactiveVoiceBridge
from expression_monitor import ObservationMonitor, ObservationSettings
from test_observation import observation


def noteworthy(progress="possible_stuck", **changes):
    return {"context_id": "editor-a", "surface": "user_task", "noteworthy": True, "progress": progress,
            "notification": "The function remains incomplete after several attempts; offer help.",
            "evidence": ["The same unresolved editor problems remain visible."], "confidence": 0.95,
            "history_span_seconds": 25, "recent_observation_count": 4, **changes}


def hub_with_event(**changes):
    hub = ObservationHub(mode="proactive_voice")
    hub.publish("computer", observed_at=100, expires_at=120, payload=noteworthy(**changes), now=100)
    hub.publish("camera", observed_at=100, expires_at=110,
                payload={"stable_expression": None, "cues": ["furrowed_brow"], "interpretation": "visible_cues_only"}, now=100)
    return hub


def test_notification_policy_combines_cues_without_asserting_emotion_and_deduplicates():
    hub = hub_with_event()
    policy = NotificationPolicy()
    notification = policy.candidate(hub.snapshot(now=101), TurnContext(), 101)
    assert notification is not None
    data = json.loads(notification.text)
    assert data["camera"]["payload"]["stable_expression"] is None
    assert data["camera"]["payload"]["cues"] == ["furrowed_brow"]
    policy.sent(notification, 101)
    assert policy.candidate(hub.snapshot(now=102), TurnContext(), 102) is None


@pytest.mark.parametrize("changes", [{"noteworthy": False}, {"confidence": 0.6}, {"surface": "monitor"},
                                     {"history_span_seconds": 5}, {"recent_observation_count": 1}, {"notification": None}])
def test_in_progress_weak_self_monitoring_and_premature_stuck_signals_do_not_notify(changes):
    hub = hub_with_event(**changes)
    assert NotificationPolicy().candidate(hub.snapshot(now=101), TurnContext(), 101) is None


@pytest.mark.parametrize("context", [TurnContext(user_speaking=True), TurnContext(response_active=True),
                                     TurnContext(audio_playing=True), TurnContext(computer_busy=True),
                                     TurnContext(last_user_activity=101), TurnContext(computer_generation=1)])
def test_notifications_wait_for_conversational_idle_and_fresh_post_user_evidence(context):
    hub = hub_with_event()
    assert NotificationPolicy().candidate(hub.snapshot(now=102), context, 102) is None


def test_expired_event_drops_and_missing_camera_does_not_block_a_clear_task_event():
    hub = hub_with_event(progress="blocked")
    policy = NotificationPolicy()
    hub.unavailable("camera", "no_face", now=101)
    notification = policy.candidate(hub.snapshot(now=102), TurnContext(), 102)
    assert notification is not None
    assert json.loads(notification.text)["camera"]["status"] == "unavailable"
    assert policy.candidate(hub.snapshot(now=121), TurnContext(), 121) is None


def test_combined_offer_waits_for_unchanged_camera_persistence_despite_uncertain_emotion():
    hub = ObservationHub(mode="proactive_voice")
    hub.publish("computer", observed_at=100, expires_at=120, now=100, payload=noteworthy(
        progress="in_progress", noteworthy=False, notification=None,
        possible_blocker="A Python syntax error prevents the test run from completing.",
    ))
    monitor = ObservationMonitor(None, None, ObservationSettings(), hub=hub)
    policy = NotificationPolicy()
    for at in (100, 102, 104):
        sample = observation(at, confidence=0.65)
        monitor.filter.observe(sample, at)
        monitor.cue_filter.observe(sample, at)
        monitor._publish_camera(at)
        decision = policy.evaluate(hub.snapshot(now=at), TurnContext(), at)
        if at < 104:
            assert decision.notification is None
    assert monitor.settings.threshold == 0.8 and monitor.settings.ttl == 10
    assert monitor.filter.state is None
    assert decision.notification.trigger == "combined_task_difficulty"
    payload = json.loads(decision.notification.text)
    assert payload["computer"]["payload"]["noteworthy"] is False
    assert payload["camera"]["payload"]["stable_expression"] is None
    assert payload["camera"]["payload"]["cues"] == ["furrowed_brow"]


@pytest.mark.parametrize("case", ["normal_typing", "no_camera", "neutral_camera", "skewed_camera", "short_history"])
def test_combined_offers_need_a_concrete_obstacle_task_history_and_aligned_camera_support(case):
    changes = dict(progress="in_progress", noteworthy=False, notification=None, possible_blocker="A syntax error is visible.")
    if case == "normal_typing":
        changes["possible_blocker"] = None
    elif case == "short_history":
        changes["history_span_seconds"] = 5
    hub = hub_with_event(**changes)
    if case == "no_camera":
        hub.unavailable("camera", "no_face", now=101)
    elif case == "neutral_camera":
        hub.publish("camera", observed_at=101, expires_at=111, now=101,
                    payload={"stable_expression": "neutral", "cues": []})
    elif case == "skewed_camera":
        hub.publish("camera", observed_at=109, expires_at=119, now=109,
                    payload={"stable_expression": None, "cues": ["furrowed_brow"]})
    now = 109 if case == "skewed_camera" else 101
    assert NotificationPolicy().candidate(hub.snapshot(now=now), TurnContext(), now) is None


def test_an_offer_is_not_repeated_when_difficulty_progress_changes_and_cooldown_applies_across_tasks():
    policy = NotificationPolicy()
    hub = hub_with_event(progress="in_progress", noteworthy=False, notification=None, possible_blocker="A syntax error is visible.")
    notification = policy.candidate(hub.snapshot(now=101), TurnContext(), 101)
    policy.sent(notification, 101)
    hub.publish("computer", observed_at=170, expires_at=190, now=170,
                payload=noteworthy(progress="blocked", possible_blocker="The error persists."))
    assert policy.evaluate(hub.snapshot(now=170), TurnContext(), 170).reason == "already_offered_for_this_task"
    hub.publish("computer", observed_at=171, expires_at=191, now=171,
                payload=noteworthy(progress="blocked", context_id="editor-b"))
    next_offer = policy.candidate(hub.snapshot(now=171), TurnContext(), 171)
    assert next_offer is not None
    policy.sent(next_offer, 171)
    hub.publish("computer", observed_at=172, expires_at=192, now=172,
                payload=noteworthy(progress="blocked", context_id="editor-c"))
    assert policy.evaluate(hub.snapshot(now=172), TurnContext(), 172).reason == "cooldown"


class Socket:
    def __init__(self):
        self.messages = []
        self.after_context = None

    async def send(self, text):
        data = json.loads(text)
        self.messages.append(data)
        if data["type"] == "conversation.item.create" and self.after_context is not None:
            self.after_context()


async def test_real_realtime_transport_serializes_context_and_a_tool_free_voice_turn():
    model = ProactiveRealtimeModel()
    socket = Socket()
    model._websocket = socket
    assert await model.send_proactive_response('{"event":"possible_stuck"}', lambda: True)
    create, response = socket.messages
    assert create["item"]["role"] == "system"
    assert "UNTRUSTED_OBSERVATIONS" in create["item"]["content"][0]["text"]
    assert response["type"] == "response.create"
    assert response["response"]["tools"] == []
    assert response["response"]["tool_choice"] == "none"
    assert response["response"]["metadata"]["kind"] == "proactive_observation"
    assert not await model.send_proactive_response("duplicate", lambda: True)  # Already pending.
    await model.clear_proactive_context()
    assert socket.messages[-1]["type"] == "conversation.item.delete"


async def test_user_speech_or_shutdown_before_commit_cancels_the_proactive_turn_and_releases_reservation():
    model = ProactiveRealtimeModel()
    socket = Socket()
    model._websocket = socket
    allowed = [True]
    socket.after_context = lambda: allowed.__setitem__(0, False)
    assert not await model.send_proactive_response("context", lambda: allowed[0])
    assert [item["type"] for item in socket.messages] == ["conversation.item.create", "conversation.item.delete"]
    assert not await model._response_create_sequencer.has_pending_response_create()
    assert model._response_control == "free"


async def test_cancellation_while_waiting_for_response_slot_does_not_block_normal_user_turns(monkeypatch):
    model = ProactiveRealtimeModel()
    model._websocket = Socket()
    waiting = asyncio.Event()

    async def slot(*args, **kwargs):
        waiting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(model._response_create_sequencer, "wait_for_response_create_slot", slot)
    task = asyncio.create_task(model.send_proactive_response("context", lambda: True))
    await waiting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not await model._response_create_sequencer.has_pending_response_create()
    assert not model._websocket.messages


async def test_bridge_delivers_event_to_main_voice_and_stops_on_the_session_event(monkeypatch):
    monkeypatch.setattr("proactive_voice.monotonic", lambda: 101)
    hub = hub_with_event()
    hub_snapshot = hub.snapshot
    monkeypatch.setattr(hub, "snapshot", lambda **kwargs: hub_snapshot(now=101, **kwargs))
    stop = asyncio.Event()
    sent = []

    async def send(text, still_relevant):
        assert still_relevant()
        sent.append(json.loads(text))
        stop.set()
        return True

    bridge = ProactiveVoiceBridge(SimpleNamespace(model=SimpleNamespace(send_proactive_response=send)),
                                  hub, lambda: TurnContext(), stop, log=lambda *args, **kwargs: None)
    await bridge.run()
    assert len(sent) == 1
    assert sent[0]["computer"]["payload"]["progress"] == "possible_stuck"
    assert sent[0]["camera"]["payload"]["cues"] == ["furrowed_brow"]


@pytest.mark.parametrize("change", ["camera_became_neutral", "camera_expired", "shutdown"])
async def test_combined_context_change_at_websocket_commit_prevents_speech_and_releases_slot(monkeypatch, change):
    now = [101]
    monkeypatch.setattr("proactive_voice.monotonic", lambda: now[0])
    hub = hub_with_event(progress="in_progress", noteworthy=False, notification=None, possible_blocker="A syntax error is visible.")
    snapshot = hub.snapshot
    monkeypatch.setattr(hub, "snapshot", lambda **kwargs: snapshot(now=now[0], **kwargs))
    stop = asyncio.Event()
    model = ProactiveRealtimeModel()
    socket = Socket()
    model._websocket = socket
    logs = []

    def change_after_context():
        if change == "camera_became_neutral":
            hub.publish("camera", observed_at=101, expires_at=111, now=101,
                        payload={"stable_expression": "neutral", "cues": []})
        elif change == "camera_expired":
            now[0] = 110
        else:
            stop.set()

    socket.after_context = change_after_context
    bridge = ProactiveVoiceBridge(SimpleNamespace(model=model), hub, lambda: TurnContext(), stop,
                                  log=lambda event, **fields: logs.append((event, fields)))
    task = asyncio.create_task(bridge.run())
    try:
        async with asyncio.timeout(2):
            while len(socket.messages) < 2:
                await asyncio.sleep(0.005)
            stop.set()
            await task
        assert [message["type"] for message in socket.messages] == ["conversation.item.create", "conversation.item.delete"]
        assert not any(event == "observation_sent_to_voice" for event, _ in logs)
        assert not await model._response_create_sequencer.has_pending_response_create()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_sent_combined_context_is_removed_when_camera_support_changes(monkeypatch):
    monkeypatch.setattr("proactive_voice.monotonic", lambda: 101)
    hub = hub_with_event(progress="in_progress", noteworthy=False, notification=None, possible_blocker="A syntax error is visible.")
    snapshot = hub.snapshot
    monkeypatch.setattr(hub, "snapshot", lambda **kwargs: snapshot(now=101, **kwargs))
    stop = asyncio.Event()
    clear = AsyncMock()
    logs = []

    async def send(text, send_if):
        assert send_if()
        stop.set()
        return True

    bridge = ProactiveVoiceBridge(SimpleNamespace(model=SimpleNamespace(send_proactive_response=send, clear_proactive_context=clear)),
                                  hub, lambda: TurnContext(), stop,
                                  log=lambda event, **fields: logs.append((event, fields)))
    await bridge.run()
    clear.assert_not_awaited()
    delivered = next(fields for event, fields in logs if event == "observation_sent_to_voice")
    assert delivered["trigger"] == "combined_task_difficulty"
    assert delivered["progress"] == "in_progress" and delivered["camera_included"] is True
    hub.publish("camera", observed_at=101, expires_at=111, now=101,
                payload={"stable_expression": "neutral", "cues": []})
    await bridge._forget_expired_context()
    clear.assert_awaited_once()
    await bridge._forget_expired_context()
    clear.assert_awaited_once()
