"""Keep unconfirmed VAD events from interrupting local SDK playback."""

from agents.realtime.model_events import RealtimeModelRawServerEvent
from agents.realtime.openai_realtime import OpenAIRealtimeWebSocketModel


class SpeechConfirmedRealtimeModel(OpenAIRealtimeWebSocketModel):
    """Adapter for the pinned openai-agents==0.24.0 VAD handler.

    The SDK normally interrupts locally on speech_started even when the server
    has interrupt_response=False. SpeechGate owns interruption after confirmed
    transcription; retain the raw event for provisional conversation timing.
    """

    def __init__(self, *, confirm_speech=True):
        super().__init__()
        self.confirm_speech = confirm_speech

    async def _handle_ws_event(self, event):
        if self.confirm_speech and event.get("type") == "input_audio_buffer.speech_started":
            await self._emit_event(RealtimeModelRawServerEvent(data=event))
            return
        await super()._handle_ws_event(event)
