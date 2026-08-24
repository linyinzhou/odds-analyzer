from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com/events"
MIN_SIGNAL_VOLUME = 10_000.0


@dataclass(frozen=True)
class PolymarketSpread:
    team: str
    line: float
    probability: float
    volume: float | None = None


@dataclass(frozen=True)
class PolymarketEvent:
    event_id: str
    slug: str
    title: str
    start_time: str | None
    updated_at: str | None
    home_team: str
    away_team: str
    home_probability: float | None
    draw_probability: float | None
    away_probability: float | None
    favorite_spread: PolymarketSpread | None
    volume: float | None
    liquidity: float | None

    @property
    def url(self) -> str:
        return f"https://polymarket.com/event/{self.slug}"

    @property
    def signal_eligible(self) -> bool:
        return self.volume is not None and self.volume >= MIN_SIGNAL_VOLUME


def fetch_evening_polymarket_events(
    slate_date: str,
    timeout: float = 20,
) -> list[PolymarketEvent]:
    start = datetime.fromisoformat(slate_date).replace(
        hour=18, minute=0, second=0, microsecond=0, tzinfo=timezone(timedelta(hours=8))
    )
    return fetch_polymarket_events(start, start + timedelta(hours=12), timeout=timeout)


def fetch_polymarket_events_for_date(
    match_date: str,
    timeout: float = 20,
) -> list[PolymarketEvent]:
    start = datetime.fromisoformat(match_date).replace(tzinfo=timezone(timedelta(hours=8)))
    return fetch_polymarket_events(start, start + timedelta(days=1), timeout=timeout)


