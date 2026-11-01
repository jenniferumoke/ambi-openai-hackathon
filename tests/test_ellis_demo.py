"""Demo data must not replace model decisions or prescribe answers."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from starlette.testclient import TestClient
from eval.test.demo import DemoProfile, ROOT, create_demo_app
from app_runtime import AppRuntime
from memory_store import MemoryStore
from proactive_controller import TurnActivity
from startup import greet_on_start

def test_demo_copies_ellis_and_isolates_editable_code_and_memory(tmp_path):
    source = json.loads((ROOT / "bench/profiles/ellis.json").read_text())
    original = (ROOT / "bench/fixtures/code/exercise.py").read_text()
    app = create_demo_app(root=tmp_path / "run", auto_start=False)
    with TestClient(app) as client:
        profile = app.state.runtime.demo_profile
        assert profile.data["memory"][:len(source["memory"])] == source["memory"]
        boot = client.get("/api/bootstrap").json()
        assert boot["state"]["status"] == "idle"
        assert boot["state"]["observations"]["mode"] == "ellis_demo"
        assert any(row["title"] == "Resolve PairMatch issue PM-17" for row in boot["state"]["memories"])
        assert app.state.memory.get("ambi-project-brief") is None
        assert app.state.memory.path == tmp_path / "run/memory.sqlite3"
        (profile.workspace / "exercise.py").write_text("# edited only in this run\n")
        assert (ROOT / "bench/fixtures/code/exercise.py").read_text() == original
    with pytest.raises(FileExistsError):
        create_demo_app(root=tmp_path / "run", auto_start=False)


async def test_demo_uses_normal_decisions_loop(tmp_path, monkeypatch):
    import app_runtime
    run = AsyncMock()
    loop = SimpleNamespace(run=run)
    factory = Mock(return_value=loop)
    monkeypatch.setattr(app_runtime, 'AmbientLoop', factory)
    memory = MemoryStore(tmp_path / 'memory.db')
    try:
        runtime = AppRuntime(memory, demo_profile=DemoProfile(tmp_path / 'code'))
        monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-test-key')
        await runtime._decisions()
        factory.assert_called_once()
        run.assert_awaited_once()
    finally:
        memory.close()


async def test_profile_and_greeting_contain_context_not_answer_scripts(tmp_path):
    profile = DemoProfile(tmp_path / 'code')
    assert 'demo' not in profile.data and 'scenarios' not in profile.data
    context = profile.system_context()
    assert 'PM-17' in context and 'Ellis Reed' in context
    for prohibited in ('opening_text', 'cue_mappings', 'action_catalog', 'suggestion.text'):
        assert prohibited not in context
    memory = MemoryStore(tmp_path / 'memory.db')
    try:
        profile.seed(memory)
        send = AsyncMock(return_value=True)
        session = SimpleNamespace(model=SimpleNamespace(send_context_response=send))
        assert await greet_on_start(session, memory, TurnActivity(), demo_profile=profile)
        assert 'opening_text' not in send.call_args.args[0]
        from startup import STARTUP_INSTRUCTIONS
        assert send.call_args.kwargs['instructions'] == STARTUP_INSTRUCTIONS
    finally:
        memory.close()
