from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"

COMPETITION_CODES = {
    "英超": "PL",
    "西甲": "PD",
    "意甲": "SA",
    "德甲": "BL1",
    "法甲": "FL1",
    "欧冠": "CL",
}

COMPETITION_NAMES_ZH = {
    "PL": "英超",
    "PD": "西甲",
    "SA": "意甲",
    "BL1": "德甲",
    "FL1": "法甲",
    "CL": "欧冠",
}

BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")


@dataclass(frozen=True)
class FootballDataFixture:
    match_id: int
    competition_code: str
    competition_name: str
    utc_date: str
    kickoff_time: str
    home_team_id: int | None
    home_team: str
    away_team_id: int | None
    away_team: str
    matchday: int | None
    stage: str | None
    status: str
    venue: str | None = None
    home_score: int | None = None
    away_score: int | None = None


@dataclass(frozen=True)
class FootballDataStanding:
    team_id: int
    team_name: str
    position: int
    played_games: int
    won: int
    draw: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int


@dataclass(frozen=True)
class FootballDataForm:
    team_id: int
    results: tuple[str, ...]

    @property
    def display(self) -> str:
        return "-".join(self.results) if self.results else "暂无近况"


@dataclass(frozen=True)
class FootballDataSnapshot:
    fixtures: tuple[FootballDataFixture, ...]
    standings: dict[int, FootballDataStanding]
    forms: dict[int, FootballDataForm]
    source: str = "football-data.org"
    errors: tuple[str, ...] = ()


def fetch_evening_football_data(
    api_key: str,
    slate_date: str,
    competition_codes: tuple[str, ...] = tuple(COMPETITION_CODES.values()),
    timeout: float = 20,
) -> FootballDataSnapshot:
    start = datetime.fromisoformat(slate_date).replace(
        hour=18, minute=0, second=0, microsecond=0, tzinfo=BEIJING
    )
    end = start + timedelta(hours=12)
    utc_start = start.astimezone(timezone.utc)
    utc_end = end.astimezone(timezone.utc)
    date_from = utc_start.date().isoformat()
    date_to = (utc_end.date() + timedelta(days=1)).isoformat()

    fixtures: list[FootballDataFixture] = []
    standings: dict[int, FootballDataStanding] = {}
    forms: dict[int, FootballDataForm] = {}
    errors: list[str] = []
    requested_codes = set(competition_codes)

    try:
        fixture_payload = _get_json(
            "/matches",
            api_key,
            {
                "dateFrom": date_from,
                "dateTo": date_to,
                "competitions": ",".join(competition_codes),
            },
            timeout,
        )
        fixtures.extend(
            fixture
            for fixture in parse_football_data_fixtures(fixture_payload, "")
            if fixture.competition_code in requested_codes
            and start <= _parse_utc(fixture.utc_date).astimezone(BEIJING) < end
        )
    except Exception as exc:
        return FootballDataSnapshot(
            fixtures=(),
            standings={},
            forms={},
            errors=(f"matches {_source_error(exc)}",),
        )

    active_codes = {fixture.competition_code for fixture in fixtures}
    for code in competition_codes:
        if code not in active_codes:
            continue
        try:
            standing_payload = _get_json(f"/competitions/{code}/standings", api_key, {}, timeout)
            standings.update(parse_football_data_standings(standing_payload))
            forms.update(parse_football_data_standing_forms(standing_payload))
        except Exception as exc:
            errors.append(f"{code} standings {_source_error(exc)}")

    return FootballDataSnapshot(
        fixtures=tuple(fixtures),
        standings=standings,
        forms=forms,
        errors=tuple(errors),
    )


def fetch_evening_fixtures(
    api_key: str,
    slate_date: str,
    competition_codes: tuple[str, ...] = tuple(COMPETITION_CODES.values()),
    timeout: float = 20,
) -> tuple[FootballDataFixture, ...]:
    start = datetime.fromisoformat(slate_date).replace(
        hour=18, minute=0, second=0, microsecond=0, tzinfo=BEIJING
    )
    end = start + timedelta(hours=12)
    utc_start = start.astimezone(timezone.utc)
    utc_end = end.astimezone(timezone.utc)
    payload = _get_json(
        "/matches",
        api_key,
        {
            "dateFrom": utc_start.date().isoformat(),
            "dateTo": (utc_end.date() + timedelta(days=1)).isoformat(),
            "competitions": ",".join(competition_codes),
        },
        timeout,
    )
    requested_codes = set(competition_codes)
    return tuple(
        fixture
        for fixture in parse_football_data_fixtures(payload, "")
        if fixture.competition_code in requested_codes
        and start <= _parse_utc(fixture.utc_date).astimezone(BEIJING) < end
    )


