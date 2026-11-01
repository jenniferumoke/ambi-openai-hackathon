import asyncio
import base64
import io
import json
import os
import platform
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image

from camera import CameraError, MacCamera, _capture_worker, _wait_for_event, resize_jpeg


def jpeg():
    output = io.BytesIO()
    image = Image.new("RGB", (1600, 1200), "white")
    exif = Image.Exif()
    exif[270] = "private camera metadata"
    image.save(output, format="JPEG", exif=exif)
    return output.getvalue()


def test_camera_resizes_and_strips_metadata_before_upload():
    result = resize_jpeg(jpeg())
    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (640, 480)
        assert not image.getexif()
        assert "private camera metadata" not in str(image.info)


async def test_camera_pipe_cancellation_releases_helper_and_ignores_stderr(monkeypatch):
    process = SimpleNamespace(
        stdin=SimpleNamespace(write=Mock(), drain=AsyncMock(), close=Mock()),
        stdout=SimpleNamespace(readline=AsyncMock(side_effect=[
            b'{"status":"ready"}\n',
            json.dumps({"status": "frame", "captured_at": 12,
                        "jpeg": base64.b64encode(b"image").decode()}).encode() + b"\n",
        ])), wait=AsyncMock(), returncode=None,
    )
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr("camera.platform.system", lambda: "Darwin")
    monkeypatch.setattr("camera.asyncio.create_subprocess_exec", spawn)
    async with MacCamera(1) as camera:
        frame = await camera.capture()
        assert (frame.captured_at, frame.jpeg) == (12, b"image")
    process.stdin.write.assert_called_once_with(b"capture\n")
    process.stdin.close.assert_called_once()
    process.wait.assert_awaited_once()
    assert spawn.call_args.kwargs["stderr"] == asyncio.subprocess.DEVNULL


async def test_camera_start_cancellation_cleans_up_instead_of_leaving_camera_running(monkeypatch):
    reading = asyncio.Event()

    async def read():
        reading.set()
        await asyncio.Event().wait()

    process = SimpleNamespace(
        stdin=SimpleNamespace(close=Mock()), stdout=SimpleNamespace(readline=read), wait=AsyncMock(),
    )
    monkeypatch.setattr("camera.platform.system", lambda: "Darwin")
    monkeypatch.setattr("camera.asyncio.create_subprocess_exec", AsyncMock(return_value=process))
    camera = MacCamera()
    task = asyncio.create_task(camera.__aenter__())
    await reading.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    process.stdin.close.assert_called_once()
    process.wait.assert_awaited_once()
    assert camera.process is None


async def test_native_crash_and_hung_shutdown_are_contained(monkeypatch):
    process = SimpleNamespace(stdin=SimpleNamespace(close=Mock()),
                              stdout=SimpleNamespace(readline=AsyncMock(return_value=b"")),
                              wait=AsyncMock(side_effect=[TimeoutError, None]), kill=Mock(), returncode=None)
    monkeypatch.setattr("camera.platform.system", lambda: "Darwin")
    monkeypatch.setattr("camera.asyncio.create_subprocess_exec", AsyncMock(return_value=process))
    camera = MacCamera()
    with pytest.raises(CameraError, match="helper exited"):
        await camera.__aenter__()
    process.kill.assert_called_once()
    assert camera.process is None


