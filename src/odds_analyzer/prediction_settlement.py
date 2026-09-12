from __future__ import annotations

import re
import math
from typing import Any

from odds_analyzer.models import AsianHandicapLine, ChineseLotteryLine, MatchScore, Selection
from odds_analyzer.settlement import settle_asian_handicap, settle_chinese_lottery


def settle_saved_prediction(match: dict[str, Any], score: MatchScore) -> dict[str, Any] | None:
    prediction = match.get("prediction") or {}
    market_type = prediction.get("market_type") or _legacy_market_type(prediction)
    if market_type == "sporttery_handicap":
        line = _saved_handicap(prediction)
        selections = _saved_selections(prediction, handicap=True)
        if line is None or not line.is_integer() or not selections:
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
        if line is None or not (line * 4).is_integer() or len(selections) != 1 or selections[0] is Selection.DRAW:
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
            parsed = float(value)
            return parsed if math.isfinite(parsed) else None
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
