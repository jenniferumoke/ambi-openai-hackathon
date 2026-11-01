"""Offline checks for opt-in profile context, fresh offers, and confirmation."""
import json
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agents.realtime.testing import ScriptedRealtimeModel
import pytest
from starlette.testclient import TestClient

from ambient import CuePacket
from app_runtime import AppRuntime
from eval.test.demo import DemoLoop, DemoProfile, ROOT, create_demo_app
from main import Settings, create_voice_runner
from memory_store import MemoryStore
from proactive_controller import TurnActivity, TurnContext
from proactive_realtime import ProactiveRealtimeModel
from startup import greet_on_start


def packet(cues, sequence=0, usable=True):
    return CuePacket(stream_id="demo-test", sequence=sequence, usable=usable,
                     cues=cues, scores={}, age_ms=0, inference_ms=10, detection_ms=800)


@pytest.fixture
def demo(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("eval.test.demo.monotonic", lambda: now[0])
    monkeypatch.setattr("app_runtime.monotonic", lambda: now[0])
    memory = MemoryStore(tmp_path / "memory.db")
    profile = DemoProfile(tmp_path / "workspace")
    profile.seed(memory)
    runtime = AppRuntime(memory, demo_profile=profile)
    runtime.status, runtime.connected_at = "connected", 90
    runtime.worker = SimpleNamespace(perform=AsyncMock())
    runtime.session = SimpleNamespace(model=SimpleNamespace(send_context_response=AsyncMock(return_value=True)),
                                      send_message=AsyncMock(), interrupt=AsyncMock())
    runtime.audio = SimpleNamespace(clear=lambda: None)
    snapshot = runtime.hub.snapshot
    monkeypatch.setattr(runtime.hub, "snapshot", lambda **kwargs: snapshot(now=now[0], **kwargs))
    item = SimpleNamespace(runtime=runtime, profile=profile, loop=DemoLoop(runtime, profile), now=now)
    yield item
    memory.close()


def test_demo_copies_ellis_and_isolates_editable_code_and_memory(tmp_path):
    source = json.loads((ROOT / "bench/profiles/ellis.json").read_text())
    original = (ROOT / "bench/fixtures/code/exercise.py").read_text()
    app = create_demo_app(root=tmp_path / "run", auto_start=False)
    with TestClient(app) as client:
        profile = app.state.runtime.demo_profile
        assert profile.data["memory"][:len(source["memory"])] == source["memory"]
        boot = client.get("/api/bootstrap").json()
        assert boot["state"]["status"] == "idle"
        assert boot["state"]["observations"]["mode"] == "ellis_demo"
        assert any(row["title"] == "Resolve PairMatch issue PM-17" for row in boot["state"]["memories"])
        assert app.state.memory.get("ambi-project-brief") is None
        assert app.state.memory.path == tmp_path / "run/memory.sqlite3"
        (profile.workspace / "exercise.py").write_text("# edited only in this run\n")
        assert (ROOT / "bench/fixtures/code/exercise.py").read_text() == original
    with pytest.raises(FileExistsError):
        create_demo_app(root=tmp_path / "run", auto_start=False)


async def test_entire_action_catalog_is_preloaded_into_actual_voice_system_context(demo):
    model = ScriptedRealtimeModel(strict=False)
    runner = create_voice_runner(demo.runtime.worker, Settings(), model=model,
                                 memory=demo.runtime.memory, demo_profile=demo.profile)
    async with await runner.run():
        instructions = model.connect_calls[0]["initial_model_settings"]["instructions"]
    assert "Ellis Reed" in instructions and "PM-17" in instructions
    for text in ("Happy", "Brave", "Night Shift", "Magic Mike", "save_note", str(demo.profile.workspace)):
        assert text in instructions
    assert "not a to-do list or standing permission" in instructions
    assert all(action.requires_confirmation for rule in demo.profile.config.cue_mappings for action in rule.actions)
    assert len([action for rule in demo.profile.config.cue_mappings for action in rule.actions]) == 5


async def test_startup_speaks_first_with_ellis_context_and_yields_if_user_started(demo):
    send = demo.runtime.session.model.send_context_response
    assert await greet_on_start(demo.runtime.session, demo.runtime.memory, TurnActivity(), demo_profile=demo.profile)
    payload = json.loads(send.call_args.args[0])
    assert payload["demo_profile"]["demo"]["opening_text"].startswith("Welcome back, Ellis")
    assert send.call_args.kwargs["kind"] == "startup"
    send.reset_mock()
    activity = TurnActivity(user_turn_generation=1)
    assert not await greet_on_start(demo.runtime.session, demo.runtime.memory, activity, demo_profile=demo.profile)
    send.assert_not_awaited()


@pytest.mark.parametrize("cue,rule,title", [
    ("smiling", "happy", "A little music?"),
    ("tired_look", "tired", "A softer screen?"),
    ("sleepy_look", "tired", "A softer screen?"),
    ("confused_look", "unsure", "A hand with PM-17?"),
    ("furrowed_brow", "unsure", "A hand with PM-17?"),
])
async def test_live_cue_proposes_one_action_without_executing_it(demo, cue, rule, title):
    r = demo.runtime
    before = r.memory.list()
    r.camera.ingest(packet([cue]), now=100)
    await demo.loop.step()
    assert r.suggestion["title"] == title
    assert demo.loop.offered == {rule}
    assert r.suggestion["action"] == "offer_task_help"
    assert "{workspace}" not in r.suggestion["task"]
    assert r.memory.list() == before
    r.worker.perform.assert_not_awaited()
    r.session.send_message.assert_not_awaited()


@pytest.mark.parametrize("blocked", ["focus", "user", "response", "audio", "computer", "recent_user",
                                   "warmup", "idle", "neutral", "face_lost", "camera_off", "expired"])
async def test_ineligible_context_cannot_propose_or_speak(demo, blocked):
    r = demo.runtime
    r.camera.ingest(packet(["smiling"]), now=100)
    if blocked == "focus":
        r.focus = True
    elif blocked in {"user", "response", "audio", "computer", "recent_user"}:
        key = {"user": "user_speaking", "response": "response_active", "audio": "audio_playing",
               "computer": "computer_busy", "recent_user": "last_user_activity"}[blocked]
        r.context = lambda: TurnContext(**{key: 99 if blocked == "recent_user" else True})
    elif blocked == "warmup":
        r.connected_at = 99
    elif blocked == "idle":
        r.status = "idle"
    elif blocked in {"neutral", "face_lost"}:
        r.camera.ingest(packet([], 1, usable=blocked != "face_lost"), now=100.1)
        demo.now[0] = 100.1
    elif blocked == "camera_off":
        r.camera.clear()
    elif blocked == "expired":
        demo.now[0] = 102
    await demo.loop.step()
    assert r.suggestion is None
    r.session.model.send_context_response.assert_not_awaited()


async def test_pending_offer_is_not_replaced_and_rule_does_not_repeat_after_dismissal(demo):
    r = demo.runtime
    r.camera.ingest(packet(["smiling"]), now=100)
    await demo.loop.step()
    first = r.suggestion
    demo.now[0] = 107
    r.camera.ingest(packet(["tired_look"], 1), now=107)
    await demo.loop.step()
    assert r.suggestion is first
    r.suggestion = None  # Dismiss.
    r.camera.ingest(packet(["smiling"], 2), now=107.1)
    await demo.loop.step()
    assert r.suggestion is None
    assert r.session.model.send_context_response.await_count == 1


async def test_demo_cooldown_allows_three_distinct_offers_inside_a_minute(demo):
    r = demo.runtime
    for index, cue in enumerate(["smiling", "tired_look", "furrowed_brow"]):
        demo.now[0] = 100 + index * 7
        r.camera.ingest(packet([cue], index), now=demo.now[0])
        await demo.loop.step()
        assert r.suggestion is not None
        r.suggestion = None
        await demo.loop.step()
        assert r.suggestion is None
    assert demo.loop.offered == {"happy", "tired", "unsure"}
    assert r.session.model.send_context_response.await_count == 3


async def test_expired_offer_can_be_followed_by_a_different_fresh_cue(demo):
    r = demo.runtime
    r.camera.ingest(packet(["smiling"]), now=100)
    await demo.loop.step()
    demo.now[0] = 113
    r.camera.ingest(packet(["tired_look"], 1), now=113)
    await demo.loop.step()
    assert r.suggestion["title"] == "A softer screen?"


async def test_fresh_held_cue_can_offer_after_greeting_outlasts_brief_episode(demo):
    r = demo.runtime
    r.camera.ingest(packet(["smiling"]), now=94)
    r.camera.ingest(packet(["smiling"], 1), now=100)
    assert r.hub.snapshot()["camera"]["payload"]["episode"] is None
    await demo.loop.step()
    assert r.suggestion["title"] == "A little music?"


class Socket:
    def __init__(self, after_context=lambda: None):
        self.messages, self.after_context = [], after_context

    async def send(self, text):
        data = json.loads(text)
        self.messages.append(data)
        if data["type"] == "conversation.item.create":
            self.after_context()


async def test_real_transport_disables_tools_on_demo_offer(demo):
    r = demo.runtime
    model = ProactiveRealtimeModel()
    socket = Socket()
    model._websocket = socket
    r.session.model = model
    r.camera.ingest(packet(["smiling"]), now=100)
    await demo.loop.step()
    response = socket.messages[-1]["response"]
    assert response["tools"] == [] and response["tool_choice"] == "none"
    assert response["metadata"]["kind"] == "demo_suggestion"
    assert r.suggestion is not None
    r.worker.perform.assert_not_awaited()


@pytest.mark.parametrize("change", ["user_turn", "neutral", "focus", "shutdown", "computer_generation"])
async def test_late_cue_cannot_speak_or_create_a_card_at_socket_commit(demo, change):
    r = demo.runtime
    def interrupt():
        if change == "user_turn":
            r.activity.confirmed_speech()
        elif change == "neutral":
            r.camera.ingest(packet([], 1), now=100.1)
        elif change == "focus":
            r.focus = True
        elif change == "shutdown":
            r.status = "stopping"
        else:
            r.context = lambda: TurnContext(computer_generation=1)
    model = ProactiveRealtimeModel()
    socket = Socket(interrupt)
    model._websocket = socket
    r.session.model = model
    r.camera.ingest(packet(["smiling"]), now=100)
    await demo.loop.step()
    assert not any(m["type"] == "response.create" for m in socket.messages)
    assert not await model._response_create_sequencer.has_pending_response_create()
    assert r.suggestion is None


async def test_busy_transport_retries_while_cue_is_fresh(demo):
    r = demo.runtime
    send = r.session.model.send_context_response
    send.side_effect = [False, True]
    r.camera.ingest(packet(["smiling"]), now=100)
    await demo.loop.step()
    assert r.suggestion is None and demo.loop.offered == set()
    await demo.loop.step()
    assert r.suggestion is not None and demo.loop.offered == {"happy"}


def test_demo_autostart_is_explicit_and_missing_key_keeps_ui_available(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_demo_app(root=tmp_path / "run")) as client:
        boot = client.get("/api/bootstrap").json()
        assert not boot["api_configured"]
        assert boot["state"]["status"] == "error"
        assert "Add OPENAI_API_KEY" in boot["state"]["error"]
        assert boot["state"]["memories"]


def test_demo_autostart_starts_voice_once_on_launch(tmp_path, monkeypatch):
    start = AsyncMock()
    monkeypatch.setattr(AppRuntime, "start", start)
    with TestClient(create_demo_app(root=tmp_path / "run")) as client:
        client.get("/api/bootstrap")
        client.get("/api/bootstrap")
        start.assert_awaited_once_with()
