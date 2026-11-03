import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx2 as httpx
import pytest
from agents.realtime.testing import ScriptedRealtimeModel
from agents.realtime.model_events import RealtimeModelToolCallEvent
from openai import APIConnectionError

import main


async def test_provider_failure_does_not_expose_request_details_or_replay_actions(desktop, monkeypatch):
    run = AsyncMock(side_effect=APIConnectionError(
        message="private-request-sentinel", request=httpx.Request("POST", "https://api.openai.com/v1/responses")))
    monkeypatch.setattr(main.Runner, "run", run)
    events = []
    worker = main.ComputerWorker(desktop, main.Settings(), emit=lambda name, **data: events.append((name, data)))
    result = await worker.perform("Open TV")
    assert "APIConnectionError" in result
    assert "private-request-sentinel" not in result
    assert "private-request-sentinel" not in str(events)
    assert "retry" in result.lower()
    assert run.await_count == 1
    assert desktop._stopped.is_set() and worker.active is None


async def test_native_app_action_uses_the_same_cancellation_generation(desktop, monkeypatch):
    launch = Mock(return_value={"application": "tv", "running": True})
    monkeypatch.setattr("mac_applications.open_application", launch)
    assert (await desktop.open_application("tv"))["running"] is True
    desktop.stop()
    with pytest.raises(main.DesktopStopped):
        await desktop.open_application("tv")
    assert launch.call_count == 1


async def test_native_target_blocks_unrelated_screen_and_input_before_os_calls(desktop, monkeypatch):
    monkeypatch.setattr('mac_applications.open_application', Mock(return_value={'running':True}))
    monkeypatch.setattr('mac_applications.visual_target_ready', lambda _:False)
    await desktop.open_application('tv')
    with pytest.raises(main.DesktopStopped, match='No screenshot or input'):
        await desktop.screenshot()
    with pytest.raises(main.DesktopStopped, match='No screenshot or input'):
        await desktop.type('synthetic test')
    desktop.gui.screenshot.assert_not_called()
    desktop.clipboard.copy.assert_not_called()
    desktop.start()
    await desktop.screenshot()
    desktop.gui.screenshot.assert_called_once()


async def test_mac_permission_revocation_blocks_launch_and_screen_before_os_calls(desktop,monkeypatch):
    monkeypatch.setattr('desktop.mac_permissions',lambda:{'Accessibility':False,'Screen Recording':True})
    launch=Mock()
    monkeypatch.setattr('mac_applications.open_application',launch)
    with pytest.raises(main.DesktopStopped,match='permissions'):
        await desktop.open_application('tv')
    with pytest.raises(main.DesktopStopped,match='permissions'):
        await desktop.screenshot()
    launch.assert_not_called()
    desktop.gui.screenshot.assert_not_called()


async def test_voice_exit_records_its_origin_without_user_text():
    exit_requested = asyncio.Event()
    events = []
    worker = SimpleNamespace(active=None, perform=AsyncMock(), stop=AsyncMock())
    model = ScriptedRealtimeModel(strict=False)
    runner = main.create_voice_runner(worker, main.Settings(), model=model,
        exit_requested=exit_requested, emit=lambda name, **data: events.append((name, data)))
    async with await runner.run() as session:
        await model.emit(RealtimeModelToolCallEvent(name="exit_agent", call_id="exit", arguments="{}"))
        async with asyncio.timeout(2):
            async for event in session:
                if event.type == "tool_end":
                    break
    assert exit_requested.is_set()
    assert events == [("session_end_requested", {"source": "voice_exit_agent"})]


def test_unknown_native_app_rejected_before_any_framework_access():
    from mac_applications import open_application
    with pytest.raises(ValueError, match="Choose"):
        open_application("/bin/sh")


@pytest.mark.parametrize("bounds,expected", [
    ({"X": 100, "Y": 100, "Width": 400, "Height": 300}, True),
    ({"X": -1600, "Y": 0, "Width": 1500, "Height": 900}, False),
    ({"X": 1920, "Y": 0, "Width": 1000, "Height": 900}, False),
    ({"X": -100, "Y": 0, "Width": 200, "Height": 900}, True),
    ({"X": 0, "Y": 0, "Width": 0, "Height": 900}, False),
])
def test_native_window_location_distinguishes_other_displays(bounds, expected):
    from mac_applications import window_on_display
    assert window_on_display(bounds, (0, 0, 1920, 1080)) is expected


def test_native_launch_reports_other_display_without_titles(monkeypatch):
    import mac_applications
    app = SimpleNamespace(processIdentifier=lambda: 42, isTerminated=lambda: False,
                          bundleIdentifier=lambda: 'com.apple.TV',activateWithOptions_=Mock(return_value=True))
    workspace = SimpleNamespace(URLForApplicationWithBundleIdentifier_=lambda _: object(),
        openApplicationAtURL_configuration_completionHandler_=lambda url, config, callback: callback(app, None),
        frontmostApplication=lambda: app)
    monkeypatch.setitem(sys.modules, 'AppKit', SimpleNamespace(
        NSApplicationActivateIgnoringOtherApps=2,
        NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: workspace),
        NSWorkspaceOpenConfiguration=SimpleNamespace(configuration=lambda: SimpleNamespace(setActivates_=Mock()))))
    monkeypatch.setitem(sys.modules, 'Quartz', SimpleNamespace(
        kCGWindowListOptionOnScreenOnly=1, kCGWindowListExcludeDesktopElements=2, kCGNullWindowID=0,
        CGMainDisplayID=lambda: 1,
        CGDisplayBounds=lambda _: SimpleNamespace(origin=SimpleNamespace(x=0,y=0),size=SimpleNamespace(width=1920,height=1080)),
        CGWindowListCopyWindowInfo=lambda *_: [
            {'kCGWindowOwnerPID':42,'kCGWindowLayer':0,'kCGWindowName':'private-title-sentinel',
             'kCGWindowBounds':{'X':-1600,'Y':0,'Width':1500,'Height':900}},
            {'kCGWindowOwnerPID':99,'kCGWindowLayer':0,'kCGWindowBounds':{'X':0,'Y':0,'Width':500,'Height':500}},
        ]))
    result = mac_applications.open_application('tv')
    assert result['running'] is True and result['frontmost'] is True
    app.activateWithOptions_.assert_called_once_with(2)
    assert result['visible_window_count'] == 1
    assert result['window_on_primary_display'] is False
    assert 'private-title-sentinel' not in str(result)


