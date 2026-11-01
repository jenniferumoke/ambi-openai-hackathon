"""Profile loading and honest observation capture, without live models or sensors."""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from bench.profile_lab import ProfileLab, profiles
from bench.server import create_app
from memory_store import MemoryStore


@pytest.mark.parametrize("profile_id", ["rowan", "ellis", "nora"])
def test_profile_loads_real_memory_and_complete_sources(tmp_path, profile_id):
    lab = ProfileLab(tmp_path)
    first = lab.prepare(profile_id)
    second = lab.prepare(profile_id)
    assert first["id"] != second["id"]
    assert first["fixture_hash"] == second["fixture_hash"]
    assert first["profile_hash"] == second["profile_hash"]
    db = MemoryStore(Path(first["path"]) / "memory.sqlite3")
    try:
        records = db.list(limit=100)
        assert len(records) == len(first["profile"]["memory"]) + 1
        assert first["id"] in db.get("bench-profile-session")["body"]
        assert db.get("ambi-project-brief") is None
        assert any(m["status"] == "done" for m in records)
        assert all(m["source"].startswith("AMBI-Bench") for m in records)
    finally:
        db.close()
    for scenario in first["profile"]["scenarios"]:
        assert lab.source_file(first["id"], scenario["source"]).is_file()
        assert scenario["expectation"] in {"offer", "quiet"}
    assert "<html" in lab.source_file(first["id"], "desktop.html").read_text()
    assert len(first["profile"]["history"]) >= 6


def test_download_age_is_recreated_for_overlooked_bill(tmp_path):
    lab = ProfileLab(tmp_path)
    item = lab.prepare("rowan")
    file = lab.source_file(item["id"], "bills/pending/BILL-103.pdf")
    assert (
        datetime.fromtimestamp(file.stat().st_mtime).date().isoformat() == "2026-10-19"
    )
    assert file.read_bytes().startswith(b"%PDF-")


def test_profile_file_route_does_not_expose_memory_or_other_files(tmp_path):
    lab = ProfileLab(tmp_path)
    item = lab.prepare("nora")
    with pytest.raises(ValueError):
        lab.source_file(item["id"], "../memory.sqlite3")
    with pytest.raises(ValueError):
        lab.source_file(item["id"], "memory.sqlite3")
    original = lab.source_file(item["id"], "travel/README.md")
    original.unlink()
    outside = tmp_path / "private.txt"
    outside.write_text("private")
    original.symlink_to(outside)
    with pytest.raises(ValueError):
        lab.source_file(item["id"], "travel/README.md")


def test_email_preview_uses_real_headers_and_escapes_content(tmp_path):
    lab = ProfileLab(tmp_path)
    item = lab.prepare("nora")
    path = "travel/inbox/2026-10-30-hotel-hold.eml"
    email = lab.source_file(item["id"], path)
    email.write_text(email.read_text() + "\n<script>alert(1)</script>")
    page = lab.source_view(item["id"], path)
    assert "provisional room hold" in page and "reception@rowanhouse.example" in page
    assert "<script>" not in page and "&lt;script&gt;" in page


async def test_observation_excludes_greeting_and_review_is_explicitly_manual(
    tmp_path, monkeypatch
):
    lab = ProfileLab(tmp_path)
    item = lab.prepare("nora")
    snapshot = {
        "status": "connected",
        "phase": "ready",
        "focus": False,
        "camera": None,
        "suggestion": None,
        "transcript": [{"id": "greeting", "role": "assistant", "text": "Hello Nora"}],
    }

    async def read(_):
        return deepcopy(snapshot)

    monkeypatch.setattr(lab, "_app_snapshot", read)
    await lab.observe(item["id"], "hotel-hold")
    snapshot["transcript"].append(
        {
            "id": "offer",
            "role": "assistant",
            "text": "Your room hold expires tomorrow. Want help drafting a reply?",
        }
    )
    snapshot["transcript"].append(
        {"id": "user", "role": "user", "text": "Some private user speech"}
    )
    captured = await lab.capture(item["id"], "hotel-hold")
    observation = captured["observations"]["hotel-hold"]["captures"][0]
    assert observation["assistant_text"] == [snapshot["transcript"][1]["text"]]
    assert "private user speech" not in json.dumps(captured)
    saved = lab.review(
        item["id"], "hotel-hold", "helpful", "Grounded offer; nothing sent."
    )
    assert saved["reviews"][0]["assessment"].startswith("operator review")
    assert "score" not in saved["reviews"][0]


