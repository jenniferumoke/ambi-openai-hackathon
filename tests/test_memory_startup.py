import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from memory_store import MemoryStore
from proactive_controller import TurnActivity
from startup import greet_on_start


def test_memory_survives_restart_and_deleted_items_stay_deleted(tmp_path):
    path = tmp_path / "memory.db"
    store = MemoryStore(path)
    item = store.put(kind="task", title="Prepare brief", body="Use the customer notes.", source="My notes")
    store.complete(item["id"])
    store.close()
    reopened = MemoryStore(path)
    assert reopened.get(item["id"])["status"] == "done"
    assert json.loads(reopened.brief())[0]["source"] == "My notes"
    assert reopened.delete(item["id"])
    reopened.close()
    final = MemoryStore(path)
    assert final.list() == []
    final.close()


def test_memory_search_is_literal_and_brief_is_bounded(tmp_path):
    store = MemoryStore(tmp_path / "db")
    for i in range(15):
        store.put(kind="note", title=f"Note {i}", body="x" * 4000)
    assert store.list("%") == []
    brief = store.brief(max_chars=2000)
    assert len(brief) <= 2000 and json.loads(brief)
    store.close()


async def test_startup_uses_memory_without_waiting_for_user(tmp_path):
    store = MemoryStore(tmp_path / "db")
    store.put(kind="task", title="Prepare the pitch", source="You")
    send = AsyncMock(return_value=True)
    session = SimpleNamespace(model=SimpleNamespace(send_context_response=send))
    assert await greet_on_start(session, store, TurnActivity())
    payload = json.loads(send.call_args.args[0])
    assert payload["memory"][0]["title"] == "Prepare the pitch"
    assert send.call_args.kwargs["kind"] == "startup"
    store.close()


async def test_startup_yields_to_user(tmp_path):
    store = MemoryStore(tmp_path / "db")
    send = AsyncMock()
    activity = TurnActivity()
    activity.confirmed_speech()
    assert not await greet_on_start(SimpleNamespace(model=SimpleNamespace(send_context_response=send)), store, activity)
    send.assert_not_awaited()
    store.close()
