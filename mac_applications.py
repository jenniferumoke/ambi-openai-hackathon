"""Narrow native app launch/read-back; no shell, URLs, documents or arbitrary code."""
from __future__ import annotations

import time
import threading

APPLICATIONS = {
    "chrome": "com.google.Chrome", "safari": "com.apple.Safari",
    "tv": "com.apple.TV", "textedit": "com.apple.TextEdit",
    "calculator": "com.apple.calculator",
}


def window_on_display(bounds, display):
    """Require positive-area intersection in Quartz global coordinates."""
    x, y, width, height = (float(bounds.get(k, 0)) for k in ("X", "Y", "Width", "Height"))
    dx, dy, dw, dh = display
    return (width > 0 and height > 0 and min(x + width, dx + dw) > max(x, dx)
            and min(y + height, dy + dh) > max(y, dy))


def visual_target_ready(application):
    """Read metadata only; never capture or type into an unrelated frontmost app."""
    import AppKit
    import ApplicationServices as AX
    import Quartz
    if application not in APPLICATIONS or not AX.AXIsProcessTrusted():
        return False
    front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    if front is None or front.bundleIdentifier() != APPLICATIONS[application]:
        return False
    app = AX.AXUIElementCreateApplication(front.processIdentifier())
    AX.AXUIElementSetMessagingTimeout(app, 0.3)
    error, window = AX.AXUIElementCopyAttributeValue(app, AX.kAXFocusedWindowAttribute, None)
    if error or window is None:
        return False
    error, value = AX.AXUIElementCopyAttributeValue(window, AX.kAXPositionAttribute, None)
    if error or value is None:
        return False
    valid, point = AX.AXValueGetValue(value, AX.kAXValueCGPointType, None)
    display = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    return bool(valid and display.origin.x <= point.x < display.origin.x + display.size.width
                and display.origin.y <= point.y < display.origin.y + display.size.height)


def observe_application(application):
    """Read-only application state for progress checks; no launch or window changes."""
    import AppKit
    if application not in APPLICATIONS:
        raise ValueError('Unsupported application identity.')
    workspace = AppKit.NSWorkspace.sharedWorkspace()
    apps = [app for app in workspace.runningApplications() if app.bundleIdentifier() == APPLICATIONS[application]]
    front = workspace.frontmostApplication()
    return {'application':application, 'running':bool(apps),
            'frontmost':bool(front and front.bundleIdentifier()==APPLICATIONS[application]),
            'focused_window_ready_on_primary':bool(apps and visual_target_ready(application))}


def move_focused_window_to_primary(pid, primary, *, exit_full_screen=False, check=lambda: None):
    """Move only this application's focused window after an explicit request."""
    import ApplicationServices as AX
    import Quartz
    if not AX.AXIsProcessTrusted():
        return {"requested": True, "verified_on_primary": False, "reason": "accessibility_unavailable"}
    app = AX.AXUIElementCreateApplication(pid)
    AX.AXUIElementSetMessagingTimeout(app, 0.3)
    check()
    error, window = AX.AXUIElementCopyAttributeValue(app, AX.kAXFocusedWindowAttribute, None)
    if error or window is None:
        return {"requested": True, "verified_on_primary": False, "reason": "focused_window_unavailable"}
    if exit_full_screen:
        check()
        error, full_screen = AX.AXUIElementCopyAttributeValue(window, "AXFullScreen", None)
        if error:
            error2, movable = AX.AXUIElementIsAttributeSettable(window, AX.kAXPositionAttribute, None)
            if error2 or not movable:
                return {"requested": True, "verified_on_primary": False, "reason": "full_screen_state_unavailable"}
            full_screen = False
        if full_screen:
            error, settable = AX.AXUIElementIsAttributeSettable(window, "AXFullScreen", None)
            if error or not settable:
                return {"requested": True, "verified_on_primary": False, "reason": "full_screen_not_settable"}
            check()
            if AX.AXUIElementSetAttributeValue(window, "AXFullScreen", False):
                return {"requested": True, "verified_on_primary": False, "reason": "full_screen_exit_rejected"}
            for _ in range(30):
                check()
                error, full_screen = AX.AXUIElementCopyAttributeValue(window, "AXFullScreen", None)
                error2, movable = AX.AXUIElementIsAttributeSettable(window, AX.kAXPositionAttribute, None)
                if not error and not full_screen and not error2 and movable:
                    break
                time.sleep(0.1)
    error, settable = AX.AXUIElementIsAttributeSettable(window, AX.kAXPositionAttribute, None)
    if error or not settable:
        return {"requested": True, "verified_on_primary": False, "reason": "window_position_not_settable"}
    point = Quartz.CGPointMake(primary[0] + 40, primary[1] + 60)
    value = AX.AXValueCreate(AX.kAXValueCGPointType, point)
    check()
    error = AX.AXUIElementSetAttributeValue(window, AX.kAXPositionAttribute, value)
    if error:
        return {"requested": True, "verified_on_primary": False, "reason": "window_move_rejected"}
    check()
    error, value = AX.AXUIElementCopyAttributeValue(window, AX.kAXPositionAttribute, None)
    if error or value is None:
        return {"requested": True, "verified_on_primary": False, "reason": "position_readback_unavailable"}
    valid, actual = AX.AXValueGetValue(value, AX.kAXValueCGPointType, None)
    verified = bool(valid and primary[0] <= actual.x < primary[0] + primary[2]
                    and primary[1] <= actual.y < primary[1] + primary[3])
    return {"requested": True, "verified_on_primary": verified}