def parse_football_data_fixtures(
    payload: dict[str, Any], fallback_competition_code: str
) -> tuple[FootballDataFixture, ...]:
    matches = payload.get("matches") or []
    parsed = []
    for item in matches:
        home = item.get("homeTeam") or {}
        away = item.get("awayTeam") or {}
        competition = item.get("competition") or payload.get("competition") or {}
        full_time = ((item.get("score") or {}).get("fullTime") or {})
        utc_date = _text(item.get("utcDate"))
        if not utc_date or not _text(home.get("name")) or not _text(away.get("name")):
            continue
        code = _text(competition.get("code")) or fallback_competition_code
        parsed.append(
            FootballDataFixture(
                match_id=_int(item.get("id")) or 0,
                competition_code=code,
                competition_name=_text(competition.get("name")) or COMPETITION_NAMES_ZH.get(code, code),
                utc_date=utc_date,
                kickoff_time=_parse_utc(utc_date).astimezone(BEIJING).strftime("%Y-%m-%d %H:%M"),
                home_team_id=_int(home.get("id")),
                home_team=_text(home.get("name")),
                away_team_id=_int(away.get("id")),
                away_team=_text(away.get("name")),
                matchday=_int(item.get("matchday")),
                stage=_text_or_none(item.get("stage")),
                status=_text(item.get("status")),
                venue=_text_or_none(item.get("venue")),
                home_score=_int(full_time.get("home")),
                away_score=_int(full_time.get("away")),
            )
        )
    return tuple(parsed)


def parse_football_data_standings(payload: dict[str, Any]) -> dict[int, FootballDataStanding]:
    standings = {}
    for row in _total_standing_rows(payload):
        team = row.get("team") or {}
        team_id = _int(team.get("id"))
        if team_id is None:
            continue
        standings[team_id] = FootballDataStanding(
            team_id=team_id,
            team_name=_text(team.get("name")),
            position=_int(row.get("position")) or 0,
            played_games=_int(row.get("playedGames")) or 0,
            won=_int(row.get("won")) or 0,
            draw=_int(row.get("draw")) or 0,
            lost=_int(row.get("lost")) or 0,
            goals_for=_int(row.get("goalsFor")) or 0,
            goals_against=_int(row.get("goalsAgainst")) or 0,
            goal_difference=_int(row.get("goalDifference")) or 0,
            points=_int(row.get("points")) or 0,
        )
    return standings


def parse_football_data_standing_forms(
    payload: dict[str, Any], limit: int = 5
) -> dict[int, FootballDataForm]:
    forms = {}
    for row in _total_standing_rows(payload):
        team_id = _int((row.get("team") or {}).get("id"))
        if team_id is None:
            continue
        results = tuple(
            result
            for result in re.split(r"[\s,;|-]+", _text(row.get("form")).upper())
            if result in {"W", "D", "L"}
        )[:limit]
        if results:
            forms[team_id] = FootballDataForm(team_id=team_id, results=results)
    return forms


def parse_football_data_forms(matches: list[dict[str, Any]], limit: int = 5) -> dict[int, FootballDataForm]:
    by_team: dict[int, list[tuple[datetime, str]]] = {}
    for item in matches:
        if _text(item.get("status")) != "FINISHED":
            continue
        score = ((item.get("score") or {}).get("fullTime") or {})
        home_goals = _int(score.get("home"))
        away_goals = _int(score.get("away"))
        home = item.get("homeTeam") or {}
        away = item.get("awayTeam") or {}
        home_id = _int(home.get("id"))
        away_id = _int(away.get("id"))
        utc_date = _text(item.get("utcDate"))
        if None in (home_goals, away_goals, home_id, away_id) or not utc_date:
            continue
        played_at = _parse_utc(utc_date)
        if home_goals > away_goals:
            home_result, away_result = "W", "L"
        elif home_goals < away_goals:
            home_result, away_result = "L", "W"
        else:
            home_result, away_result = "D", "D"
        by_team.setdefault(home_id, []).append((played_at, home_result))
        by_team.setdefault(away_id, []).append((played_at, away_result))

    return {
        team_id: FootballDataForm(
            team_id=team_id,
            results=tuple(result for _, result in sorted(items, reverse=True)[:limit]),
        )
        for team_id, items in by_team.items()
    }


def fixture_dashboard_id(fixture: FootballDataFixture) -> str:
    date_part = fixture.kickoff_time[:10]
    return f"{date_part}-{_slug(fixture.home_team)}-{_slug(fixture.away_team)}"


def _get_json(path: str, api_key: str, query: dict[str, str], timeout: float) -> dict[str, Any]:
    suffix = f"?{urlencode(query)}" if query else ""
    request = Request(
        f"{FOOTBALL_DATA_BASE_URL}{path}{suffix}",
        headers={
            "X-Auth-Token": api_key,
            "User-Agent": "odds-analyzer/0.1",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return cleaned.strip("-") or "team"


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _text_or_none(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _total_standing_rows(payload: dict[str, Any]):
    for standing in payload.get("standings") or []:
        if standing.get("type") == "TOTAL":
            yield from standing.get("table") or []


def _source_error(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        reason = getattr(exc, "reason", "") or ""
        message = _http_error_message(exc)
        detail = f": {message}" if message else ""
        return f"HTTP {exc.code} {reason}{detail}".strip()
    if isinstance(exc, URLError):
        return f"URL error {exc.reason}"
    return type(exc).__name__


def _http_error_message(exc: HTTPError) -> str:
    try:
        payload = json.loads(exc.read(4096).decode("utf-8", errors="replace"))
    except (AttributeError, json.JSONDecodeError, OSError, UnicodeError):
        return ""

    if not isinstance(payload, dict):
        return ""
    message = payload.get("message") or payload.get("error")
    if not isinstance(message, str):
        return ""
    return re.sub(r"\s+", " ", message).strip()[:200]
