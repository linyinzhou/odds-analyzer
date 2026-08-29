from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from odds_analyzer.analysis import check_lottery_asian_mismatch
from odds_analyzer.fallback_queue import has_sufficient_fundamental_context
from odds_analyzer.models import AsianHandicapLine, ChineseLotteryLine, Selection


def analyze_slate_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [analyze_slate_match(match) for match in matches]


def analyze_slate_match(match: dict[str, Any]) -> dict[str, Any]:
    analyzed = deepcopy(match)
    european = analyzed.get("european_odds")
    asian = analyzed.get("asian_handicap")
    lottery = analyzed.get("chinese_lottery")
    context = analyzed.get("fundamental_context") or {}

    european_probabilities = _normalized_probabilities(european)
    fundamental_zh, fundamental_en = _fundamental_read(analyzed, context, european_probabilities)
    market_zh, market_en = _market_read(analyzed, european_probabilities)
    mismatch = _mismatch_read(analyzed, context, european_probabilities)
    prediction = _prediction(analyzed, context, european_probabilities, mismatch)

    analyzed["market_read"] = market_zh
    analyzed["market_read_en"] = market_en
    analyzed["mismatch"] = mismatch["dashboard"]
    analyzed["recommendation"] = {
        "fundamental": fundamental_zh,
        "fundamental_en": fundamental_en,
        "mismatch": mismatch["recommendation_zh"],
        "mismatch_en": mismatch["recommendation_en"],
    }
    analyzed["prediction"] = prediction
    analyzed["checker"] = _checker_text(prediction)
    analyzed["risks"] = _risks(analyzed, prediction)

    if mismatch["dashboard"]["matched"]:
        analyzed["status"] = "mismatch"
        analyzed["signal_label"] = (
            "错盘候选" if mismatch["dashboard"].get("limited_sample") else "错盘命中"
        )
    elif prediction["market"] != "无推荐":
        analyzed["status"] = "watch"
        analyzed["signal_label"] = "盘口观察"
    else:
        analyzed["status"] = "pending"
        analyzed["signal_label"] = "数据不足"
    return analyzed


def _normalized_probabilities(odds: dict[str, Any] | None) -> dict[str, float] | None:
    if not odds:
        return None
    try:
        raw = {key: 1.0 / float(odds[key]) for key in ("home", "draw", "away")}
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    total = sum(raw.values())
    if total <= 0:
        return None
    return {key: value / total for key, value in raw.items()}


def _fundamental_read(
    match: dict[str, Any],
    context: dict[str, Any],
    probabilities: dict[str, float] | None,
) -> tuple[str, str]:
    comparison = _fundamental_comparison(context)
    if comparison is not None:
        home = match.get("home_team", "主队")
        away = match.get("away_team", "客队")
        limited_sample = not has_sufficient_fundamental_context(context)
        zh_caveat = "；但当前赛季样本不足3场，方向信心有限。" if limited_sample else "。"
        en_caveat = "; however, fewer than three current-season results makes this a low-confidence direction." if limited_sample else "."
        if comparison > 0.2:
            return (
                f"排名、场均积分和净胜球样本偏向{home}{zh_caveat}",
                f"Table position, points per game and goal difference favor {home}{en_caveat}",
            )
        if comparison < -0.2:
            return (
                f"排名、场均积分和净胜球样本偏向{away}{zh_caveat}",
                f"Table position, points per game and goal difference favor {away}{en_caveat}",
            )
        return (
            f"双方现有排名、场均积分和净胜球样本接近，基本面方向中性{zh_caveat}",
            f"The available table, points-per-game and goal-difference sample is neutral{en_caveat}",
        )

    if match.get("football_data_snapshot"):
        return (
            "已取得官方赛程与排名接口数据，但赛季初有效比赛样本不足；本次方向主要参考查询时欧亚盘。",
            "Official fixture and standings data is available, but the early-season sample is limited; the call is market-led.",
        )
    if probabilities:
        return (
            "缺少可比较的排名与近期战绩，本次只记录市场方向，不形成高信心基本面结论。",
            "Comparable standings and form are unavailable; this is a market observation, not a high-confidence fundamental call.",
        )
    return (
        "基本面与盘口数据不足，暂不形成赛前方向。",
        "Fundamental and market data is insufficient for a pre-match direction.",
    )


