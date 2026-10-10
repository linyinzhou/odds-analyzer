from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from odds_analyzer.analysis import check_lottery_asian_mismatch
from odds_analyzer.fallback_queue import has_sufficient_fundamental_context
from odds_analyzer.models import AsianHandicapLine, ChineseLotteryLine, Selection
from odds_analyzer.staking import build_staking_plan, recommended_staking_references


def analyze_slate_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [analyze_slate_match(match) for match in matches]


def analyze_slate_match(match: dict[str, Any]) -> dict[str, Any]:
    analyzed = deepcopy(match)
    european = analyzed.get("european_odds")
    asian = analyzed.get("asian_handicap")
    lottery = analyzed.get("chinese_lottery")
    context = analyzed.get("fundamental_context") or {}

    european_probabilities = _normalized_probabilities(european)
    market_zh, market_en = _market_read(analyzed, european_probabilities)
    mismatch = _mismatch_read(analyzed, context, european_probabilities)
    prediction = _prediction(analyzed, context, european_probabilities, mismatch)
    evidence_zh, evidence_en = _fundamental_evidence(analyzed, context, prediction)

    analyzed["market_read"] = market_zh
    analyzed["market_read_en"] = market_en
    analyzed["mismatch"] = mismatch["dashboard"]
    analyzed["recommendation"] = {
        "fundamental": evidence_zh,
        "fundamental_en": evidence_en,
        "fundamental_evidence": evidence_zh,
        "fundamental_evidence_en": evidence_en,
        "mismatch": mismatch["recommendation_zh"],
        "mismatch_en": mismatch["recommendation_en"],
    }
    if mismatch["dashboard"]["matched"]:
        plan = build_staking_plan(lottery, prediction["selection_keys"])
        prediction["staking_plan"] = plan
        prediction["betting_eligible"] = plan["status"] == "feasible" and plan.get("single_available") is not False
        analyzed["mismatch"]["staking_plan"] = plan
        analyzed["recommendation"]["mismatch"] += " " + plan["note_zh"]
        analyzed["recommendation"]["mismatch_en"] += " " + plan["note_en"]
        prediction["detail"] += " " + plan["note_zh"]
        prediction["detail_en"] += " " + plan["note_en"]
    analyzed["staking_references"] = recommended_staking_references(lottery, prediction)
    analyzed["prediction"] = prediction
    analyzed["checker"] = _checker_text(prediction)
    analyzed["risks"] = _risks(analyzed)
    if prediction.get("staking_plan"):
        analyzed["checker"] += " " + prediction["staking_plan"]["note_zh"]

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


