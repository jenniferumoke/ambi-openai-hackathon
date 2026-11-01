"""Sequential, cancellable benchmark execution and reproducible local reports."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from time import perf_counter
from typing import Literal
from uuid import uuid4

from agents import set_tracing_disabled
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from bench.adapters import OFFLINE_ADAPTERS, classifier_adapter
from bench.metrics import report_metrics

ROOT = Path(__file__).resolve().parents[1]
DATASET = Path(__file__).with_name("cases.json")


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def source_hash():
    paths = sorted([*ROOT.glob("*.py"), *Path(__file__).parent.glob("*.py")])
    return digest(b"".join(str(p.relative_to(ROOT)).encode() + b"\0" + p.read_bytes() for p in paths))


def git(*args):
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    suite: Literal["policy", "cues", "speech", "scheduler", "classifier"]
    category: str
    title: str
    input: dict
    expected: list[str] = Field(min_length=1)
    rationale: str
    critical: bool
    split: Literal["dev", "holdout"]


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["offline", "live"] = "offline"
    adapter: Literal["product", "always_quiet", "always_intervene"] = "product"
    split: Literal["all", "dev", "holdout"] = "all"


def load_cases(path=DATASET):
    raw = Path(path).read_bytes()
    dataset = json.loads(raw)
    cases = [Case.model_validate(c) for c in dataset["cases"]]
    if len({c.id for c in cases}) != len(cases):
        raise ValueError("Duplicate case IDs")
    return dataset, cases, digest(raw)


def select_cases(cases, config):
    selected = [c for c in cases if (c.suite == "classifier") == (config.mode == "live")
                and (config.split == "all" or c.split == config.split)]
    if config.adapter != "product":
        selected = [c for c in selected if c.suite in {"policy", "classifier"}]
    return selected


class BenchRunner:
    def __init__(self, output_dir=None):
        self.output_dir = Path(output_dir or ROOT / "data" / "bench")
        self.loaded_source_hash = source_hash()
        self.current = None
        self.task = None
        self._cancel = asyncio.Event()
        self.revision = 0

    @property
    def active(self):
        return self.task is not None and not self.task.done()

    def changed(self):
        self.revision += 1

    def catalog(self):
        dataset, cases, data_hash = load_cases()
        return {"version": dataset["version"], "hash": data_hash, "provenance": dataset["provenance"],
                "cases": [c.model_dump(exclude={"input"}) for c in cases],
                "api_configured": bool(os.getenv("OPENAI_API_KEY")),
                "model": os.getenv("DECISIONS_MODEL", "gpt-6-luna"),
                "restart_required": source_hash() != self.loaded_source_hash}

    def start(self, config: RunConfig):
        if self.active:
            raise ValueError("A benchmark is already running. Cancel it or wait for completion.")
        if source_hash() != self.loaded_source_hash:
            raise ValueError("Team code changed. Restart the benchmark server to load the new version.")
        if config.mode == "live" and config.adapter == "product" and not os.getenv("OPENAI_API_KEY"):
            raise ValueError("Live classifier evaluation needs the team's OPENAI_API_KEY. Offline suites are available now.")
        dataset, cases, data_hash = load_cases()
        cases = select_cases(cases, config)
        if not cases:
            raise ValueError("No cases match this configuration.")
        self._cancel = asyncio.Event()
        self.current = {
            "id": uuid4().hex, "status": "running", "started_at": timestamp(), "finished_at": None,
            "config": config.model_dump(), "total": len(cases), "completed": 0, "active_case": None,
            "results": [], "metrics": report_metrics([]), "dataset_version": dataset["version"],
            "dataset_hash": data_hash, "source_hash": self.loaded_source_hash,
            "commit": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
            "worktree_dirty": bool(git("status", "--porcelain")), "base_main": git("rev-parse", "origin/main"),
            "model": os.getenv("DECISIONS_MODEL", "gpt-6-luna") if config.mode == "live" and config.adapter == "product" else None,
            "execution": "live_model" if config.mode == "live" and config.adapter == "product" else
                         "baseline" if config.adapter != "product" else "offline_product_code",
        }
        self.changed()
        self.task = asyncio.create_task(self._run(cases, config))
        return self.current["id"]

    async def cancel(self):
        self._cancel.set()
        if self.active:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            # A task cancelled before its first tick never enters _run's finally.
            if self.current and self.current["status"] == "running":
                self.current.update(status="cancelled", active_case=None, finished_at=timestamp())
                self._save()
                self.changed()

    async def _run(self, cases, config):
        run = self.current
        client = None
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            (self.output_dir / "running.lock").write_text(json.dumps({"pid": os.getpid(), "run": run["id"]}))
            if run["execution"] == "live_model":
                client = AsyncOpenAI(timeout=12, max_retries=0)
                set_tracing_disabled(True)
            for case in cases:
                if self._cancel.is_set():
                    break
                run["active_case"] = case.id
                self.changed()
                await asyncio.sleep(0)  # Yield actual progress to connected clients.
                started = perf_counter()
                result = {**case.model_dump(), "actual": [], "status": "error", "detail": {}}
                try:
                    async with asyncio.timeout(15):
                        if config.adapter != "product":
                            quiet = config.adapter == "always_quiet"
                            prediction = ("ignore" if quiet else "offer") if case.suite == "policy" else ("none" if quiet else "offer_task_help")
                            actual, detail = [prediction] * (len(case.input["steps"]) if case.suite == "policy" else 1), {"implementation": config.adapter, "model_calls": 0}
                        elif case.suite == "classifier":
                            actual, detail = await classifier_adapter(case.input, client, run["model"])
                        else:
                            actual, detail = await OFFLINE_ADAPTERS[case.suite](case.input)
                    result.update(actual=actual, detail=detail, status="pass" if actual == case.expected else "fail")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # Never surface SDK exception text, response bodies or credentials.
                    result["detail"] = {"error_type": type(exc).__name__, "message": "Adapter failed; check compatibility, access or connectivity."}
                result["duration_ms"] = round((perf_counter() - started) * 1000, 3)
                run["results"].append(result)
                run["completed"] += 1
                run["metrics"] = report_metrics(run["results"])
                self._save()
                self.changed()
                # Stop paid runs after repeated infrastructure errors, preserving every result.
                if client and len(run["results"]) >= 3 and all(r["status"] == "error" for r in run["results"][-3:]):
                    run["stop_reason"] = "Stopped after three consecutive adapter errors; remaining cases were not evaluated."
                    break
            run["status"] = "cancelled" if self._cancel.is_set() else "completed" if run["completed"] == run["total"] else "incomplete"
        except asyncio.CancelledError:
            run["status"] = "cancelled"
        except Exception as exc:
            run["status"] = "error"
            run["stop_reason"] = f"Runner failed ({type(exc).__name__}); no unrun cases are counted as passes."
        finally:
            if client:
                await client.close()
            run["active_case"] = None
            run["finished_at"] = timestamp()
            run["source_changed_during_run"] = source_hash() != self.loaded_source_hash
            if run["source_changed_during_run"]:
                run["status"] = "invalidated"
                run["stop_reason"] = "Source changed during this run. Restart the server and rerun before comparing scores."
            try:
                self._save()
                (self.output_dir / "running.lock").unlink(missing_ok=True)
            finally:
                self.changed()

    def _save(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{self.current['id']}.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.current, indent=2, allow_nan=False) + "\n")
        temp.chmod(0o600)
        temp.replace(path)

    def history(self):
        rows = []
        for path in sorted(self.output_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:12]:
            try:
                run = json.loads(path.read_text())
                rows.append({key: run.get(key) for key in ("id", "status", "started_at", "config", "execution", "completed", "total", "metrics", "dataset_hash", "source_hash", "commit")})
            except (OSError, ValueError):
                continue
        return rows

    def read_report(self, run_id):
        if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
            raise ValueError("Invalid run ID")
        return json.loads((self.output_dir / f"{run_id}.json").read_text())