def test_windows_worker_keeps_existing_computer_tool_only(desktop, monkeypatch):
    monkeypatch.setattr('desktop.platform.system', lambda: 'Windows')
    worker = main.ComputerWorker(desktop, main.Settings())
    assert len(worker.agent.tools) == 1


def test_native_move_only_changes_selected_app_focused_window_and_reads_back(monkeypatch):
    from mac_applications import move_focused_window_to_primary
    changes = []
    def read(element, attribute, _):
        if attribute == 'focused':
            assert element == 'app-42'
            return 0, 'focused-window'
        assert element == 'focused-window' and attribute == 'position'
        return 0, 'readback'
    monkeypatch.setitem(sys.modules, 'ApplicationServices', SimpleNamespace(
        AXIsProcessTrusted=lambda: True, AXUIElementCreateApplication=lambda pid: f'app-{pid}',
        AXUIElementSetMessagingTimeout=lambda *_: 0, kAXFocusedWindowAttribute='focused',
        kAXPositionAttribute='position', kAXValueCGPointType=1,
        AXUIElementCopyAttributeValue=read,
        AXUIElementIsAttributeSettable=lambda *_: (0, True), AXValueCreate=lambda _,point: point,
        AXUIElementSetAttributeValue=lambda window,attr,value: changes.append((window,attr,value)) or 0,
        AXValueGetValue=lambda *_: (True, SimpleNamespace(x=40,y=60))))
    monkeypatch.setitem(sys.modules, 'Quartz', SimpleNamespace(CGPointMake=lambda x,y:(x,y)))
    result = move_focused_window_to_primary(42, (0,0,1920,1080))
    assert changes == [('focused-window','position',(40,60))]
    assert result == {'requested':True,'verified_on_primary':True}


def test_native_move_rejects_missing_permission_without_touching_app(monkeypatch):
    from mac_applications import move_focused_window_to_primary
    monkeypatch.setitem(sys.modules, 'ApplicationServices', SimpleNamespace(AXIsProcessTrusted=lambda:False))
    result = move_focused_window_to_primary(42, (0,0,1920,1080))
    assert result['verified_on_primary'] is False and result['reason']=='accessibility_unavailable'


@pytest.mark.parametrize('allow_exit', [False, True])
def test_full_screen_exit_requires_explicit_flag_and_reads_back(monkeypatch, allow_exit):
    from mac_applications import move_focused_window_to_primary
    state = {'fullscreen':True}
    changes = []
    def read(_, attribute, out):
        if attribute == 'focused':return 0, 'selected-window'
        if attribute == 'AXFullScreen':return 0, state['fullscreen']
        return 0, 'point'
    def write(window, attribute, value):
        changes.append((window,attribute,value))
        if attribute == 'AXFullScreen':state['fullscreen']=value
        return 0
    monkeypatch.setitem(sys.modules,'ApplicationServices',SimpleNamespace(
        AXIsProcessTrusted=lambda:True, AXUIElementCreateApplication=lambda _: 'app',
        AXUIElementSetMessagingTimeout=lambda *_:0, kAXFocusedWindowAttribute='focused',
        kAXPositionAttribute='position', kAXValueCGPointType=1,
        AXUIElementCopyAttributeValue=read, AXUIElementSetAttributeValue=write,
        AXUIElementIsAttributeSettable=lambda _,attr,out:(0, attr=='AXFullScreen' or not state['fullscreen']),
        AXValueCreate=lambda _,point:point, AXValueGetValue=lambda *_:(True,SimpleNamespace(x=40,y=60))))
    monkeypatch.setitem(sys.modules,'Quartz',SimpleNamespace(CGPointMake=lambda x,y:(x,y)))
    result=move_focused_window_to_primary(42,(0,0,1920,1080),exit_full_screen=allow_exit)
    assert result['verified_on_primary'] is allow_exit
    if allow_exit:
        assert changes == [('selected-window','AXFullScreen',False),('selected-window','position',(40,60))]
    else:
        assert changes == [] and state['fullscreen'] is True


@pytest.mark.parametrize('native_host', [True, False])
def test_native_host_skips_workspace_dotenv_but_cli_keeps_existing_behavior(monkeypatch, tmp_path, native_host):
    import companion_service
    import dotenv
    import server
    import uvicorn
    load = Mock()
    monkeypatch.setattr(dotenv, 'load_dotenv', load)
    monkeypatch.setattr(server, 'create_app', lambda **_: object())
    monkeypatch.setattr(uvicorn, 'run', Mock())
    monkeypatch.setattr(sys, 'argv', ['AmbiService'])
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    monkeypatch.setenv('AMBI_NATIVE_HOST', '1' if native_host else '0')
    monkeypatch.setenv('AMBI_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('AMBI_FRONTEND_ORIGINS', '')
    companion_service.main()
    assert load.call_count == (0 if native_host else 1)