def _market_read(
    match: dict[str, Any], probabilities: dict[str, float] | None
) -> tuple[str, str]:
    asian = match.get("asian_handicap")
    lottery = match.get("chinese_lottery")
    if not probabilities or not asian:
        polymarket_zh, polymarket_en = _polymarket_market_read(match)
        return (
            "缺少本次查询的完整欧赔或亚盘，不生成盘口建议。" + polymarket_zh,
            "Current European or Asian prices are incomplete, so no market recommendation is generated." + polymarket_en,
        )

    home = match.get("home_team", "主队")
    away = match.get("away_team", "客队")
    favorite_key = max(("home", "draw", "away"), key=probabilities.get)
    favorite = {"home": home, "draw": "平局", "away": away}[favorite_key]
    line = _format_line(float(asian["handicap"]))
    provider = asian.get("provider") or "亚盘来源"
    lottery_text = "本次竞彩已取得，可继续做三盘比较。" if lottery else "本次竞彩未取得，只做欧亚盘分析。"
    polymarket_zh, polymarket_en = _polymarket_market_read(match)
    zh = (
        f"欧赔去水后主/平/客约为 {probabilities['home']:.0%}/{probabilities['draw']:.0%}/{probabilities['away']:.0%}，"
        f"最高方向为{favorite}；{provider}主队视角 {line}。{lottery_text}{polymarket_zh}"
    )
    en = (
        f"De-vigged 1X2 is about {probabilities['home']:.0%}/{probabilities['draw']:.0%}/{probabilities['away']:.0%}; "
        f"the highest outcome is {favorite}. {provider} lists the home line at {line}. "
        + ("Current Sporttery data is available for the three-market check." if lottery else "Current Sporttery data is unavailable, so this is a European/Asian read only.")
        + polymarket_en
    )
    return zh, en


def _polymarket_market_read(match: dict[str, Any]) -> tuple[str, str]:
    market = match.get("polymarket") or {}
    probabilities = (market.get("home"), market.get("draw"), market.get("away"))
    if not all(isinstance(value, (int, float)) for value in probabilities):
        return "", ""
    spread = market.get("favorite_spread") or {}
    quality_zh = "可参与市场交叉验证" if market.get("signal_eligible") else "流动性偏低，只展示不参与信心修正"
    quality_en = "eligible for cross-market validation" if market.get("signal_eligible") else "low liquidity, display only"
    spread_zh = ""
    spread_en = ""
    if isinstance(spread.get("probability"), (int, float)):
        spread_zh = (
            f"；{spread.get('team', '热门方')} {_format_line(float(spread.get('line', -1.5)))}"
            f"支持率约 {spread['probability']:.0%}"
        )
        spread_en = (
            f"; {spread.get('team', 'favorite')} {_format_line(float(spread.get('line', -1.5)))}"
            f" is about {spread['probability']:.0%}"
        )
    return (
        f" Polymarket实时主/平/客约为 {probabilities[0]:.0%}/{probabilities[1]:.0%}/{probabilities[2]:.0%}{spread_zh}，{quality_zh}。",
        f" Polymarket live home/draw/away is about {probabilities[0]:.0%}/{probabilities[1]:.0%}/{probabilities[2]:.0%}{spread_en}; {quality_en}.",
    )