@pytest.mark.parametrize("permission,device_count,fail_photo", [(3, 1, False), (2, 1, False), (3, 0, False), (3, 1, True), (0, 1, False)])
def test_native_worker_permission_capture_and_cleanup_with_fake_camera(monkeypatch, capsys, permission, device_count, fail_photo):
    pending = []
    callbacks = []
    authorization = [permission]

    def pump(*_):
        if pending:
            pending.pop(0)()
            return True
        return False

    def request_access(media_type, callback):
        def respond():
            authorization[0] = 3
            callback(True)
        pending.append(respond)

    class Object:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

    session = SimpleNamespace(canAddInput_=lambda _: True, canAddOutput_=lambda _: True,
                              addInput_=Mock(), addOutput_=Mock(), startRunning=Mock(),
                              isRunning=lambda: True, stopRunning=Mock())

    def capture(settings, delegate):
        photo = SimpleNamespace(fileDataRepresentation=lambda: jpeg())
        error = SimpleNamespace(domain=lambda: "AVFoundationErrorDomain", code=lambda: -11800,
                                localizedDescription=lambda: "private device details") if fail_photo else None

        def processed():
            callbacks.append("processed")
            delegate.captureOutput_didFinishProcessingPhoto_error_(None, photo, error)

        def finished():
            callbacks.append("finished")
            delegate.captureOutput_didFinishCaptureForResolvedSettings_error_(None, None, error)

        # Real native callbacks are deferred. An Event.wait() without pumping
        # the run loop never delivers these and reproduces the reported timeout.
        pending.extend([processed, finished])

    av = SimpleNamespace(
        AVMediaTypeVideo="video", AVAuthorizationStatusNotDetermined=0, AVAuthorizationStatusAuthorized=3,
        AVCaptureDevice=SimpleNamespace(authorizationStatusForMediaType_=lambda _: authorization[0],
                                       devicesWithMediaType_=lambda _: [object()] * device_count,
                                       requestAccessForMediaType_completionHandler_=request_access),
        AVCaptureDeviceInput=SimpleNamespace(deviceInputWithDevice_error_=lambda *_: (object(), None)),
        AVCaptureSession=SimpleNamespace(alloc=lambda: SimpleNamespace(init=lambda: session)),
        AVCapturePhotoOutput=SimpleNamespace(alloc=lambda: SimpleNamespace(init=lambda: SimpleNamespace(
            capturePhotoWithSettings_delegate_=capture,
        ))),
        AVCapturePhotoSettings=SimpleNamespace(photoSettingsWithFormat_=lambda value: value),
        AVVideoCodecKey="codec", AVVideoCodecTypeJPEG="jpeg",
    )
    monkeypatch.setitem(sys.modules, "AVFoundation", av)
    monkeypatch.setitem(sys.modules, "objc", SimpleNamespace(protocolNamed=lambda _: object()))
    monkeypatch.setitem(sys.modules, "Foundation", SimpleNamespace(
        NSObject=Object, NSDefaultRunLoopMode="default",
        NSDate=SimpleNamespace(dateWithTimeIntervalSinceNow_=lambda seconds: seconds),
        NSRunLoop=SimpleNamespace(currentRunLoop=lambda: SimpleNamespace(runMode_beforeDate_=pump)),
    ))
    monkeypatch.setattr(sys, "stdin", io.StringIO("capture\n"))
    _capture_worker(0)
    messages = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    if permission == 2 or device_count == 0:
        assert messages[0]["status"] == "error"
        session.startRunning.assert_not_called()
    else:
        assert messages[0]["status"] == "ready"
        assert messages[1]["status"] == ("error" if fail_photo else "frame")
        session.stopRunning.assert_called_once()
        if not fail_photo:
            frame = Image.open(io.BytesIO(base64.b64decode(messages[1]["jpeg"])))
            assert frame.size == (640, 480)
            assert callbacks == ["processed", "finished"]
        else:
            assert "AVFoundationErrorDomain" in messages[1]["reason"]
            assert "-11800" in messages[1]["reason"]
            assert "private device details" not in str(messages)


@pytest.mark.skipif(platform.system() != "Darwin", reason="Requires AVFoundation; does not open a camera")
def test_installed_native_photo_api_without_opening_camera():
    import AVFoundation as av
    import objc

    assert objc.protocolNamed("AVCapturePhotoCaptureDelegate") is not None
    settings = av.AVCapturePhotoSettings.photoSettingsWithFormat_({av.AVVideoCodecKey: av.AVVideoCodecTypeJPEG})
    assert settings is not None


@pytest.mark.skipif(platform.system() != "Darwin", reason="Requires Cocoa; does not open a camera")
def test_native_runloop_delivers_deferred_callback_without_opening_camera():
    import threading
    from Foundation import NSTimer

    event = threading.Event()
    timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(0.01, False, lambda _: event.set())
    try:
        assert _wait_for_event(event, 1)
    finally:
        timer.invalidate()


def test_native_wait_remains_bounded_when_callback_never_arrives(monkeypatch):
    import threading

    now = [0.0]
    ticks = []

    def pump(mode, deadline):
        ticks.append(deadline)
        now[0] = deadline
        return True

    monkeypatch.setattr("camera.monotonic", lambda: now[0])
    monkeypatch.setitem(sys.modules, "Foundation", SimpleNamespace(
        NSDefaultRunLoopMode="default",
        NSDate=SimpleNamespace(dateWithTimeIntervalSinceNow_=lambda interval: now[0] + interval),
        NSRunLoop=SimpleNamespace(currentRunLoop=lambda: SimpleNamespace(runMode_beforeDate_=pump)),
    ))
    assert not _wait_for_event(threading.Event(), 0.05)
    assert now[0] == pytest.approx(0.05)
    assert len(ticks) == 3


@pytest.mark.skipif(platform.system() != "Darwin" or os.getenv("RUN_CAMERA_TESTS") != "1",
                    reason="Opt-in live camera test; set RUN_CAMERA_TESTS=1 (no upload or recording)")
async def test_live_camera_captures_across_idle_periods_and_releases():
    async with MacCamera() as camera:
        process = camera.process
        previous = float("-inf")
        for _ in range(3):
            frame = await camera.capture()
            assert frame.captured_at > previous
            previous = frame.captured_at
            with Image.open(io.BytesIO(frame.jpeg)) as image:
                assert image.format == "JPEG"
                assert max(image.size) <= 640
                assert not image.getexif()
            del frame
            await asyncio.sleep(0.5)
    assert process.returncode == 0
    assert camera.process is None
