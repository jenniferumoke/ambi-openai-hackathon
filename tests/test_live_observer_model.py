"""Explicit opt-in model check with synthetic screen data, never the user's screen."""
import io
import os
import asyncio
import array
import random
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from dotenv import load_dotenv
from openai import AsyncOpenAI
from PIL import Image, ImageDraw, ImageFont

from screen_capture import ScreenFrame
from screen_observer import ScreenAnalyzer, ScreenObservationSettings


@pytest.mark.skipif(os.getenv("RUN_LIVE_OBSERVER_TESTS") != "1", reason="Opt-in paid API check on synthetic audio")
async def test_transcription_rejects_synthetic_keyboard_clicks():
    from agents.realtime import RealtimeModelSendRawMessage
    from main import Settings, create_voice_runner
    from proactive_controller import TurnActivity
    from voice_input import SpeechGate

    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not configured")
    rng = random.Random(12)
    samples = array.array("h")
    for i in range(48000):
        offset = i % 4800
        samples.append(int(rng.uniform(-9000, 9000) * (1 - offset / 720)) if offset < 720 else 0)
    runner = create_voice_runner(SimpleNamespace(perform=AsyncMock(), stop=AsyncMock()), Settings())
    activity = TurnActivity(confirmed_input_only=True)
    logs = []
    gate = SpeechGate(activity, log=lambda event, **fields: logs.append((event, fields)))
    async with await runner.run() as session:
        # Commit exactly one synthetic buffer, independent of VAD segmentation.
        await session.model.send_event(RealtimeModelSendRawMessage(message={
            "type": "session.update", "other_data": {"session": {"type": "realtime",
            "audio": {"input": {"turn_detection": None}},
            "include": ["item.input_audio_transcription.logprobs"]}},
        }))
        await session.send_audio(samples.tobytes(), commit=True)
        async with asyncio.timeout(30):
            async for event in session:
                assert event.type not in ("audio", "error"), event
                if event.type == "raw_model_event" and event.data.type == "raw_server_event":
                    raw = event.data.data
                    await gate.on_event(raw, session, SimpleNamespace(clear=Mock()))
                    if raw.get("type") == "conversation.item.input_audio_transcription.completed":
                        break
        assert [name for name, _ in logs] == ["voice_input_rejected"], logs
        assert activity.user_turn_generation == 0


@pytest.mark.skipif(os.getenv("RUN_LIVE_OBSERVER_TESTS") != "1", reason="Opt-in paid API check on synthetic data")
@pytest.mark.parametrize("case", ["wrong_result", "normal_editing"])
async def test_model_recognizes_wrong_algorithm_result(case):
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not configured")
    image = Image.new("RGB", (1400, 900), "#202124")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 26)
    lines = [
        "Python editor - Two Sum exercise", "",
        "Goal: Return two indices whose values sum to target.", "",
        "def two_sum(nums, target):",
        "    if target in nums:",
        "        return nums.index(target)", "",
        "print(two_sum([2, 7, 11, 15], 9))", "",
        "Terminal:", "None", "Process exited with code 0",
    ]
    if case == "normal_editing":
        lines = lines[:5] + ["    # Starting implementation", "    pass", "", "Terminal: (no runs yet)"]
    for index, line in enumerate(lines):
        draw.text((35, 30 + index * 48), line, font=font, fill="white")
    output = io.BytesIO()
    image.save(output, format="JPEG")
    async with AsyncOpenAI(timeout=30, max_retries=0) as client:
        analyzer = ScreenAnalyzer(client, ScreenObservationSettings())
        result = await analyzer.analyze(ScreenFrame(monotonic(), output.getvalue(), "Editor", "synthetic-task"))
    if case == "wrong_result":
        assert result.task_failure, result.model_dump()
        assert result.noteworthy and result.progress == "blocked", result.model_dump()
    else:
        assert not result.task_failure and not result.noteworthy, result.model_dump()
