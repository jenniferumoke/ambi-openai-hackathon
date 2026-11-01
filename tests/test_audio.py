import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from audio_io import AudioIO, BLOCK_SIZE, ECHO_TAIL_SECONDS, SAMPLE_RATE
from agents.realtime import RealtimeModelSendAudio, RealtimeModelSendRawMessage
from agents.realtime.testing import ScriptedRealtimeModel
from main import Settings, create_voice_runner, push_to_talk


class ImmediateLoop:
    def call_soon_threadsafe(self, fn, *args):
        fn(*args)


@pytest.fixture
def playback(monkeypatch):
    now = [10.0]
    monkeypatch.setattr("audio_io.monotonic", lambda: now[0])
    audio = AudioIO()
    audio._loop = ImmediateLoop()
    audio._closed = False
    return audio, now


def test_audio_chunk_boundaries_silence_and_interruption():
    audio = AudioIO()

    audio._loop = ImmediateLoop()
    audio._closed = False
    audio.play(b"\x01\x00\x02\x00\x03\x00", "item_1", 0)
    output = bytearray(4)
    audio._output(output, 2, None, None)
    assert output == b"\x01\x00\x02\x00"
    audio._output(output, 2, None, None)
    assert output == b"\x03\x00\x00\x00"
    assert audio.tracker.get_state()["elapsed_ms"] == 3 / 24_000 * 1000
    audio.play(b"\x01\x00", "item_2", 0)
    generation = audio._generation
    audio.clear()
    audio._played(generation, "item_2", 0, 100)
    audio._output(output, 2, None, None)
    assert output == b"\x00" * 4
    assert audio.tracker.get_state()["current_item_id"] is None


