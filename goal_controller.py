"""Bounded execute/check/replan loop with private, text-only checkpoints."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class GoalReview(BaseModel):
    status: Literal['achieved', 'continue', 'needs_user', 'blocked']
    summary: str = Field(max_length=2000)
    evidence_ids: list[str] = Field(max_length=8)
    strategy: Literal['none', 'observe_again', 'refocus_target', 'alternative_ui', 'continue_steps']
    next_step: str = Field(max_length=2000)
    requires_approval: bool


@dataclass
class ExecutionReport:
    summary: str
    error_type: str | None = None
    recoverable: bool = True


@dataclass
class CheckedReview:
    review: GoalReview
    observed_ids: set[str]
    contradictions: tuple[str, ...] = ()


@dataclass
class GoalOutcome:
    goal_id: str
    status: str
    summary: str


class GoalJournal:
    def __init__(self, db):
        self.db = db
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS companion_goals (id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL)')
            # Restart never silently replays desktop work.
            db.execute("UPDATE companion_goals SET status='paused' WHERE status='running'")

    def get(self, goal_id):
        row = self.db.execute('SELECT status,payload FROM companion_goals WHERE id=?', (goal_id,)).fetchone()
        if not row:
            return None
        data = json.loads(row[1])
        return {**data, 'id': goal_id, 'status': row[0]}

    def latest_paused(self):
        row = self.db.execute("SELECT id FROM companion_goals WHERE status='paused' ORDER BY updated_at DESC LIMIT 1").fetchone()
        return self.get(row[0]) if row else None

    def latest_resumable(self):
        row = self.db.execute("SELECT id FROM companion_goals WHERE status IN ('paused','cancelled') ORDER BY updated_at DESC LIMIT 1").fetchone()
        return self.get(row[0]) if row else None

    def save(self, goal_id, status, *, task, plan, summary='', round=0):
        data = {'task': task[:4000], 'plan': plan[:2000], 'summary': summary[:2000], 'round': round}
        with self.db:
            self.db.execute('INSERT INTO companion_goals VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,payload=excluded.payload,updated_at=excluded.updated_at',
                (goal_id, status, json.dumps(data), datetime.now(timezone.utc).isoformat()))


class GoalController:
    def __init__(self, *, journal=None, max_rounds=6, timeout=900, emit=None):
        if not 1 <= max_rounds <= 20 or not 0 < timeout <= 3600:
            raise ValueError('Goal budget must be 1–20 rounds and at most 3600 seconds.')
        self.journal = journal
        self.max_rounds, self.timeout = max_rounds, timeout
        self.emit = emit or (lambda *args, **kwargs: None)

    async def run(self, task, execute, check, *, resume_goal_id=None):
        saved = self.journal.get(resume_goal_id) if self.journal and resume_goal_id else None
        if resume_goal_id and (not saved or saved['status'] not in {'paused','cancelled'}):
            raise ValueError('Only a saved paused or stopped goal can be explicitly resumed.')
        goal_id = resume_goal_id or uuid4().hex
        task = saved['task'] if saved else task
        plan = saved['plan'] if saved else task
        summary = saved['summary'] if saved else ''
        round_offset = saved.get('round',0) if saved else 0
        round_number = round_offset

        def checkpoint(status):
            if self.journal:
                self.journal.save(goal_id, status, task=task, plan=plan, summary=summary, round=round_number)
            self.emit('goal_checkpoint', goal_id=goal_id, status=status, round=round_number)

        def finish(status, detail):
            nonlocal summary
            summary = detail
            checkpoint(status)
            return GoalOutcome(goal_id, status, detail)

        checkpoint('running')
        seen_plans = {}
        try:
            async with asyncio.timeout(self.timeout):
                for attempt in range(1, self.max_rounds + 1):
                    round_number = round_offset + attempt
                    if saved:
                        # A resumed goal checks today's state before taking another action.
                        report = ExecutionReport('Resuming from a text checkpoint; prior actions must be revalidated. ' + summary)
                        saved = None
                    else:
                        report = await execute(task, plan, summary)
                    if not report.recoverable:
                        return finish('paused', 'Paused for your review: ' + report.summary)
                    self.emit('goal_review_started', goal_id=goal_id, round=round_number)
                    checked = await check(task, report)
                    review = checked.review
                    fresh = bool(review.evidence_ids) and set(review.evidence_ids).issubset(checked.observed_ids)
                    summary = review.summary
                    self.emit('goal_review', goal_id=goal_id, round=round_number,
                              decision=review.status, summary=summary)
                    if review.requires_approval:
                        return finish('paused', 'Your approval is needed: ' + summary)
                    if review.status in {'needs_user', 'blocked'}:
                        return finish('paused', 'Paused: ' + summary)
                    if not fresh:
                        return finish('paused', 'The result could not be checked with fresh evidence. ' + summary)
                    if review.status == 'achieved':
                        if checked.contradictions:
                            return finish('paused', 'Fresh read-back contradicts completion: ' + '; '.join(checked.contradictions))
                        return finish('achieved', summary)
                    if not review.next_step.strip() or review.strategy == 'none':
                        return finish('paused', 'No permitted next step was established. ' + summary)
                    key = (review.strategy, ' '.join(review.next_step.casefold().split()),
                           ' '.join(review.summary.casefold().split()))
                    seen_plans[key] = seen_plans.get(key, 0) + 1
                    if seen_plans[key] > 2:
                        return finish('paused', 'The same approach repeated without a verified result. ' + summary)
                    plan = review.next_step
                    checkpoint('running')
                    self.emit('goal_next_step', goal_id=goal_id, round=round_number,
                              strategy=review.strategy, summary=plan)
                return finish('paused', 'The review-round budget was reached. Progress is checkpointed. ' + summary)
        except TimeoutError:
            return finish('paused', 'The task time budget was reached. Review current state before resuming. ' + summary)
        except asyncio.CancelledError:
            finish('cancelled', 'Stopped by request. Earlier actions are not undone.')
            raise
        except Exception as exc:
            return finish('paused', f'Progress is checkpointed after {type(exc).__name__}. No action was automatically replayed.')
