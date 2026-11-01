"""Confirm microphone turns before requesting speech or invalidating context."""
from __future__ import annotations

import math
import re
from collections import deque
from time import monotonic

from agents.realtime import RealtimeModelSendRawMessage
from expression_monitor import terminal_log


class SpeechGate:
    def __init__(self, activity, *, log=terminal_log):
        self.activity = activity
        self.log = log
        self.pending = {}
        self.handled = deque(maxlen=256)
        self.reply_pending = False

    def _sync(self):
        self.activity.user_speaking = bool(self.pending)

    @staticmethod
    def rejection(raw):
        text = raw.get("transcript", "").strip()
        if not any(c.isalpha() for c in text):
            return "no_speech"
        if re.fullmatch(r"\s*[\[(].*[\])]\s*", text, re.S):
            return "non_speech_annotation"
        if text.lower().strip(" .!") in {"silence", "inaudible", "unintelligible", "keyboard typing", "typing", "clicking", "background noise", "music", "um", "uh", "erm"}:
            return "non_speech_annotation"
        scores = [entry.get("logprob") for entry in (raw.get("logprobs") or [])]
        if scores and (any(not isinstance(p, (int, float)) or not math.isfinite(p) for p in scores)
                       or sum(scores) / len(scores) < -1):
            return "low_transcription_confidence"
        return None

    async def on_event(self, raw, session, audio):
        kind, item = raw.get("type"), raw.get("item_id")
        if kind in ("input_audio_buffer.speech_started", "input_audio_buffer.speech_stopped") and not item:
            return
        if kind == "input_audio_buffer.speech_started":
            self.pending[item] = float("inf")
            self._sync()
        elif kind == "input_audio_buffer.speech_stopped":
            self.pending[item] = monotonic()
            self._sync()
        elif kind in ("conversation.item.input_audio_transcription.completed", "conversation.item.input_audio_transcription.failed"):
            if not item or item in self.handled:
                return
            self.handled.append(item)
            self.pending.pop(item, None)
            self._sync()
            reason = "transcription_failed" if kind.endswith("failed") else self.rejection(raw)
            if reason:
                # Remove rejected audio so later turns cannot reinterpret it.
                await session.model.send_event(RealtimeModelSendRawMessage(message={
                    "type": "conversation.item.delete", "other_data": {"item_id": item},
                }))
                self.log("voice_input_rejected", reason=reason)
                await self._respond_if_ready(session, audio)
                return
            self.activity.confirmed_speech()
            self.activity.user_speaking = bool(self.pending)
            self.log("voice_input_accepted", characters=len(raw["transcript"]),
                     confidence_available=bool(raw.get("logprobs")))
            self.reply_pending = True
            await self._respond_if_ready(session, audio)

    async def _respond_if_ready(self, session, audio):
        if self.reply_pending and not self.pending:
            self.reply_pending = False
            # Real speech can interrupt a reply; keyboard noise cannot. Wait
            # for any subsequent utterance already being transcribed as well.
            await session.interrupt()
            audio.clear()
            self.activity.response_active = True
            await session.model.send_event(RealtimeModelSendRawMessage(message={"type": "response.create"}))

    async def maintain(self, session, audio):
        import asyncio
        while True:
            for item, at in list(self.pending.items()):
                if monotonic() - at >= 12:
                    await self.on_event({"type": "conversation.item.input_audio_transcription.failed",
                                         "item_id": item}, session, audio)
            await asyncio.sleep(0.25)