def open_application(application, *, bring_to_primary=False, exit_full_screen=False, check=lambda: None):
    """Open an allowlisted app and report observed state, excluding window titles."""
    if application not in APPLICATIONS:
        raise ValueError("Choose chrome, safari, tv, textedit or calculator.")
    if exit_full_screen and not bring_to_primary:
        raise ValueError("Explicit full-screen exit is available only with primary-window targeting.")
    import AppKit
    import Quartz

    check()
    workspace = AppKit.NSWorkspace.sharedWorkspace()
    bundle_id = APPLICATIONS[application]
    url = workspace.URLForApplicationWithBundleIdentifier_(bundle_id)
    if url is None:
        return {"application": application, "installed": False, "running": False}
    completed = threading.Event()
    launched = []
    def did_launch(app, error):
        launched.extend((app, error))
        completed.set()
    configuration = AppKit.NSWorkspaceOpenConfiguration.configuration()
    configuration.setActivates_(True)
    check()
    workspace.openApplicationAtURL_configuration_completionHandler_(url, configuration, did_launch)
    for _ in range(100):
        check()
        if completed.wait(0.1):
            break
    if not completed.is_set():
        return {"application": application, "installed": True, "running": None,
                "detail": "Native launch acknowledgement timed out; outcome is unverified. Do not replay automatically."}
    running, error = launched
    if running is None or error is not None:
        return {"application": application, "installed": True, "running": False,
                "detail": "Native launch did not return a running application."}
    check()
    activation_accepted = bool(running.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps))
    # Launch completion can precede activation; read back after a bounded wait.
    for _ in range(15):
        check()
        front = workspace.frontmostApplication()
        if front and front.bundleIdentifier() == bundle_id:
            break
        time.sleep(0.1)
    windows = []
    for _ in range(30):
        check()
        windows = [window for window in (Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID) or [])
            if window.get("kCGWindowOwnerPID") == running.processIdentifier()
            and window.get("kCGWindowLayer") == 0]
        if windows or running.isTerminated():
            break
        time.sleep(0.1)
    display = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    primary = (display.origin.x, display.origin.y, display.size.width, display.size.height)
    move = ({"requested": False} if not bring_to_primary else
            move_focused_window_to_primary(running.processIdentifier(), primary,
                                          exit_full_screen=exit_full_screen, check=check))
    if bring_to_primary:
        check()
        activation_accepted = bool(running.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps))
        for _ in range(15):
            check()
            front = workspace.frontmostApplication()
            if front and front.bundleIdentifier() == bundle_id:
                break
            time.sleep(0.1)
        windows = [window for window in (Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID) or [])
            if window.get("kCGWindowOwnerPID") == running.processIdentifier()
            and window.get("kCGWindowLayer") == 0]
    frontmost = workspace.frontmostApplication()
    check()
    return {"application": application, "installed": True,
            "running": not running.isTerminated(),
            "activation_accepted": activation_accepted,
            "frontmost": bool(frontmost and frontmost.bundleIdentifier() == bundle_id),
            "focused_window_move": move,
            "visible_window_count": len(windows),
            "window_on_primary_display": any(window_on_display(w.get("kCGWindowBounds", {}), primary) for w in windows),
            "detail": "Observed native app/window metadata. Use screenshots to verify page or document contents."}