def _mismatch_read(
    match: dict[str, Any],
    context: dict[str, Any],
    probabilities: dict[str, float] | None,
) -> dict[str, Any]:
    asian = match.get("asian_handicap")
    lottery = match.get("chinese_lottery")
    lottery_line = lottery.get("handicap") if lottery else None
    if not asian or lottery_line is None:
        reason = "不符合错盘检查条件：本次查询缺少亚盘或竞彩让球。"
        return _mismatch_payload(
            False,
            reason,
            "不进入错盘栏",
            reason,
            "Mismatch check unavailable because current Asian or Sporttery handicap data is missing or invalid.",
        )

    try:
        asian_line = float(asian["handicap"])
        lottery_value = int(lottery_line)
    except (KeyError, TypeError, ValueError):
        reason = "不符合错盘检查条件：盘口格式无法比较。"
        return _mismatch_payload(
            False,
            reason,
            "不进入错盘栏",
            reason,
            "Mismatch check unavailable because current Asian or Sporttery handicap data is missing or invalid.",
        )

    favorite_home = asian_line <= 0
    if abs(asian_line) < 0.01 and probabilities:
        favorite_home = probabilities["home"] >= probabilities["away"]
    if not _market_supports_favorite(favorite_home, probabilities):
        reason = "不符合错盘规则：欧赔方向与亚盘热门方不一致。"
        return _mismatch_payload(
            False,
            reason,
            "不进入错盘栏",
            reason,
            "Mismatch check unavailable because current Asian or Sporttery handicap data is missing or invalid.",
        )

    comparison = _fundamental_comparison(context)
    if comparison is None:
        reason = "发现竞彩与亚盘线差，但缺少可比较的基本面方向，只记录观察。"
        return _mismatch_payload(
            False,
            reason,
            "基本面待验证",
            reason,
            "A line gap exists, but comparable fundamentals are unavailable.",
        )
    sample_sufficient = has_sufficient_fundamental_context(context)
    fundamentals_conflict = (favorite_home and comparison < -0.2) or (
        not favorite_home and comparison > 0.2
    )
    fundamentals_support_favorite = (favorite_home and comparison > 0.2) or (
        not favorite_home and comparison < -0.2
    )

    favorite_asian_line = asian_line if favorite_home else -asian_line
    favorite_lottery_line = lottery_value if favorite_home else -lottery_value
    max_margin = float(max(1, math.ceil(abs(favorite_asian_line))))
    check = check_lottery_asian_mismatch(
        AsianHandicapLine(home_handicap=favorite_asian_line),
        ChineseLotteryLine(home_handicap=favorite_lottery_line),
        max_supported_home_margin=max_margin,
    )

    limited_sample = False
    if check.status == "lottery_deeper_small_win":
        if not fundamentals_conflict:
            reason = (
                "不符合反热门错盘条件：现有基本面与盘口热门方方向一致。"
                if fundamentals_support_favorite
                else "发现竞彩深于亚盘，但现有基本面方向中性，只记录观察。"
            )
            return _mismatch_payload(
                False,
                reason,
                "不进入错盘栏",
                reason,
                "The deeper Sporttery line is only an observation because fundamentals do not favor the underdog.",
            )
        limited_sample = not sample_sufficient
    elif not sample_sufficient:
        reason = "发现竞彩与亚盘线差，但基本面样本不足，只记录观察。"
        return _mismatch_payload(
            False,
            reason,
            "基本面待验证",
            reason,
            "A line gap exists, but the fundamental sample is insufficient.",
        )
    elif not fundamentals_support_favorite:
        reason = "不符合错盘规则：基本面不支持浅盘所需的热门方向。"
        return _mismatch_payload(
            False,
            reason,
            "不进入错盘栏",
            reason,
            "Fundamentals do not support the favorite required by the shallower-line pattern.",
        )

    polymarket_validation = _polymarket_lottery_validation(match, check.status)
    check_reason = check.reason
    if check.status == "lottery_deeper_small_win":
        check_reason = check_reason.rstrip("。") + "；基本面偏受让方，不支持盘口热门方打穿竞彩深盘。"
        if limited_sample:
            check_reason += "当前赛季样本不足3场，按错盘候选处理。"
    check_reason = check_reason.rstrip("。") + polymarket_validation["note_zh"]

    selections = check.preferred_selections
    if not favorite_home:
        selections = tuple(_reverse_selection(selection) for selection in selections)

    matched = check.status in {
        "lottery_deeper_small_win",
        "lottery_shallower_favorite_supported",
    } and polymarket_validation["status"] != "conflict"
    pick = _lottery_pick(selections) if matched else "不进入错盘栏"
    if matched:
        label = "符合错盘候选形态" if limited_sample else "符合错盘规则"
        recommendation = (
            f"{label}；竞彩让球 {lottery_value:+d}：{pick}。"
            f"{polymarket_validation['recommendation_zh']}"
        )
    elif polymarket_validation["status"] == "conflict":
        recommendation = (
            "竞彩与欧亚盘存在错盘形态，但Polymarket有效市场给出反向信号，"
            "本次降级为观察，不进入竞彩建议。"
        )
    else:
        recommendation = f"不符合明确错盘条件：{check.reason}"
    recommendation_en = (
        f"Mismatch confirmed; Sporttery handicap {lottery_value:+d}: {_selection_labels_en(selections)}. "
        f"{polymarket_validation['recommendation_en']}"
        if matched
        else (
            "The line pattern exists, but a liquid Polymarket signal conflicts with the Sporttery selection; watch only."
            if polymarket_validation["status"] == "conflict"
            else "No confirmed mismatch opportunity after the line, market and fundamental checks."
        )
    )
    payload = _mismatch_payload(
        matched,
        check_reason,
        pick,
        recommendation,
        recommendation_en,
        check.status,
        check.line_gap,
        selections,
    )
    payload["dashboard"]["polymarket_validation"] = polymarket_validation["status"]
    payload["dashboard"]["limited_sample"] = limited_sample
    return payload


