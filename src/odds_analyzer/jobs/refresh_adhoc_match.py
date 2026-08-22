from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from odds_analyzer.dashboard_payload import upsert_history
from odds_analyzer.fallback_queue import build_fallback_requests, merge_fallback_requests
from odds_analyzer.jobs.refresh_evening_slate import (
    BEIJING,
    DEFAULT_PAYLOAD_PATH,
    _attach_bilingual_reports,
    _enrich_with_football_data,
    _enrich_with_weather,
    _match_from_football_data_fixture,
    _normalize_team,
    _placeholder_match,
    _sporttery_lottery_payload,
)
from odds_analyzer.slate_analysis import analyze_slate_match
from odds_analyzer.sources import (
    FootballDataSnapshot,
    LEAGUE_SPORT_KEYS,
    OddsApiEvent,
    SportteryMatch,
    fetch_fixture_weather,
    fetch_odds_api_events,
    fetch_official_sporttery_matches,
)
from odds_analyzer.sources.football_data import (
    FootballDataFixture,
    fetch_fixtures_for_beijing_date,
)


def refresh_adhoc_match(
    path: Path,
    match_date: str,
    home_team: str,
    away_team: str,
    competition_label: str = "",
    kickoff_time: str = "",
    odds_sport_key: str = "",
) -> dict[str, Any]:
    existing = json.loads(path.read_text(encoding="utf-8"))
    source_status: dict[str, str] = {}

    fixtures: tuple[FootballDataFixture, ...] = ()
    football_key = os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()
    if football_key:
        try:
            fixtures = fetch_fixtures_for_beijing_date(football_key, match_date)
            source_status["football_data"] = f"football-data.org: {len(fixtures)} date fixtures"
        except Exception as exc:
            source_status["football_data"] = f"football-data.org unavailable: {type(exc).__name__}"
    else:
        source_status["football_data"] = "football-data.org skipped: missing key"

    odds_events: list[OddsApiEvent] = []
    odds_key = os.environ.get("THE_ODDS_API_KEY", "").strip()
    if odds_key and odds_sport_key:
        try:
            start = datetime.fromisoformat(match_date).replace(tzinfo=BEIJING)
            odds_events = fetch_odds_api_events(
                odds_key,
                odds_sport_key,
                start,
                start + timedelta(days=1),
            )
            source_status["odds_api"] = f"The Odds API: {len(odds_events)} sport events"
        except Exception as exc:
            source_status["odds_api"] = f"The Odds API unavailable: {type(exc).__name__}"
    elif not odds_sport_key:
        source_status["odds_api"] = "The Odds API skipped: missing odds_sport_key"
    else:
        source_status["odds_api"] = "The Odds API skipped: missing key"

    try:
        sporttery_matches = fetch_official_sporttery_matches(match_date)
        source_status["sporttery"] = f"Sporttery official: {len(sporttery_matches)} date fixtures"
    except Exception as exc:
        sporttery_matches = []
        source_status["sporttery"] = f"Sporttery unavailable: {type(exc).__name__}"

    fixture = _find_match(fixtures, home_team, away_team, lambda item: (item.home_team, item.away_team))
    odds_event = _find_match(odds_events, home_team, away_team, lambda item: (item.home_team, item.away_team))
    sporttery_match = _find_match(
        sporttery_matches,
        home_team,
        away_team,
        lambda item: (item.home_team, item.away_team),
    )
    match = _build_match(
        match_date,
        home_team,
        away_team,
        competition_label,
        kickoff_time,
        odds_sport_key,
        fixture,
        odds_event,
        sporttery_match,
    )
    match["adhoc_source_status"] = source_status
    match["batch_date"] = match_date
    match["adhoc"] = True
    match["generated_at"] = datetime.now(BEIJING).isoformat(timespec="seconds")
    match["id"] = _adhoc_id(match_date, home_team, away_team)
    match["request"] = {
        "home_team": home_team,
        "away_team": away_team,
        "match_date": match_date,
        "competition_label": competition_label,
        "kickoff_time": kickoff_time,
        "odds_sport_key": odds_sport_key,
    }
    match = analyze_slate_match(match)
    match = _attach_bilingual_reports([match])[0]

    existing["adhoc_history"] = upsert_history(existing.get("adhoc_history", []), [match])
    adhoc_status = {
        "football_data_source": source_status["football_data"],
        "odds_api_source": source_status["odds_api"],
        "sporttery_source": source_status["sporttery"],
    }
    fallback_id = f"adhoc:{match['id']}"
    existing_fallback = [
        item
        for item in existing.get("fallback_requests", [])
        if item.get("id") != fallback_id
    ]
    existing["fallback_requests"] = merge_fallback_requests(
        existing_fallback,
        build_fallback_requests([match], adhoc_status, scope="adhoc"),
    )
    existing["last_adhoc"] = {
        "generated_at": datetime.now(BEIJING).isoformat(timespec="seconds"),
        "match_date": match_date,
        "home_team": home_team,
        "away_team": away_team,
        "matched_football_data": fixture is not None,
        "matched_odds_api": odds_event is not None,
        "matched_sporttery": sporttery_match is not None,
    }
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return existing


