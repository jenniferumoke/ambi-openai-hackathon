"""Deterministic metrics. Missing denominators stay null, errors never pass."""
from __future__ import annotations

from collections import Counter
import math

INTERVENTIONS = {"offer", "offer_task_help", "acknowledge_progress"}
INTERVENTION_SUITES = {"policy", "scheduler", "classifier"}


def percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * quantile
    low, high = math.floor(rank), math.ceil(rank)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (rank - low), 3)


def ratio(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else None


def summarize(results):
    counts = Counter(row["status"] for row in results)
    tp = fp = fn = tn = positive_total = negative_total = error_opportunities = 0
    confusion = Counter()
    for row in results:
        if row["suite"] not in INTERVENTION_SUITES:
            continue
        for index, expected in enumerate(row["expected"]):
            positive = expected in INTERVENTIONS
            positive_total += positive
            negative_total += not positive
            if row["status"] == "error":
                error_opportunities += 1
                confusion[(expected, "ERROR")] += 1
                # Failure to produce an intervention is still a missed opportunity.
                fn += positive
                continue
            predicted = row["actual"][index] if index < len(row["actual"]) else "MISSING"
            confusion[(expected, predicted)] += 1
            intervened = predicted in INTERVENTIONS
            tp += positive and intervened
            fp += not positive and intervened
            fn += positive and not intervened
            tn += not positive and not intervened
    latencies = [row["duration_ms"] for row in results if row["status"] != "error"]
    return {
        "total": len(results), "passed": counts["pass"], "failed": counts["fail"], "errors": counts["error"],
        "pass_rate": ratio(counts["pass"], len(results)),
        "critical_failures": sum(row["critical"] and row["status"] != "pass" for row in results),
        "false_interruptions": fp, "quiet_opportunities": negative_total,
        "false_interruption_rate": ratio(fp, negative_total),
        "missed_help": fn, "help_opportunities": positive_total, "missed_help_rate": ratio(fn, positive_total),
        "intervention_precision": ratio(tp, tp + fp), "intervention_recall": ratio(tp, positive_total),
        "error_opportunities": error_opportunities,
        "latency_p50_ms": percentile(latencies, .5), "latency_p95_ms": percentile(latencies, .95),
        "confusion": [{"expected": a, "actual": b, "count": n} for (a, b), n in sorted(confusion.items())],
    }


def report_metrics(results):
    overall = summarize(results)
    # Mixed-suite wall times are not a useful latency metric.
    overall.pop("latency_p50_ms")
    overall.pop("latency_p95_ms")
    return {"overall": overall, "suites": {suite: summarize([r for r in results if r["suite"] == suite])
            for suite in sorted({row["suite"] for row in results})}}
