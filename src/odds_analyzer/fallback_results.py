from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from odds_analyzer.dashboard_payload import upsert_history, with_batch_date, without_batch
from odds_analyzer.fallback_queue import missing_fields_for_match
from odds_analyzer.jobs.refresh_evening_slate import (
    BEIJING,
    _attach_bilingual_reports,
    _checker_candidates,
    _normalize_team,
)
from odds_analyzer.slate_analysis import analyze_slate_match


ALLOWED_FIELDS = {"fundamentals", "european_odds", "asian_handicap", "sporttery"}
FIELD_TARGETS = {
    "european_odds": "european_odds",
    "asian_handicap": "asian_handicap",
    "sporttery": "chinese_lottery",
}
REVIEW_KEYS = {
    "final_score",
    "review",
    "reviewed",
    "hit",
    "void",
    "review_note",
    "reviewed_at",
}


def apply_fallback_results(payload_path: Path, results_path: Path) -> dict[str, Any]:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    result_payload = json.loads(results_path.read_text(encoding="utf-8"))
    results = result_payload.get("results")
    if not isinstance(results, list):
        raise ValueError("Fallback results file must contain a results list")

    applied = 0
    resolved = 0
    for result in results:
        request = _find_request(payload, result)
        match, collection = _find_match(payload, request)
        updated, filled = _apply_result(match, request, result)
        _replace_match(payload, collection, updated)
        remaining = missing_fields_for_match(updated)
        _settle_request(request, result, remaining)
        applied += len(filled)
        if not remaining:
            resolved += 1

    if any(str(result.get("request_id") or "").startswith("daily:") for result in results):
        _rebuild_daily_histories(payload)

    payload["last_fallback_import"] = {
        "imported_at": datetime.now(BEIJING).isoformat(timespec="seconds"),
        "result_count": len(results),
        "field_count": applied,
        "resolved_count": resolved,
    }
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _find_request(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError("Each fallback result must be an object")
    request_id = str(result.get("request_id") or "")
    if not request_id:
        raise ValueError("Fallback result is missing request_id")
    for request in payload.get("fallback_requests", []):
        if request.get("id") == request_id and request.get("status") == "pending":
            return request
    raise ValueError(f"Pending fallback request not found: {request_id}")


def _find_match(
    payload: dict[str, Any], request: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    collection = "adhoc_history" if request.get("scope") == "adhoc" else "current_matches"
    for match in payload.get(collection, []):
        if match.get("id") == request.get("match_id"):
            return match, collection
    raise ValueError(f"Match not found for fallback request: {request.get('id')}")


def _apply_result(
    match: dict[str, Any],
    request: dict[str, Any],
    result: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    _validate_identity(match, result)
    queried_at = _timestamp(result.get("queried_at"), "queried_at")
    fields = result.get("fields") or {}
    if not isinstance(fields, dict):
        raise ValueError("fields must be an object")
    unknown = set(fields) - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"Unsupported fallback fields: {sorted(unknown)}")
    requested = set(request.get("missing_fields") or [])
    unrequested = set(fields) - requested
    if unrequested:
        raise ValueError(f"Fields were not requested: {sorted(unrequested)}")

    updated = deepcopy(match)
    filled = []
    for field, value in fields.items():
        sources = _sources_for_field(result, field)
        _ensure_missing(updated, field)
        _apply_field(updated, field, value)
        _record_audit(updated, field, queried_at, sources)
        filled.append(field)

    updated = analyze_slate_match(updated)
    updated = _attach_bilingual_reports([updated])[0]
    return updated, filled


def _validate_identity(match: dict[str, Any], result: dict[str, Any]) -> None:
    for key in ("home_team", "away_team"):
        value = str(result.get(key) or "")
        if not value:
            raise ValueError(f"Fallback result is missing {key}")
        if _normalize_team(value) != _normalize_team(str(match.get(key) or "")):
            raise ValueError(f"Fallback result {key} does not match request")


def _ensure_missing(match: dict[str, Any], field: str) -> None:
    if field == "fundamentals":
        if field not in missing_fields_for_match(match):
            raise ValueError("Refusing to overwrite existing fundamentals")
        return
    target = FIELD_TARGETS[field]
    if match.get(target):
        raise ValueError(f"Refusing to overwrite existing {target}")


def _apply_field(match: dict[str, Any], field: str, value: Any) -> None:
    if field == "fundamentals":
        _apply_fundamentals(match, value)
    elif field == "european_odds":
        match["european_odds"] = _three_way(value, "european_odds")
    elif field == "asian_handicap":
        match["asian_handicap"] = _asian(value)
    elif field == "sporttery":
        match["chinese_lottery"] = _sporttery(value)


def _apply_fundamentals(match: dict[str, Any], value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("fundamentals must be an object")
    context = value.get("fundamental_context")
    rows = value.get("fundamentals")
    if not isinstance(context, dict) or not all(
        isinstance(context.get(side), dict) for side in ("home", "away")
    ):
        raise ValueError("fundamentals.fundamental_context must include home and away objects")
    if not isinstance(rows, list) or not rows:
        raise ValueError("fundamentals.fundamentals must be a non-empty list")
    for row in rows:
        if (
            not isinstance(row, dict)
            or not str(row.get("home") or "")
            or not str(row.get("away") or "")
        ):
            raise ValueError("Each fundamentals row must include home and away text")
    match["fundamental_context"] = deepcopy(context)
    match["fundamentals"] = deepcopy(rows)
    if value.get("venue") and str(match.get("venue") or "") in {"", "待补"}:
        match["venue"] = str(value["venue"])


def _three_way(value: Any, field: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return {
        key: _decimal_odds(value.get(key), f"{field}.{key}")
        for key in ("home", "draw", "away")
    }


def _asian(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("asian_handicap must be an object")
    handicap = _number(value.get("handicap"), "asian_handicap.handicap")
    if abs(handicap * 4 - round(handicap * 4)) > 1e-9 or abs(handicap) > 5:
        raise ValueError("Asian handicap must be a quarter-ball line between -5 and 5")
    provider = str(value.get("provider") or "").strip()
    if not provider:
        raise ValueError("asian_handicap.provider is required")
    return {
        "provider": provider,
        "handicap": handicap,
        "home_odds": _decimal_odds(value.get("home_odds"), "asian_handicap.home_odds"),
        "away_odds": _decimal_odds(value.get("away_odds"), "asian_handicap.away_odds"),
    }


def _sporttery(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("sporttery must be an object")
    standard = (
        _three_way(value["standard"], "sporttery.standard")
        if value.get("standard")
        else None
    )
    handicap = value.get("handicap")
    if handicap is not None and (isinstance(handicap, bool) or not isinstance(handicap, int)):
        raise ValueError("Sporttery handicap must be an integer")
    handicap_odds = (
        _three_way(value["handicap_odds"], "sporttery.handicap_odds")
        if value.get("handicap_odds")
        else None
    )
    if standard is None and (handicap is None or handicap_odds is None):
        raise ValueError("Sporttery needs standard odds or handicap plus handicap odds")
    return {
        "standard": standard,
        "handicap": handicap,
        "handicap_odds": handicap_odds,
        "source": "Codex fallback",
    }


def _sources_for_field(result: dict[str, Any], field: str) -> list[dict[str, str]]:
    sources = (result.get("sources") or {}).get(field)
    if not isinstance(sources, list) or not sources:
        raise ValueError(f"At least one source is required for {field}")
    validated = []
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError(f"Invalid source for {field}")
        name = str(source.get("name") or "").strip()
        url = str(source.get("url") or "").strip()
        tier = str(source.get("tier") or "").strip()
        parsed_url = urlparse(url)
        if not name or parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError(f"Source name and HTTP(S) URL are required for {field}")
        if tier not in {"primary", "secondary"}:
            raise ValueError(f"Source tier must be primary or secondary for {field}")
        source_time = _timestamp(source.get("queried_at"), f"source {field} queried_at")
        validated.append(
            {"name": name, "url": url, "tier": tier, "queried_at": source_time}
        )
    return validated


def _timestamp(value: Any, label: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(BEIJING).isoformat(timespec="seconds")


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    return float(value)


def _decimal_odds(value: Any, label: str) -> float:
    odds = _number(value, label)
    if odds <= 1 or odds > 1000:
        raise ValueError(f"{label} must be decimal odds between 1 and 1000")
    return odds


def _record_audit(
    match: dict[str, Any],
    field: str,
    queried_at: str,
    sources: list[dict[str, str]],
) -> None:
    audit = deepcopy(match.get("fallback_research") or {})
    audit[field] = {"queried_at": queried_at, "sources": sources}
    match["fallback_research"] = audit
    display_sources = list(match.get("sources") or [])
    for source in sources:
        label = f"Codex fallback: {source['name']}"
        if label not in display_sources:
            display_sources.append(label)
    match["sources"] = display_sources


def _replace_match(payload: dict[str, Any], collection: str, updated: dict[str, Any]) -> None:
    payload[collection] = [
        updated if match.get("id") == updated.get("id") else match
        for match in payload.get(collection, [])
    ]


def _settle_request(
    request: dict[str, Any],
    result: dict[str, Any],
    remaining: list[str],
) -> None:
    request["attempts"] = int(request.get("attempts") or 0) + 1
    request["last_attempt_at"] = _timestamp(result.get("queried_at"), "queried_at")
    request["missing_fields"] = remaining
    if remaining:
        request["status"] = "pending"
        request["unresolved_reason"] = str(
            result.get("unresolved_reason") or "Fields remain unverified"
        )
    else:
        request["status"] = "resolved"
        request["resolved_at"] = request["last_attempt_at"]
        request.pop("unresolved_reason", None)


def _rebuild_daily_histories(payload: dict[str, Any]) -> None:
    batch_date = str((payload.get("slate") or {}).get("date") or "")
    if not batch_date:
        raise ValueError("Cannot rebuild daily histories without slate.date")
    current = payload.get("current_matches", [])
    mismatches = [
        match for match in current if match.get("mismatch", {}).get("matched") is True
    ]
    payload["mismatch_history"] = upsert_history(
        without_batch(payload.get("mismatch_history", []), batch_date),
        with_batch_date(mismatches, batch_date),
    )
    candidates = _checker_candidates(current, batch_date)
    previous = {
        match.get("id"): match
        for match in payload.get("checker_history", [])
        if str(match.get("batch_date") or "") == batch_date
    }
    candidates = [
        _preserve_review(candidate, previous.get(candidate.get("id")))
        for candidate in candidates
    ]
    payload["checker_history"] = upsert_history(
        without_batch(payload.get("checker_history", []), batch_date),
        with_batch_date(candidates, batch_date),
    )


def _preserve_review(
    fresh: dict[str, Any], previous: dict[str, Any] | None
) -> dict[str, Any]:
    copied = deepcopy(fresh)
    if previous:
        for key in REVIEW_KEYS:
            if key in previous:
                copied[key] = deepcopy(previous[key])
    return copied