def fetch_polymarket_events(
    start: datetime,
    end: datetime,
    timeout: float = 20,
) -> list[PolymarketEvent]:
    # Sports events can open days before kickoff, so filter by their resolution/end window.
    query = urlencode(
        {
            "active": "true",
            "closed": "false",
            "limit": 500,
            "end_date_min": _utc_iso(start - timedelta(hours=6)),
            "end_date_max": _utc_iso(end + timedelta(hours=6)),
        }
    )
    request = Request(
        f"{POLYMARKET_GAMMA_URL}?{query}",
        headers={"User-Agent": "odds-analyzer/0.1", "Accept": "application/json"},
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return parse_polymarket_events(payload)


def parse_polymarket_events(payload: list[dict[str, Any]]) -> list[PolymarketEvent]:
    if not isinstance(payload, list):
        raise ValueError("Polymarket events response must be a list")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in payload:
        game_id = _text(item.get("gameId"))
        key = game_id or _text(item.get("slug"))
        grouped.setdefault(key, []).append(item)
    return [event for items in grouped.values() if (event := _parse_event_group(items)) is not None]


def _parse_event_group(items: list[dict[str, Any]]) -> PolymarketEvent | None:
    primary = min(items, key=lambda item: len(_text(item.get("title"))) or 10_000)
    title = _text(primary.get("title"))
    teams = re.split(r"\s+vs\.?\s+", title, maxsplit=1, flags=re.IGNORECASE)
    if len(teams) != 2:
        return None
    home_team, away_team = (team.strip() for team in teams)
    markets = [market for item in items for market in (item.get("markets") or [])]
    probabilities = _moneyline_probabilities(markets, home_team, away_team)
    favorite_home = probabilities.get("home", 0.0) >= probabilities.get("away", 0.0)
    favorite_spread = _favorite_spread(markets, home_team, away_team, favorite_home)
    if not probabilities and favorite_spread is None:
        return None

    start_time = _text(primary.get("eventStartTime")) or _first_market_time(markets)
    updated_at = _latest_text(markets, "updatedAt") or _latest_text(items, "updatedAt") or None
    volumes = [_float(item.get("volume")) for item in items]
    liquidities = [_float(item.get("liquidity")) for item in items]
    return PolymarketEvent(
        event_id=_text(primary.get("id")),
        slug=_text(primary.get("slug")),
        title=title,
        start_time=start_time or None,
        updated_at=updated_at,
        home_team=home_team,
        away_team=away_team,
        home_probability=probabilities.get("home"),
        draw_probability=probabilities.get("draw"),
        away_probability=probabilities.get("away"),
        favorite_spread=favorite_spread,
        volume=max((value for value in volumes if value is not None), default=None),
        liquidity=max((value for value in liquidities if value is not None), default=None),
    )


def _moneyline_probabilities(
    markets: list[dict[str, Any]], home_team: str, away_team: str
) -> dict[str, float]:
    result: dict[str, float] = {}
    for market in markets:
        market_type = _text(market.get("sportsMarketType")).casefold()
        descriptor = " ".join(
            _text(market.get(key))
            for key in ("question", "groupItemTitle", "slug")
        )
        if "moneyline" not in market_type and not _looks_like_match_winner(descriptor):
            continue
        outcomes = _json_list(market.get("outcomes"))
        prices = [_float(value) for value in _json_list(market.get("outcomePrices"))]
        if len(outcomes) == 3 and len(prices) == 3:
            for outcome, price in zip(outcomes, prices):
                key = _selection_key(_text(outcome), home_team, away_team)
                if key and price is not None:
                    result[key] = price
            continue
        probability = _yes_probability(outcomes, prices)
        key = _selection_key(descriptor, home_team, away_team)
        if key and probability is not None:
            result[key] = probability

    if all(key in result for key in ("home", "draw", "away")):
        total = sum(result.values())
        if total > 0:
            return {key: result[key] / total for key in ("home", "draw", "away")}
    return result


def _favorite_spread(
    markets: list[dict[str, Any]], home_team: str, away_team: str, favorite_home: bool
) -> PolymarketSpread | None:
    spreads: list[PolymarketSpread] = []
    for market in markets:
        market_type = _text(market.get("sportsMarketType")).casefold()
        descriptor = " ".join(
            _text(market.get(key))
            for key in ("question", "groupItemTitle", "slug")
        )
        if "spread" not in market_type and not re.search(r"[+-]\s*\d+(?:\.\d+)?", descriptor):
            continue
        team_descriptor = " ".join(
            _text(market.get(key)) for key in ("question", "groupItemTitle")
        )
        team_key = _selection_key(team_descriptor, home_team, away_team)
        if team_key not in {"home", "away"}:
            continue
        line = _line_from_descriptor(team_descriptor)
        if line is None:
            line = _float(market.get("line"))
        probability = _yes_probability(
            _json_list(market.get("outcomes")),
            [_float(value) for value in _json_list(market.get("outcomePrices"))],
        )
        if line is None or probability is None:
            continue
        spreads.append(
            PolymarketSpread(
                team=home_team if team_key == "home" else away_team,
                line=line,
                probability=probability,
                volume=_float(market.get("volumeNum")) or _float(market.get("volume")),
            )
        )
    favorite_team = home_team if favorite_home else away_team
    negative = [spread for spread in spreads if spread.line < 0 and spread.team == favorite_team]
    if not negative:
        return None
    return min(negative, key=lambda spread: abs(abs(spread.line) - 1.5))


def _selection_key(value: str, home_team: str, away_team: str) -> str | None:
    normalized = _normalize(value)
    if "draw" in normalized or "tie" in normalized:
        return "draw"
    home = _normalize(home_team)
    away = _normalize(away_team)
    if home and home in normalized:
        return "home"
    if away and away in normalized:
        return "away"
    return None


def _looks_like_match_winner(value: str) -> bool:
    normalized = value.casefold()
    return " win" in normalized or "winner" in normalized or " draw" in normalized


def _line_from_descriptor(value: str) -> float | None:
    match = re.search(r"([+-])\s*(\d+(?:\.\d+)?)", value)
    if not match:
        return None
    number = float(match.group(2))
    return number if match.group(1) == "+" else -number


def _yes_probability(outcomes: list[Any], prices: list[float | None]) -> float | None:
    for outcome, price in zip(outcomes, prices):
        if _text(outcome).casefold() in {"yes", "y"}:
            return price
    return prices[0] if len(prices) == 2 else None


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _first_market_time(markets: list[dict[str, Any]]) -> str:
    for market in markets:
        value = _text(market.get("gameStartTime")) or _text(market.get("eventStartTime"))
        if value:
            return value
    return ""


def _latest_text(markets: list[dict[str, Any]], key: str) -> str:
    values = [_text(market.get(key)) for market in markets if _text(market.get(key))]
    return max(values, default="")


def _sum_market_value(markets: list[dict[str, Any]], key: str) -> float | None:
    values = [_float(market.get(key)) for market in markets]
    available = [value for value in values if value is not None]
    return sum(available) if available else None


def _normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold()).encode("ascii", "ignore").decode("ascii")
    tokens = re.findall(r"[a-z0-9]+", folded)
    ignored = {"afc", "cf", "cfc", "club", "fc", "the", "ud"}
    return "".join(token for token in tokens if token not in ignored)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
