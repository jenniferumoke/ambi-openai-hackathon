from linux_session import session_checks
import pytest


def test_x11_prerequisites():
    checks = session_checks({"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}, lambda name: name)
    assert all(checks.values())


def test_wayland_and_missing_utilities_fail_closed():
    for env in ({}, {"DISPLAY": ":0", "XDG_SESSION_TYPE": "wayland"}, {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}):
        assert not session_checks(env, lambda name: name)["X11 session"]
    checks = session_checks({"DISPLAY": ":0"}, lambda name: None)
    assert not checks["Screenshot utility"] and not checks["Clipboard utility"]


async def test_linux_access_loss_blocks_input_and_screen(desktop, monkeypatch):
    from desktop import DesktopStopped
    monkeypatch.setattr('desktop.platform.system', lambda: 'Linux')
    monkeypatch.setattr('desktop.mac_permissions', lambda: {'X11 session': False})
    with pytest.raises(DesktopStopped, match='Linux X11'):
        await desktop.click(10, 20, 'left')
    with pytest.raises(DesktopStopped, match='Linux X11'):
        await desktop.screenshot()
    desktop.gui.click.assert_not_called()
    desktop.gui.screenshot.assert_not_called()


def test_linux_uses_compatible_audio_without_mac_frameworks(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import main
    monkeypatch.setattr(main.sys, 'platform', 'linux')
    factory = Mock()
    monkeypatch.setattr('audio_io.AudioIO', factory)
    args = SimpleNamespace(push_to_talk=False, input_device=None, output_device=None)
    assert main.create_audio_io(SimpleNamespace(echo_gate_rms=0.1), args) is factory.return_value
    factory.assert_called_once_with(None, None, push_to_talk=False)
