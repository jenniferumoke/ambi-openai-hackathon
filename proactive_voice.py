"""Offer task help from fresh combined observations in explicit proactive mode."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from time import monotonic

from expression_monitor import terminal_log


def _camera_context(snapshot, context, now):
    camera = snapshot["camera"] if snapshot["pair"]["aligned"] else {
        "status": "unavailable", "reason": snapshot["pair"]["reason"],
    }
    if camera["status"] == "available" and (now >= camera["expires_at"]
                                              or camera["observed_at"] < context.last_user_activity):
        return {"status": "unavailable", "reason": "camera_not_current"}
    return camera


def _supports_task_help(camera):
    if camera["status"] != "available":
        return False
    expression = camera["payload"]
    return (expression.get("stable_expression") in ("confused", "angry", "sad")
            or bool({"frowning", "furrowed_brow", "tense_expression"}.intersection(expression.get("cues", []))))


@dataclass(frozen=True)
class Notification:
    key: tuple
    observed_at: float
    expires_at: float
    text: str
    trigger: str
    camera_included: bool


@dataclass(frozen=True)
class OfferDecision:
    action: str
    reason: str
    notification: Notification | None = None


class NotificationPolicy:
    def __init__(self, *, cooldown=60, threshold=0.8, min_stuck_seconds=20, max_event_age=None):
        self.cooldown = cooldown
        self.threshold = threshold
        self.min_stuck_seconds = min_stuck_seconds
        self.max_event_age = max_event_age
        self.last_sent = float("-inf")
        self.last_key = None

    def evaluate(self, snapshot, context, now):
        computer = snapshot["computer"]
        if computer["status"] != "available":
            return OfferDecision("ignore", "computer_unavailable")
        data = computer["payload"]
        if data.get("computer_generation", 0) != context.computer_generation:
            return OfferDecision("ignore", "task_context_changed")
        if data.get("surface") != "user_task":
            return OfferDecision("ignore", "not_user_task")
        if not data.get("evidence") or data.get("confidence", 0) < self.threshold:
            return OfferDecision("ignore", "insufficient_task_evidence")
        if (now >= computer["expires_at"] or (self.max_event_age is not None
                                             and now - computer["observed_at"] > self.max_event_age)):
            return OfferDecision("ignore", "task_observation_expired")
        if computer["observed_at"] < context.last_user_activity:
            return OfferDecision("ignore", "observation_before_user_turn")

        camera = _camera_context(snapshot, context, now)

        progress = data.get("progress")
        history_supported = (data.get("history_span_seconds", 0) >= self.min_stuck_seconds
                             and data.get("recent_observation_count", 0) >= 2)
        if data.get("noteworthy") and data.get("notification") and progress in ("possible_stuck", "blocked", "completed"):
            if progress == "possible_stuck" and not history_supported:
                return OfferDecision("ignore", "insufficient_task_history")
            trigger = "noteworthy_task"
        else:
            # Camera data here has already passed the camera sidecar's unchanged
            # threshold/persistence checks. Never derive a cue from raw scores.
            # It may support a tentative offer about a concrete task obstacle;
            # it cannot establish that the user feels an emotion or is stuck.
            if progress not in ("in_progress", "possible_stuck", "blocked") or not data.get("possible_blocker"):
                self.last_key = None
                return OfferDecision("ignore", "no_concrete_task_obstacle")
            if not history_supported:
                return OfferDecision("ignore", "insufficient_task_history")
            if camera["status"] != "available":
                return OfferDecision("ignore", "no_aligned_camera_support")
            if not _supports_task_help(camera):
                return OfferDecision("ignore", "no_supporting_camera_cue")
            trigger = "combined_task_difficulty"

        # One offer per continuing task difficulty, even if an observer later
        # upgrades in_progress to possible_stuck or blocked.
        opportunity = "task_completed" if progress == "completed" else "task_help"
        key = (data.get("context_id"), opportunity, context.computer_generation)
        if key == self.last_key:
            return OfferDecision("ignore", "already_offered_for_this_task")
        if now - self.last_sent < self.cooldown:
            return OfferDecision("defer", "cooldown")
        for busy, reason in (
            (context.user_speaking, "user_speaking"),
            (context.response_active, "response_in_progress"),
            (context.audio_playing, "speaker_audio_playing"),
            (context.computer_busy, "computer_task_running"),
            (now - context.last_user_activity < 2, "recent_user_activity"),
        ):
            if busy:
                return OfferDecision("defer", reason)

        text = json.dumps({"event": "proactive_offer_opportunity", "trigger": trigger, "computer": computer,
                           "camera": camera, "pair": snapshot["pair"]}, ensure_ascii=True)
        expires_at = computer["expires_at"]
        if camera["status"] == "available":
            expires_at = min(expires_at, camera["expires_at"])
        notification = Notification(key, computer["observed_at"], expires_at, text, trigger, camera["status"] == "available")
        return OfferDecision("offer", trigger, notification)

    def candidate(self, snapshot, context, now):
        return self.evaluate(snapshot, context, now).notification

    def sent(self, notification, now):
        self.last_key = notification.key
        self.last_sent = now


class ProactiveVoiceBridge:
    def __init__(self, session, hub, context, stop_event, *, policy=None, log=terminal_log):
        self.session = session
        self.hub = hub
        self.context = context
        self.stop_event = stop_event
        self.policy = policy or NotificationPolicy()
        self.log = log
        self._context_expires_at = float("inf")
        self._context_key = None
        self._context_trigger = None
        self._last_decision = None

    async def _forget_expired_context(self):
        if self._context_key is None:
            return
        snapshot = self.hub.snapshot()
        current = snapshot["computer"]
        data = current.get("payload", {})
        context = self.context()
        opportunity = "task_completed" if data.get("progress") == "completed" else "task_help"
        matches = (current["status"] == "available" and self._context_key is not None
                   and data.get("computer_generation", 0) == context.computer_generation
                   and data.get("context_id") == self._context_key[0] and opportunity == self._context_key[1])
        if self._context_trigger == "combined_task_difficulty":
            matches = (matches and bool(data.get("possible_blocker"))
                       and _supports_task_help(_camera_context(snapshot, context, monotonic())))
        else:
            matches = matches and data.get("noteworthy")
        if monotonic() >= self._context_expires_at or not matches:
            clear = getattr(self.session.model, "clear_proactive_context", None)
            if clear is not None:
                async with asyncio.timeout(0.5):
                    await clear()
            self._context_expires_at = float("inf")
            self._context_key = None
            self._context_trigger = None

    async def run(self):
        send = getattr(self.session.model, "send_proactive_response", None)
        if send is None:
            self.log("proactive_disabled", reason="Transport does not support guarded proactive turns.")
            return
        self.log("proactive_started", cooldown_seconds=self.policy.cooldown,
                 triggers=["noteworthy_task", "combined_task_difficulty"], desktop_actions="require_user_request")
        while not self.stop_event.is_set():
            try:
                await self._forget_expired_context()
            except Exception:
                pass
            context = self.context()
            snapshot = self.hub.snapshot(context=context)
            decision = self.policy.evaluate(snapshot, context, monotonic())
            decision_key = (decision.action, decision.reason)
            if decision_key != self._last_decision:
                self.log("proactive_decision", action=decision.action, reason=decision.reason,
                         camera_aligned=snapshot["pair"]["aligned"],
                         computer_progress=snapshot["computer"].get("payload", {}).get("progress"))
                self._last_decision = decision_key
            notification = decision.notification
            if notification is not None:
                def still_relevant():
                    if self.stop_event.is_set():
                        return False
                    current = self.context()
                    if (current.user_turn_generation != context.user_turn_generation
                            or current.computer_generation != context.computer_generation):
                        return False
                    candidate = self.policy.candidate(self.hub.snapshot(context=current), current, monotonic())
                    # Include camera content/freshness in the final check, not
                    # just the computer timestamp. A newly neutral/expired cue
                    # must invalidate the previously prepared combined offer.
                    return candidate is not None and candidate.key == notification.key and candidate.text == notification.text

                try:
                    async with asyncio.timeout(5):
                        committed = await send(notification.text, still_relevant)
                    if committed:
                        self.policy.sent(notification, monotonic())
                        self._context_expires_at = notification.expires_at
                        self._context_key = notification.key
                        self._context_trigger = notification.trigger
                        self.log("observation_sent_to_voice", trigger=notification.trigger,
                                 progress=snapshot["computer"]["payload"]["progress"],
                                 camera_included=notification.camera_included, desktop_actions="disabled_for_this_turn")
                except Exception as exc:
                    self.log("proactive_unavailable", error=type(exc).__name__)
                    await asyncio.sleep(2)
            await asyncio.sleep(0.25)
