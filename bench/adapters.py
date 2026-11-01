"""Invoke real AMBI components with synthetic context and no sensor/action handles."""
from __future__ import annotations

import asyncio
import copy
import json
from time import monotonic
from types import SimpleNamespace

from ambient import AmbientClassifier, AmbientLoop, CuePacket, FastCamera
from app_runtime import AppRuntime
from observation_hub import ObservationHub
from proactive_controller import TurnContext
from proactive_voice import NotificationPolicy
from voice_input import SpeechGate


BASE_COMPUTER = {
    "context_id": "synthetic-form-a", "surface": "user_task", "noteworthy": True,
    "progress": "blocked", "notification": "The event form still cannot be submitted; offer to help.",
    "evidence": ["Location-required validation error remains after three attempts."],
    "confidence": .95, "history_span_seconds": 25, "recent_observation_count": 4,
    "possible_blocker": "A required location field prevents submission.",
    "task_goal": "Submit the community event form", "computer_generation": 0,
}
BASE_CAMERA = {"stable_expression": None, "cues": ["furrowed_brow"],
               "episode": "synthetic-episode-a", "interpretation": "visible_cues_only"}


class FixtureMemory:
    """The classifier's memory protocol, backed only by the current fixture."""
    def __init__(self, rows=()):
        self.rows = copy.deepcopy(list(rows))

    def list(self, **_):
        return copy.deepcopy(self.rows)

    def brief(self, max_chars=3500, **_):
        result = []
        for row in self.rows:
            if len(json.dumps(result + [row])) <= max_chars:
                result.append(row)
        return json.dumps(result)


def fixture_context(spec, *, default_now=100):
    """Expand fixture defaults, then use the production hub's freshness logic."""
    now = spec.get("now", default_now + 1)
    observed = spec.get("observed_at", default_now)
    expires = spec.get("expires_at", observed + 20)
    hub = ObservationHub(mode="benchmark")
    for source, defaults, ttl in (("computer", BASE_COMPUTER, 20), ("camera", BASE_CAMERA, 10)):
        changes = spec.get(source, {})
        if changes is None:
            hub.unavailable(source, "synthetic_unavailable", now=observed)
            continue
        payload = {**copy.deepcopy(defaults), **copy.deepcopy(changes)}
        at = payload.pop("observed_at", observed)
        expiry = payload.pop("expires_at", expires if source == "computer" else at + ttl)
        hub.publish(source, observed_at=at, expires_at=expiry, payload=payload, now=at)
    context = TurnContext(**spec.get("runtime", {}))
    return hub, context, now


async def policy_adapter(spec):
    policy = NotificationPolicy()
    predictions, reasons = [], []
    for step in spec["steps"]:
        hub, context, now = fixture_context(step)
        decision = policy.evaluate(hub.snapshot(now=now, context=context), context, now)
        predictions.append(decision.action)
        reasons.append(decision.reason)
        if decision.notification is not None:
            policy.sent(decision.notification, now)
    return predictions, {"reasons": reasons, "implementation": "proactive_voice.NotificationPolicy"}


async def cues_adapter(spec):
    hub = ObservationHub()
    camera = FastCamera(hub)
    predictions, accepted = [], []
    for index, step in enumerate(spec["steps"]):
        at = step["at"]
        if not step.get("snapshot_only"):
            packet = CuePacket(stream_id=step.get("stream_id", "synthetic-stream"),
                               sequence=step.get("sequence", index), usable=step.get("usable", True),
                               cues=step.get("cues", []), scores={}, age_ms=step.get("age_ms", 0),
                               inference_ms=12, detection_ms=134)
            accepted.append(camera.ingest(packet, now=at))
        record = hub.snapshot(now=at)["camera"]
        predictions.append("unavailable" if record["status"] != "available" else
                           "retained" if record["payload"]["cues"] else "none")
    return predictions, {"accepted_packets": accepted, "implementation": "ambient.FastCamera + ObservationHub"}


async def speech_adapter(spec):
    reason = SpeechGate.rejection(spec)
    return ["reject" if reason else "accept"], {"reason": reason, "implementation": "voice_input.SpeechGate"}


async def scheduler_adapter(spec):
    """Real loop + real quiet gate. Scripted classifier, no voice or worker."""
    memory = FixtureMemory([] if spec.get("no_goal") else [
        {"id": "synthetic-task", "kind": "task", "status": "active", "title": "Prepare a community invitation"}
    ])
    runtime = AppRuntime(memory)
    runtime.status = "connected"
    runtime.connected_at = monotonic() - 10
    runtime.focus = spec.get("focus", False)
    state = dict(spec.get("runtime", {}))
    runtime.context = lambda: TurnContext(**state)
    runtime.camera.ingest(CuePacket(stream_id="bench", sequence=0, usable=True,
                                   cues=["furrowed_brow"], age_ms=0, inference_ms=12, detection_ms=134))
    calls = 0
    delivered = []

    if spec.get("transport_during"):
        async def send(_text, still_relevant):
            # Simulate a state change while a real transport would wait for its slot.
            if spec["transport_during"] == "generation":
                state["computer_generation"] = state.get("computer_generation", 0) + 1
            delivered.append(still_relevant())
            return delivered[-1]
        runtime.session = SimpleNamespace(model=SimpleNamespace(send_proactive_response=send))

    async def decide(*_):
        nonlocal calls
        calls += 1
        change = spec.get("during")
        if change == "user_turn":
            runtime.activity.confirmed_speech()
        elif change == "generation":
            state["computer_generation"] = 1
        elif change == "focus":
            runtime.focus = True
        elif change == "camera_off":
            runtime.camera.clear()
        await asyncio.sleep(0)
        return spec.get("prediction", "offer_task_help")

    loop = AmbientLoop(runtime, SimpleNamespace(decide=decide))
    if spec.get("cooldown"):
        loop.last_offer = monotonic()
    task = asyncio.create_task(loop.run())
    try:
        await asyncio.sleep(.34)  # Two real scheduler ticks; no accelerated product clock.
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    prediction = runtime.suggestion["action"] if runtime.suggestion else "none"
    if spec.get("transport_during") and not any(delivered):
        prediction = "none"
    return [prediction], {
        "classifier_calls": calls, "implementation": "ambient.AmbientLoop + AppRuntime.quiet",
        "model": "scripted; not an AI quality measurement", "desktop_actions": 0,
        "transport_committed": any(delivered),
    }


async def classifier_adapter(spec, client, model):
    hub, context, now = fixture_context(spec)
    prediction = await AmbientClassifier(client, model).decide(
        hub.snapshot(now=now, context=context), FixtureMemory(spec.get("memory", [])))
    return [prediction], {"implementation": "ambient.AmbientClassifier", "model": model}


OFFLINE_ADAPTERS = {"policy": policy_adapter, "cues": cues_adapter,
                    "speech": speech_adapter, "scheduler": scheduler_adapter}