def _prediction(
    match: dict[str, Any],
    context: dict[str, Any],
    probabilities: dict[str, float] | None,
    mismatch: dict[str, Any],
) -> dict[str, Any]:
    if mismatch["dashboard"]["matched"]:
        lottery_line = int(match["chinese_lottery"]["handicap"])
        polymarket_adjustment = _polymarket_confidence_adjustment(match, mismatch["dashboard"]["status"])
        confidence = min(72, 62 + round(abs(mismatch["line_gap"]) * 6) + polymarket_adjustment)
        if mismatch["dashboard"].get("limited_sample"):
            confidence = min(confidence, 58)
        pick = mismatch["dashboard"]["pick"].split("：", 1)[-1]
        return {
            "market": f"竞彩让球 {lottery_line:+d}",
            "pick": pick,
            "confidence": confidence,
            "detail": mismatch["recommendation_zh"],
            "market_en": f"Sporttery handicap {lottery_line:+d}",
            "pick_en": _selection_labels_en(mismatch["selections"]),
            "detail_en": mismatch["recommendation_en"],
            "basis": "fresh_multi_market_snapshot" if polymarket_adjustment else "fresh_three_market_snapshot",
            "market_type": "sporttery_handicap",
            "home_handicap": lottery_line,
            "selection_keys": [selection.value for selection in mismatch["selections"]],
        }

    asian = match.get("asian_handicap")
    if not asian or not probabilities or not match.get("football_data_snapshot"):
        return _no_prediction()
    try:
        home_price = float(asian["home_odds"])
        away_price = float(asian["away_odds"])
        home_line = float(asian["handicap"])
    except (KeyError, TypeError, ValueError):
        return _no_prediction()
    if min(home_price, away_price) <= 1:
        return _no_prediction()

    home_cover, away_cover = _two_way_probabilities(home_price, away_price)
    if abs(home_cover - away_cover) < 0.01:
        pick_home = probabilities["home"] >= probabilities["away"]
    else:
        pick_home = home_cover > away_cover
    selected_cover = home_cover if pick_home else away_cover
    selected_win = probabilities["home"] if pick_home else probabilities["away"]
    favorite_agrees = (pick_home and probabilities["home"] >= probabilities["away"]) or (
        not pick_home and probabilities["away"] > probabilities["home"]
    )
    fundamental_agrees = _fundamental_agrees(context, pick_home)
    confidence = round(selected_cover * 100) + (2 if favorite_agrees else 0) + (2 if fundamental_agrees else 0)
    confidence = max(51, min(60, confidence))

    team = match.get("home_team", "主队") if pick_home else match.get("away_team", "客队")
    selection_line = home_line if pick_home else -home_line
    line = _format_line(selection_line)
    provider = asian.get("provider") or "亚盘"
    detail = (
        f"查询时{provider}去水后该方向覆盖概率约 {selected_cover:.0%}，欧赔胜向约 {selected_win:.0%}；"
        "这是基于当前市场与有限基本面的盘口方向，不代表存在正期望收益。"
    )
    detail_en = (
        f"The de-vigged Asian market gives this side about {selected_cover:.0%} cover probability and the 1X2 win probability is about {selected_win:.0%}. "
        "This is a current-market direction, not proof of positive expected value."
    )
    return {
        "market": f"亚盘 {provider}",
        "pick": f"{team} {line}",
        "confidence": confidence,
        "detail": detail,
        "market_en": f"Asian handicap {provider}",
        "pick_en": f"{team} {line}",
        "detail_en": detail_en,
        "basis": "fresh_european_asian_snapshot",
        "market_type": "asian_handicap",
        "home_handicap": home_line,
        "selection_keys": ["home" if pick_home else "away"],
    }


