"""Run selected observers and their joint terminal log without voice access."""

from __future__ import annotations

import asyncio

from expression_monitor import terminal_log
from observation_hub import ObservationHub, log_joint_observations
from proactive_controller import TurnContext


async def run_sidecars(camera_settings=None, screen_settings=None, *, device_index=0,
                       context=lambda: TurnContext(), log=None, hub=None, started=None):
    """Own observers until cancelled; signal when source initialization has begun.

    ``started`` does not wait for permissions, camera warmup, or model output.
    It lets the voice session connect after observation startup, independently
    of microphone input, while retaining ownership of every observer task.
    """
    sources = tuple(source for source, settings in (("camera", camera_settings), ("computer", screen_settings))
                    if settings is not None)
    hub = hub or ObservationHub(sources)
    emit = log or terminal_log
    emit("observation_starting", sources=list(sources), startup_trigger="session_start",
         waits_for_user_speech=False)
    observers = []
    options = {"context": context, **({"log": log} if log is not None else {})}
    if camera_settings is not None:
        from expression_monitor import run_observation

        observers.append(asyncio.create_task(run_observation(
            camera_settings, device_index=device_index, hub=hub, **options,
        )))
    if screen_settings is not None:
        from screen_observer import run_screen_observation

        observers.append(asyncio.create_task(run_screen_observation(screen_settings, hub, **options)))
    logger = asyncio.create_task(log_joint_observations(hub, log=log or terminal_log, context=context))
    try:
        # Give each source its first turn before permitting voice connection.
        # Source initialization may continue concurrently with that connection.
        await asyncio.sleep(0)
        if started is not None:
            started.set()
        if observers:
            await asyncio.gather(*observers)
    finally:
        # Only cancel once: a second cancellation can interrupt native cleanup.
        for task in (*observers, logger):
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*observers, logger, return_exceptions=True)
        (log or terminal_log)("joint_observation", **hub.snapshot(context=context()))
