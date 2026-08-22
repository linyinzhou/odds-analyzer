from __future__ import annotations

from copy import deepcopy
from typing import Any


FIELD_SOURCES = {
    "fundamentals": "football_data_source",
    "european_odds": "odds_api_source",
    "asian_handicap": "odds_api_source",
    "sporttery": "sporttery_source",
}


def build_fallback_requests(
    matches: list[dict[str, Any]],
    source_status: dict[str, str],
    scope: str = "daily",
) -> list[dict[str, Any]]:
    requests = []
    for match in matches:
        missing_fields = _missing_fields(match)
        if not missing_fields:
            continue
        statuses = {
            field: source_status.get(FIELD_SOURCES[field], "source status unavailable")
            for field in missing_fields
        }
        requests.append(
            {
                "id": f"{scope}:{match.get('id', '')}",
                "scope": scope,
                "status": "pending",
                "match_id": match.get("id"),
                "batch_date": match.get("batch_date"),
                "kickoff_time": match.get("kickoff_time"),
                "competition": match.get("competition"),
                "home_team": match.get("home_team"),
                "away_team": match.get("away_team"),
                "missing_fields": missing_fields,
                "source_status": statuses,
                "failure_type": _failure_type(statuses.values()),
                "search_queries": _search_queries(match, missing_fields),
            }
        )
    return requests


def merge_fallback_requests(
    existing: list[dict[str, Any]],
    fresh: list[dict[str, Any]],
    replace_scope: str | None = None,
) -> list[dict[str, Any]]:
    retained = [item for item in existing if item.get("scope") != replace_scope] if replace_scope else existing
    result = []
    seen = set()
    for item in [*fresh, *retained]:
        key = str(item.get("id") or "")
        if not key or key in seen:
            continue
        result.append(deepcopy(item))
        seen.add(key)
    return result


def _missing_fields(match: dict[str, Any]) -> list[str]:
    fields = []
    if not _has_fundamentals(match):
        fields.append("fundamentals")
    if not match.get("european_odds"):
        fields.append("european_odds")
    if not match.get("asian_handicap"):
        fields.append("asian_handicap")
    if not match.get("chinese_lottery"):
        fields.append("sporttery")
    return fields


def _has_fundamentals(match: dict[str, Any]) -> bool:
    context = match.get("fundamental_context") or {}
    for side in ("home", "away"):
        team = context.get(side) or {}
        if "position" not in team and not team.get("form"):
            return False
    return True


def _failure_type(statuses: Any) -> str:
    normalized = " ".join(str(status).lower() for status in statuses)
    if "missing" in normalized or "skipped" in normalized:
        return "missing_configuration"
    if "unavailable" in normalized or "error" in normalized:
        return "source_failure"
    return "no_match_coverage"


def _search_queries(match: dict[str, Any], missing_fields: list[str]) -> list[str]:
    teams = f"{match.get('home_team', '')} vs {match.get('away_team', '')}"
    kickoff = str(match.get("kickoff_time") or "")[:10]
    topics = {
        "fundamentals": "standings recent form venue",
        "european_odds": "current European 1X2 odds",
        "asian_handicap": "current Asian handicap odds",
        "sporttery": "竞彩 让球胜平负 SP",
    }
    return [f"{teams} {kickoff} {topics[field]}".strip() for field in missing_fields]
