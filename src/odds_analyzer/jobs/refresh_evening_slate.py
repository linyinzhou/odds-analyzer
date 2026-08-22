from __future__ import annotations

import argparse
import json
import os
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from odds_analyzer.dashboard_payload import merge_dashboard_payload
from odds_analyzer.sources import (
    FootballDataSnapshot,
    OddsApiEvent,
    SportteryMatch,
    fetch_evening_football_data,
    fetch_evening_odds_api_events,
    fetch_official_sporttery_matches,
    fixture_dashboard_id,
)


BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PAYLOAD_PATH = PROJECT_ROOT / "dashboard" / "data" / "daily_matches.json"

EXISTING_DETAIL_IDS_BY_DATE = {
    "2026-08-22": [
        "2026-08-22-hull-man-united",
        "2026-08-22-everton-crystal-palace",
        "2026-08-22-ipswich-sunderland",
        "2026-08-22-nottingham-forest-leeds",
        "2026-08-23-brentford-tottenham",
    ]
}

TEAM_ALIASES = {
    "Hull City": "赫尔城",
    "Hull City AFC": "赫尔城",
    "Manchester United": "曼联",
    "Manchester United FC": "曼联",
    "Everton": "埃弗顿",
    "Everton FC": "埃弗顿",
    "Crystal Palace": "水晶宫",
    "Crystal Palace FC": "水晶宫",
    "Ipswich Town": "伊普斯",
    "Ipswich Town FC": "伊普斯",
    "Sunderland": "桑德兰",
    "Sunderland AFC": "桑德兰",
    "Nottingham Forest": "诺丁汉",
    "Nottingham Forest FC": "诺丁汉",
    "Leeds United": "利兹联",
    "Leeds United FC": "利兹联",
    "Brentford": "布伦特",
    "Brentford FC": "布伦特",
    "Tottenham Hotspur": "热刺",
    "Tottenham Hotspur FC": "热刺",
    "Athletic Club": "毕尔巴鄂",
    "Sevilla FC": "塞维利亚",
    "Valencia CF": "巴伦西亚",
    "Celta Vigo": "塞尔塔",
    "RC Celta de Vigo": "塞尔塔",
    "Espanyol": "西班牙人",
    "RCD Espanyol de Barcelona": "西班牙人",
    "Real Madrid": "皇马",
    "Real Madrid CF": "皇马",
    "Inter Milan": "国际米兰",
    "FC Internazionale Milano": "国际米兰",
    "Monza": "蒙扎",
    "AC Monza": "蒙扎",
    "Udinese": "乌迪内斯",
    "Udinese Calcio": "乌迪内斯",
    "Como": "科莫",
    "Como 1907": "科莫",
    "Genoa": "热那亚",
    "Genoa CFC": "热那亚",
    "Napoli": "那不勒斯",
    "SSC Napoli": "那不勒斯",
    "Parma": "帕尔马",
    "Parma Calcio 1913": "帕尔马",
    "Cagliari": "卡利亚里",
    "Cagliari Calcio": "卡利亚里",
    "Lens": "朗斯",
    "Racing Club de Lens": "朗斯",
    "RC Lens": "朗斯",
    "Auxerre": "欧塞尔",
    "Le Mans": "勒芒",
    "Le Mans FC": "勒芒",
    "Brest": "布雷斯特",
    "Stade Brestois 29": "布雷斯特",
    "AJ Auxerre": "欧塞尔",
    "Nice": "尼斯",
    "OGC Nice": "尼斯",
    "Lorient": "洛里昂",
    "FC Lorient": "洛里昂",
    "Toulouse": "图卢兹",
    "Toulouse FC": "图卢兹",
    "Lyon": "里昂",
    "Olympique Lyonnais": "里昂",
    "Troyes": "特鲁瓦",
    "ES Troyes AC": "特鲁瓦",
    "Paris FC": "巴黎FC",
    "赫尔城": "赫尔城",
    "曼联": "曼联",
    "埃弗顿": "埃弗顿",
    "水晶宫": "水晶宫",
    "伊普斯维奇": "伊普斯",
    "桑德兰": "桑德兰",
    "诺丁汉森林": "诺丁汉",
    "利兹联": "利兹联",
    "布伦特福德": "布伦特",
    "热刺": "热刺",
}
CURATED_FIXTURES_BY_DATE = {
    "2026-08-22": [
        {
            "id": "2026-08-22-athletic-club-sevilla-fc",
            "kickoff_time": "2026-08-22 23:00",
            "competition": "西甲 2026/27 第 2 轮",
            "home_team": "Athletic Club",
            "away_team": "Sevilla FC",
            "round": "第 2 轮",
        },
        {
            "id": "2026-08-23-valencia-cf-celta-vigo",
            "kickoff_time": "2026-08-23 01:30",
            "competition": "西甲 2026/27 第 2 轮",
            "home_team": "Valencia CF",
            "away_team": "Celta Vigo",
            "round": "第 2 轮",
        },
        {
            "id": "2026-08-23-espanyol-real-madrid",
            "kickoff_time": "2026-08-23 03:30",
            "competition": "西甲 2026/27 第 2 轮",
            "home_team": "Espanyol",
            "away_team": "Real Madrid",
            "round": "第 2 轮",
        },
        {
            "id": "2026-08-23-inter-milan-monza",
            "kickoff_time": "2026-08-23 00:30",
            "competition": "意甲 2026/27 第 1 轮",
            "home_team": "Inter Milan",
            "away_team": "Monza",
            "round": "第 1 轮",
        },
        {
            "id": "2026-08-23-udinese-como",
            "kickoff_time": "2026-08-23 00:30",
            "competition": "意甲 2026/27 第 1 轮",
            "home_team": "Udinese",
            "away_team": "Como",
            "round": "第 1 轮",
        },
        {
            "id": "2026-08-23-genoa-napoli",
            "kickoff_time": "2026-08-23 02:45",
            "competition": "意甲 2026/27 第 1 轮",
            "home_team": "Genoa",
            "away_team": "Napoli",
            "round": "第 1 轮",
        },
        {
            "id": "2026-08-23-parma-cagliari",
            "kickoff_time": "2026-08-23 02:45",
            "competition": "意甲 2026/27 第 1 轮",
            "home_team": "Parma",
            "away_team": "Cagliari",
            "round": "第 1 轮",
        },
        {
            "id": "2026-08-22-lens-auxerre",
            "kickoff_time": "2026-08-22 23:15",
            "competition": "法甲 2026/27 第 1 轮",
            "home_team": "Lens",
            "away_team": "Auxerre",
            "round": "第 1 轮",
        },
        {
            "id": "2026-08-23-le-mans-brest",
            "kickoff_time": "2026-08-23 02:45",
            "competition": "法甲 2026/27 第 1 轮",
            "home_team": "Le Mans",
            "away_team": "Brest",
            "round": "第 1 轮",
        },
        {
            "id": "2026-08-23-nice-lorient",
            "kickoff_time": "2026-08-23 02:45",
            "competition": "法甲 2026/27 第 1 轮",
            "home_team": "Nice",
            "away_team": "Lorient",
            "round": "第 1 轮",
        },
        {
            "id": "2026-08-23-toulouse-lyon",
            "kickoff_time": "2026-08-23 02:45",
            "competition": "法甲 2026/27 第 1 轮",
            "home_team": "Toulouse",
            "away_team": "Lyon",
            "round": "第 1 轮",
        },
        {
            "id": "2026-08-23-troyes-paris-fc",
            "kickoff_time": "2026-08-23 02:45",
            "competition": "法甲 2026/27 第 1 轮",
            "home_team": "Troyes",
            "away_team": "Paris FC",
            "round": "第 1 轮",
        },
    ]
}


