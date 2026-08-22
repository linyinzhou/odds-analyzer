from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


OFFICIAL_SPORTTERY_URL = "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry"
SPORTTERY_POOLS = ("had", "hhad", "crs", "ttg", "hafu")
POOL_LABELS = {
    "had": "胜平负",
    "hhad": "让球胜平负",
    "crs": "比分",
    "ttg": "总进球",
    "hafu": "半全场",
}


@dataclass(frozen=True)
class SportteryOutcome:
    key: str
    label: str
    odds: float
    trend: str


@dataclass(frozen=True)
class SportteryMarket:
    code: str
    label: str
    line: float | None
    outcomes: tuple[SportteryOutcome, ...]
    updated_at: str | None = None


@dataclass(frozen=True)
class SportteryMatch:
    match_id: str
    match_no: str
    business_date: str
    league: str
    home_team: str
    away_team: str
    kickoff_at: str
    markets: tuple[SportteryMarket, ...]

    @property
    def handicap(self) -> float | None:
        market = self.market("hhad")
        return market.line if market else None

    def market(self, code: str) -> SportteryMarket | None:
        return next((market for market in self.markets if market.code == code), None)


def fetch_official_sporttery_matches(business_date: str, timeout: float = 15) -> list[SportteryMatch]:
    query = urlencode({"poolCode": ",".join(SPORTTERY_POOLS), "channel": "c"})
    request = Request(
        f"{OFFICIAL_SPORTTERY_URL}?{query}",
        headers={
            "Referer": "https://m.sporttery.cn/",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent": "odds-analyzer/0.1",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return parse_official_sporttery(payload, business_date)


def parse_official_sporttery(payload: dict[str, Any], business_date: str) -> list[SportteryMatch]:
    groups = (payload.get("value") or {}).get("matchInfoList")
    if not isinstance(groups, list):
        raise ValueError("Sporttery response missing value.matchInfoList")

    matches: list[SportteryMatch] = []
    updated_at = _text((payload.get("value") or {}).get("lastUpdateTime")) or None
    for group in groups:
        group_date = _normalize_date(_text(group.get("businessDate") or group.get("matchNumDate")))
        for item in group.get("subMatchList") or []:
            item_date = _normalize_date(
                _text(item.get("businessDate") or group.get("businessDate") or group.get("matchNumDate"))
            )
            if item_date != business_date and group_date != business_date:
                continue

            markets = tuple(
                market
                for pool in SPORTTERY_POOLS
                if (market := _parse_market(pool, item.get(pool) or {}, updated_at)) is not None
            )
            matches.append(
                SportteryMatch(
                    match_id=_text(item.get("matchId")),
                    match_no=_text(item.get("matchNumStr")),
                    business_date=business_date,
                    league=_text(item.get("leagueAbbName") or item.get("leagueAllName")),
                    home_team=_text(item.get("homeTeamAbbName") or item.get("homeTeamAllName")),
                    away_team=_text(item.get("awayTeamAbbName") or item.get("awayTeamAllName")),
                    kickoff_at=_kickoff(
                        _text(item.get("matchDate")) or business_date,
                        _text(item.get("matchTime")),
                    ),
                    markets=markets,
                )
            )
    return matches


def _parse_market(pool: str, raw: dict[str, Any], updated_at: str | None) -> SportteryMarket | None:
    outcomes: list[SportteryOutcome] = []
    for code in _market_codes(pool, raw):
        try:
            odds = float(raw[code])
        except (KeyError, TypeError, ValueError):
            continue
        if odds <= 1:
            continue
        key, label = _decode_outcome(pool, code)
        outcomes.append(SportteryOutcome(key=key, label=label, odds=odds, trend=_trend(raw.get(f"{code}f"))))

    if not outcomes:
        return None

    return SportteryMarket(
        code=pool,
        label=POOL_LABELS[pool],
        line=_optional_float(raw.get("goalLineValue", raw.get("goalLine"))),
        outcomes=tuple(outcomes),
        updated_at=_text(raw.get("updateTime")) or updated_at,
    )


def _market_codes(pool: str, raw: dict[str, Any]) -> list[str]:
    canonical = {
        "had": ("h", "d", "a"),
        "hhad": ("h", "d", "a"),
        "ttg": ("s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7"),
        "hafu": ("hh", "hd", "ha", "dh", "dd", "da", "ah", "ad", "aa"),
    }.get(pool, ())
    present = [key for key in raw if key not in {"goalLine", "goalLineValue", "updateDate", "updateTime", "id"}]
    present = [key for key in present if not key.endswith("f")]
    return [key for key in canonical if key in present] + [key for key in present if key not in canonical]


def _decode_outcome(pool: str, code: str) -> tuple[str, str]:
    if pool in ("had", "hhad"):
        return {
            "h": ("home", "主胜"),
            "d": ("draw", "平"),
            "a": ("away", "客胜"),
        }.get(code, (code, code))
    if pool == "ttg" and code.startswith("s") and code[1:].isdigit():
        value = int(code[1:])
        return ("7+", "7球+") if value >= 7 else (str(value), f"{value}球")
    if pool == "hafu" and len(code) == 2:
        labels = {"h": "胜", "d": "平", "a": "负"}
        if code[0] in labels and code[1] in labels:
            return code.upper(), f"{labels[code[0]]}/{labels[code[1]]}"
    if pool == "crs" and code.startswith("s") and "s" in code[1:]:
        home, away = code[1:].split("s", 1)
        if home.isdigit() and away.isdigit():
            return f"{int(home)}:{int(away)}", f"{int(home)}:{int(away)}"
    return {
        "s1sh": ("win-other", "胜其它"),
        "s1sd": ("draw-other", "平其它"),
        "s1sa": ("loss-other", "负其它"),
    }.get(code, (code, code))


def _kickoff(day: str, clock: str) -> str:
    normalized = _normalize_date(day)
    return f"{normalized}T{clock or '00:00:00'}"


def _normalize_date(value: str) -> str:
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%y%m%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return value


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _trend(value: Any) -> str:
    return {"1": "up", "0": "flat", "-1": "down"}.get(_text(value), "unknown")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
