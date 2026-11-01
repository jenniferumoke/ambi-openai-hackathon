"""A read-only rehearsal of proactive turn timing. This module cannot speak."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic


@dataclass
class TurnActivity:
    user_speaking: bool = False
    response_active: bool = False
    user_turn_generation: int = 0
    last_user_activity: float = 0
    confirmed_input_only: bool = False

    def speech_started(self):
        self.user_speaking = True
        self.confirmed_speech()

    def confirmed_speech(self):
        self.user_turn_generation += 1
        self.last_user_activity = monotonic()

    def on_event(self, event):
        if event.type != "raw_model_event":
            return
        data = event.data
        if data.type == "turn_started":
            self.response_active = True
        elif data.type == "turn_ended":
            self.response_active = False
        elif data.type == "raw_server_event":
            raw = data.data
            kind = raw.get("type") if isinstance(raw, dict) else getattr(raw, "type", None)
            if kind == "input_audio_buffer.speech_started":
                if not self.confirmed_input_only:
                    self.speech_started()
            elif kind == "input_audio_buffer.speech_stopped":
                if not self.confirmed_input_only:
                    self.user_speaking = False
                    self.response_active = True
            elif kind == "response.created":
                self.response_active = True
            elif kind == "response.done":
                self.response_active = False


@dataclass(frozen=True)
class TurnContext:
    user_speaking: bool = False
    response_active: bool = False
    audio_playing: bool = False
    computer_busy: bool = False
    computer_generation: int = 0
    user_turn_generation: int = 0
    last_user_activity: float = 0


@dataclass(frozen=True)
class ShadowDecision:
    action: str
    reason: str
    proposed_text: str | None = None


class ShadowController:
    """Propose at most one check-in per expression episode, with a cooldown.

    Receives plain state only: no Realtime session, tools, or desktop handles.
    A proposal is a terminal event, never a request to the voice agent.
    """

    SUGGESTIONS = {
        "confused": "Would a walkthrough help?",
        "angry": "Would you like some help with the task, or a moment to yourself?",
        "sad": "Would you like to talk, or would some help be useful?",
    }

    def __init__(self, cooldown=60):
        self.cooldown = cooldown
        self.last_proposal = float("-inf")
        self.handled_episode = None

    def evaluate(self, state, now, context=TurnContext()):
        if state is None or now >= state.expires_at:
            return ShadowDecision("ignore", "no_fresh_stable_expression")
        text = self.SUGGESTIONS.get(state.label)
        if text is None:
            return ShadowDecision("ignore", "no_check_in_needed")
        episode = (state.label, state.started_at)
        if episode == self.handled_episode:
            return ShadowDecision("ignore", "already_proposed_for_this_episode")
        if now - self.last_proposal < self.cooldown:
            return ShadowDecision("defer", "cooldown")
        for busy, reason in [
            (context.user_speaking, "user_speaking"),
            (context.response_active, "response_in_progress"),
            (context.audio_playing, "speaker_audio_playing"),
            (context.computer_busy, "computer_task_running"),
        ]:
            if busy:
                return ShadowDecision("defer", reason)
        self.last_proposal = now
        self.handled_episode = episode
        return ShadowDecision("would_check_in", "observation_only_no_speech", text)
