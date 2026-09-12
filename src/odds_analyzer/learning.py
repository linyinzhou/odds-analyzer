"""Append-only forecasts and chronological evaluation, with no model dependencies."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any

from odds_analyzer.calibration import apply_confidence_calibration, build_strategy_performance, strategy_key
from odds_analyzer.models import MatchScore
from odds_analyzer.prediction_settlement import settle_saved_prediction

BEIJING = timezone(timedelta(hours=8))
RULE_VERSION = "market-rules-v2-staking"
CALIBRATION_VERSION = "frozen-walk-forward-v1"
POLICY = "first-valid-prematch-per-fixture"


def timestamp(value: Any, *, kickoff: bool = False) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace(" Asia/Shanghai", "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=BEIJING) if kickoff else None
        return parsed
    except (TypeError, ValueError):
        return None


def now_iso() -> str:
    return datetime.now(BEIJING).isoformat(timespec="microseconds")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def fixture_identity(match: dict) -> str:
    provider_id = (match.get("football_data_snapshot") or {}).get("match_id")
    if provider_id:
        return f"football-data:{provider_id}"
    # Do not use batch ids: daily and ad hoc requests can refer to the same game.
    kickoff = timestamp(match.get("kickoff_time"), kickoff=True)
    parts = [str(match.get(key) or "").strip().casefold() for key in ("home_team", "away_team")]
    parts.append(kickoff.astimezone(timezone.utc).isoformat() if kickoff else str(match.get("kickoff_time")))
    return "fixture:" + digest(parts)[:24]


def valid_prediction(match: dict) -> bool:
    prediction = match.get("prediction") or {}
    if prediction.get("betting_eligible") is False:
        return False
    keys = prediction.get("selection_keys")
    if not isinstance(keys, list) or not keys or len(set(keys)) != len(keys):
        return False
    if any(key not in {"home", "draw", "away"} for key in keys):
        return False
    base = prediction.get("base_confidence", prediction.get("confidence"))
    if isinstance(base, bool) or not isinstance(base, (int, float)) or not 0 < base < 100:
        return False
    confidence = prediction.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 < confidence < 100:
        return False
    market = prediction.get("market_type")
    if market not in {"asian_handicap", "sporttery_handicap", "sporttery_standard"}:
        return False
    if market != "sporttery_standard" and prediction.get("home_handicap") is None:
        return False
    try:
        return settle_saved_prediction(match, MatchScore(0, 0)) is not None
    except (ValueError, TypeError, OverflowError):
        return False


def freeze_predictions(payload: dict, matches: list[dict], recorded_at: str | None = None, *, batch_date: str = "") -> None:
    """Record at actual generation/import time, never a user-supplied research time."""
    recorded_at = recorded_at or now_iso()
    recorded = timestamp(recorded_at)
    if recorded is None:
        raise ValueError("recorded_at must include a timezone")
    archive = payload.setdefault("prediction_archive", [])
    known = {item["snapshot_id"] for item in archive}
    for match in matches:
        kickoff = timestamp(match.get("kickoff_time"), kickoff=True)
        reason = None
        if kickoff is None:
            reason = "unknown_kickoff"
        elif recorded >= kickoff:
            reason = "recorded_after_kickoff"
        elif match.get("review") or match.get("result_snapshot") or match.get("final_score"):
            reason = "result_already_present"
        elif not valid_prediction(match):
            reason = "no_valid_recommendation"
        frozen = deepcopy(match)
        for key in ("review", "result_snapshot", "review_error", "final_score"):
            frozen.pop(key, None)
        snapshot = {
            "fixture_key": fixture_identity(match), "recorded_at": recorded_at,
            "batch_date": str(match.get("batch_date") or batch_date),
            "rule_version": RULE_VERSION, "selection_policy": POLICY,
            "eligible": reason is None, "exclusion_reason": reason, "match": frozen,
        }
        snapshot["snapshot_id"] = digest(snapshot)
        if snapshot["snapshot_id"] not in known:
            archive.append(snapshot)
            known.add(snapshot["snapshot_id"])
    payload["learning_evaluation"] = evaluate_archive(payload)


def verify_record(record: dict, key: str) -> None:
    if record.get(key) != digest({name: value for name, value in record.items() if name != key}):
        raise ValueError(f"Modified archive record: {record.get(key)}")


def selected_snapshots(payload: dict) -> list[dict]:
    selected = {}
    for snapshot in sorted(payload.get("prediction_archive", []), key=lambda item: (timestamp(item["recorded_at"]), item["snapshot_id"])):
        verify_record(snapshot, "snapshot_id")
        if snapshot.get("eligible"):
            selected.setdefault(snapshot["fixture_key"], snapshot)
    return list(selected.values())


def available_results(payload: dict, before: datetime | None = None) -> dict[str, dict]:
    results = {}
    for observation in sorted(payload.get("result_archive", []), key=lambda item: (timestamp(item["observed_at"]), item["result_id"])):
        verify_record(observation, "result_id")
        observed = timestamp(observation.get("observed_at"))
        if observed is not None and (before is None or observed < before):
            results[observation["fixture_key"]] = observation
    return results


def record_result(payload: dict, snapshot: dict, home: int, away: int, observed_at: str, *, status: str = "FINISHED", source: str = "football-data.org") -> None:
    observed = timestamp(observed_at)
    kickoff = timestamp(snapshot["match"].get("kickoff_time"), kickoff=True)
    if observed is None or kickoff is None or observed <= kickoff:
        return
    if status != "FINISHED" or any(type(value) is not int or value < 0 for value in (home, away)):
        return
    observation = {
        "fixture_key": snapshot["fixture_key"], "home_goals": home, "away_goals": away,
        "observed_at": observed_at, "status": status, "source": source,
    }
    archive = payload.setdefault("result_archive", [])
    latest = available_results(payload).get(snapshot["fixture_key"])
    # An unchanged re-review must not move the first-known result timestamp.
    if latest and all(latest.get(key) == observation[key] for key in ("home_goals", "away_goals", "status", "source")):
        return
    observation["result_id"] = digest(observation)
    if not any(item["result_id"] == observation["result_id"] for item in archive):
        archive.append(observation)


def training_performance(payload: dict, as_of: str) -> dict:
    cutoff = timestamp(as_of)
    if cutoff is None:
        raise ValueError("as_of must include a timezone")
    results = available_results(payload, cutoff)
    rows, ids = [], []
    for snapshot in selected_snapshots(payload):
        if timestamp(snapshot["recorded_at"]) >= cutoff:
            continue
        result = results.get(snapshot["fixture_key"])
        if result is None:
            continue
        match = deepcopy(snapshot["match"])
        decision = settle_saved_prediction(match, MatchScore(result["home_goals"], result["away_goals"]))
        if decision is None or decision["void"]:
            continue
        match["batch_date"] = snapshot["batch_date"]
        match["review"] = {"reviewed": True, **decision}
        rows.append(match)
        ids.append({"snapshot_id": snapshot["snapshot_id"], "result_id": result["result_id"]})
    performance = build_strategy_performance(rows, as_of)
    performance.update({"as_of": as_of, "version": CALIBRATION_VERSION, "selection_policy": POLICY, "training_records": ids})
    return performance


def calibrate_predictions(payload: dict, matches: list[dict], as_of: str) -> tuple[list[dict], dict]:
    performance = training_performance(payload, as_of)
    calibrated = [apply_confidence_calibration(match, performance) for match in matches]
    for match in calibrated:
        calibration = (match.get("prediction") or {}).get("calibration")
        if calibration is not None:
            calibration.update({"version": CALIBRATION_VERSION, "as_of": as_of,
                                "training_digest": digest(performance["training_records"])})
    return calibrated, performance


def _prices(value: Any, keys: tuple[str, ...]) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        prices = {key: float(value[key]) for key in keys}
        return prices if all(math.isfinite(price) and price > 1 for price in prices.values()) else None
    except (KeyError, TypeError, ValueError):
        return None


def market_prices(match: dict) -> dict | None:
    prediction = match["prediction"]
    market = prediction["market_type"]
    if market == "asian_handicap":
        asian = match.get("asian_handicap") or {}
        if asian.get("handicap") != prediction.get("home_handicap"):
            return None
        prices = _prices(asian, ("home_odds", "away_odds"))
        return {"home": prices["home_odds"], "away": prices["away_odds"]} if prices else None
    lottery = match.get("chinese_lottery") or {}
    if market == "sporttery_handicap" and lottery.get("handicap") != prediction.get("home_handicap"):
        return None
    return _prices(lottery.get("standard" if market == "sporttery_standard" else "handicap_odds"), ("home", "draw", "away"))


def market_probability(match: dict) -> float | None:
    prediction = match["prediction"]
    if prediction["market_type"] == "asian_handicap":
        # Refunded stakes make inverse odds incompatible with P(positive settlement).
        if abs(float(prediction["home_handicap"])) % 1 != 0.5:
            return None
    prices = market_prices(match)
    if not prices:
        return None
    total = sum(1 / price for price in prices.values())
    return sum(1 / prices[key] for key in prediction["selection_keys"]) / total


def unit_profit(match: dict, decision: dict) -> float | None:
    prices = market_prices(match)
    if not prices:
        return None
    keys = match["prediction"]["selection_keys"]
    if match["prediction"]["market_type"] == "asian_handicap":
        settlement = decision["settlement"]
        return settlement * (prices[keys[0]] - 1) if settlement > 0 else settlement
    # Normalize the frozen integer allocation to one total unit; legacy rows use equal stakes.
    winning = decision["settlement"]
    plan = match["prediction"].get("staking_plan")
    if plan is not None:
        if plan.get("status") != "feasible":
            return None
        stakes = {row["selection"]: row["stake"] for row in plan.get("allocations", [])}
        if set(stakes) != set(keys) or any(type(value) is not int or value <= 0 or value % 2 for value in stakes.values()):
            return None
        total = sum(stakes.values())
        returned = ((Decimal(str(prices[winning])) * stakes[winning]).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                    if winning in stakes else Decimal(0))
        return float((returned - total) / total)
    return (prices[winning] / len(keys) if winning in keys else 0) - 1


def _scores(pairs: list[tuple[float, bool]]) -> dict:
    if not pairs:
        return {"n": 0, "brier": None, "log_loss": None}
    clipped = [(max(1e-12, min(1 - 1e-12, p)), y) for p, y in pairs]
    return {"n": len(pairs), "brier": round(sum((p - y) ** 2 for p, y in pairs) / len(pairs), 6),
            "log_loss": round(-sum(math.log(p if y else 1 - p) for p, y in clipped) / len(pairs), 6)}


def _summary(rows: list[dict]) -> dict:
    scoring = [row for row in rows if row["hit"] is not None]
    paired = [row for row in scoring if row["market_probability"] is not None]
    profits = [row["unit_profit"] for row in rows if row["unit_profit"] is not None]
    base = _scores([(row["base"], row["hit"]) for row in scoring])
    calibrated = _scores([(row["calibrated"], row["hit"]) for row in scoring])
    return {
        "settled": len(rows), "outcomes": dict(Counter(row["outcome"] for row in rows)),
        "hit_rate_excluding_push": round(sum(row["hit"] for row in scoring) / len(scoring), 6) if scoring else None,
        "base": base, "calibrated": calibrated,
        "brier_delta": round(calibrated["brier"] - base["brier"], 6) if scoring else None,
        "market_paired": {name: _scores([(row[field], row["hit"]) for row in paired])
                          for name, field in (("market", "market_probability"), ("base", "base"), ("calibrated", "calibrated"))},
        "roi": {"priced_n": len(profits), "missing_prices": len(rows) - len(profits),
                "unit_profit": round(sum(profits), 6), "return_per_unit": round(sum(profits) / len(profits), 6) if profits else None},
    }


def evaluate_archive(payload: dict) -> dict:
    selected = selected_snapshots(payload)
    results = available_results(payload)
    rows, excluded = [], Counter()
    for snapshot in payload.get("prediction_archive", []):
        if not snapshot.get("eligible"):
            excluded[snapshot.get("exclusion_reason") or "ineligible"] += 1
    for snapshot in selected:
        result = results.get(snapshot["fixture_key"])
        if result is None:
            continue
        match = snapshot["match"]
        prediction = match["prediction"]
        calibration = prediction.get("calibration") or {}
        # Replay only the calibration, using the frozen base and results known THEN.
        # Never reconstruct pre-match features from today's mutable dashboard rows.
        as_of = timestamp(calibration.get("as_of"))
        valid = (calibration.get("version") == CALIBRATION_VERSION and as_of is not None
                 and as_of <= timestamp(snapshot["recorded_at"]))
        if valid:
            exact, exact_performance = calibrate_predictions(payload, [match], calibration["as_of"])
            expected = exact[0]["prediction"]["confidence"]
            valid = (expected == prediction["confidence"] and
                     digest(exact_performance["training_records"]) == calibration.get("training_digest"))
        if not valid:
            excluded["unverifiable_calibration"] += 1
            continue
        decision = settle_saved_prediction(match, MatchScore(result["home_goals"], result["away_goals"]))
        if decision is None:
            excluded["unsupported_settlement"] += 1
            continue
        rows.append({
            "snapshot_id": snapshot["snapshot_id"], "fixture_key": snapshot["fixture_key"],
            "recorded_at": snapshot["recorded_at"], "batch_date": snapshot["batch_date"],
            "strategy": strategy_key(match), "rule_version": snapshot["rule_version"],
            "result_id": result["result_id"], "training_sample": (exact_performance["strategies"].get(strategy_key(match)) or {}).get("sample_size", 0),
            "base": float(prediction.get("base_confidence", prediction["confidence"])) / 100,
            "calibrated": float(prediction["confidence"]) / 100, "replayed_confidence": expected,
            "market_probability": market_probability(match), "unit_profit": unit_profit(match, decision),
            "hit": decision["hit"], "outcome": decision["outcome"],
        })
    by_strategy, by_period = defaultdict(list), defaultdict(list)
    for row in rows:
        by_strategy[f"{row['rule_version']}:{row['strategy']}"].append(row)
        day = timestamp(row["recorded_at"]).astimezone(BEIJING).date()
        week = day - timedelta(days=day.weekday())
        by_period[week.isoformat()].append(row)
    return {
        "version": CALIBRATION_VERSION, "selection_policy": POLICY, "status": "collecting" if not rows else "diagnostic",
        "snapshot_count": len(payload.get("prediction_archive", [])), "selected_fixtures": len(selected),
        "observed_fixtures": len({item["fixture_key"] for item in payload.get("prediction_archive", [])}),
        "pending_results": sum(item["fixture_key"] not in results for item in selected),
        "duplicate_versions_excluded": sum(bool(s.get("eligible")) for s in payload.get("prediction_archive", [])) - len(selected),
        "mutable_checker_rows_not_used": len(payload.get("checker_history", [])),
        "exclusions": dict(excluded), "overall": _summary(rows),
        "by_strategy": {key: _summary(value) for key, value in sorted(by_strategy.items())},
        "weekly_walk_forward": [{"week_start": key, **_summary(value)} for key, value in sorted(by_period.items())],
        "rows": rows,
        "limitations": ["Confidence is a heuristic score; Brier/log loss here diagnose treating it as P(positive settlement | no push).",
                        "Base and calibration have identical picks: hit rate and ROI cannot improve from confidence changes alone.",
                        "Market comparison uses the same event and paired subset; integer/quarter Asian lines have no compatible binary market baseline.",
                        "Legacy mutable records are not backfilled as frozen predictions. No automatic promotion or accuracy claim."],
    }


def merge_learning_archives(preferred: dict, other: dict) -> dict:
    """Preserve both ledgers even when UI payload selection prefers stale main data."""
    merged = deepcopy(preferred)
    for collection, key in (("prediction_archive", "snapshot_id"), ("result_archive", "result_id")):
        records = {}
        for item in [*preferred.get(collection, []), *other.get(collection, [])]:
            if item[key] in records and records[item[key]] != item:
                raise ValueError(f"Conflicting immutable record: {item[key]}")
            records[item[key]] = deepcopy(item)
        merged[collection] = list(records.values())
    merged["learning_evaluation"] = evaluate_archive(merged)
    return merged
