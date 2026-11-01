"""Local desktop adapter for the SDK's built-in ComputerTool.

``main.ComputerWorker`` supplies this adapter to the SDK, which calls its async
methods to take screenshots and perform mouse and keyboard actions. Operations
run on a thread so desktop interaction does not block the voice session.
"""

from __future__ import annotations

import asyncio
import base64
import io
import math
import platform
import threading
import time
from contextlib import contextmanager

from agents.computer import AsyncComputer, Button, Environment
from PIL import Image


class DesktopStopped(RuntimeError):
    """A computer action was stopped or requires a safety review."""


def mac_permissions():
    """Return the macOS permissions needed for desktop control and screenshots."""
    if platform.system() != "Darwin":
        return {}
    import ctypes
    from Quartz import CGPreflightScreenCaptureAccess

    framework = ctypes.CDLL(
        "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
    )
    framework.AXIsProcessTrusted.restype = ctypes.c_bool
    return {
        "Accessibility": bool(framework.AXIsProcessTrusted()),
        "Screen Recording": bool(CGPreflightScreenCaptureAccess()),
    }


class Desktop(AsyncComputer):
    """Translate SDK computer actions into serialized primary-display OS calls."""
    def __init__(self):
        # Lazy imports keep --help, audio diagnostics, and mock tests display-independent.
        import pyautogui
        import pyperclip

        self.gui = pyautogui
        self.clipboard = pyperclip
        self.gui.FAILSAFE = True
        self.gui.PAUSE = 0.08
        self._dimensions = tuple(self.gui.size())
        self._stopped = threading.Event()
        self._stopped.set()
        self._generation = 0
        self._lock = threading.Lock()

    @property
    def environment(self) -> Environment:
        return {"Darwin": "mac", "Windows": "windows"}.get(platform.system(), "ubuntu")

    @property
    def dimensions(self) -> tuple[int, int]:
        return self._dimensions

    @property
    def generation(self) -> int:
        """Read-only task identity so observers can discard assistant-era frames."""
        return self._generation

    def start(self):
        """Start a new task generation; stale actions from older tasks stay stopped."""
        self._generation += 1
        self._stopped.clear()

    def stop(self):
        """Prevent the current task from starting further desktop operations."""
        self._stopped.set()

    def _check(self, generation):
        """Reject cancelled or stale actions and respect the mouse-corner fail-safe."""
        if self._stopped.is_set() or generation != self._generation:
            raise DesktopStopped("Computer task stopped.")
        self.gui.failSafeCheck()

    async def _run(self, label, operation):
        """Run one OS operation off the event loop, serialized with other actions."""
        generation = self._generation

        def execute():
            # Serialize OS calls, including calls that finish after async cancellation.
            with self._lock:
                self._check(generation)
                print(f"[computer] {label}", flush=True)
                return operation(generation)

        return await asyncio.to_thread(execute)

    def _point(self, x, y):
        width, height = self.dimensions
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(f"Point {(x, y)} is outside the primary display {self.dimensions}.")
        return x, y

    def _key(self, key):
        normalized = key.lower().replace("_", "").replace(" ", "")
        aliases = {
            "meta": "command" if self.environment == "mac" else "win",
            "super": "command" if self.environment == "mac" else "win",
            "cmd": "command", "control": "ctrl", "option": "alt",
            "return": "enter", "escape": "esc", "spacebar": "space",
            "arrowup": "up", "arrowdown": "down", "arrowleft": "left",
            "arrowright": "right", "pageup": "pgup", "pagedown": "pgdn",
            "backspace": "backspace", "del": "delete",
        }
        value = aliases.get(normalized, normalized)
        if value not in self.gui.KEYBOARD_KEYS:
            raise ValueError(f"Unsupported key: {key}")
        return value

    def _release(self, operation, *args):
        # A fail-safe must still release keys/buttons already held by this process.
        enabled = self.gui.FAILSAFE
        try:
            self.gui.FAILSAFE = False
            operation(*args)
        finally:
            self.gui.FAILSAFE = enabled

    @contextmanager
    def _held(self, keys, generation):
        """Hold modifier keys for an operation, releasing them even on failure."""
        pressed = []
        try:
            for key in keys or []:
                self._check(generation)
                mapped = self._key(key)
                self.gui.keyDown(mapped)
                pressed.append(mapped)
            yield
        finally:
            for key in reversed(pressed):
                self._release(self.gui.keyUp, key)

    async def screenshot(self) -> str:
        """Return a base64 PNG in the same coordinate space as mouse actions."""
        def capture(generation):
            image = self.gui.screenshot()
            # macOS Retina screenshots use physical pixels, but mouse input uses points.
            # Send exactly the coordinate space used by the mouse adapter.
            if image.size != self.dimensions:
                image = image.resize(self.dimensions, Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
            self._check(generation)
            return base64.b64encode(buffer.getvalue()).decode("ascii")

        return await self._run("screenshot", capture)

    async def click(self, x: int, y: int, button: Button, *, keys=None):
        x, y = self._point(x, y)
        button = {"wheel": "middle"}.get(button, button)
        if button not in {"left", "right", "middle"}:
            raise ValueError(f"Unsupported mouse button: {button}")

        def action(generation):
            with self._held(keys, generation):
                self._check(generation)
                self.gui.click(x, y, button=button)

        await self._run(f"{button} click ({x}, {y})", action)

    async def double_click(self, x: int, y: int, *, keys=None):
        x, y = self._point(x, y)

        def action(generation):
            with self._held(keys, generation):
                self._check(generation)
                self.gui.doubleClick(x, y, interval=0.1)

        await self._run(f"double click ({x}, {y})", action)

    async def move(self, x: int, y: int, *, keys=None):
        x, y = self._point(x, y)

        def action(generation):
            with self._held(keys, generation):
                self._check(generation)
                self.gui.moveTo(x, y)

        await self._run(f"move ({x}, {y})", action)

    async def scroll(self, x: int, y: int, scroll_x: int, scroll_y: int, *, keys=None):
        x, y = self._point(x, y)

        def ticks(pixels):
            return int(math.copysign(math.ceil(abs(pixels) / 100), pixels)) if pixels else 0

        def action(generation):
            with self._held(keys, generation):
                self.gui.moveTo(x, y)
                # The API uses pixel-like distances, while PyAutoGUI uses wheel ticks.
                if scroll_y:
                    self._check(generation)
                    self.gui.scroll(-ticks(scroll_y))
                if scroll_x:
                    self._check(generation)
                    self.gui.hscroll(ticks(scroll_x))

        await self._run("scroll", action)

    async def type(self, text: str):
        def action(generation):
            # Clipboard paste supports Unicode and the user's keyboard layout.
            previous = self.clipboard.paste()
            try:
                self.clipboard.copy(text)
                modifier = "command" if self.environment == "mac" else "ctrl"
                with self._held([modifier], generation):
                    self._check(generation)
                    self.gui.press("v")
                time.sleep(0.15)
            finally:
                self.clipboard.copy(previous)

        await self._run(f"paste {len(text)} characters", action)

    async def keypress(self, keys: list[str]):
        def action(generation):
            with self._held(keys, generation):
                pass

        await self._run(f"keypress {'+'.join(keys)}", action)

    async def drag(self, path: list[tuple[int, int]], *, keys=None):
        if not path or len(path) > 1000:
            raise ValueError("Drag requires between 1 and 1000 points.")
        points = [self._point(x, y) for x, y in path]

        def action(generation):
            with self._held(keys, generation):
                self.gui.moveTo(*points[0])
                self._check(generation)
                self.gui.mouseDown()
                try:
                    for point in points[1:]:
                        self._check(generation)
                        self.gui.moveTo(*point, _pause=False)
                        time.sleep(0.01)
                finally:
                    self._release(self.gui.mouseUp)

        await self._run("drag", action)

    async def wait(self):
        self._check(self._generation)
        await asyncio.sleep(0.5)
