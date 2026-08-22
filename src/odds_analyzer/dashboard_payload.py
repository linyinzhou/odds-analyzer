from __future__ import annotations

from copy import deepcopy
from typing import Any

MatchRecord = dict[str, Any]
Payload = dict[str, Any]

def merge_dashboard_payload(existing: Payload, batch: Payload) -> Payload:
    """Merge a generated batch into the persisted dashboard payload.

    The current slate is always replaced. Historical mismatch and checker lists are
    upserted by same fixture and same batch date so a rerun refreshes stale odds or
    recommendations instead of appending duplicates.
    """

    merged = deepcopy(existing)
    current_matches = deepcopy(batch.get("current_matches", []))
    batch_date = batch_key(batch, current_matches)

    merged["slate"] = deepcopy(batch.get("slate", existing.get("slate", {})))
    merged["current_matches"] = current_matches
    if "next_matchday" in batch:
        merged["next_matchday"] = deepcopy(batch["next_matchday"])

    merged["mismatch_history"] = upsert_history(
        existing.get("mismatch_history", []),
        with_batch_date(batch.get("mismatch_history", []), batch_date),
    )
    merged["checker_history"] = upsert_history(
        existing.get("checker_history", []),
        with_batch_date(batch.get("checker_history", []), batch_date),
    )
    return merged

def upsert_history(existing: list[MatchRecord], fresh: list[MatchRecord]) -> list[MatchRecord]:
    result: list[MatchRecord] = []
    used_keys: set[tuple[str, str]] = set()

    for item in fresh:
        key = history_key(item)
        if key in used_keys:
            continue
        result.append(deepcopy(item))
        used_keys.add(key)

    for item in existing:
        key = history_key(item)
        if key in used_keys:
            continue
        result.append(deepcopy(item))
        used_keys.add(key)

    return result

def with_batch_date(items: list[MatchRecord], batch_date: str) -> list[MatchRecord]:
    dated = []
    for item in items:
        copied = deepcopy(item)
        copied.setdefault("batch_date", batch_date)
        dated.append(copied)
    return dated

def history_key(item: MatchRecord) -> tuple[str, str]:
    return str(item.get("batch_date") or item.get("generated_at") or ""), fixture_key(item)

def fixture_key(item: MatchRecord) -> str:
    if item.get("id"):
        return str(item["id"])
    home = normalize(item.get("home_team"))
    away = normalize(item.get("away_team"))
    kickoff = normalize(item.get("kickoff_time"))
    return f"{home}|{away}|{kickoff}"

def batch_key(batch: Payload, current_matches: list[MatchRecord]) -> str:
    slate = batch.get("slate", {})
    if slate.get("date"):
        return str(slate["date"])
    for item in current_matches:
        if item.get("batch_date"):
            return str(item["batch_date"])
    return ""

def normalize(value: Any) -> str:
    return str(value or "").strip().casefold()


