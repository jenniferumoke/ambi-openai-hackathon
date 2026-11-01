"""Confirmed speech and per-reply delivery on the pinned Realtime transport."""

from dataclasses import replace

from agents.realtime.model_events import RealtimeModelRawServerEvent
from agents.realtime.openai_realtime import OpenAIRealtimeWebSocketModel
from openai.types.realtime import ResponseCreateEvent

from voice_style import STYLES, delivery_instructions, soften_pcm16


class SpeechConfirmedRealtimeModel(OpenAIRealtimeWebSocketModel):
    """Adapter for the pinned openai-agents==0.24.0 VAD handler.

    The SDK normally interrupts locally on speech_started even when the server
    has interrupt_response=False. SpeechGate owns interruption after confirmed
    transcription; retain the raw event for provisional conversation timing.
    """

    def __init__(self, *, confirm_speech=True):
        super().__init__()
        self.confirm_speech = confirm_speech
        self._voice_style = None
        self._voice_base_instructions = ""
        self._voice_response_styles = {}

    def configure_voice_style(self, select_style, instructions):
        self._voice_style = select_style
        self._voice_base_instructions = instructions

    def _with_voice_style(self, event):
        if self._voice_style is None:
            return event
        if event.type == "session.update":
            instructions = getattr(event.session, "instructions", None)
            if instructions is not None:
                self._voice_base_instructions = instructions
        if event.type != "response.create":
            return event
        # This runs after the response sequencer has granted a send slot. A cue
        # can expire or change while a typed/spoken/tool/proactive turn is queued.
        style = self._voice_style()
        response = event.response.model_dump(exclude_unset=True) if event.response else {}
        instructions = response.get("instructions")
        if instructions is None:
            instructions = self._voice_base_instructions
        response["instructions"] = instructions + delivery_instructions(style)
        response["metadata"] = {**(response.get("metadata") or {}), "ambi_voice_style": style.name}
        return ResponseCreateEvent.model_validate({**event.model_dump(exclude_unset=True), "response": response})

    async def _send_raw_message(self, event):
        await super()._send_raw_message(self._with_voice_style(event))

    async def _send_raw_message_if(self, event, send_if):
        if not send_if():
            return False
        return await super()._send_raw_message_if(self._with_voice_style(event), send_if)

    async def _emit_event(self, event):
        if event.type == "audio":
            style = self._voice_response_styles.get(event.response_id, STYLES["balanced"])
            # Both audio backends receive the same scaled samples. Playback
            # timing, interruption offsets, and the microphone remain unchanged.
            event = replace(event, data=soften_pcm16(event.data, style.gain))
        await super()._emit_event(event)

    def _reset_connection_state(self):
        super()._reset_connection_state()
        self._voice_response_styles.clear()

    async def _handle_ws_event(self, event):
        if event.get("type") == "response.created" and self._voice_style is not None:
            response = event.get("response", {})
            response_id = response.get("id")
            if response_id:
                name = (response.get("metadata") or {}).get("ambi_voice_style")
                self._voice_response_styles[response_id] = STYLES.get(name, STYLES["balanced"])
                # Defensive bound, including malformed/incomplete provider turns.
                if len(self._voice_response_styles) > 64:
                    self._voice_response_styles.pop(next(iter(self._voice_response_styles)))
        if self.confirm_speech and event.get("type") == "input_audio_buffer.speech_started":
            await self._emit_event(RealtimeModelRawServerEvent(data=event))
            return
        await super()._handle_ws_event(event)
        if event.get("type") == "response.done":
            self._voice_response_styles.pop(event.get("response", {}).get("id"), None)
