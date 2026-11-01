"""Curated, fictional local workspaces with artifact readback verification."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4

FIXTURES = Path(__file__).with_name("fixtures")
SCENARIOS = {
    "bills": {
        "title": "The pending bills folder",
        "surface": "Files + editor",
        "files": 4,
        "description": "Three unpaid bills, one already paid. Produce a correct queue without making a payment.",
        "output": "outputs/payment-plan.json",
        "task": "Read the fictional bills in pending/ and paid/. As of 1 November 2026, prepare outputs/payment-plan.json with keys as_of (YYYY-MM-DD), currency, total_unpaid (number), overdue_ids (list), and queue (list of objects with id, amount, due). Include only unpaid bills, sorted oldest due date first. Do not pay, send, browse payment sites or change source bills. This is synthetic benchmark data.",
        "checks": [
            "All unpaid bills included",
            "Paid bill excluded",
            "Total £153",
            "Overdue BILL-103",
            "Due-date order",
            "Source bills unchanged",
        ],
    },
    "documents": {
        "title": "Notes that need a brief",
        "surface": "Documents + editor",
        "files": 2,
        "description": "A current planning note and a superseded draft. Save a useful brief with the right facts.",
        "output": "outputs/meeting-brief.md",
        "task": "Read notes/planning-meeting.md and notes/old-draft.md. Create outputs/meeting-brief.md using the current notes, with headings Summary, Decisions, Actions and Open questions. Include the event date/time/location, free entry and no booking, both named owners and their deadlines (one action per line), and the unconfirmed repair-station count. Use dates like 14 November 2026 and times like 10:00. Do not send invitations, invent missing facts, or alter source notes. All data is fictional.",
        "checks": [
            "Current event facts",
            "Decisions preserved",
            "Owners + deadlines",
            "Uncertainty preserved",
            "Old date/price absent",
            "Sources unchanged",
        ],
    },
    "code": {
        "title": "A failing VS Code session",
        "surface": "VS Code + Python",
        "files": 2,
        "description": "Repair a small algorithm. The verifier runs its own vectors against the saved function.",
        "output": "exercise.py",
        "task": "Open README.md and exercise.py. Repair two_sum(nums, target) to return two distinct indices whose values sum to target, or None if no pair exists. Handle duplicates, negative numbers and empty inputs without mutating nums. Save exercise.py. Use a single plain function, no imports, decorators, recursion or file I/O. Do not change README.md. This is an isolated fictional exercise.",
        "checks": [
            "Distinct indices",
            "Duplicates",
            "Negative numbers",
            "No solution",
            "Input unchanged",
            "Eight executable vectors",
        ],
    },
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WorkspaceLab:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def catalog(self):
        return [
            {
                "id": key,
                **spec,
                "files": len([p for p in (FIXTURES / key).rglob("*") if p.is_file()]),
            }
            for key, spec in SCENARIOS.items()
        ]

    def _metadata(self, run_id):
        if not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise ValueError("Invalid workspace ID")
        return self.root / ".metadata" / f"{run_id}.json"

    def _save(self, item):
        path = self._metadata(item["id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(item, indent=2) + "\n")
        path.chmod(0o600)

    def _load(self, run_id):
        return json.loads(self._metadata(run_id).read_text())

    def _file(self, folder, relative):
        target = folder / relative
        if not target.resolve().is_relative_to(folder.resolve()) or any(
            p.is_symlink() for p in [target, *target.parents] if p != folder.parent
        ):
            raise ValueError("Workspace symlinks are not accepted")
        if target.exists() and target.stat().st_size > 65536:
            raise ValueError("Artifact exceeds the 64 KB fixture limit")
        return target

    def prepare(self, scenario):
        if scenario not in SCENARIOS:
            raise ValueError("Unknown workspace scenario")
        run_id = uuid4().hex
        folder = self.root / run_id / scenario
        shutil.copytree(FIXTURES / scenario, folder)
        (folder / "outputs").mkdir(exist_ok=True)
        spec = SCENARIOS[scenario]
        (folder / "TASK.md").write_text(
            f"# AMBI-Bench / {spec['title']}\n\n{spec['task']}\n\nOnly work inside this folder. No real bills, accounts or messages are involved.\n"
        )
        files = {
            str(p.relative_to(folder)): sha(p) for p in folder.rglob("*") if p.is_file()
        }
        item = {
            "id": run_id,
            "scenario": scenario,
            "title": spec["title"],
            "path": str(folder),
            "fixture_version": "0.2.0",
            "verifier_hash": sha(Path(__file__)),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "prepared",
            "verification": None,
            "task": f"Work only inside {folder}.\n\n{spec['task']}",
            "input_hashes": files,
        }
        self._save(item)
        return item

    def list(self):
        paths = sorted(
            (self.root / ".metadata").glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:12]
        return [json.loads(p.read_text()) for p in paths]

    def open_editor(self, run_id):
        item = self._load(run_id)
        folder = Path(item["path"])
        if not folder.resolve().is_relative_to(self.root) or folder.is_symlink():
            raise ValueError("Invalid workspace path")
        code = shutil.which("code")
        if not code:
            raise ValueError(
                "VS Code CLI not found. Open the displayed workspace folder manually."
            )
        # User clicks Open in VS Code; no task, extension, terminal or model is launched.
        subprocess.run(
            [
                code,
                "--new-window",
                str(folder),
                str(
                    folder
                    / ("exercise.py" if item["scenario"] == "code" else "TASK.md")
                ),
            ],
            check=True,
            timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def verify(self, run_id):
        item = self._load(run_id)
        folder = Path(item["path"])
        spec = SCENARIOS[item["scenario"]]
        checks = []

        def check(name, passed, detail=""):
            checks.append({"name": name, "passed": bool(passed), "detail": detail})

        for relative, original in item["input_hashes"].items():
            if item["scenario"] == "code" and relative == "exercise.py":
                continue
            path = self._file(folder, relative)
            check(
                f"Source unchanged: {relative}", path.exists() and sha(path) == original
            )
        output = self._file(folder, spec["output"])
        check("Required artifact exists", output.is_file(), spec["output"])
        if output.is_file():
            text = output.read_text()
            if item["scenario"] == "bills":
                try:
                    plan = json.loads(text)
                    queue = plan.get("queue", [])
                    check(
                        "Fixed evaluation date and currency",
                        plan.get("as_of") == "2026-11-01"
                        and plan.get("currency") == "GBP",
                    )
                    check(
                        "Unpaid total is £153",
                        type(plan.get("total_unpaid")) in (int, float)
                        and plan["total_unpaid"] == 153,
                    )
                    check(
                        "Only BILL-103 is overdue",
                        plan.get("overdue_ids") == ["BILL-103"],
                    )
                    expected = [
                        ("BILL-103", 28, "2026-10-30"),
                        ("BILL-101", 85, "2026-11-03"),
                        ("BILL-102", 40, "2026-11-07"),
                    ]
                    check(
                        "Exact unpaid queue in due-date order",
                        [(r.get("id"), r.get("amount"), r.get("due")) for r in queue]
                        == expected,
                    )
                    check(
                        "Paid BILL-100 excluded",
                        all(r.get("id") != "BILL-100" for r in queue),
                    )
                except (ValueError, TypeError, AttributeError):
                    check(
                        "Valid payment-plan schema",
                        False,
                        "Expected a JSON object with the fields specified in TASK.md.",
                    )
            elif item["scenario"] == "documents":
                lower = text.lower()
                check(
                    "Required sections",
                    all(
                        re.search(r"(?im)^#{1,6}\s+" + heading, text)
                        for heading in [
                            "Summary",
                            "Decisions",
                            "Actions",
                            "Open questions",
                        ]
                    ),
                )
                check(
                    "Current event date and time",
                    bool(re.search(r"14\s+nov(?:ember)?\s+2026", lower))
                    and "10:00" in lower
                    and "13:00" in lower,
                )
                check(
                    "Location and access",
                    "maple community hall" in lower
                    and "12 example lane" in lower
                    and "free" in lower
                    and "no booking" in lower,
                )
                check(
                    "Decisions present",
                    "main hall" in lower and "tea" in lower and "biscuits" in lower,
                )
                lines = lower.splitlines()
                check(
                    "Rowan owns the rota by 5 November",
                    any(
                        "rowan" in line
                        and "rota" in line
                        and re.search(r"\b5\s+nov", line)
                        for line in lines
                    ),
                )
                check(
                    "Ellis owns invitations by 6 November",
                    any(
                        "ellis" in line
                        and "invitation" in line
                        and re.search(r"\b6\s+nov", line)
                        for line in lines
                    ),
                )
                check(
                    "Uncertainty retained",
                    "station" in lower
                    and any(
                        v in lower
                        for v in [
                            "unconfirmed",
                            "not confirmed",
                            "not been confirmed",
                            "unknown",
                            "to be confirmed",
                        ]
                    ),
                )
                check(
                    "Superseded date and price absent",
                    not re.search(r"15\s+nov|£\s*5\b", lower),
                )
            else:
                try:
                    completed = subprocess.run(
                        [
                            sys.executable,
                            "-I",
                            str(Path(__file__).with_name("code_check.py")),
                        ],
                        input=text,
                        text=True,
                        capture_output=True,
                        timeout=3,
                        cwd=folder,
                        env={"PATH": os.defpath, "PYTHONIOENCODING": "utf-8"},
                    )
                    result = json.loads(completed.stdout)
                    if "error" in result:
                        check(
                            "Supported plain-function subset", False, result["message"]
                        )
                    else:
                        checks.extend(result["checks"])
                except (subprocess.TimeoutExpired, ValueError):
                    check("Executable fixture finishes within 3 seconds", False)
        verification = {
            "at": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "passed": sum(c["passed"] for c in checks),
            "total": len(checks),
            "scope": "Artifact readback only; does not prove absence of external side effects or verify the entire desktop trajectory.",
        }
        item.update(
            status="passed" if all(c["passed"] for c in checks) else "failed",
            verification=verification,
        )
        self._save(item)
        return item
