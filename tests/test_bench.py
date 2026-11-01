"""Tests for graders and evidence integrity; not a requirement that AMBI scores 100%."""
import asyncio
import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from bench.code_check import evaluate
from bench.metrics import summarize
from bench.runner import BenchRunner, RunConfig, load_cases, select_cases
from bench.server import create_app
from bench.workspaces import WorkspaceLab

GOOD_CODE = '''def two_sum(nums, target):
    seen = {}
    for i, value in enumerate(nums):
        other = target - value
        if other in seen:
            return [seen[other], i]
        seen[value] = i
    return None
'''
GOOD_PLAN = {"as_of":"2026-11-01", "currency":"GBP", "total_unpaid":153,
             "overdue_ids":["BILL-103"], "queue":[
                 {"id":"BILL-103", "amount":28, "due":"2026-10-30"},
                 {"id":"BILL-101", "amount":85, "due":"2026-11-03"},
                 {"id":"BILL-102", "amount":40, "due":"2026-11-07"}]}
GOOD_BRIEF = '''# Summary
Repair cafe: 14 November 2026, 10:00–13:00, Maple Community Hall, 12 Example Lane.
Free entry, no booking.
# Decisions
Use the main hall. Serve tea and biscuits.
# Actions
- Rowan: confirm volunteer rota by 5 November.
- Ellis: prepare invitation by 6 November.
# Open questions
Repair-station count is unconfirmed.
'''


def row(expected, actual, status="pass", critical=False):
    return dict(suite="policy", expected=expected, actual=actual, status=status, critical=critical, duration_ms=1)


def test_metrics_expose_trivial_baselines_and_errors():
    quiet = summarize([row(["offer"], ["ignore"], "fail"), row(["ignore"], ["ignore"])])
    assert quiet["false_interruption_rate"] == 0
    assert quiet["missed_help_rate"] == 1
    assert quiet["intervention_precision"] is None
    loud = summarize([row(["offer"], ["offer"]), row(["ignore"], ["offer"], "fail")])
    assert loud["false_interruption_rate"] == 1
    errors = summarize([row(["offer"], [], "error", True), row(["ignore"], [], "error")])
    assert errors["passed"] == 0 and errors["errors"] == 2
    assert errors["critical_failures"] == 1 and errors["missed_help"] == 1
    assert errors["error_opportunities"] == 2
    assert errors["latency_p50_ms"] is None


def test_dataset_ids_splits_and_baseline_scope():
    _, cases, _ = load_cases()
    assert len(cases) == 62
    assert {c.split for c in cases} == {"dev", "holdout"}
    assert len(select_cases(cases, RunConfig())) == 50
    assert {c.suite for c in select_cases(cases, RunConfig(adapter="always_quiet"))} == {"policy"}
    assert len(select_cases(cases, RunConfig(mode="live"))) == 12


async def test_immediate_cancel_is_persisted(tmp_path):
    runner = BenchRunner(tmp_path)
    run_id = runner.start(RunConfig())
    await runner.cancel()
    report = runner.read_report(run_id)
    assert report["status"] == "cancelled" and report["completed"] == 0
    assert report["metrics"]["overall"]["pass_rate"] is None
    assert not (tmp_path / "running.lock").exists()


