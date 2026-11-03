from types import SimpleNamespace
import sys
import pytest
import main
from app_runtime import UnavailableWorker


def test_windows_hands_free_never_constructs_mac_audio(monkeypatch):
    calls = []
    instance = object()
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr('audio_io.AudioIO', lambda *args, **kw: (calls.append((args, kw)), instance)[1])
    monkeypatch.setattr('mac_audio.MacVoiceAudioIO', lambda *a, **kw: pytest.fail('Mac audio selected on Windows'))
    args = SimpleNamespace(push_to_talk=False, input_device=None, output_device=None)
    assert main.create_audio_io(SimpleNamespace(), args) is instance
    assert calls == [((None, None), {'push_to_talk': False})]


def test_windows_explicit_push_to_talk_preserved(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr('audio_io.AudioIO', lambda *args, **kw: calls.append(kw))
    main.create_audio_io(SimpleNamespace(), SimpleNamespace(push_to_talk=True, input_device=None, output_device=None))
    assert calls == [{'push_to_talk': True}]


@pytest.mark.asyncio
async def test_windows_worker_does_not_suggest_mac_permissions(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    result = await UnavailableWorker().perform('Inspect my computer')
    assert 'Computer control is off or unavailable' in result
    assert 'Setup & connections' in result
    assert 'Enable Accessibility' not in result
