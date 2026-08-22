from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from odds_analyzer.models import AsianHandicapOdds, ThreeWayOdds


ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4/sports"
DEFAULT_REGIONS = "uk,eu"
DEFAULT_MARKETS = "h2h,spreads"

LEAGUE_SPORT_KEYS = {
    "英超": "soccer_epl",
    "西甲": "soccer_spain_la_liga",
    "意甲": "soccer_italy_serie_a",
    "德甲": "soccer_germany_bundesliga",
    "法甲": "soccer_france_ligue_one",
    "欧冠": "soccer_uefa_champs_league",
}


@dataclass(frozen=True)
class OddsApiEvent:
    event_id: str
    sport_key: str
    commence_time: str
    home_team: str
    away_team: str
    bookmaker: str | None
    bookmaker_key: str | None
    updated_at: str | None
    european_odds: ThreeWayOdds | None = None
    asian_handicap: AsianHandicapOdds | None = None


def fetch_odds_api_events(
    api_key: str,
    sport_key: str,
    commence_time_from: datetime,
    commence_time_to: datetime,
    timeout: float = 20,
) -> list[OddsApiEvent]:
    query = urlencode(
        {
            "apiKey": api_key,
            "regions": DEFAULT_REGIONS,
            "markets": DEFAULT_MARKETS,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
            "commenceTimeFrom": _utc_iso(commence_time_from),
            "commenceTimeTo": _utc_iso(commence_time_to),
        }
    )
    request = Request(
        f"{ODDS_API_BASE_URL}/{sport_key}/odds?{query}",
        headers={"User-Agent": "odds-analyzer/0.1"},
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return parse_odds_api_events(payload, sport_key)


def fetch_evening_odds_api_events(
    api_key: str,
    slate_date: str,
    sport_keys: tuple[str, ...] = tuple(LEAGUE_SPORT_KEYS.values()),
) -> list[OddsApiEvent]:
    start = datetime.fromisoformat(slate_date).replace(
        hour=18, minute=0, second=0, microsecond=0, tzinfo=timezone(timedelta(hours=8))
    )
    end = start + timedelta(hours=12)
    events: list[OddsApiEvent] = []
    for sport_key in sport_keys:
        events.extend(fetch_odds_api_events(api_key, sport_key, start, end))
    return events


def parse_odds_api_events(payload: list[dict[str, Any]], sport_key: str) -> list[OddsApiEvent]:
    if not isinstance(payload, list):
        raise ValueError("The Odds API response must be a list")

    return [event for item in payload if (event := _parse_event(item, sport_key)) is not None]


def _parse_event(item: dict[str, Any], sport_key: str) -> OddsApiEvent | None:
    home_team = _text(item.get("home_team"))
    away_team = _text(item.get("away_team"))
    if not home_team or not away_team:
        return None

    bookmaker = _select_bookmaker(item.get("bookmakers") or [])
    h2h = _parse_h2h(bookmaker, home_team, away_team) if bookmaker else None
    spread = _parse_spread(bookmaker, home_team, away_team) if bookmaker else None

    return OddsApiEvent(
        event_id=_text(item.get("id")),
        sport_key=_text(item.get("sport_key")) or sport_key,
        commence_time=_text(item.get("commence_time")),
        home_team=home_team,
        away_team=away_team,
        bookmaker=_text(bookmaker.get("title")) if bookmaker else None,
        bookmaker_key=_text(bookmaker.get("key")) if bookmaker else None,
        updated_at=_text(bookmaker.get("last_update")) if bookmaker else None,
        european_odds=h2h,
        asian_handicap=spread,
    )


def _select_bookmaker(bookmakers: list[dict[str, Any]]) -> dict[str, Any] | None:
    preferred = ("pinnacle", "bet365", "williamhill", "unibet", "betfair_ex_eu")
    by_key = {_text(bookmaker.get("key")): bookmaker for bookmaker in bookmakers}
    for key in preferred:
        if key in by_key:
            return by_key[key]
    return bookmakers[0] if bookmakers else None


def _parse_h2h(bookmaker: dict[str, Any], home_team: str, away_team: str) -> ThreeWayOdds | None:
    market = _market(bookmaker, "h2h")
    if not market:
        return None
    odds = {_text(outcome.get("name")): _float(outcome.get("price")) for outcome in market.get("outcomes") or []}
    home = odds.get(home_team)
    draw = odds.get("Draw") or odds.get("draw") or odds.get("平局")
    away = odds.get(away_team)
    if None in (home, draw, away):
        return None
    return ThreeWayOdds(home=home, draw=draw, away=away)


def _parse_spread(bookmaker: dict[str, Any], home_team: str, away_team: str) -> AsianHandicapOdds | None:
    market = _market(bookmaker, "spreads")
    if not market:
        return None
    outcomes = market.get("outcomes") or []
    home = next((outcome for outcome in outcomes if _text(outcome.get("name")) == home_team), None)
    away = next((outcome for outcome in outcomes if _text(outcome.get("name")) == away_team), None)
    if not home or not away:
        return None
    point = _float(home.get("point"))
    home_odds = _float(home.get("price"))
    away_odds = _float(away.get("price"))
    if None in (point, home_odds, away_odds):
        return None
    return AsianHandicapOdds(
        handicap=point,
        home_odds=home_odds,
        away_odds=away_odds,
        provider=_text(bookmaker.get("title")) or "The Odds API",
    )


def _market(bookmaker: dict[str, Any], key: str) -> dict[str, Any] | None:
    return next((market for market in bookmaker.get("markets") or [] if market.get("key") == key), None)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
