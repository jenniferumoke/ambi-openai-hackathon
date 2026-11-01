"""Bounded, in-memory context shared by observation-only sidecars.

This module has no model, audio, or desktop action handles. Publishers run on
the same asyncio loop; snapshots are independent copies containing no images.
"""

from __future__ import annotations

import asyncio
import copy
import math
from collections import deque
from dataclasses import asdict
from time import monotonic

from proactive_controller import TurnContext

SOURCES = ("camera", "computer")


class ObservationHub:
    def __init__(self, enabled_sources=SOURCES, *, max_pair_skew=8, history_limit=12, mode="observation_only"):
        self.mode = mode
        self.enabled_sources = frozenset(enabled_sources)
        if not self.enabled_sources <= set(SOURCES):
            raise ValueError("Unknown observation source.")
        if not math.isfinite(max_pair_skew) or max_pair_skew < 0 or history_limit < 1:
            raise ValueError("Invalid observation alignment or history limit.")
        self.max_pair_skew = max_pair_skew
        self.version = 0
        self._records = {source: None for source in SOURCES}
        self._status = {source: ("waiting", "awaiting_observation") if source in self.enabled_sources
                        else ("disabled", "not_enabled") for source in SOURCES}
        self._watermarks = {source: float("-inf") for source in SOURCES}
        self._history = deque(maxlen=history_limit)

    def _changed(self, source, event, reason, at):
        self.version += 1
        self._history.append({"version": self.version, "source": source, "event": event,
                              "reason": reason, "at": at})

    def publish(self, source, *, observed_at, expires_at, payload, now=None):
        now = monotonic() if now is None else now
        if source not in SOURCES:
            raise ValueError("Unknown observation source.")
        if source not in self.enabled_sources:
            return False
        if not all(math.isfinite(value) for value in (observed_at, expires_at, now)):
            return False
        if observed_at > now or expires_at <= now or expires_at <= observed_at:
            return False
        if observed_at <= self._watermarks[source]:
            return False
        previous = self._records[source]
        record = {"observed_at": observed_at, "expires_at": expires_at, "payload": copy.deepcopy(payload)}
        self._records[source] = record
        self._watermarks[source] = observed_at
        changed = self._status[source][0] != "available" or previous is None or previous["payload"] != payload
        self._status[source] = ("available", None)
        if changed:
            self._changed(source, "updated", "observation_changed", observed_at)
        else:
            # Freshness advances even when the meaning stays the same. History
            # keeps meaningful changes only, rather than every repeated sample.
            self.version += 1
        return True

    def unavailable(self, source, reason, *, status="unavailable", now=None):
        if source not in SOURCES:
            raise ValueError("Unknown observation source.")
        now = monotonic() if now is None else now
        if self._records[source] is not None or self._status[source] != (status, reason):
            self._records[source] = None
            self._status[source] = (status, reason)
            self._changed(source, "cleared", reason, now)

    def snapshot(self, *, now=None, context=TurnContext()):
        now = monotonic() if now is None else now
        sources = {}
        for source in SOURCES:
            record = self._records[source]
            if record is not None and now >= record["expires_at"]:
                self.unavailable(source, "expired", now=now)
                record = None
            status, reason = self._status[source]
            sources[source] = {"status": status, "reason": reason, **(copy.deepcopy(record) if record else {})}
        available = [self._records[source] for source in SOURCES]
        skew = abs(available[0]["observed_at"] - available[1]["observed_at"]) if all(available) else None
        aligned = skew is not None and skew <= self.max_pair_skew
        return {
            "version": self.version, "mode": self.mode, **sources,
            "pair": {"aligned": aligned, "skew_seconds": round(skew, 3) if skew is not None else None,
                     "reason": "aligned" if aligned else "observations_too_far_apart" if skew is not None else "source_unavailable"},
            "runtime": asdict(context),
        }

    @property
    def history(self):
        return copy.deepcopy(list(self._history))


async def log_joint_observations(hub, *, log, context=lambda: TurnContext()):
    """Expose combined context to the terminal; never send it to voice."""
    previous = None
    while True:
        snapshot = hub.snapshot(context=context())
        key = (snapshot["version"], tuple(snapshot["runtime"].items()))
        if key != previous:
            log("joint_observation", **snapshot)
            previous = key
        await asyncio.sleep(0.25)
