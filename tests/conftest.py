import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agents import set_tracing_disabled
from PIL import Image

from desktop import Desktop


@pytest.fixture(autouse=True)
def disable_traces():
    set_tracing_disabled(True)


@pytest.fixture
def desktop(monkeypatch):
    gui = SimpleNamespace(
        size=Mock(return_value=(100, 80)),
        screenshot=Mock(return_value=Image.new("RGB", (200, 160), "white")),
        failSafeCheck=Mock(),
        KEYBOARD_KEYS=["command", "ctrl", "alt", "shift", "enter", "esc", "space", "a", "v", "left"],
        **{name: Mock() for name in [
            "click", "doubleClick", "moveTo", "scroll", "hscroll", "keyDown", "keyUp",
            "press", "mouseDown", "mouseUp",
        ]},
    )
    clipboard = SimpleNamespace(paste=Mock(return_value="previous clipboard"), copy=Mock())
    monkeypatch.setitem(sys.modules, "pyautogui", gui)
    monkeypatch.setitem(sys.modules, "pyperclip", clipboard)
    monkeypatch.setattr("desktop.time.sleep", lambda _: None)
    monkeypatch.setattr("desktop.platform.system", lambda: "Darwin")
    monkeypatch.setattr('desktop.mac_permissions',lambda:{'Accessibility':True,'Screen Recording':True})
    result = Desktop()
    result.start()
    return result
