import asyncio
import base64
import io
from unittest.mock import call

import pytest
from PIL import Image

from desktop import DesktopStopped


async def test_retina_screenshot_uses_mouse_coordinates(desktop):
    image = Image.open(io.BytesIO(base64.b64decode(await desktop.screenshot())))
    assert image.size == desktop.dimensions == (100, 80)


async def test_scroll_directions_and_small_distances(desktop):
    await desktop.scroll(10, 20, scroll_x=150, scroll_y=1)
    desktop.gui.scroll.assert_called_once_with(-1)
    desktop.gui.hscroll.assert_called_once_with(2)


async def test_modifiers_are_released_if_click_fails(desktop):
    desktop.gui.click.side_effect = RuntimeError("OS error")
    with pytest.raises(RuntimeError, match="OS error"):
        await desktop.click(10, 20, "left", keys=["SHIFT"])
    desktop.gui.keyUp.assert_called_once_with("shift")
    assert desktop.gui.FAILSAFE is True


async def test_unicode_paste_restores_clipboard_even_on_error(desktop):
    desktop.gui.press.side_effect = RuntimeError("paste failed")
    with pytest.raises(RuntimeError, match="paste failed"):
        await desktop.type("café 👋")
    assert desktop.clipboard.copy.call_args_list == [call("café 👋"), call("previous clipboard")]
    desktop.gui.keyUp.assert_called_once_with("command")


async def test_stopped_and_out_of_bounds_actions_do_not_click(desktop):
    with pytest.raises(ValueError, match="outside"):
        await desktop.click(100, 0, "left")
    desktop.stop()
    with pytest.raises(DesktopStopped):
        await desktop.click(10, 20, "left")
    desktop.gui.click.assert_not_called()


async def test_corner_failsafe_blocks_screenshots_too(desktop):
    desktop.gui.failSafeCheck.side_effect = RuntimeError("corner stop")
    with pytest.raises(RuntimeError, match="corner stop"):
        await desktop.screenshot()
    desktop.gui.screenshot.assert_not_called()


async def test_cancelled_queued_os_call_cannot_run_after_new_task(desktop):
    # Hold the OS lock until the background call is queued, then cancel/restart.
    desktop._lock.acquire()
    task = asyncio.create_task(desktop.click(10, 20, "left"))
    await asyncio.sleep(0.02)
    desktop.stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    desktop.start()
    desktop._lock.release()
    # A new capture serializes behind the stale click; it must not execute that click.
    await desktop.screenshot()
    desktop.gui.click.assert_not_called()
