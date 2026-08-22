from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from odds_analyzer.dashboard_payload import merge_dashboard_payload


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


def _filter_next_matchday(existing_next_matchday: dict, current_ids: set[str]) -> dict:
    next_matchday = deepcopy(existing_next_matchday)
    competitions = []
    for competition in next_matchday.get("competitions", []):
        fixtures = [
            fixture
            for fixture in competition.get("fixtures", [])
            if fixture.get("id") not in current_ids
        ]
        if fixtures:
            updated = deepcopy(competition)
            updated["fixtures"] = fixtures
            competitions.append(updated)
    next_matchday["competitions"] = competitions
    return next_matchday


def build_evening_slate_batch(existing_payload: dict, slate_date: str) -> dict:
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

    current_ids = {match["id"] for match in current_matches}
    next_matchday = _filter_next_matchday(
        existing_payload.get("next_matchday", {}), current_ids
    )

    next_date = (date.fromisoformat(slate_date) + timedelta(days=1)).isoformat()
    window = f"{slate_date} 18:00 -> {next_date} 06:00 GMT+8"

    return {
        "slate": {
            "date": slate_date,
            "window": window,
            "generated_at": datetime.now(BEIJING).isoformat(timespec="seconds"),
            "source": "manual evening-report job",
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
    batch_payload = build_evening_slate_batch(existing_payload, slate_date)
    merged_payload = merge_dashboard_payload(existing_payload, batch_payload)
    _write_payload(path, merged_payload)
    return merged_payload


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