async def test_cannot_arm_during_greeting_or_capture_without_observation(
    tmp_path, monkeypatch
):
    lab = ProfileLab(tmp_path)
    item = lab.prepare("rowan")

    async def busy(_):
        return {"status": "connected", "phase": "speaking"}

    monkeypatch.setattr(lab, "_app_snapshot", busy)
    with pytest.raises(ValueError, match="greeting"):
        await lab.observe(item["id"], "overdue-invoice")
    with pytest.raises(ValueError, match="Begin observation"):
        await lab.capture(item["id"], "overdue-invoice")


async def test_capture_rejects_an_app_with_different_memory(tmp_path, monkeypatch):
    lab = ProfileLab(tmp_path)
    item = lab.prepare("rowan")
    lab.process = SimpleNamespace(poll=lambda: None)
    lab.active_id = item["id"]
    monkeypatch.setattr(
        "bench.profile_lab.read_app_state",
        lambda: {"memories": [{"id": "personal", "body": "Not the test profile"}]},
    )
    with pytest.raises(ValueError, match="No session data was captured"):
        await lab._app_snapshot(item["id"])


def test_profile_api_and_source_preview_roundtrip(tmp_path):
    with TestClient(create_app(output_dir=tmp_path)) as client:
        boot = client.get("/api/bootstrap").json()
        assert len(boot["profiles"]) == 3
        headers = {"x-bench-token": boot["token"]}
        assert (
            client.post("/api/profile-prepare", json={"profile": "rowan"}).status_code
            == 403
        )
        item = client.post(
            "/api/profile-prepare", json={"profile": "rowan"}, headers=headers
        ).json()
        assert (
            client.get(
                f"/profile-files/{item['id']}/bills/pending/BILL-103.pdf"
            ).headers["content-type"]
            == "application/pdf"
        )
        assert (
            client.get(f"/profile-files/{item['id']}/memory.sqlite3").status_code == 404
        )
        page = client.get(
            f"/profile-view/{item['id']}/bills/correspondence/2026-10-31-equipment-reminder.eml"
        )
        assert page.status_code == 200 and "Friendly reminder" in page.text
        response = client.post(
            "/api/profile-review",
            json={
                "id": item["id"],
                "scenario": "overdue-invoice",
                "verdict": "not_tested",
                "notes": "Awaiting live session",
            },
            headers=headers,
        )
        assert response.json()["reviews"][0]["verdict"] == "not_tested"
        assert client.get(f"/api/profile-report/{item['id']}").status_code == 403
        assert (
            client.get(f"/api/profile-report/{item['id']}", headers=headers).status_code
            == 200
        )


def test_all_profiles_have_both_help_and_quiet_scenarios():
    for profile in profiles():
        assert {s["expectation"] for s in profile["scenarios"]} == {"offer", "quiet"}
        assert profile["fictional"] is True


def test_team_app_keeps_cue_journals_inside_each_profile(tmp_path):
    from ambient import CuePacket
    from server import create_app as create_product_app

    lab = ProfileLab(tmp_path)
    one, two = lab.prepare("rowan"), lab.prepare("nora")
    apps = [
        create_product_app(db_path=Path(item["path"]) / "memory.sqlite3", seed=False)
        for item in (one, two)
    ]
    try:
        for app, item in zip(apps, (one, two)):
            assert app.state.cue_store.path.parent == Path(item["path"])
            assert app.state.memory.get("ambi-project-brief") is None
        apps[0].state.cue_store.record(
            CuePacket(
                stream_id="synthetic",
                sequence=0,
                usable=True,
                cues=["smiling"],
                scores={},
                age_ms=0,
                inference_ms=10,
                detection_ms=120,
            )
        )
        assert len(apps[0].state.cue_store.list()) == 1
        assert apps[1].state.cue_store.list() == []
    finally:
        for app in apps:
            app.state.memory.close()
            app.state.cue_store.close()