def test_long_replies_play_in_full_even_when_next_reply_arrives_early(playback):
    audio, now = playback
    first = b"\x01\x00" * (SAMPLE_RATE * 8)
    second = b"\x02\x00" * (SAMPLE_RATE * 3)
    # Match streaming: several deltas for the first reply, then generation done,
    # then a second reply, all arriving before the first reply has finished playing.
    for offset in range(0, len(first), 12_000):
        audio.play(first[offset:offset + 12_000], "first", 0)
    audio.finish("first", 0)
    audio.play(second, "second", 0)
    audio.finish("second", 0)
    assert audio._mute_microphone()

    played = bytearray()
    output = bytearray(BLOCK_SIZE * 2)
    for _ in range(11 * SAMPLE_RATE // BLOCK_SIZE):
        audio._output(output, BLOCK_SIZE, None, None)
        played.extend(output)
        now[0] += BLOCK_SIZE / SAMPLE_RATE
    assert played == first + second
    assert not audio._chunks
    assert audio._mute_microphone()  # The speaker echo tail still needs to drain.
    now[0] += ECHO_TAIL_SECONDS + 0.01
    assert not audio._mute_microphone()
    assert audio.tracker.get_state()["elapsed_ms"] == pytest.approx(3000)


def test_mic_stays_muted_during_gaps_in_audio_generation(playback):
    audio, now = playback
    audio.play(b"\x01\x00" * BLOCK_SIZE, "reply", 0)
    audio._output(bytearray(BLOCK_SIZE * 2), BLOCK_SIZE, None, None)
    now[0] += 2
    assert not audio._chunks
    assert audio._mute_microphone()  # More deltas may still be on their way.
    audio.finish("reply", 0)
    assert not audio._mute_microphone()


def test_speaker_echo_is_muted_at_capture_even_if_enqueue_runs_late(playback):
    audio, now = playback
    callbacks = []
    audio._loop = SimpleNamespace(call_soon_threadsafe=lambda fn, *args: callbacks.append((fn, args)))
    echo = b"\x10\x00" * BLOCK_SIZE
    audio.play(echo, "reply", 0)
    audio._input(echo, BLOCK_SIZE, None, None)
    audio.finish("reply", 0)
    audio._output(bytearray(len(echo)), BLOCK_SIZE, None, None)
    now[0] += 2  # The async event loop only processes the mic callback after playback.
    assert not audio._mute_microphone()
    for callback, args in callbacks:
        callback(*args)
    assert audio.microphone.get_nowait() == bytes(len(echo))
    audio._input(echo, BLOCK_SIZE, None, None)
    callback, args = callbacks[-1]
    callback(*args)
    assert audio.microphone.get_nowait() == echo


async def test_mic_chunks_queued_before_playback_are_silenced_before_sending(playback):
    audio, _ = playback
    chunk = b"\x10\x00" * BLOCK_SIZE
    audio._enqueue(chunk)
    audio.play(chunk, "reply", 0)

    class Session:
        async def send_audio(self, data):
            assert data == bytes(len(chunk))
            raise RuntimeError("first chunk sent")

    with pytest.raises(RuntimeError, match="first chunk sent"):
        await audio.send_microphone(Session())


async def test_headphone_mode_keeps_barge_in_available_during_playback():
    audio = AudioIO(allow_barge_in=True)
    audio._loop = ImmediateLoop()
    audio._closed = False
    chunk = b"\x10\x00" * BLOCK_SIZE
    audio.play(chunk, "reply", 0)
    audio._input(chunk, BLOCK_SIZE, None, None)

    class Session:
        async def send_audio(self, data):
            assert data == chunk
            raise RuntimeError("first chunk sent")

    with pytest.raises(RuntimeError, match="first chunk sent"):
        await audio.send_microphone(Session())


def test_echo_guard_includes_hardware_output_latency(playback):
    audio, now = playback
    audio.play(b"\x01\x00" * BLOCK_SIZE, "reply", 0)
    audio.finish("reply", 0)
    timing = SimpleNamespace(outputBufferDacTime=100.5, currentTime=100.0)
    audio._output(bytearray(BLOCK_SIZE * 2), BLOCK_SIZE, timing, None)
    now[0] += ECHO_TAIL_SECONDS + BLOCK_SIZE / SAMPLE_RATE + 0.01
    assert audio._mute_microphone()
    now[0] += 0.5
    assert not audio._mute_microphone()


async def test_microphone_queue_is_bounded_and_sends_bytes():
    audio = AudioIO()
    audio._closed = False
    for number in range(120):
        audio._enqueue(bytes([number]))
    assert audio.microphone.qsize() == 100

    class Session:
        async def send_audio(self, chunk):
            assert chunk == bytes([20])
            raise RuntimeError("done")

    try:
        await audio.send_microphone(Session())
    except RuntimeError as exc:
        assert str(exc) == "done"


async def test_push_to_talk_records_only_explicit_turn_and_never_responds_to_echo(monkeypatch):
    read_fd, write_fd = os.pipe()

    class Input:
        def isatty(self):
            return True

        def fileno(self):
            return read_fd

        def readline(self):
            return os.read(read_fd, 1).decode()

    monkeypatch.setattr("main.sys.stdin", Input())
    audio = AudioIO(push_to_talk=True)
    audio._closed = False
    audio._loop = asyncio.get_running_loop()
    worker = SimpleNamespace(perform=AsyncMock(), stop=AsyncMock())
    model = ScriptedRealtimeModel(strict=False)
    runner = create_voice_runner(worker, Settings(), model=model, hands_free=False)
    chunk = b"\x11\x22" * BLOCK_SIZE

    async def wait_for(predicate):
        async with asyncio.timeout(2):
            while not predicate():
                await asyncio.sleep(0.005)

    try:
        async with await runner.run() as session:
            assert model.connect_calls[0]["initial_model_settings"]["audio"]["input"]["turn_detection"] is None
            sender = asyncio.create_task(audio.send_microphone(session))
            control = asyncio.create_task(push_to_talk(session, audio))
            try:
                await asyncio.sleep(0)  # Register the terminal reader.
                audio._input(chunk, BLOCK_SIZE, None, None)
                await asyncio.sleep(0)
                assert not any(isinstance(event, RealtimeModelSendAudio) for event in model.sent_events)

                os.write(write_fd, b"\n")
                await wait_for(audio._recording.is_set)
                for _ in range(6):  # 120 ms, above the API's minimum input duration.
                    audio._input(chunk, BLOCK_SIZE, None, None)
                await wait_for(lambda: audio.recorded_bytes == len(chunk) * 6)
                os.write(write_fd, b"\n")
                await wait_for(lambda: any(
                    isinstance(event, RealtimeModelSendRawMessage)
                    and event.message["type"] == "response.create"
                    for event in model.sent_events
                ))
                sent = model.sent_events
                assert [event.message["type"] for event in sent if isinstance(event, RealtimeModelSendRawMessage)] == [
                    "input_audio_buffer.clear", "input_audio_buffer.commit", "response.create"
                ]
                assert b"".join(event.audio for event in sent if isinstance(event, RealtimeModelSendAudio)) == chunk * 6

                # Echo during the generated reply cannot be sent, and an early Enter
                # cannot open the mic before the reply is finished.
                audio.play(chunk * 4, "reply", 0)
                audio.finish("reply", 0)
                audio._input(chunk, BLOCK_SIZE, None, None)
                os.write(write_fd, b"\n")
                await asyncio.sleep(0.05)
                assert not audio._recording.is_set()
                assert len(model.sent_events) == len(sent)
            finally:
                control.cancel()
                sender.cancel()
                await asyncio.gather(control, sender, return_exceptions=True)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_push_to_talk_discards_delayed_capture_after_recording_stops():
    callbacks = []
    audio = AudioIO(push_to_talk=True)
    audio._closed = False
    audio._loop = SimpleNamespace(call_soon_threadsafe=lambda fn, *args: callbacks.append((fn, args)))
    audio.start_recording()
    audio._input(b"\x11\x22", 1, None, None)
    audio.stop_recording()
    audio.start_recording()
    callback, args = callbacks[0]
    callback(*args)
    assert audio.microphone.empty()


def test_observation_sees_portaudio_playback_including_device_and_echo_tail(playback):
    audio, now = playback
    assert not audio.playback_active()
    audio.play(b"\x01\x00" * BLOCK_SIZE, "reply", 0)
    audio.finish("reply", 0)
    assert audio.playback_active()
    audio._output(bytearray(BLOCK_SIZE * 2), BLOCK_SIZE, None, None)
    assert audio.playback_active()
    now[0] += ECHO_TAIL_SECONDS + BLOCK_SIZE / SAMPLE_RATE + 0.01
    assert not audio.playback_active()