def _today_beijing() -> str:
    return datetime.now(BEIJING).date().isoformat()


def _load_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_payload(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _placeholder_match(fixture: dict) -> dict:
    home = fixture["home_team"]
    away = fixture["away_team"]
    return {
        **fixture,
        "venue": "待补",
        "weather": "待补",
        "status": "pending",
        "signal_label": "数据待补",
        "european_odds": None,
        "asian_handicap": None,
        "chinese_lottery": None,
        "fundamentals": [
            {
                "home": f"{home} 赛程已进入本批次，基本面数据源待接入。",
                "away": f"{away} 赛程已进入本批次，基本面数据源待接入。",
            }
        ],
        "market_read": "欧赔、亚盘、竞彩数据待补；不做盘口判断。",
        "mismatch": {
            "matched": False,
            "reason": "缺少亚盘或竞彩让球数据，不能运行错盘检查。",
            "pick": "不进入错盘栏",
        },
        "recommendation": {
            "fundamental": "数据不足，暂不形成赛前方向。",
            "mismatch": "不符合错盘检查条件：缺少亚盘或竞彩让球。",
        },
        "prediction": {
            "market": "无推荐",
            "pick": "跳过",
            "confidence": 0,
            "detail": "缺少赔率、竞彩和基本面数据，不能给出可复盘下注建议。",
        },
        "checker": "数据不足，不进入高信心 checker。",
        "risks": ["盘口、基本面、伤停和天气数据待补。"],
        "sources": ["Curated fixture seed / evening slate"],
    }





def _add_football_data_fixtures(matches: list[dict], snapshot: FootballDataSnapshot) -> list[dict]:
    result = [deepcopy(match) for match in matches]
    existing_keys = {_dashboard_match_key(match) for match in result}
    for fixture in snapshot.fixtures:
        candidate = _match_from_football_data_fixture(fixture)
        if _dashboard_match_key(candidate) in existing_keys:
            continue
        existing_keys.add(_dashboard_match_key(candidate))
        result.append(candidate)
    return result


def _match_from_football_data_fixture(fixture) -> dict:
    competition = _football_data_competition_label(fixture)
    match = _placeholder_match(
        {
            "id": fixture_dashboard_id(fixture),
            "kickoff_time": fixture.kickoff_time,
            "competition": competition,
            "home_team": fixture.home_team,
            "away_team": fixture.away_team,
            "round": _football_data_round_label(fixture),
        }
    )
    match["venue"] = fixture.venue or "待补"
    match["football_data_snapshot"] = _football_data_fixture_snapshot(fixture)
    match["sources"] = ["football-data.org"]
    return match


def _enrich_with_football_data(matches: list[dict], snapshot: FootballDataSnapshot) -> list[dict]:
    fixture_index = {_football_data_fixture_key(fixture): fixture for fixture in snapshot.fixtures}
    enriched = []
    for match in matches:
        copied = deepcopy(match)
        fixture = fixture_index.get(_dashboard_match_key(copied))
        if fixture is None:
            enriched.append(copied)
            continue

        if fixture.venue:
            copied["venue"] = fixture.venue
        copied["competition"] = _football_data_competition_label(fixture)
        copied["round"] = _football_data_round_label(fixture)
        copied["football_data_snapshot"] = _football_data_fixture_snapshot(fixture)
        copied["fundamentals"] = [
            {
                "home": _fundamental_summary(
                    fixture.home_team,
                    fixture.home_team_id,
                    snapshot,
                ),
                "away": _fundamental_summary(
                    fixture.away_team,
                    fixture.away_team_id,
                    snapshot,
                ),
            }
        ]
        sources = list(copied.get("sources", []))
        if "football-data.org" not in sources:
            sources.append("football-data.org")
        copied["sources"] = sources
        if copied.get("status") == "pending":
            copied["signal_label"] = "基本面已抓取"
        enriched.append(copied)
    return enriched


def _football_data_fixture_key(fixture) -> tuple[str, str, str, str]:
    return (
        _football_data_league_key(fixture.competition_code),
        _kickoff_key(fixture.kickoff_time),
        _normalize_team(fixture.home_team),
        _normalize_team(fixture.away_team),
    )


def _football_data_league_key(code: str) -> str:
    mapping = {
        "PL": "英超",
        "PD": "西甲",
        "SA": "意甲",
        "BL1": "德甲",
        "FL1": "法甲",
        "CL": "欧冠",
    }
    return mapping.get(code, code)


def _football_data_competition_label(fixture) -> str:
    league = _football_data_league_key(fixture.competition_code)
    round_label = _football_data_round_label(fixture)
    return f"{league} {round_label}" if round_label else league


def _football_data_round_label(fixture) -> str:
    if fixture.matchday is not None:
        return f"第 {fixture.matchday} 轮"
    if fixture.stage:
        return fixture.stage.replace("_", " ")
    return ""


def _football_data_fixture_snapshot(fixture) -> dict:
    return {
        "match_id": fixture.match_id,
        "competition_code": fixture.competition_code,
        "utc_date": fixture.utc_date,
        "status": fixture.status,
        "source": "football-data.org",
    }


def _fundamental_summary(team_name: str, team_id: int | None, snapshot: FootballDataSnapshot) -> str:
    if team_id is None:
        return f"{team_name}：football-data.org 未返回球队 ID，排名和近况待补。"
    standing = snapshot.standings.get(team_id)
    form = snapshot.forms.get(team_id)
    parts = [team_name]
    if standing is not None:
        parts.append(
            f"排名第 {standing.position}，{standing.played_games} 场 {standing.won}胜{standing.draw}平{standing.lost}负，"
            f"进{standing.goals_for}失{standing.goals_against}，净胜{standing.goal_difference:+d}，{standing.points}分"
        )
    else:
        parts.append("排名待补")
    if form is not None:
        parts.append(f"近5场 {form.display}")
    else:
        parts.append("近5场待补")
    return "：".join((parts[0], "；".join(parts[1:])))
def _enrich_with_odds_api(matches: list[dict], odds_events: list[OddsApiEvent]) -> list[dict]:
    index = {_odds_api_key(event): event for event in odds_events}
    enriched = []
    for match in matches:
        copied = deepcopy(match)
        event = index.get(_dashboard_match_key(copied))
        if event is not None:
            if event.european_odds is not None:
                copied["european_odds"] = {
                    "home": event.european_odds.home,
                    "draw": event.european_odds.draw,
                    "away": event.european_odds.away,
                }
            if event.asian_handicap is not None:
                copied["asian_handicap"] = {
                    "provider": event.asian_handicap.provider,
                    "handicap": event.asian_handicap.handicap,
                    "home_odds": event.asian_handicap.home_odds,
                    "away_odds": event.asian_handicap.away_odds,
                }
            copied["odds_api_snapshot"] = {
                "event_id": event.event_id,
                "sport_key": event.sport_key,
                "bookmaker": event.bookmaker,
                "bookmaker_key": event.bookmaker_key,
                "updated_at": event.updated_at,
                "source": "The Odds API",
            }
            sources = list(copied.get("sources", []))
            if "The Odds API" not in sources:
                sources.append("The Odds API")
            copied["sources"] = sources
            if copied.get("status") == "pending" and (
                copied.get("european_odds") is not None or copied.get("asian_handicap") is not None
            ):
                copied["signal_label"] = "盘口已抓取" if copied.get("chinese_lottery") is None else "竞彩/盘口已抓取"
                copied["market_read"] = "欧赔/亚盘数据已抓取；基本面仍待补，暂不生成投注建议。"
                copied["recommendation"] = {
                    "fundamental": "基本面数据不足，暂不形成赛前方向。",
                    "mismatch": "盘口数据已补充，但缺少完整基本面校验；暂不进入错盘建议。",
                }
        enriched.append(copied)
    return enriched


def _odds_api_key(event: OddsApiEvent) -> tuple[str, str, str, str]:
    return (
        _league_from_sport_key(event.sport_key),
        _kickoff_key(_beijing_time_key(event.commence_time)),
        _normalize_team(event.home_team),
        _normalize_team(event.away_team),
    )


def _league_from_sport_key(sport_key: str) -> str:
    mapping = {
        "soccer_epl": "英超",
        "soccer_spain_la_liga": "西甲",
        "soccer_italy_serie_a": "意甲",
        "soccer_germany_bundesliga": "德甲",
        "soccer_france_ligue_one": "法甲",
        "soccer_uefa_champs_league": "欧冠",
    }
    return mapping.get(sport_key, sport_key)


def _beijing_time_key(value: str) -> str:
    if not value:
        return ""
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return value
    return parsed.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M")
def _enrich_with_sporttery(matches: list[dict], sporttery_matches: list[SportteryMatch]) -> list[dict]:
    index = {_sporttery_key(match): match for match in sporttery_matches}
    enriched = []
    for match in matches:
        copied = deepcopy(match)
        sporttery = index.get(_dashboard_match_key(copied))
        if sporttery is not None:
            copied["chinese_lottery"] = _sporttery_lottery_payload(sporttery)
            copied["sporttery_snapshot"] = {
                "match_no": sporttery.match_no,
                "match_id": sporttery.match_id,
                "source": "Sporttery official",
            }
            sources = list(copied.get("sources", []))
            if "Sporttery official" not in sources:
                sources.append("Sporttery official")
            copied["sources"] = sources
            if copied.get("status") == "pending":
                copied["signal_label"] = "竞彩已抓取"
                copied["market_read"] = "竞彩官方数据已抓取；欧赔、亚盘和基本面待补，暂不做错盘判断。"
                copied["recommendation"] = {
                    "fundamental": "基本面数据不足，暂不形成赛前方向。",
                    "mismatch": "不符合错盘检查条件：缺少亚盘数据，无法与竞彩让球比较。",
                }
        enriched.append(copied)
    return enriched


def _sporttery_key(match: SportteryMatch) -> tuple[str, str, str, str]:
    return (
        match.league,
        _kickoff_key(match.kickoff_at),
        _normalize_team(match.home_team),
        _normalize_team(match.away_team),
    )


def _dashboard_match_key(match: dict) -> tuple[str, str, str, str]:
    return (
        _competition_key(match.get("competition")),
        _kickoff_key(str(match.get("kickoff_time", ""))),
        _normalize_team(str(match.get("home_team", ""))),
        _normalize_team(str(match.get("away_team", ""))),
    )


def _competition_key(value: object) -> str:
    text = str(value or "")
    for league in ("英超", "西甲", "意甲", "德甲", "法甲", "欧冠"):
        if league in text:
            return league
    return text.strip()


def _kickoff_key(value: str) -> str:
    text = value.strip().replace("T", " ")
    if len(text) >= 16 and text[4] == "-":
        return text[:16]
    if len(text) >= 11 and text[2] == "-":
        return f"2026-{text[:11]}"
    return text[:16]


def _normalize_team(value: str) -> str:
    return TEAM_ALIASES.get(value, value).replace(" ", "").strip().casefold()


def _sporttery_lottery_payload(match: SportteryMatch) -> dict:
    had = _three_way_from_market(match.market("had"))
    hhad = match.market("hhad")
    return {
        "standard": had,
        "handicap": int(hhad.line) if hhad and hhad.line is not None else None,
        "handicap_odds": _three_way_from_market(hhad),
        "source": "Sporttery official",
        "match_no": match.match_no,
        "updated_at": _market_updated_at(match),
    }


def _three_way_from_market(market) -> dict | None:
    if market is None:
        return None
    values = {outcome.key: outcome.odds for outcome in market.outcomes}
    if not all(key in values for key in ("home", "draw", "away")):
        return None
    return {"home": values["home"], "draw": values["draw"], "away": values["away"]}


def _market_updated_at(match: SportteryMatch) -> str | None:
    for market in match.markets:
        if market.updated_at:
            return market.updated_at
    return None

def _attach_bilingual_reports(matches: list[dict]) -> list[dict]:
    """Attach compact query-time reports without turning unavailable inputs into facts."""
    reports = []
    for match in matches:
        copied = deepcopy(match)
        home = copied.get("home_team", "主队")
        away = copied.get("away_team", "客队")
        kickoff = copied.get("kickoff_time", "开球时间待补")
        prediction = copied.get("prediction", {})
        market = prediction.get("market", "无推荐")
        pick = prediction.get("pick", "跳过")
        confidence = prediction.get("confidence", 0)
        chinese_lottery = "已取得" if copied.get("chinese_lottery") else "未取得"
        european = "已取得" if copied.get("european_odds") else "未取得"
        asian = "已取得" if copied.get("asian_handicap") else "未取得"
        copied["report_zh"] = (
            f"{home} vs {away}，开球：{kickoff}。欧赔{european}、亚盘{asian}、竞彩{chinese_lottery}。"
            f"{copied.get('market_read', '市场解读待补')} 预测：{market} {pick}（信心 {confidence}%）。"
        )
        copied["report_en"] = (
            f"{home} vs {away}, kickoff {kickoff}. Query-time snapshot: European 1X2 {european}, "
            f"Asian handicap {asian}, Sporttery {chinese_lottery}. "
            f"Prediction: {market} {pick} (confidence {confidence}%)."
        )
        reports.append(copied)
    return reports
def _dedupe_fixtures(fixtures: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for fixture in fixtures:
        fixture_id = fixture.get("id")
        if fixture_id in seen:
            continue
        seen.add(fixture_id)
        result.append(fixture)
    return result


def _filter_next_matchday(
    existing_next_matchday: dict,
    current_matches: list[dict],
    query_time: datetime,
) -> dict:
    next_matchday = deepcopy(existing_next_matchday)
    current_keys = {
        _schedule_fixture_key(match.get("kickoff_time", ""), match.get("home_team", ""), match.get("away_team", ""))
        for match in current_matches
    }
    competitions = []
    for competition in next_matchday.get("competitions", []):
        fixtures = [
            fixture
            for fixture in competition.get("fixtures", [])
            if _fixture_is_after_query_time(fixture, query_time)
            and _schedule_fixture_key(
                fixture.get("kickoff_time", ""),
                fixture.get("home_team", ""),
                fixture.get("away_team", ""),
            )
            not in current_keys
        ]
        fixtures.sort(key=lambda fixture: _kickoff_key(str(fixture.get("kickoff_time", ""))))
        if fixtures:
            updated = deepcopy(competition)
            updated["fixtures"] = fixtures
            competitions.append(updated)
        elif competition.get("name") == "欧冠":
            competitions.append(deepcopy(competition))

    if not any(competition.get("name") == "欧冠" for competition in competitions):
        competitions.append(
            {
                "name": "欧冠",
                "status": "欧冠主阶段赛程未从可靠来源取得；不展示资格赛、附加赛或推测对阵。",
                "fixtures": [],
            }
        )
    next_matchday["competitions"] = competitions
    return next_matchday


def _schedule_fixture_key(kickoff_time: object, home_team: object, away_team: object) -> tuple[str, str, str]:
    return (
        _kickoff_key(str(kickoff_time)),
        _normalize_team(str(home_team)),
        _normalize_team(str(away_team)),
    )


def _fixture_is_after_query_time(fixture: dict, query_time: datetime) -> bool:
    kickoff = _kickoff_key(str(fixture.get("kickoff_time", "")))
    try:
        parsed = datetime.strptime(kickoff, "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING)
    except ValueError:
        return False
    return parsed > query_time


def build_evening_slate_batch(
    existing_payload: dict,
    slate_date: str,
    sporttery_matches: list[SportteryMatch] | None = None,
    sporttery_source: str = "not requested",
    odds_api_events: list[OddsApiEvent] | None = None,
    odds_api_source: str = "not requested",
    football_data_snapshot: FootballDataSnapshot | None = None,
    football_data_source: str = "not requested",
) -> dict:
    current_by_id = {
        match.get("id"): match for match in existing_payload.get("current_matches", [])
    }
    current_matches = []
    for match_id in EXISTING_DETAIL_IDS_BY_DATE.get(slate_date, []):
        if match_id in current_by_id:
            match = deepcopy(current_by_id[match_id])
            match["batch_date"] = slate_date
            current_matches.append(match)

    for fixture in _dedupe_fixtures(CURATED_FIXTURES_BY_DATE.get(slate_date, [])):
        match = _placeholder_match(fixture)
        match["batch_date"] = slate_date
        current_matches.append(match)

    if football_data_snapshot is not None:
        current_matches = _add_football_data_fixtures(current_matches, football_data_snapshot)
        current_matches = _enrich_with_football_data(current_matches, football_data_snapshot)
    if sporttery_matches:
        current_matches = _enrich_with_sporttery(current_matches, sporttery_matches)
    if odds_api_events:
        current_matches = _enrich_with_odds_api(current_matches, odds_api_events)
    current_matches = _attach_bilingual_reports(current_matches)

    next_matchday = _filter_next_matchday(
        existing_payload.get("next_matchday", {}),
        current_matches,
        datetime.now(BEIJING),
    )

    next_date = (date.fromisoformat(slate_date) + timedelta(days=1)).isoformat()
    window = f"{slate_date} 18:00 -> {next_date} 06:00 GMT+8"

    return {
        "slate": {
            "date": slate_date,
            "window": window,
            "generated_at": datetime.now(BEIJING).isoformat(timespec="seconds"),
            "source": "manual evening-report job",
            "sporttery_source": sporttery_source,
            "odds_api_source": odds_api_source,
            "football_data_source": football_data_source,
        },
        "current_matches": current_matches,
        "mismatch_history": [
            match
            for match in current_matches
            if match.get("mismatch", {}).get("matched") is True
        ],
        "checker_history": _checker_candidates(current_matches, slate_date),
        "next_matchday": next_matchday,
        "replace_history_batch": True,
    }


def _checker_candidates(matches: list[dict], slate_date: str) -> list[dict]:
    candidates = [
        match
        for match in matches
        if match.get("prediction", {}).get("confidence", 0) > 0
        and match.get("prediction", {}).get("market") != "无推荐"
    ]
    candidates.sort(
        key=lambda match: match.get("prediction", {}).get("confidence", 0),
        reverse=True,
    )
    return candidates[:8]


def refresh_evening_slate(path: Path, slate_date: str) -> dict:
    existing_payload = _load_payload(path)
    football_data_key = os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()
    if football_data_key:
        try:
            football_data_snapshot = fetch_evening_football_data(football_data_key, slate_date)
            football_data_source = _football_data_source_status(football_data_snapshot)
        except Exception as exc:
            football_data_snapshot = None
            football_data_source = f"football-data.org unavailable: {type(exc).__name__}"
    else:
        football_data_snapshot = None
        football_data_source = "football-data.org skipped: missing FOOTBALL_DATA_API_KEY"
    try:
        sporttery_matches = fetch_official_sporttery_matches(slate_date)
        sporttery_source = "Sporttery official"
    except Exception as exc:
        sporttery_matches = []
        sporttery_source = f"Sporttery unavailable: {type(exc).__name__}"
    odds_api_key = os.environ.get("THE_ODDS_API_KEY", "").strip()
    if odds_api_key:
        try:
            odds_api_events = fetch_evening_odds_api_events(odds_api_key, slate_date)
            odds_api_source = "The Odds API"
        except Exception as exc:
            odds_api_events = []
            odds_api_source = f"The Odds API unavailable: {type(exc).__name__}"
    else:
        odds_api_events = []
        odds_api_source = "The Odds API skipped: missing THE_ODDS_API_KEY"
    batch_payload = build_evening_slate_batch(
        existing_payload,
        slate_date,
        sporttery_matches=sporttery_matches,
        sporttery_source=sporttery_source,
        odds_api_events=odds_api_events,
        odds_api_source=odds_api_source,
        football_data_snapshot=football_data_snapshot,
        football_data_source=football_data_source,
    )
    merged_payload = merge_dashboard_payload(existing_payload, batch_payload)
    _write_payload(path, merged_payload)
    return merged_payload



def _football_data_source_status(snapshot: FootballDataSnapshot) -> str:
    if snapshot.fixtures and snapshot.errors:
        return "football-data.org partial: " + "; ".join(snapshot.errors[:6])
    if snapshot.fixtures:
        return "football-data.org"
    if snapshot.errors:
        return "football-data.org unavailable: " + "; ".join(snapshot.errors[:6])
    return "football-data.org empty: no fixtures in slate window"

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh dashboard data for the Beijing evening football slate."
    )
    parser.add_argument(
        "--date",
        default="",
        help="Slate date in YYYY-MM-DD, interpreted as Beijing local date.",
    )
    parser.add_argument(
        "--payload",
        default=str(DEFAULT_PAYLOAD_PATH),
        help="Path to dashboard/data/daily_matches.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    slate_date = args.date.strip() or _today_beijing()
    date.fromisoformat(slate_date)
    payload_path = Path(args.payload)
    payload = refresh_evening_slate(payload_path, slate_date)
    print(
        f"Refreshed {len(payload.get('current_matches', []))} matches "
        f"for {slate_date} into {payload_path}"
    )


if __name__ == "__main__":
    main()
