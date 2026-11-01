"""Opt-in macOS still capture, isolated from the voice process.

The helper owns AVFoundation and returns one resized JPEG per request over a
private pipe. No files are written. A native camera crash or permission failure
cannot take down audio; closing the pipe (or terminating the helper) releases it.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import platform
import queue
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from PIL import Image, ImageOps


class CameraError(RuntimeError):
    pass


@dataclass(frozen=True)
class CameraFrame:
    captured_at: float
    jpeg: bytes


def resize_jpeg(data: bytes) -> bytes:
    """Bound image size and strip camera metadata before sending it anywhere."""
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((640, 640))
        image.info.clear()
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=75)
        return output.getvalue()


class MacCamera:
    """Async camera interface with exactly one requested frame in flight."""

    def __init__(self, device_index=0):
        self.device_index = device_index
        self.process = None
        self.device_info = {"index": device_index}

    async def __aenter__(self):
        if platform.system() != "Darwin":
            raise CameraError("Camera observation currently requires macOS.")
        try:
            self.process = await asyncio.create_subprocess_exec(
                sys.executable, str(Path(__file__).resolve()), "--capture-worker", str(self.device_index),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=1_000_000,
            )
            async with asyncio.timeout(60):
                result = await self._read()
            if result.get("status") != "ready":
                raise CameraError("Camera did not become ready.")
            self.device_info = result.get("device", self.device_info)
        except BaseException:
            await self.close()
            raise
        return self

    async def _read(self):
        line = await self.process.stdout.readline()
        if not line:
            raise CameraError(
                "Camera helper exited. Check Camera access for your terminal in "
                "System Settings > Privacy & Security, then restart observation."
            )
        try:
            result = json.loads(line)
        except (ValueError, TypeError) as exc:
            raise CameraError("Invalid camera helper response.") from exc
        if result.get("status") == "error":
            raise CameraError(result["reason"])
        return result

    async def capture(self) -> CameraFrame:
        if self.process is None:
            raise CameraError("Camera is closed.")
        try:
            async with asyncio.timeout(8):
                self.process.stdin.write(b"capture\n")
                await self.process.stdin.drain()
                result = await self._read()
            return CameraFrame(result["captured_at"], base64.b64decode(result["jpeg"], validate=True))
        except (TimeoutError, BrokenPipeError, ConnectionResetError, KeyError, ValueError) as exc:
            raise CameraError("Camera capture failed or timed out; restart observation.") from exc

    async def close(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.stdin:
            process.stdin.close()
        try:
            async with asyncio.timeout(2):
                await process.wait()
        except TimeoutError:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()

    async def __aexit__(self, *_):
        await self.close()


def _wait_for_event(event, timeout=None):
    """Keep Cocoa/GCD callbacks running while the native helper waits.

    Event.wait() on this thread starves the main run loop used by AVFoundation's
    photo pipeline. The helper is a separate process, so pumping this loop does
    not block or change the voice agent's asyncio loop.
    """
    from Foundation import NSDate, NSDefaultRunLoopMode, NSRunLoop

    deadline = None if timeout is None else monotonic() + timeout
    run_loop = NSRunLoop.currentRunLoop()
    while not event.is_set():
        remaining = 0.02 if deadline is None else min(0.02, deadline - monotonic())
        if remaining <= 0:
            return False
        handled = run_loop.runMode_beforeDate_(
            NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(remaining),
        )
        if not handled:
            # A run loop with no sources returns immediately; avoid a busy spin.
            event.wait(remaining)
    return True


def _camera_commands():
    """Read the pipe off the main thread so native callbacks run between frames."""
    commands = queue.Queue(maxsize=1)
    available = threading.Event()

    def read():
        try:
            for line in sys.stdin:
                commands.put(line.strip())
                available.set()
        finally:
            commands.put(None)
            available.set()

    threading.Thread(target=read, name="camera-commands", daemon=True).start()
    while True:
        available.clear()
        try:
            command = commands.get_nowait()
        except queue.Empty:
            _wait_for_event(available)
            continue
        if command is None:
            return
        yield command


def _photo_failure(error):
    # Native descriptions can include device details or paths. Domain/code give
    # useful diagnostics without printing arbitrary native exception contents.
    try:
        domain = str(error.domain())
        domain = "".join(char for char in domain if char.isalnum() or char in "._-")[:80]
        return f"Camera photo capture failed ({domain}, code {int(error.code())})."
    except Exception:
        return "Camera photo capture failed."


def _capture_worker(device_index):
    """Native code runs only in the explicitly started camera helper."""
    import AVFoundation as av
    import objc
    from Foundation import NSObject

    class ObservationPhotoDelegate(NSObject, protocols=[objc.protocolNamed("AVCapturePhotoCaptureDelegate")]):
        def captureOutput_didFinishProcessingPhoto_error_(self, output, photo, error):
            if error is not None:
                self.failure = _photo_failure(error)
                self.finished.set()
            else:
                try:
                    data = photo.fileDataRepresentation()
                    self.data = bytes(data) if data is not None else None
                except Exception:
                    self.failure = "Camera could not encode the captured photo."
                    self.finished.set()

        def captureOutput_didFinishCaptureForResolvedSettings_error_(self, output, settings, error):
            if error is not None:
                self.failure = _photo_failure(error)
            # Wait for the full capture to finish before reusing the output or
            # releasing the Python delegate, even after image processing ends.
            self.finished.set()

    def reply(**fields):
        print(json.dumps(fields), flush=True)

    session = None
    try:
        status = av.AVCaptureDevice.authorizationStatusForMediaType_(av.AVMediaTypeVideo)
        if status == av.AVAuthorizationStatusNotDetermined:
            answered = threading.Event()

            def authorized(_granted):
                answered.set()

            av.AVCaptureDevice.requestAccessForMediaType_completionHandler_(av.AVMediaTypeVideo, authorized)
            if not _wait_for_event(answered, 55):
                raise CameraError("Camera permission request timed out; restart observation after granting access.")
            status = av.AVCaptureDevice.authorizationStatusForMediaType_(av.AVMediaTypeVideo)
        if status != av.AVAuthorizationStatusAuthorized:
            raise CameraError("Camera access denied. Enable Camera access for your terminal, then restart observation.")

        devices = av.AVCaptureDevice.devicesWithMediaType_(av.AVMediaTypeVideo)
        if not 0 <= device_index < len(devices):
            raise CameraError("Camera device index unavailable; try --camera-device 0 or reconnect the camera.")
        source, error = av.AVCaptureDeviceInput.deviceInputWithDevice_error_(devices[device_index], None)
        if source is None:
            raise CameraError("Could not open the camera; close other camera apps and retry.")
        session = av.AVCaptureSession.alloc().init()
        output = av.AVCapturePhotoOutput.alloc().init()
        if not session.canAddInput_(source):
            raise CameraError("Camera input unavailable.")
        session.addInput_(source)
        if not session.canAddOutput_(output):
            raise CameraError("Camera does not support still image capture.")
        session.addOutput_(output)
        session.startRunning()
        if not session.isRunning():
            raise CameraError("Camera session could not start.")
        reply(status="ready", device={"index": device_index,
              "name": str(devices[device_index].localizedName()) if hasattr(devices[device_index], "localizedName") else "unknown",
              "available_count": len(devices)})

        for command in _camera_commands():
            if command != "capture":
                break
            delegate = ObservationPhotoDelegate.alloc().init()
            delegate.finished = threading.Event()
            delegate.data = None
            delegate.failure = None
            settings = av.AVCapturePhotoSettings.photoSettingsWithFormat_({
                av.AVVideoCodecKey: av.AVVideoCodecTypeJPEG,
            })
            output.capturePhotoWithSettings_delegate_(settings, delegate)
            if not _wait_for_event(delegate.finished, 6):
                raise CameraError("Camera photo callbacks did not finish within 6 seconds; restart observation.")
            if delegate.failure:
                raise CameraError(delegate.failure)
            if delegate.data is None:
                raise CameraError("Camera completed capture without image data; restart observation.")
            captured_at = monotonic()
            jpeg = resize_jpeg(delegate.data)
            delegate.data = None
            reply(status="frame", captured_at=captured_at, jpeg=base64.b64encode(jpeg).decode("ascii"))
    except CameraError as exc:
        reply(status="error", reason=str(exc))
    except Exception:
        # Never print native exceptions that might contain image data or paths.
        reply(status="error", reason="Native camera capture failed; restart observation.")
    finally:
        if session is not None:
            session.stopRunning()


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--capture-worker":
    _capture_worker(int(sys.argv[2]))
