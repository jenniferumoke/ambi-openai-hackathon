"""Read-only macOS screen capture, independent of ComputerWorker lifecycle.

Quartz returns image data in memory. No shell screenshot command, temporary
image file, mouse, keyboard, or clipboard API is used.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import platform
import threading
from dataclasses import dataclass
from time import monotonic

from PIL import Image


class ScreenCaptureError(RuntimeError):
    pass


class ScreenContextChanged(ScreenCaptureError):
    pass


@dataclass(frozen=True)
class ScreenFrame:
    captured_at: float
    jpeg: bytes
    application: str
    context_id: str

    @property
    def fingerprint(self):
        return hashlib.sha256(self.context_id.encode() + self.jpeg).hexdigest()


def encode_screen_image(native_image):
    import Quartz as q
    from Foundation import NSMutableData

    data = NSMutableData.data()
    destination = q.CGImageDestinationCreateWithData(data, "public.png", 1, None)
    if destination is None:
        raise ScreenCaptureError("Could not create an in-memory screen image.")
    q.CGImageDestinationAddImage(destination, native_image, None)
    if not q.CGImageDestinationFinalize(destination):
        raise ScreenCaptureError("Could not encode the screen image.")
    with Image.open(io.BytesIO(bytes(data))) as source:
        image = source.convert("RGB")
        image.thumbnail((1600, 1600))
        image.info.clear()
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        return buffer.getvalue()


class ReadOnlyScreenCapture:
    def __init__(self):
        if platform.system() != "Darwin":
            raise ScreenCaptureError("Computer observation currently requires macOS.")
        self._closed = threading.Event()
        self._lock = threading.Lock()

    def _context(self):
        import Quartz as q

        # Query WindowServer each time. NSWorkspace's cached frontmost app can
        # remain stuck on Terminal in a process without a Cocoa main run loop.
        windows = q.CGWindowListCopyWindowInfo(
            q.kCGWindowListOptionOnScreenOnly | q.kCGWindowListExcludeDesktopElements, q.kCGNullWindowID,
        ) or []
        bounds = q.CGDisplayBounds(q.CGMainDisplayID())

        def on_primary(entry):
            area = entry.get(q.kCGWindowBounds, {})
            x, y = area.get("X", 0), area.get("Y", 0)
            width, height = area.get("Width", 0), area.get("Height", 0)
            return (min(x + width, bounds.origin.x + bounds.size.width) > max(x, bounds.origin.x)
                    and min(y + height, bounds.origin.y + bounds.size.height) > max(y, bounds.origin.y))

        window = next((entry for entry in windows if entry.get(q.kCGWindowLayer) == 0
                       and entry.get(q.kCGWindowAlpha, 1) > 0 and on_primary(entry)), None)
        if window is None:
            return "unknown", "unknown"
        application = str(window.get(q.kCGWindowOwnerName) or "unknown")[:80]
        # Window titles help detect tab/document switches, but are not uploaded
        # as metadata or written to logs; retain only a digest as the identity.
        identity = [window.get(q.kCGWindowOwnerPID), window.get(q.kCGWindowNumber), window.get(q.kCGWindowName)]
        return application, hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:20]

    async def context_id(self):
        return (await asyncio.to_thread(self._context))[1]

    def _capture(self):
        import Quartz as q

        with self._lock:
            if self._closed.is_set():
                raise ScreenCaptureError("Screen observer is closed.")
            if not q.CGPreflightScreenCaptureAccess():
                raise ScreenCaptureError(
                    "Enable Screen Recording for your terminal in System Settings > Privacy & Security, "
                    "then quit/reopen that terminal and restart observation."
                )
            application, identity = self._context()
            captured_at = monotonic()
            native_image = q.CGDisplayCreateImage(q.CGMainDisplayID())
            if native_image is None:
                raise ScreenCaptureError("Screen capture unavailable; check Screen Recording access and the primary display.")
            jpeg = encode_screen_image(native_image)
            if self._closed.is_set():
                raise ScreenCaptureError("Screen observer is closed.")
            if self._context()[1] != identity:
                raise ScreenContextChanged("Foreground window changed during capture.")
            return ScreenFrame(captured_at, jpeg, application, identity)

    async def capture(self):
        return await asyncio.to_thread(self._capture)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self._closed.set()
