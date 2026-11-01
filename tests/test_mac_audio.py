import asyncio
import platform
from array import array
from types import SimpleNamespace

import pytest

from mac_audio import MacVoiceAudioIO, PLAYBACK_FRAMES


class Buffer:
    @classmethod
    def alloc(cls):
        return cls()

    def initWithPCMFormat_frameCapacity_(self, fmt, frames):
        self.data = bytearray(frames * 2)
        return self

    def setFrameLength_(self, frames):
        self.frames = frames

    def mutableAudioBufferList(self):
        return [SimpleNamespace(mData=memoryview(self.data))]


class Player:
    def __init__(self):
        self.callbacks = []
        self.stops = 0
        self.plays = 0

    def scheduleBuffer_completionCallbackType_completionHandler_(self, buffer, kind, callback):
        self.callbacks.append((buffer, kind, callback))

    def stop(self):
        self.stops += 1

    def play(self):
        self.plays += 1


class ImmediateLoop:
    def call_soon_threadsafe(self, fn, *args):
        fn(*args)


@pytest.fixture
def native_audio(monkeypatch):
    monkeypatch.setattr("mac_audio.platform.system", lambda: "Darwin")
    audio = MacVoiceAudioIO()
    audio._av = SimpleNamespace(
        AVAudioPCMBuffer=Buffer, AVAudioPlayerNodeCompletionDataPlayedBack=2,
    )
    audio._pcm_format = object()
    audio._player = Player()
    audio._loop = ImmediateLoop()
    audio._closed = False
    return audio


def test_output_tracks_what_was_heard_and_discards_stale_callbacks(native_audio):
    audio = native_audio
    pcm = b"\x12\x34" * (PLAYBACK_FRAMES * 2 + PLAYBACK_FRAMES // 2)
    audio.play(pcm, "first", 0)
    assert [bytes(entry[0].data) for entry in audio._player.callbacks] == [
        pcm[:4800], pcm[4800:9600], pcm[9600:]
    ]
    assert audio.tracker.get_state()["elapsed_ms"] == 0
    audio._player.callbacks[0][2](2)
    assert audio.tracker.get_state()["elapsed_ms"] == 100
    audio.clear()
    assert audio._player.stops == 1
    assert audio._player.plays == 1
    assert audio.tracker.get_state()["current_item_id"] is None
    for _, _, callback in audio._player.callbacks[1:]:
        callback(2)
    assert audio.tracker.get_state()["current_item_id"] is None
    audio.play(b"\x00\x01" * 2400, "next", 0)
    audio._player.callbacks[-1][2](2)
    assert audio.tracker.get_state()["current_item_id"] == "next"
    assert audio.tracker.get_state()["elapsed_ms"] == 100


def test_noise_gate_rejects_isolated_spikes_and_preserves_speech_onset(native_audio, monkeypatch):
    now = [10.0]
    monkeypatch.setattr("mac_audio.monotonic", lambda: now[0])
    audio = native_audio
    quiet = array("h", [100] * 2400).tobytes()
    voice = array("h", [1000] * 2400).tobytes()
    assert audio._suppress_residual_echo(quiet) == bytes(len(quiet))
    # A single loud block cannot start a turn, even when speakers are idle.
    assert audio._suppress_residual_echo(voice) == bytes(len(quiet))
    assert audio._suppress_residual_echo(quiet) == bytes(len(voice))
    # Two loud blocks confirm speech; the delayed first block is retained.
    audio.play(b"\x00\x01" * 2400, "reply", 0)
    assert audio._suppress_residual_echo(voice) == bytes(len(quiet))
    now[0] += 0.1
    assert audio._suppress_residual_echo(voice) == voice
    now[0] += 0.2
    assert audio._suppress_residual_echo(quiet) == voice
    now[0] += 0.1
    assert audio._suppress_residual_echo(quiet) == quiet
    now[0] += 0.3
    assert audio._suppress_residual_echo(quiet) == bytes(len(quiet))


def test_noise_gate_can_be_disabled(native_audio):
    native_audio.echo_gate_rms = 0
    data = array("h", [100] * 2400).tobytes()
    assert native_audio._suppress_residual_echo(data) == data


@pytest.mark.skipif(platform.system() != "Darwin", reason="Requires macOS AVFoundation")
async def test_microphone_conversion_preserves_speech_without_muting_during_playback():
    import AVFoundation as av

    audio = MacVoiceAudioIO()
    audio._av = av
    audio._loop = asyncio.get_running_loop()
    audio._closed = False
    audio._input_format = av.AVAudioFormat.alloc().initWithCommonFormat_sampleRate_channels_interleaved_(
        av.AVAudioPCMFormatFloat32, 48000, 2, False,
    )
    audio._pcm_format = av.AVAudioFormat.alloc().initWithCommonFormat_sampleRate_channels_interleaved_(
        av.AVAudioPCMFormatInt16, 24000, 1, False,
    )
    audio._converter = audio._make_converter(av, audio._input_format, audio._pcm_format)
    source = av.AVAudioPCMBuffer.alloc().initWithPCMFormat_frameCapacity_(audio._input_format, 4800)
    source.setFrameLength_(4800)
    source.mutableAudioBufferList()[0].mData[:] = array("f", [0.25] * 4800).tobytes()
    source.mutableAudioBufferList()[1].mData[:] = array("f", [-0.25] * 4800).tobytes()

    # Capture continues during a reply: it is the macOS engine, not a mute gate,
    # that removes speaker echo while preserving the user's voice.
    audio._generating.add(("reply", 0))
    audio._capture(source, None)
    audio._capture(source, None)
    await asyncio.wait_for(audio.microphone.get(), 1)
    data = await asyncio.wait_for(audio.microphone.get(), 1)
    assert isinstance(data, bytes)
    assert len(data) > 3000
    samples = array("h")
    samples.frombytes(data)
    assert max(samples) > 1000  # The first channel survived instead of being silenced.


def test_custom_devices_are_explicitly_rejected_for_native_audio(monkeypatch):
    monkeypatch.setattr("mac_audio.platform.system", lambda: "Darwin")
    with pytest.raises(ValueError, match="macOS default"):
        MacVoiceAudioIO(input_device=1)


def test_observation_sees_playback_until_native_buffers_have_drained(native_audio):
    audio = native_audio
    assert not audio.playback_active()
    audio.play(b"\x00\x01" * 2400, "reply", 0)
    audio.finish("reply", 0)
    assert audio.playback_active()  # Generation ended, but the speaker is still busy.
    audio._player.callbacks[-1][2](2)
    assert not audio.playback_active()
