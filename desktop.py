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
from uuid import uuid4
from contextlib import contextmanager

from agents.computer import AsyncComputer, Button, Environment
from PIL import Image


class DesktopStopped(RuntimeError):
    """A computer action was stopped or requires a safety review."""


class DesktopTargetUnavailable(DesktopStopped):
    """Recoverable targeting failure; no screen capture or input was sent."""


def mac_permissions():
    """Return the macOS permissions needed for desktop control and screenshots."""
    if platform.system() == "Linux":
        from linux_session import session_checks
        return session_checks()
    if platform.system() == "Windows":
        import ctypes
        user32 = ctypes.windll.user32
        user32.OpenInputDesktop.restype = ctypes.c_void_p
        handle = user32.OpenInputDesktop(0, False, 1)
        if handle:
            user32.CloseDesktop(ctypes.c_void_p(handle))
        return {"Interactive desktop": bool(handle)}
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
    def __init__(self, *, emit=None):
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
        self._visual_target = None
        self._lock = threading.Lock()
        self.emit = emit or (lambda *args, **kwargs: None)

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
        self._visual_target = None
        self._stopped.clear()

    def stop(self):
        """Prevent the current task from starting further desktop operations."""
        self._stopped.set()

    def _check(self, generation):
        """Reject cancelled or stale actions and respect the mouse-corner fail-safe."""
        if self._stopped.is_set() or generation != self._generation:
            raise DesktopStopped("Computer task stopped.")
        if platform.system() == "Windows" and not all(mac_permissions().values()):
            raise DesktopStopped("The interactive Windows desktop is unavailable. Unlock the PC and review the task before restarting it.")
        if platform.system() == 'Darwin' and not all(mac_permissions().values()):
            raise DesktopStopped('Mac computer permissions are unavailable. Review setup before resuming.')
        if platform.system() == 'Linux' and not all(mac_permissions().values()):
            raise DesktopStopped('Linux X11 desktop prerequisites are unavailable. Wayland control is not supported by this preview.')
        self.gui.failSafeCheck()

    async def _run(self, label, operation):
        """Run one OS operation off the event loop, serialized with other actions."""
        generation = self._generation

        def execute():
            # Serialize OS calls, including calls that finish after async cancellation.
            with self._lock:
                self._check(generation)
                if self._visual_target and label != "open application":
                    from mac_applications import visual_target_ready
                    for _ in range(10):
                        self._check(generation)
                        if visual_target_ready(self._visual_target):
                            break
                        time.sleep(0.1)
                    else:
                        raise DesktopTargetUnavailable("Target app is not focused on the primary display. No screenshot or input was sent.")
                print(f"[computer] {label}", flush=True)
                return operation(generation)

        step_id = uuid4().hex
        self.emit("computer_step_started", step_id=step_id, label=label)
        try:
            result = await asyncio.to_thread(execute)
        except BaseException as exc:
            status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            self.emit("computer_step_finished", step_id=step_id, status=status,
                      detail="Action interrupted; earlier changes may remain." if status == "cancelled"
                      else f"Action stopped ({type(exc).__name__}).")
            raise
        self.emit("computer_step_finished", step_id=step_id, status="completed",
                  detail="Desktop operation returned. Task outcome still requires verification.")
        return result

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

    async def open_application(self, application: str, *, bring_to_primary=False, exit_full_screen=False):
        """Use native macOS launch/read-back within the same Stop boundary."""
        if self.environment != "mac":
            raise ValueError("Native application launch is available only on macOS.")
        from mac_applications import open_application
        def launch(generation):
            self._visual_target = application
            result = open_application(application, bring_to_primary=bring_to_primary, exit_full_screen=exit_full_screen,
                                      check=lambda: self._check(generation))
            self._check(generation)
            self.emit('native_application_observed', **{key:result[key] for key in (
                'application','installed','running','frontmost','activation_accepted','focused_window_move',
                'visible_window_count','window_on_primary_display') if key in result})
            return result
        return await self._run("open application", launch)

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
