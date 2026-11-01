"""PortAudio backend used by the push-to-talk mode in ``main.py``.

PortAudio callbacks capture and play 24 kHz mono PCM16, while an asyncio queue
feeds microphone chunks to the Realtime session. This backend mutes the input
during playback by default; hands-free macOS audio lives in ``mac_audio.py``.
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from contextlib import ExitStack
from time import monotonic

import sounddevice as sd
from agents.realtime.model import RealtimePlaybackTracker

SAMPLE_RATE = 24_000
BLOCK_SIZE = 480  # 20 ms
ECHO_TAIL_SECONDS = 0.35


class AudioIO:
    """Bridge PortAudio callbacks and the Realtime session's async interface."""
    def __init__(self, input_device=None, output_device=None, *, allow_barge_in=False,
                 push_to_talk=False):
        self.input_device = input_device
        self.output_device = output_device
        self.allow_barge_in = allow_barge_in
        self.push_to_talk = push_to_talk
        self.microphone = asyncio.Queue(maxsize=100)
        self.tracker = RealtimePlaybackTracker()
        self._chunks = deque()
        self._generating = set()
        self._response_active = False
        self._mute_until = 0.0
        self._lock = threading.Lock()
        self._capture_lock = threading.Lock()
        self._recording = threading.Event()
        self._capture_generation = 0
        self.recorded_bytes = 0
        self._generation = 0
        self._closed = True
        self._stack = ExitStack()

    def __enter__(self):
        self._loop = asyncio.get_running_loop()
        self._closed = False
        try:
            self._stack.enter_context(sd.RawOutputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=BLOCK_SIZE,
                device=self.output_device, callback=self._output, latency="low",
            ))
            self._stack.enter_context(sd.RawInputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=BLOCK_SIZE,
                device=self.input_device, callback=self._input, latency="low",
            ))
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        self._closed = True
        self._stack.close()
        self.clear()

    def _input(self, data, frames, timing, status):
        """Move captured audio from the PortAudio thread to the event loop."""
        if not self._closed:
            with self._capture_lock:
                if self.push_to_talk and not self._recording.is_set():
                    return
                capture_generation = self._capture_generation if self.push_to_talk else None
            # Gate at capture time too: delayed callbacks must not enqueue speaker echo
            # after the reply has finished playing.
            chunk = bytes(data)
            if self._mute_microphone():
                chunk = bytes(len(chunk))
            self._loop.call_soon_threadsafe(self._enqueue, chunk, capture_generation)

    def _mute_microphone(self):
        """Keep speaker playback and its acoustic tail out of captured turns."""
        if self.allow_barge_in:
            return False
        with self._lock:
            return bool(
                self._response_active or self._generating or self._chunks
                or monotonic() < self._mute_until
            )

    def _enqueue(self, data, capture_generation=None):
        if self._closed:
            return
        if capture_generation is not None and capture_generation != self._capture_generation:
            return
        if self.microphone.full():
            self.microphone.get_nowait()
            self.microphone.task_done()
        self.microphone.put_nowait(data)

    def start_recording(self):
        """Start a fresh push-to-talk turn and invalidate older callbacks."""
        with self._capture_lock:
            self._capture_generation += 1
            self._recording.set()
        self.recorded_bytes = 0

    def stop_recording(self):
        """Stop capture and discard late callbacks from the completed turn."""
        with self._capture_lock:
            self._recording.clear()
            # Discard callbacks that were captured before stop but arrive afterward.
            self._capture_generation += 1

    def response_started(self):
        with self._lock:
            self._response_active = True

    def response_finished(self):
        with self._lock:
            self._response_active = False

    def playback_active(self):
        """Read-only status including device latency and the acoustic tail."""
        with self._lock:
            return bool(self._chunks or self._generating or monotonic() < self._mute_until)

    def play(self, data: bytes, item_id: str, content_index: int):
        """Queue generated speech for the output callback."""
        with self._lock:
            self._generating.add((item_id, content_index))
            self._chunks.append((data, item_id, content_index))

    def finish(self, item_id: str, content_index: int):
        # Generation can finish seconds before playback. Keep all buffered speech.
        with self._lock:
            self._generating.discard((item_id, content_index))

    def clear(self):
        """Drop queued audio and invalidate pending playback updates."""
        with self._lock:
            self._chunks.clear()
            self._generating.clear()
            self._generation += 1
        self.tracker.on_interrupted()

    def _played(self, generation, item_id, content_index, milliseconds):
        if generation == self._generation and not self._closed:
            self.tracker.on_play_ms(item_id, content_index, milliseconds)

    def _output(self, outdata, frames, timing, status):
        """Drain queued audio into a device buffer and track what was played."""
        output = bytearray(frames * 2)
        cursor = 0
        with self._lock:
            generation = self._generation
            while self._chunks and cursor < len(output):
                data, item_id, content_index = self._chunks.popleft()
                length = min(len(data), len(output) - cursor)
                output[cursor:cursor + length] = data[:length]
                cursor += length
                if length < len(data):
                    self._chunks.appendleft((data[length:], item_id, content_index))
                self._loop.call_soon_threadsafe(
                    self._played, generation, item_id, content_index,
                    length / (SAMPLE_RATE * 2) * 1000,
                )
            if cursor:
                # Include the device's queued playback, then let acoustic echo decay.
                device_delay = max(0.0, timing.outputBufferDacTime - timing.currentTime) if timing else 0.0
                self._mute_until = max(
                    self._mute_until,
                    monotonic() + device_delay + frames / SAMPLE_RATE + ECHO_TAIL_SECONDS,
                )
        outdata[:] = output

    async def send_microphone(self, session):
        """Forward queued input to Realtime and account for completed chunks."""
        while True:
            chunk = await self.microphone.get()
            try:
                # Recheck for microphone chunks queued just before playback began.
                if self._mute_microphone():
                    chunk = bytes(len(chunk))
                await session.send_audio(chunk)
                self.recorded_bytes += len(chunk)
            finally:
                self.microphone.task_done()
