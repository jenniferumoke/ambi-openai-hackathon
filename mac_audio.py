"""Full-duplex macOS audio for the Realtime session in ``main.py``.

One AVAudioEngine handles both capture and playback so macOS voice processing
can cancel speaker echo. Native callbacks pass microphone chunks to asyncio;
playback completion updates the SDK tracker used when the user interrupts.
"""

from __future__ import annotations

import asyncio
import array
import math
import platform
import threading
from time import monotonic

from agents.realtime.model import RealtimePlaybackTracker

from audio_io import SAMPLE_RATE

# Track playback at 100 ms granularity so Realtime can truncate at the point heard.
PLAYBACK_FRAMES = 2400
SPEECH_HOLD_SECONDS = 0.4


class MacVoiceAudioIO:
    """Run microphone and speaker through one voice-processing audio engine."""

    def __init__(self, input_device=None, output_device=None, *, echo_gate_rms=250):
        if platform.system() != "Darwin":
            raise RuntimeError("Echo-cancelled audio requires macOS; use --push-to-talk on other systems.")
        if input_device is not None or output_device is not None:
            raise ValueError(
                "Echo-cancelled audio uses the macOS default input and output devices. "
                "Choose them in System Settings > Sound, or use --push-to-talk with device IDs."
            )
        self.microphone = asyncio.Queue(maxsize=100)
        self.tracker = RealtimePlaybackTracker()
        self.echo_gate_rms = echo_gate_rms
        self._closed = True
        self._generation = 0
        self._next_token = 0
        self._pending = {}
        self._generating = set()
        self._state_lock = threading.Lock()
        self._speech_until = 0.0
        self._previous_audio = None
        self._previous_loud = False
        self._engine = None
        self._player = None
        self._input = None
        self._tap_installed = False

    @staticmethod
    def _make_converter(av, input_format, pcm_format):
        """Convert the native input route to the Realtime API's mono PCM format."""
        converter = av.AVAudioConverter.alloc().initFromFormat_toFormat_(input_format, pcm_format)
        if converter is None:
            raise RuntimeError("Could not convert the microphone format to 24 kHz mono audio.")
        # Some macOS voice-processing routes expose multiple identical processed
        # channels without a usable channel layout. In that case AVAudioConverter's
        # default mono map can be -1 (silence), so select the first input explicitly.
        converter.setChannelMap_([0])
        return converter

    def __enter__(self):
        """Start the shared input/output engine and enable voice processing."""
        import AVFoundation as av

        self._av = av
        self._loop = asyncio.get_running_loop()
        self._closed = False
        try:
            self._engine = av.AVAudioEngine.alloc().init()
            self._input = self._engine.inputNode()
            enabled, error = self._input.setVoiceProcessingEnabled_error_(True, None)
            if not enabled:
                raise RuntimeError(f"Could not enable macOS voice processing: {error}")
            if not self._input.isVoiceProcessingEnabled() or not self._engine.outputNode().isVoiceProcessingEnabled():
                raise RuntimeError("macOS did not enable voice processing for both audio directions.")
            self._input_format = self._input.outputFormatForBus_(0)
            self._pcm_format = av.AVAudioFormat.alloc().initWithCommonFormat_sampleRate_channels_interleaved_(
                av.AVAudioPCMFormatInt16, SAMPLE_RATE, 1, False,
            )
            self._converter = self._make_converter(av, self._input_format, self._pcm_format)
            self._player = av.AVAudioPlayerNode.alloc().init()
            self._engine.attachNode_(self._player)
            self._engine.connect_to_format_(self._player, self._engine.mainMixerNode(), self._pcm_format)
            self._input.installTapOnBus_bufferSize_format_block_(0, 1024, self._input_format, self._capture)
            self._tap_installed = True
            self._engine.prepare()
            started, error = self._engine.startAndReturnError_(None)
            if not started:
                raise RuntimeError(f"Could not start macOS voice audio: {error}")
            self._player.play()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        """Stop native callbacks and playback before releasing the engine."""
        self._closed = True
        self._generation += 1
        if self._tap_installed:
            self._input.removeTapOnBus_(0)
            self._tap_installed = False
        if self._player is not None:
            self._player.stop()
        if self._engine is not None:
            self._engine.stop()
        self._pending.clear()
        self.tracker.on_interrupted()

    def _capture(self, input_buffer, _time):
        """Convert one native microphone buffer and queue it on the event loop."""
        if self._closed:
            return
        try:
            frames = input_buffer.frameLength()
            capacity = math.ceil(frames * SAMPLE_RATE / self._input_format.sampleRate()) + 128
            converted = self._av.AVAudioPCMBuffer.alloc().initWithPCMFormat_frameCapacity_(
                self._pcm_format, capacity,
            )
            supplied = False

            def provide_input(_packets, _status):
                nonlocal supplied
                if not supplied:
                    supplied = True
                    return input_buffer, self._av.AVAudioConverterInputStatus_HaveData
                return None, self._av.AVAudioConverterInputStatus_NoDataNow

            status, error = self._converter.convertToBuffer_error_withInputFromBlock_(
                converted, None, provide_input,
            )
            if error or status == self._av.AVAudioConverterOutputStatus_Error:
                raise RuntimeError(f"Microphone conversion failed: {error}")
            size = converted.frameLength() * 2
            if size:
                data = bytes(converted.audioBufferList()[0].mData[:size])
                data = self._suppress_residual_echo(data)
                self._post_to_loop(self._enqueue, data)
        except Exception as exc:
            self._post_to_loop(self._enqueue, exc)

    def _post_to_loop(self, callback, *args):
        if self._closed:
            return
        try:
            self._loop.call_soon_threadsafe(callback, *args)
        except RuntimeError:
            # A native callback may finish as the application is shutting down.
            pass

    def _suppress_residual_echo(self, data):
        """Reject isolated noise while retaining the start of sustained speech.

        Capture arrives in roughly 100 ms blocks. Delay one block so that the
        first loud block can be sent once the next one confirms speech, rather
        than clipping the start of a spoken interruption.
        """
        if not self.echo_gate_rms:
            return data
        now = monotonic()
        samples = array.array("h")
        samples.frombytes(data)
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) if samples else 0
        loud = rms >= self.echo_gate_rms
        if loud and (self._previous_loud or now < self._speech_until):
            self._speech_until = now + SPEECH_HOLD_SECONDS
        previous = self._previous_audio
        self._previous_audio = data
        self._previous_loud = loud
        if previous is None:
            return bytes(len(data))
        return previous if now < self._speech_until else bytes(len(previous))

    def _enqueue(self, data):
        if self._closed:
            return
        if self.microphone.full():
            self.microphone.get_nowait()
            self.microphone.task_done()
        self.microphone.put_nowait(data)

    def play(self, data: bytes, item_id: str, content_index: int):
        """Schedule generated audio without waiting for the speaker to drain."""
        if not data:
            return
        if len(data) % 2:
            raise ValueError("Realtime output is not aligned to 16-bit PCM samples.")
        with self._state_lock:
            self._generating.add((item_id, content_index))
        if self.tracker.get_state()["current_item_id"] is None:
            # Even if interrupted before the first buffer plays, truncate at zero.
            self.tracker.on_play_ms(item_id, content_index, 0)
        for offset in range(0, len(data), PLAYBACK_FRAMES * 2):
            chunk = data[offset:offset + PLAYBACK_FRAMES * 2]
            self._schedule_chunk(chunk, item_id, content_index)

    def _schedule_chunk(self, chunk, item_id, content_index):
        """Keep each native buffer alive until its playback callback completes."""
        buffer = self._av.AVAudioPCMBuffer.alloc().initWithPCMFormat_frameCapacity_(
            self._pcm_format, len(chunk) // 2,
        )
        buffer.setFrameLength_(len(chunk) // 2)
        buffer.mutableAudioBufferList()[0].mData[:len(chunk)] = chunk
        token = self._next_token
        self._next_token += 1
        generation = self._generation

        def on_played(_kind, *, token=token, generation=generation,
                      item_id=item_id, content_index=content_index, size=len(chunk)):
            self._post_to_loop(
                self._played, token, generation, item_id, content_index, size,
            )

        with self._state_lock:
            self._pending[token] = (buffer, on_played)
        try:
            self._player.scheduleBuffer_completionCallbackType_completionHandler_(
                buffer, self._av.AVAudioPlayerNodeCompletionDataPlayedBack, on_played,
            )
        except BaseException:
            with self._state_lock:
                self._pending.pop(token, None)
            raise

    def _played(self, token, generation, item_id, content_index, size):
        """Record only audio heard from the current playback generation."""
        with self._state_lock:
            self._pending.pop(token, None)
        if not self._closed and generation == self._generation:
            self.tracker.on_play_ms(item_id, content_index, size / (SAMPLE_RATE * 2) * 1000)

    def clear(self):
        """Stop queued audio immediately after a user interruption."""
        self._generation += 1
        with self._state_lock:
            self._pending.clear()
            self._generating.clear()
        self.tracker.on_interrupted()
        if self._player is not None and not self._closed:
            self._player.stop()
            self._player.play()

    def finish(self, item_id, content_index):
        """Mark generation complete while the player drains scheduled audio."""
        with self._state_lock:
            self._generating.discard((item_id, content_index))

    def response_started(self):
        """Match the audio backend interface; native capture remains open."""
        pass

    def response_finished(self):
        """Match the audio backend interface; playback completion is tracked separately."""
        pass

    def playback_active(self):
        """Read-only status for observation timing, including undrained buffers."""
        with self._state_lock:
            return bool(self._pending or self._generating)

    async def send_microphone(self, session):
        """Forward converted audio to Realtime until the session is stopped."""
        # Ignore audio captured before the session was connected.
        while not self.microphone.empty():
            self.microphone.get_nowait()
            self.microphone.task_done()
        while True:
            data = await self.microphone.get()
            try:
                if isinstance(data, Exception):
                    raise RuntimeError("macOS microphone capture failed") from data
                await session.send_audio(data)
            finally:
                self.microphone.task_done()
