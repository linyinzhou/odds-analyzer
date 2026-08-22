from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
LEAGUE_IDS = {"PL": 39, "PD": 140, "SA": 135, "BL1": 78, "FL1": 61, "CL": 2}
CODE_BY_LEAGUE_ID = {value: key for key, value in LEAGUE_IDS.items()}


@dataclass(frozen=True)
class PlayerAbsence:
    player_name: str
    kind: str
    reason: str


@dataclass(frozen=True)
class ConfirmedLineup:
    formation: str | None
    starting_xi: tuple[str, ...]


@dataclass(frozen=True)
class TeamNews:
    team_id: int | None
    team_name: str
    absences: tuple[PlayerAbsence, ...]
    lineup: ConfirmedLineup | None = None


@dataclass(frozen=True)
class ApiFootballMatchNews:
    fixture_id: int
    competition_code: str
    kickoff_time: str
    home: TeamNews
    away: TeamNews
    queried_at: str = ""


@dataclass(frozen=True)
class ApiFootballNewsBatch:
    matches: tuple[ApiFootballMatchNews, ...]
    requests_made: int
    remaining_requests: int | None
    errors: tuple[str, ...] = ()
    source: str = "API-Football"


def fetch_evening_api_football_news(
    api_key: str,
    slate_date: str,
    competition_codes: tuple[str, ...],
    now: datetime | None = None,
    timeout: float = 20,
) -> ApiFootballNewsBatch:
    start = datetime.fromisoformat(slate_date).replace(hour=18, tzinfo=BEIJING)
    end = start + timedelta(hours=12)
    query_now = now or datetime.now(BEIJING)
    if query_now.tzinfo is None:
        query_now = query_now.replace(tzinfo=BEIJING)
    season = start.year if start.month >= 7 else start.year - 1
    dates = tuple(dict.fromkeys((start.date().isoformat(), (end - timedelta(seconds=1)).date().isoformat())))
    requested_ids = {LEAGUE_IDS[code] for code in competition_codes if code in LEAGUE_IDS}

    fixtures: dict[int, dict[str, Any]] = {}
    injuries: dict[tuple[int, int], list[PlayerAbsence]] = {}
    lineups: dict[tuple[int, int], ConfirmedLineup] = {}
    errors: list[str] = []
    requests_made = 0
    remaining: int | None = None

    for code in competition_codes:
        league_id = LEAGUE_IDS.get(code)
        if league_id is None:
            continue
        for match_date in dates:
            try:
                payload, quota = _get_json(
                    "/fixtures",
                    api_key,
                    {"league": str(league_id), "season": str(season), "date": match_date},
                    timeout,
                )
                requests_made += 1
                remaining = _lowest_quota(remaining, quota)
                fixtures.update(_parse_fixtures(payload, requested_ids, start, end))
            except Exception as exc:
                requests_made += 1
                errors.append(f"{code} fixtures {match_date}: {_source_error(exc)}")

    if fixtures:
        for match_date in dates:
            try:
                payload, quota = _get_json(
                    "/injuries", api_key, {"date": match_date}, timeout
                )
                requests_made += 1
                remaining = _lowest_quota(remaining, quota)
                _merge_injuries(injuries, payload, set(fixtures))
            except Exception as exc:
                requests_made += 1
                errors.append(f"injuries {match_date}: {_source_error(exc)}")

    for fixture_id, fixture in fixtures.items():
        kickoff = fixture["kickoff"]
        minutes_to_kickoff = (kickoff - query_now.astimezone(BEIJING)).total_seconds() / 60
        if not 0 <= minutes_to_kickoff <= 90:
            continue
        try:
            payload, quota = _get_json(
                "/fixtures/lineups", api_key, {"fixture": str(fixture_id)}, timeout
            )
            requests_made += 1
            remaining = _lowest_quota(remaining, quota)
            _merge_lineups(lineups, fixture_id, payload)
        except Exception as exc:
            requests_made += 1
            errors.append(f"lineups {fixture_id}: {_source_error(exc)}")

    matches = tuple(
        _build_match_news(
            fixture,
            injuries,
            lineups,
            query_now.astimezone(BEIJING).isoformat(timespec="seconds"),
        )
        for fixture in sorted(fixtures.values(), key=lambda item: item["kickoff"])
    )
    return ApiFootballNewsBatch(
        matches=matches,
        requests_made=requests_made,
        remaining_requests=remaining,
        errors=tuple(errors),
    )


