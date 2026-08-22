from __future__ import annotations

import argparse
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from odds_analyzer.jobs.refresh_evening_slate import (
    BEIJING,
    DEFAULT_PAYLOAD_PATH,
    _dashboard_match_key,
    _football_data_fixture_key,
)
from odds_analyzer.models import AsianHandicapLine, ChineseLotteryLine, MatchScore, Selection
from odds_analyzer.settlement import settle_asian_handicap, settle_chinese_lottery
from odds_analyzer.sources import FootballDataFixture, fetch_evening_fixtures


FINISHED_STATUSES = {"FINISHED", "AWARDED"}


def review_checker_results(
    payload: dict[str, Any],
    slate_date: str,
    fixtures: tuple[FootballDataFixture, ...],
    reviewed_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    updated = deepcopy(payload)
    reviewed_at = reviewed_at or datetime.now(BEIJING).isoformat(timespec="seconds")
    fixtures_by_id = {fixture.match_id: fixture for fixture in fixtures if fixture.match_id}
    fixtures_by_key = {_football_data_fixture_key(fixture): fixture for fixture in fixtures}
    counts = {"reviewed": 0, "pending": 0, "unsupported": 0, "not_found": 0}

    history = []
    for match in updated.get("checker_history", []):
        copied = deepcopy(match)
        if str(copied.get("batch_date", "")) != slate_date:
            history.append(copied)
            continue

        fixture = _fixture_for_match(copied, fixtures_by_id, fixtures_by_key)
        if fixture is None:
            counts["not_found"] += 1
            history.append(copied)
            continue
        if (
            fixture.status not in FINISHED_STATUSES
            or fixture.home_score is None
            or fixture.away_score is None
        ):
            counts["pending"] += 1
            history.append(copied)
            continue

        decision = settle_saved_prediction(
            copied,
            MatchScore(home_goals=fixture.home_score, away_goals=fixture.away_score),
        )
        if decision is None:
            counts["unsupported"] += 1
            copied["review_error"] = "无法识别已保存的具体市场；未自动判定命中或未中。"
            history.append(copied)
            continue

        copied.pop("review_error", None)
        copied["review"] = {
            "final_score": f"{fixture.home_score}-{fixture.away_score}",
            "reviewed": True,
            "hit": decision["hit"],
            "void": decision["void"],
            "outcome": decision["outcome"],
            "settlement": decision.get("settlement"),
            "review_note": decision["note"],
            "reviewed_at": reviewed_at,
            "source": "football-data.org",
        }
        copied["result_snapshot"] = {
            "match_id": fixture.match_id,
            "status": fixture.status,
            "source": "football-data.org",
        }
        counts["reviewed"] += 1
        history.append(copied)

    updated["checker_history"] = history
    updated["last_result_review"] = {
        "batch_date": slate_date,
        "reviewed_at": reviewed_at,
        "source": "football-data.org",
        "fixture_count": len(fixtures),
        **counts,
    }
    return updated, counts


def settle_saved_prediction(match: dict[str, Any], score: MatchScore) -> dict[str, Any] | None:
    prediction = match.get("prediction") or {}
    market_type = prediction.get("market_type") or _legacy_market_type(prediction)
    if market_type == "sporttery_handicap":
        line = _saved_handicap(prediction)
        selections = _saved_selections(prediction, handicap=True)
        if line is None or not selections:
            return None
        result = settle_chinese_lottery(score, ChineseLotteryLine(home_handicap=int(line)))
        hit = result in selections
        return {
            "hit": hit,
            "void": False,
            "outcome": "win" if hit else "loss",
            "settlement": result.value,
            "note": f"竞彩让球结果为{_selection_zh(result)}；保存建议为{prediction.get('pick', '')}，判定{'命中' if hit else '未中'}。",
        }

    if market_type == "sporttery_standard":
        selections = _saved_selections(prediction, handicap=False)
        if not selections:
            return None
        result = settle_chinese_lottery(score, ChineseLotteryLine(home_handicap=0))
        hit = result in selections
        return {
            "hit": hit,
            "void": False,
            "outcome": "win" if hit else "loss",
            "settlement": result.value,
            "note": f"胜平负结果为{_selection_zh(result, handicap=False)}；保存建议为{prediction.get('pick', '')}，判定{'命中' if hit else '未中'}。",
        }

    if market_type == "asian_handicap":
        line = _saved_handicap(prediction)
        selections = _saved_selections(prediction, handicap=False)
        if line is None or len(selections) != 1 or selections[0] is Selection.DRAW:
            return None
        stake_result = settle_asian_handicap(
            score,
            AsianHandicapLine(home_handicap=float(line)),
            selections[0],
        )
        void = stake_result == 0
        hit = None if void else stake_result > 0
        outcome = {
            1.0: "win",
            0.5: "half_win",
            0.0: "push",
            -0.5: "half_loss",
            -1.0: "loss",
        }[stake_result]
        note = {
            "win": "亚盘全赢",
            "half_win": "亚盘半赢",
            "push": "亚盘走盘，不计入命中率",
            "half_loss": "亚盘半输",
            "loss": "亚盘全输",
        }[outcome]
        return {
            "hit": hit,
            "void": void,
            "outcome": outcome,
            "settlement": stake_result,
            "note": f"{prediction.get('pick', '')}结算为{note}。",
        }

    return None


def review_results(path: Path, slate_date: str, api_key: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    review_date = slate_date or _latest_review_batch(payload)
    reviewed_at = datetime.now(BEIJING).isoformat(timespec="seconds")
    if not api_key:
        payload["last_result_review"] = {
            "batch_date": review_date,
            "reviewed_at": reviewed_at,
            "status": "skipped",
            "source": "football-data.org",
            "error": "missing FOOTBALL_DATA_API_KEY",
        }
        _write_payload(path, payload)
        return payload

    try:
        fixtures = fetch_evening_fixtures(api_key, review_date)
    except Exception as exc:
        payload["last_result_review"] = {
            "batch_date": review_date,
            "reviewed_at": reviewed_at,
            "status": "unavailable",
            "source": "football-data.org",
            "error": type(exc).__name__,
        }
        _write_payload(path, payload)
        return payload

    payload, counts = review_checker_results(payload, review_date, fixtures, reviewed_at)
    payload["last_result_review"]["status"] = "success"
    _write_payload(path, payload)
    print(
        f"Reviewed {counts['reviewed']} checker entries for {review_date}; "
        f"pending={counts['pending']} unsupported={counts['unsupported']} not_found={counts['not_found']}"
    )
    return payload


def _fixture_for_match(
    match: dict[str, Any],
    fixtures_by_id: dict[int, FootballDataFixture],
    fixtures_by_key: dict[tuple[str, str, str, str], FootballDataFixture],
) -> FootballDataFixture | None:
    match_id = (match.get("football_data_snapshot") or {}).get("match_id")
    try:
        fixture = fixtures_by_id.get(int(match_id)) if match_id is not None else None
    except (TypeError, ValueError):
        fixture = None
    return fixture or fixtures_by_key.get(_dashboard_match_key(match))


def _legacy_market_type(prediction: dict[str, Any]) -> str:
    market = str(prediction.get("market", ""))
    if "竞彩让球" in market:
        return "sporttery_handicap"
    if "竞彩胜平负" in market:
        return "sporttery_standard"
    if "亚盘" in market:
        return "asian_handicap"
    return "unsupported"


def _saved_handicap(prediction: dict[str, Any]) -> float | None:
    value = prediction.get("home_handicap")
    if value is not None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    match = re.search(r"([+-]\d+(?:\.\d+)?)", str(prediction.get("market", "")))
    if match:
        return float(match.group(1))
    pick_match = re.search(r"([+-]\d+(?:\.\d+)?)\s*$", str(prediction.get("pick", "")))
    return float(pick_match.group(1)) if pick_match else None


def _saved_selections(prediction: dict[str, Any], handicap: bool) -> tuple[Selection, ...]:
    keys = prediction.get("selection_keys") or []
    parsed = []
    for key in keys:
        try:
            parsed.append(Selection(str(key)))
        except ValueError:
            continue
    if parsed:
        return tuple(parsed)

    pick = str(prediction.get("pick", ""))
    labels = (
        (("让胜", Selection.HOME), ("让平", Selection.DRAW), ("让负", Selection.AWAY))
        if handicap
        else (("主胜", Selection.HOME), ("平", Selection.DRAW), ("客胜", Selection.AWAY))
    )
    return tuple(selection for label, selection in labels if label in pick)


def _selection_zh(selection: Selection, handicap: bool = True) -> str:
    if handicap:
        return {Selection.HOME: "让胜", Selection.DRAW: "让平", Selection.AWAY: "让负"}[selection]
    return {Selection.HOME: "主胜", Selection.DRAW: "平", Selection.AWAY: "客胜"}[selection]


def _latest_review_batch(payload: dict[str, Any]) -> str:
    batches = [str(match.get("batch_date")) for match in payload.get("checker_history", []) if match.get("batch_date")]
    if batches:
        return max(batches)
    return (datetime.now(BEIJING).date() - timedelta(days=1)).isoformat()


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Settle stored checker predictions from final scores.")
    parser.add_argument("--date", default="", help="Checker batch date in Asia/Shanghai YYYY-MM-DD.")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD_PATH))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    slate_date = args.date.strip()
    if slate_date:
        datetime.fromisoformat(slate_date)
    review_results(
        Path(args.payload),
        slate_date,
        os.environ.get("FOOTBALL_DATA_API_KEY", "").strip(),
    )


if __name__ == "__main__":
    main()