async def test_baseline_runs_without_key_and_preserves_report(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runner = BenchRunner(tmp_path)
    run_id = runner.start(RunConfig(mode="live", adapter="always_quiet"))
    await runner.task
    report = runner.read_report(run_id)
    assert report["execution"] == "baseline" and report["completed"] == 12
    assert report["metrics"]["overall"]["missed_help_rate"] == 1
    assert report["model"] is None
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        runner.start(RunConfig(mode="live"))


async def test_adapter_errors_never_leak_provider_messages(tmp_path, monkeypatch):
    from bench import runner as module
    async def failing(_):
        raise RuntimeError("private credential should never appear")
    monkeypatch.setitem(module.OFFLINE_ADAPTERS, "speech", failing)
    runner = BenchRunner(tmp_path)
    runner.start(RunConfig())
    await runner.task
    assert len([r for r in runner.current["results"] if r["suite"] == "speech" and r["status"] == "error"]) == 8
    assert "private credential" not in json.dumps(runner.current)


async def test_changed_sources_block_new_runs(tmp_path, monkeypatch):
    from bench import runner as module
    runner = BenchRunner(tmp_path)
    monkeypatch.setattr(module, "source_hash", lambda: "changed")
    with pytest.raises(ValueError, match="Restart"):
        runner.start(RunConfig())


def test_api_requires_token_and_same_origin(tmp_path):
    with TestClient(create_app(output_dir=tmp_path)) as client:
        assert client.post("/api/prepare", json={"scenario":"bills"}).status_code == 403
        assert client.get("/api/bootstrap", headers={"origin":"https://untrusted.example"}).status_code == 403
        data = client.get("/api/bootstrap").json()
        headers = {"x-bench-token":data["token"]}
        assert client.post("/api/prepare", json={"scenario":"bills"}, headers={**headers,"origin":"https://untrusted.example"}).status_code == 403
        created = client.post("/api/prepare", json={"scenario":"bills"}, headers=headers)
        assert created.status_code == 201
        verified = client.post("/api/verify", json={"id":created.json()["id"]}, headers=headers)
        assert verified.json()["status"] == "failed"
        assert client.post("/api/run", json={"unexpected": True}, headers=headers).status_code == 400
        assert client.get("/app.js").status_code == 200


@pytest.mark.parametrize("scenario", ["bills", "documents", "code"])
def test_fresh_workspaces_fail_then_correct_artifacts_pass(tmp_path, scenario):
    lab = WorkspaceLab(tmp_path)
    item = lab.prepare(scenario)
    assert lab.verify(item["id"])["status"] == "failed"
    folder = Path(item["path"])
    outputs = {"bills":("outputs/payment-plan.json",json.dumps(GOOD_PLAN)),
               "documents":("outputs/meeting-brief.md", GOOD_BRIEF), "code":("exercise.py",GOOD_CODE)}
    name, content = outputs[scenario]
    (folder / name).write_text(content)
    assert lab.verify(item["id"])["status"] == "passed"
    protected = folder / ("README.md" if scenario == "code" else "TASK.md")
    protected.write_text("Modified input")
    assert lab.verify(item["id"])["status"] == "failed"


def test_bills_reject_paid_extra_and_wrong_totals(tmp_path):
    lab = WorkspaceLab(tmp_path)
    item = lab.prepare("bills")
    output = Path(item["path"]) / "outputs/payment-plan.json"
    for plan in [{**GOOD_PLAN, "total_unpaid":213}, {**GOOD_PLAN, "queue":list(reversed(GOOD_PLAN["queue"]))},
                 {**GOOD_PLAN,"queue":[*GOOD_PLAN["queue"],{"id":"BILL-100","amount":60,"due":"2026-10-28"}]}, [], "not a plan"]:
        output.write_text(json.dumps(plan))
        assert lab.verify(item["id"])["status"] == "failed"


def test_documents_reject_owner_deadline_swap_and_stale_facts(tmp_path):
    lab = WorkspaceLab(tmp_path)
    item = lab.prepare("documents")
    output = Path(item["path"]) / "outputs/meeting-brief.md"
    for text in [GOOD_BRIEF.replace("5 November", "6 November"), GOOD_BRIEF.replace("14 November", "15 November"), GOOD_BRIEF.replace("unconfirmed", "four")]:
        output.write_text(text)
        assert lab.verify(item["id"])["status"] == "failed"


def test_workspace_cannot_read_symlink_outside_folder(tmp_path):
    lab = WorkspaceLab(tmp_path / "lab")
    item = lab.prepare("bills")
    outside = tmp_path / "private.json"
    outside.write_text("private")
    (Path(item["path"]) / "outputs/payment-plan.json").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        lab.verify(item["id"])
    with pytest.raises(ValueError):
        lab.verify("../../private.json")


def test_code_checker_requires_behavior_not_successful_exit():
    assert all(c["passed"] for c in evaluate(GOOD_CODE))
    assert not all(c["passed"] for c in evaluate("def two_sum(nums, target):\n    return None\n"))
    assert not all(c["passed"] for c in evaluate("def two_sum(nums, target):\n    return [0, 0]\n"))


@pytest.mark.parametrize("source", ["import os\n", "def two_sum(nums, target):\n    return open('/etc/passwd')", "def two_sum(nums, target):\n    return nums.__class__", "@print\ndef two_sum(nums, target):\n    return None", "def two_sum(nums, target):\n    return two_sum(nums, target)"])
def test_code_checker_rejects_external_access_and_recursion(source):
    with pytest.raises(ValueError):
        evaluate(source)