def _polymarket_lottery_validation(match: dict[str, Any], status: str) -> dict[str, str]:
    market = match.get("polymarket") or {}
    if not market.get("signal_eligible"):
        return {
            "status": "unavailable",
            "note_zh": "；Polymarket无有效流动性信号，本次不参与竞彩验证",
            "recommendation_zh": "Polymarket本次不可用于验证。",
            "recommendation_en": "Polymarket is unavailable for validation.",
        }
    if status == "lottery_deeper_small_win" and not market.get("spread_signal_eligible"):
        return {
            "status": "unavailable",
            "note_zh": "；Polymarket对应让球市场流动性不足，本次不参与竞彩验证",
            "recommendation_zh": "Polymarket让球市场本次不可用于验证。",
            "recommendation_en": "The corresponding Polymarket spread is unavailable for validation.",
        }
    if status == "lottery_deeper_small_win":
        spread = market.get("favorite_spread") or {}
        probability = spread.get("probability")
        if isinstance(probability, (int, float)) and probability <= 0.40:
            return {
                "status": "support",
                "note_zh": f"；Polymarket热门方 -1.5 支持率约 {probability:.0%}，验证热门方难以净胜两球",
                "recommendation_zh": "Polymarket有效市场支持该竞彩方向。",
                "recommendation_en": "A liquid Polymarket spread supports this Sporttery selection.",
            }
        if isinstance(probability, (int, float)) and probability >= 0.55:
            return {
                "status": "conflict",
                "note_zh": f"；Polymarket热门方 -1.5 支持率约 {probability:.0%}，与竞彩防大胜方向冲突",
                "recommendation_zh": "Polymarket有效市场与该竞彩方向冲突。",
                "recommendation_en": "A liquid Polymarket spread conflicts with this Sporttery selection.",
            }
    if status == "lottery_shallower_favorite_supported":
        side = market.get("favorite_side")
        probability = market.get(side) if side in {"home", "away"} else None
        if isinstance(probability, (int, float)) and probability >= 0.50:
            return {
                "status": "support",
                "note_zh": f"；Polymarket热门方胜率约 {probability:.0%}，验证竞彩热门方向",
                "recommendation_zh": "Polymarket有效市场支持该竞彩方向。",
                "recommendation_en": "A liquid Polymarket moneyline supports this Sporttery selection.",
            }
        if isinstance(probability, (int, float)) and probability <= 0.40:
            return {
                "status": "conflict",
                "note_zh": f"；Polymarket热门方胜率约 {probability:.0%}，与竞彩热门方向冲突",
                "recommendation_zh": "Polymarket有效市场与该竞彩方向冲突。",
                "recommendation_en": "A liquid Polymarket moneyline conflicts with this Sporttery selection.",
            }
    return {
        "status": "neutral",
        "note_zh": "；Polymarket有效市场未形成明确支持或反对",
        "recommendation_zh": "Polymarket验证结果中性。",
        "recommendation_en": "Polymarket validation is neutral.",
    }


def _polymarket_confidence_adjustment(match: dict[str, Any], status: str) -> int:
    market = match.get("polymarket") or {}
    if not market.get("signal_eligible"):
        return 0
    if status == "lottery_deeper_small_win" and not market.get("spread_signal_eligible"):
        return 0
    if status == "lottery_deeper_small_win":
        probability = (market.get("favorite_spread") or {}).get("probability")
        if isinstance(probability, (int, float)):
            if probability <= 0.40:
                return 3
            if probability >= 0.55:
                return -3
    if status == "lottery_shallower_favorite_supported":
        side = market.get("favorite_side")
        probability = market.get(side) if side in {"home", "away"} else None
        if isinstance(probability, (int, float)):
            if probability >= 0.50:
                return 2
            if probability <= 0.40:
                return -2
    return 0


def _fundamental_comparison(context: dict[str, Any]) -> float | None:
    home = context.get("home") or {}
    away = context.get("away") or {}
    try:
        home_played = int(home["played_games"])
        away_played = int(away["played_games"])
        home_ppg = float(home["points"]) / home_played
        away_ppg = float(away["points"]) / away_played
        home_gd = float(home["goal_difference"]) / home_played
        away_gd = float(away["goal_difference"]) / away_played
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    return (home_ppg - away_ppg) + 0.25 * (home_gd - away_gd)