def _fundamental_evidence(
    match: dict[str, Any], context: dict[str, Any], prediction: dict[str, Any]
) -> tuple[str, str]:
    """Give a numerical comparison without treating strength as proof of a margin."""
    sides = []
    for side, zh_label, en_label in (("home", "主队", "Home"), ("away", "客队", "Away")):
        data = context.get(side) or {}
        try:
            played = int(data["played_games"])
            won = int(data["won"])
            drawn = int(data["draw"])
            lost = int(data["lost"])
            goals_for = int(data["goals_for"])
            goals_against = int(data["goals_against"])
            position = int(data["position"])
        except (KeyError, TypeError, ValueError):
            return (
                "缺少双方完整的赛季战绩与进失球，暂不能据此判断实力差或所需胜差。",
                "Complete season records and goals are unavailable for both teams; the strength and required margin cannot be assessed from them.",
            )
        if played <= 0 or min(won, drawn, lost, goals_for, goals_against) < 0:
            return (
                "赛季样本尚未形成，暂不能据此判断实力差或所需胜差。",
                "The season sample is not yet usable for a strength or winning-margin assessment.",
            )
        form = data.get("form") or []
        recent_wins = (
            form.count("W") if isinstance(form, list) and len(form) >= 3
            and all(result in ("W", "D", "L") for result in form) else None
        )
        sides.append({
            "name": match.get(f"{side}_team") or zh_label,
            "en_label": en_label,
            "position": position,
            "played": played,
            "won": won,
            "drawn": drawn,
            "lost": lost,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "ppg": (3 * won + drawn) / played,
            "gdpg": (goals_for - goals_against) / played,
            "form_games": len(form) if recent_wins is not None else 0,
            "recent_wins": recent_wins,
        })

    home, away = sides
    zh = (
        f"{home['name']}第{home['position']}，{home['played']}场{home['won']}胜{home['drawn']}平{home['lost']}负、"
        f"进{home['goals_for']}失{home['goals_against']}；"
        f"{away['name']}第{away['position']}，{away['played']}场{away['won']}胜{away['drawn']}平{away['lost']}负、"
        f"进{away['goals_for']}失{away['goals_against']}。"
        f"场均积分{home['ppg']:.1f}比{away['ppg']:.1f}、场均净胜球{home['gdpg']:+.1f}比{away['gdpg']:+.1f}"
    )
    en = (
        f"{home['en_label']} are {home['position']}th with {home['won']}W-{home['drawn']}D-{home['lost']}L "
        f"and {home['goals_for']}-{home['goals_against']} goals in {home['played']} games; "
        f"{away['en_label']} are {away['position']}th with {away['won']}W-{away['drawn']}D-{away['lost']}L "
        f"and {away['goals_for']}-{away['goals_against']} goals in {away['played']}. "
        f"Points per game are {home['ppg']:.1f} vs {away['ppg']:.1f}, goal difference per game "
        f"{home['gdpg']:+.1f} vs {away['gdpg']:+.1f}"
    )
    if home["recent_wins"] is not None and away["recent_wins"] is not None:
        zh += (
            f"，近{home['form_games']}场主队{home['recent_wins']}胜、"
            f"近{away['form_games']}场客队{away['recent_wins']}胜"
        )
        en += (
            f", with {home['recent_wins']} wins in the last {home['form_games']} "
            f"vs {away['recent_wins']} in the last {away['form_games']}"
        )
    home_ahead = (
        home["position"] < away["position"] and home["ppg"] > away["ppg"] + 0.1
        and home["gdpg"] > away["gdpg"] + 0.1
    )
    away_ahead = (
        away["position"] < home["position"] and away["ppg"] > home["ppg"] + 0.1
        and away["gdpg"] > home["gdpg"] + 0.1
    )
    if home_ahead or away_ahead:
        stronger = home if home_ahead else away
        zh += f"，这三项一致支持{stronger['name']}整体占优。"
        en += f"; these three measures agree that {stronger['en_label'].lower()} have the stronger record."
        if home["recent_wins"] is not None and away["recent_wins"] is not None:
            recent_gap = home["recent_wins"] / home["form_games"] - away["recent_wins"] / away["form_games"]
            if (home_ahead and recent_gap < 0) or (away_ahead and recent_gap > 0):
                zh += "但近期胜场呈反向信号。"
                en += " Recent wins point the other way."
    else:
        zh += "，排名、积分效率和净胜球未形成一致优势。"
        en += "; rank, points rate and goal difference do not show a consistent edge."
    if min(home["played"], away["played"]) < 3:
        zh += "赛季样本不足3场，方向判断不稳。"
        en += " Fewer than three season games make this direction uncertain."
    elif not home["form_games"] or not away["form_games"]:
        zh += "近期战绩记录不足3条，未核验近期状态。"
        en += " Fewer than three recent results are available, so current form is unverified."
    lottery = match.get("chinese_lottery") or {}
    selections = set(prediction.get("selection_keys") or [])
    handicap = lottery.get("handicap")
    if isinstance(handicap, int) and selections in ({"home", "draw"}, {"draw", "away"}):
        margin = -handicap
        if selections == {"home", "draw"}:
            requirement_zh = f"主队净胜球至少为{margin}"
            requirement_en = f"the home goal margin must be at least {margin}"
        else:
            requirement_zh = f"主队净胜球至多为{margin}"
            requirement_en = f"the home goal margin must be at most {margin}"
        relation_zh = "高于" if home["gdpg"] > margin else "低于" if home["gdpg"] < margin else "等于"
        relation_en = "above" if home["gdpg"] > margin else "below" if home["gdpg"] < margin else "equal to"
        zh += (
            f"竞彩让球{handicap:+d}双选要求{requirement_zh}；"
            f"主队本季场均净胜{home['gdpg']:+.1f}球，{relation_zh}该门槛，"
            "但均值不能说明逐场达标频率。"
        )
        en += (
            f" The selected Sporttery handicap {handicap:+d} pair requires {requirement_en}; "
            f"the home side's season goal difference is {home['gdpg']:+.1f} per game, {relation_en} that threshold, "
            "but the average does not establish how often the margin occurs."
        )
    return zh, en


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


def _risks(match: dict[str, Any]) -> list[str]:
    risks = []
    weather = match.get("weather_snapshot") or {}
    if (weather.get("precipitation_probability") or 0) >= 50:
        risks.append(f"开赛时降水概率约 {weather['precipitation_probability']:.0f}%，需关注湿滑场地对节奏的影响。")
    if (weather.get("wind_gusts_kmh") or 0) >= 45:
        risks.append(f"开赛时阵风约 {weather['wind_gusts_kmh']:.0f} km/h，长传和高球稳定性可能受影响。")
    if not match.get("chinese_lottery"):
        risks.append("本次未取得竞彩数据，未运行完整三盘比较。")
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