def _parse_fixtures(
    payload: dict[str, Any],
    requested_ids: set[int],
    start: datetime,
    end: datetime,
) -> dict[int, dict[str, Any]]:
    fixtures = {}
    for item in payload.get("response") or []:
        fixture = item.get("fixture") or {}
        league = item.get("league") or {}
        teams = item.get("teams") or {}
        fixture_id = _integer(fixture.get("id"))
        league_id = _integer(league.get("id"))
        kickoff = _datetime(fixture.get("date"))
        home = teams.get("home") or {}
        away = teams.get("away") or {}
        if (
            fixture_id is None
            or league_id not in requested_ids
            or kickoff is None
            or not start <= kickoff.astimezone(BEIJING) < end
            or not _text(home.get("name"))
            or not _text(away.get("name"))
        ):
            continue
        fixtures[fixture_id] = {
            "fixture_id": fixture_id,
            "competition_code": CODE_BY_LEAGUE_ID[league_id],
            "kickoff": kickoff.astimezone(BEIJING),
            "home_id": _integer(home.get("id")),
            "home_name": _text(home.get("name")),
            "away_id": _integer(away.get("id")),
            "away_name": _text(away.get("name")),
        }
    return fixtures


def _merge_injuries(
    target: dict[tuple[int, int], list[PlayerAbsence]],
    payload: dict[str, Any],
    fixture_ids: set[int],
) -> None:
    for item in payload.get("response") or []:
        fixture_id = _integer((item.get("fixture") or {}).get("id"))
        team_id = _integer((item.get("team") or {}).get("id"))
        player = item.get("player") or {}
        if fixture_id not in fixture_ids or team_id is None or not _text(player.get("name")):
            continue
        absence = PlayerAbsence(
            player_name=_text(player.get("name")),
            kind=_text(player.get("type")) or "Unavailable",
            reason=_text(player.get("reason")) or "Reason not reported",
        )
        bucket = target.setdefault((fixture_id, team_id), [])
        if absence not in bucket:
            bucket.append(absence)


def _merge_lineups(
    target: dict[tuple[int, int], ConfirmedLineup],
    fixture_id: int,
    payload: dict[str, Any],
) -> None:
    for item in payload.get("response") or []:
        team_id = _integer((item.get("team") or {}).get("id"))
        if team_id is None:
            continue
        names = tuple(
            _text((row.get("player") or {}).get("name"))
            for row in item.get("startXI") or []
            if _text((row.get("player") or {}).get("name"))
        )
        if names:
            target[(fixture_id, team_id)] = ConfirmedLineup(
                formation=_text(item.get("formation")) or None,
                starting_xi=names,
            )


def _build_match_news(
    fixture: dict[str, Any],
    injuries: dict[tuple[int, int], list[PlayerAbsence]],
    lineups: dict[tuple[int, int], ConfirmedLineup],
    queried_at: str,
) -> ApiFootballMatchNews:
    fixture_id = fixture["fixture_id"]
    home_id = fixture["home_id"]
    away_id = fixture["away_id"]
    return ApiFootballMatchNews(
        fixture_id=fixture_id,
        competition_code=fixture["competition_code"],
        kickoff_time=fixture["kickoff"].strftime("%Y-%m-%d %H:%M"),
        home=TeamNews(
            team_id=home_id,
            team_name=fixture["home_name"],
            absences=tuple(injuries.get((fixture_id, home_id), ())),
            lineup=lineups.get((fixture_id, home_id)),
        ),
        away=TeamNews(
            team_id=away_id,
            team_name=fixture["away_name"],
            absences=tuple(injuries.get((fixture_id, away_id), ())),
            lineup=lineups.get((fixture_id, away_id)),
        ),
        queried_at=queried_at,
    )


def _get_json(
    path: str,
    api_key: str,
    query: dict[str, str],
    timeout: float,
) -> tuple[dict[str, Any], int | None]:
    request = Request(
        f"{API_FOOTBALL_BASE_URL}{path}?{urlencode(query)}",
        headers={"x-apisports-key": api_key, "User-Agent": "odds-analyzer/0.1"},
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
        remaining = _integer(response.headers.get("x-ratelimit-requests-remaining"))
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if errors:
        raise ValueError(f"API-Football errors: {errors}")
    return payload, remaining


def _lowest_quota(current: int | None, incoming: int | None) -> int | None:
    if incoming is None:
        return current
    return incoming if current is None else min(current, incoming)


def _datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _source_error(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, URLError):
        return f"URL error {exc.reason}"
    return str(exc)[:200] or type(exc).__name__