def _fundamental_agrees(context: dict[str, Any], pick_home: bool) -> bool:
    comparison = _fundamental_comparison(context)
    if comparison is None:
        return False
    return comparison >= 0 if pick_home else comparison <= 0


def _market_supports_favorite(
    favorite_home: bool, probabilities: dict[str, float] | None
) -> bool:
    if not probabilities:
        return False
    return probabilities["home"] >= probabilities["away"] if favorite_home else probabilities["away"] > probabilities["home"]


def _two_way_probabilities(home_price: float, away_price: float) -> tuple[float, float]:
    home_raw = 1.0 / home_price
    away_raw = 1.0 / away_price
    total = home_raw + away_raw
    return home_raw / total, away_raw / total


def _reverse_selection(selection: Selection) -> Selection:
    if selection is Selection.HOME:
        return Selection.AWAY
    if selection is Selection.AWAY:
        return Selection.HOME
    return Selection.DRAW


def _lottery_pick(selections: tuple[Selection, ...]) -> str:
    labels = {Selection.HOME: "让胜", Selection.DRAW: "让平", Selection.AWAY: "让负"}
    return " + ".join(labels[selection] for selection in selections)


def _selection_labels_en(selections: tuple[Selection, ...]) -> str:
    labels = {Selection.HOME: "handicap home", Selection.DRAW: "handicap draw", Selection.AWAY: "handicap away"}
    return " + ".join(labels[selection] for selection in selections)


def _mismatch_payload(
    matched: bool,
    reason: str,
    pick: str,
    recommendation_zh: str,
    recommendation_en: str,
    status: str = "unavailable",
    line_gap: float = 0.0,
    selections: tuple[Selection, ...] = (),
) -> dict[str, Any]:
    return {
        "dashboard": {"matched": matched, "reason": reason, "pick": pick, "status": status},
        "recommendation_zh": recommendation_zh,
        "recommendation_en": recommendation_en,
        "line_gap": line_gap,
        "selections": selections,
    }


def _checker_text(prediction: dict[str, Any]) -> str:
    if prediction["market"] == "无推荐":
        return "本次数据不足，不进入高信心 checker。"
    return (
        f"检验建议：{prediction['market']} {prediction['pick']}（信心 {prediction['confidence']}%）。"
        "赛后按这一条具体盘口结算，不改换市场。"
    )


def _risks(match: dict[str, Any], prediction: dict[str, Any]) -> list[str]:
    risks = ["赔率会临场变化，本报告只使用本次查询快照。"]
    team_news = match.get("team_news") or {}
    if team_news:
        sides = [team_news.get("home") or {}, team_news.get("away") or {}]
        absence_count = sum(len(side.get("absences") or []) for side in sides)
        lineup_count = sum(1 for side in sides if side.get("lineup"))
        risks.append(
            f"API-Football 本次返回 {absence_count} 条确认缺阵，{lineup_count}/2 队官方首发；空结果不等同于确定无人缺阵。"
        )
    else:
        risks.append("本次未取得已确认伤停和官方首发，不将预测阵容作为事实。")
    weather = match.get("weather_snapshot") or {}
    if (weather.get("precipitation_probability") or 0) >= 50:
        risks.append(f"开赛时降水概率约 {weather['precipitation_probability']:.0f}%，需关注湿滑场地对节奏的影响。")
    if (weather.get("wind_gusts_kmh") or 0) >= 45:
        risks.append(f"开赛时阵风约 {weather['wind_gusts_kmh']:.0f} km/h，长传和高球稳定性可能受影响。")
    if not match.get("chinese_lottery"):
        risks.append("本次未取得竞彩数据，未运行完整三盘比较。")
    if prediction["market"] != "无推荐":
        risks.append("信心值为市场与有限基本面的排序指标，不等同于长期盈利概率。")
    return risks


def _no_prediction() -> dict[str, Any]:
    return {
        "market": "无推荐",
        "pick": "跳过",
        "confidence": 0,
        "detail": "本次基本面、欧赔或亚盘不完整，不能生成可复盘的具体建议。",
        "market_en": "No bet",
        "pick_en": "Skip",
        "detail_en": "Current fundamentals, European odds or Asian handicap data is incomplete.",
        "basis": "insufficient_current_data",
        "market_type": "none",
        "selection_keys": [],
    }


def _format_line(value: float) -> str:
    if abs(value) < 0.001:
        return "0"
    return f"{value:+g}"