def _build_match(
    match_date: str,
    home_team: str,
    away_team: str,
    competition_label: str,
    kickoff_time: str,
    odds_sport_key: str,
    fixture: FootballDataFixture | None,
    odds_event: OddsApiEvent | None,
    sporttery_match: SportteryMatch | None,
) -> dict[str, Any]:
    if fixture is not None:
        snapshot = FootballDataSnapshot(fixtures=(fixture,), standings={}, forms={})
        match = _match_from_football_data_fixture(fixture)
        match = _enrich_with_football_data([match], snapshot)[0]
        try:
            weather = fetch_fixture_weather((fixture,))
            match = _enrich_with_weather([match], weather.forecasts)[0]
        except Exception:
            pass
    else:
        base_home = odds_event.home_team if odds_event else sporttery_match.home_team if sporttery_match else home_team
        base_away = odds_event.away_team if odds_event else sporttery_match.away_team if sporttery_match else away_team
        match = _placeholder_match(
            {
                "id": _adhoc_id(match_date, home_team, away_team),
                "kickoff_time": _fallback_kickoff(match_date, kickoff_time, odds_event, sporttery_match),
                "competition": competition_label or _competition_label(odds_sport_key, sporttery_match),
                "home_team": base_home,
                "away_team": base_away,
                "round": "自选查询",
            }
        )
        match["sources"] = ["Manual adhoc request"]

    if competition_label:
        match["competition"] = competition_label
    if odds_event is not None:
        _apply_odds(match, odds_event)
    if sporttery_match is not None:
        match["chinese_lottery"] = _sporttery_lottery_payload(sporttery_match)
        match["sporttery_snapshot"] = {
            "match_id": sporttery_match.match_id,
            "match_no": sporttery_match.match_no,
            "source": "Sporttery official",
        }
        _add_source(match, "Sporttery official")
    return match


def _apply_odds(match: dict[str, Any], event: OddsApiEvent) -> None:
    if event.european_odds is not None:
        match["european_odds"] = {
            "home": event.european_odds.home,
            "draw": event.european_odds.draw,
            "away": event.european_odds.away,
        }
    if event.asian_handicap is not None:
        match["asian_handicap"] = {
            "provider": event.asian_handicap.provider,
            "handicap": event.asian_handicap.handicap,
            "home_odds": event.asian_handicap.home_odds,
            "away_odds": event.asian_handicap.away_odds,
        }
    match["odds_api_snapshot"] = {
        "event_id": event.event_id,
        "sport_key": event.sport_key,
        "bookmaker": event.bookmaker,
        "bookmaker_key": event.bookmaker_key,
        "updated_at": event.updated_at,
        "source": "The Odds API",
    }
    _add_source(match, "The Odds API")


def _find_match(
    items: Iterable[Any],
    home_team: str,
    away_team: str,
    teams: Any,
) -> Any | None:
    ranked = []
    for item in items:
        candidate_home, candidate_away = teams(item)
        home_score = _team_similarity(home_team, candidate_home)
        away_score = _team_similarity(away_team, candidate_away)
        if min(home_score, away_score) >= 0.72:
            ranked.append((home_score + away_score, item))
    return max(ranked, key=lambda value: value[0])[1] if ranked else None


def _team_similarity(left: str, right: str) -> float:
    normalized_left = _normalize_team(left)
    normalized_right = _normalize_team(right)
    if normalized_left == normalized_right:
        return 1.0
    if min(len(normalized_left), len(normalized_right)) >= 3 and (
        normalized_left in normalized_right or normalized_right in normalized_left
    ):
        return 0.9
    return SequenceMatcher(None, normalized_left, normalized_right).ratio()


def _fallback_kickoff(
    match_date: str,
    kickoff_time: str,
    odds_event: OddsApiEvent | None,
    sporttery_match: SportteryMatch | None,
) -> str:
    if odds_event and odds_event.commence_time:
        parsed = datetime.fromisoformat(odds_event.commence_time.replace("Z", "+00:00"))
        return parsed.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M")
    if sporttery_match and sporttery_match.kickoff_at:
        return sporttery_match.kickoff_at.replace("T", " ")[:16]
    if kickoff_time:
        return kickoff_time if len(kickoff_time) > 5 else f"{match_date} {kickoff_time}"
    return f"{match_date} 时间待确认"


def _competition_label(odds_sport_key: str, sporttery_match: SportteryMatch | None) -> str:
    if sporttery_match and sporttery_match.league:
        return sporttery_match.league
    reverse = {sport_key: label for label, sport_key in LEAGUE_SPORT_KEYS.items()}
    return reverse.get(odds_sport_key, odds_sport_key or "自选比赛")


def _add_source(match: dict[str, Any], source: str) -> None:
    sources = list(match.get("sources", []))
    if source not in sources:
        sources.append(source)
    match["sources"] = sources


def _adhoc_id(match_date: str, home_team: str, away_team: str) -> str:
    raw = f"{match_date}|{_normalize_team(home_team)}|{_normalize_team(away_team)}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"adhoc-{match_date}-{digest}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate one ad hoc football match report.")
    parser.add_argument("--date", required=True, help="Match date in Asia/Shanghai YYYY-MM-DD.")
    parser.add_argument("--home", required=True)
    parser.add_argument("--away", required=True)
    parser.add_argument("--competition", default="")
    parser.add_argument("--kickoff", default="")
    parser.add_argument("--odds-sport-key", default="")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD_PATH))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    date.fromisoformat(args.date)
    if not args.home.strip() or not args.away.strip():
        raise SystemExit("Both --home and --away are required.")
    payload = refresh_adhoc_match(
        Path(args.payload),
        args.date,
        args.home.strip(),
        args.away.strip(),
        args.competition.strip(),
        args.kickoff.strip(),
        args.odds_sport_key.strip(),
    )
    print(f"Generated ad hoc report; total={len(payload.get('adhoc_history', []))}")


if __name__ == "__main__":
    main()
