from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any


MINIMUM_SAMPLE = 20
MAX_ADJUSTMENT = 5


def strategy_key(match: dict[str, Any]) -> str | None:
    prediction = match.get("prediction") or {}
    if not prediction or prediction.get("market") == "无推荐":
        return None
    mismatch = match.get("mismatch") or {}
    if mismatch.get("matched") and mismatch.get("status"):
        return f"mismatch:{mismatch['status']}"
    market_type = prediction.get("market_type")
    return f"market:{market_type}" if market_type else None


def build_strategy_performance(
    checker_history: list[dict[str, Any]],
    generated_at: str | None = None,
    before_batch: str | None = None,
) -> dict[str, Any]:
    buckets: dict[str, list[tuple[bool, float]]] = {}
    latest_batch = ""
    for match in checker_history:
        batch_date = str(match.get("batch_date") or "")
        if before_batch and batch_date >= before_batch:
            continue
        review = match.get("review") or {}
        if not review.get("reviewed") or review.get("void"):
            continue
        key = strategy_key(match)
        confidence = (match.get("prediction") or {}).get("base_confidence")
        if confidence is None:
            confidence = (match.get("prediction") or {}).get("confidence")
        if key is None or not isinstance(confidence, (int, float)):
            continue
        buckets.setdefault(key, []).append((bool(review.get("hit")), float(confidence)))
        latest_batch = max(latest_batch, batch_date)

    strategies = {}
    for key, rows in sorted(buckets.items()):
        total = len(rows)
        hits = sum(hit for hit, _ in rows)
        hit_rate = hits / total
        average_confidence = sum(confidence for _, confidence in rows) / total
        active = total >= MINIMUM_SAMPLE
        adjustment = 0
        if active:
            gap = hit_rate * 100 - average_confidence
            shrinkage = total / (total + MINIMUM_SAMPLE)
            adjustment = round(gap * shrinkage * 0.5)
            adjustment = max(-MAX_ADJUSTMENT, min(MAX_ADJUSTMENT, adjustment))
        strategies[key] = {
            "sample_size": total,
            "hits": hits,
            "hit_rate": round(hit_rate, 4),
            "average_confidence": round(average_confidence, 1),
            "adjustment": adjustment,
            "active": active,
        }

    return {
        "generated_at": generated_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        "trained_through_batch": latest_batch or None,
        "minimum_sample": MINIMUM_SAMPLE,
        "max_adjustment": MAX_ADJUSTMENT,
        "strategies": strategies,
    }


def apply_confidence_calibration(
    match: dict[str, Any],
    performance: dict[str, Any] | None,
) -> dict[str, Any]:
    calibrated = deepcopy(match)
    prediction = calibrated.get("prediction") or {}
    confidence = prediction.get("confidence")
    key = strategy_key(calibrated)
    if key is None or not isinstance(confidence, (int, float)) or confidence <= 0:
        return calibrated

    base_confidence = prediction.get("base_confidence", confidence)
    strategy = ((performance or {}).get("strategies") or {}).get(key) or {}
    adjustment = int(strategy.get("adjustment") or 0) if strategy.get("active") else 0
    prediction["base_confidence"] = base_confidence
    prediction["confidence"] = max(1, min(99, round(float(base_confidence) + adjustment)))
    prediction["calibration"] = {
        "strategy": key,
        "status": "active" if strategy.get("active") else "collecting",
        "sample_size": int(strategy.get("sample_size") or 0),
        "minimum_sample": int((performance or {}).get("minimum_sample") or MINIMUM_SAMPLE),
        "adjustment": adjustment,
        "trained_through_batch": (performance or {}).get("trained_through_batch"),
    }
    calibrated["prediction"] = prediction
    return calibrated
