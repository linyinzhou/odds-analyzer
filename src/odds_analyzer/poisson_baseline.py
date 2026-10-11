"""Independent, deliberately conservative goal-count baseline for shadow research."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from odds_analyzer.models import AsianHandicapLine, MatchScore, Selection
from odds_analyzer.settlement import settle_asian_handicap, settle_chinese_lottery
from odds_analyzer.models import ChineseLotteryLine

MIN_LEAGUE_MATCHES = 100
MIN_TEAM_MATCHES = 8
PRIOR_MATCHES = 8


def _date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Training and kickoff dates must include a timezone")
    return parsed.astimezone(timezone.utc)


def fit_goals(
    fixtures: list[dict[str, Any]], competition: str, kickoff: str, home_id: int, away_id: int
) -> dict[str, Any] | None:
    """Fit pre-kickoff team rates with league shrinkage; return None for thin samples."""
    cutoff = _date(kickoff)
    matches = []
    for item in fixtures:
        if item.get("competition_code") != competition or item.get("status") != "FINISHED":
            continue
        if _date(str(item["utc_date"])) >= cutoff:
            continue
        if any(type(item.get(key)) is not int or item[key] < 0 for key in
               ("home_team_id", "away_team_id", "home_score", "away_score")):
            continue
        if item["home_team_id"] == item["away_team_id"]:
            continue
        matches.append(item)
    if len(matches) < MIN_LEAGUE_MATCHES:
        return None

    totals: dict[int, dict[str, int]] = defaultdict(lambda: {"games": 0, "for": 0, "against": 0})
    home_goals = away_goals = 0
    for item in matches:
        hg, ag = item["home_score"], item["away_score"]
        home_goals += hg
        away_goals += ag
        for team, scored, conceded in ((item["home_team_id"], hg, ag),
                                       (item["away_team_id"], ag, hg)):
            totals[team]["games"] += 1
            totals[team]["for"] += scored
            totals[team]["against"] += conceded
    if min(totals[home_id]["games"], totals[away_id]["games"]) < MIN_TEAM_MATCHES:
        return None
    n = len(matches)
    league_home = home_goals / n
    league_away = away_goals / n
    league_all = (home_goals + away_goals) / (2 * n)
    if min(league_home, league_away, league_all) <= 0:
        return None

    def rate(team: int, key: str) -> float:
        data = totals[team]
        return (data[key] + PRIOR_MATCHES * league_all) / (data["games"] + PRIOR_MATCHES)

    # Market prices and the target fixture's result never enter these rates.
    expected_home = league_home * rate(home_id, "for") / league_all * rate(away_id, "against") / league_all
    expected_away = league_away * rate(away_id, "for") / league_all * rate(home_id, "against") / league_all
    if not all(math.isfinite(x) and 0 < x <= 5 for x in (expected_home, expected_away)):
        return None
    return {
        "expected_home_goals": expected_home,
        "expected_away_goals": expected_away,
        "training_matches": n,
        "home_team_matches": totals[home_id]["games"],
        "away_team_matches": totals[away_id]["games"],
        "training_cutoff": cutoff.isoformat(),
        "model": "independent_poisson_shrunk_rates_v1",
    }


def fit_from_standings(context: dict[str, Any]) -> dict[str, Any] | None:
    """Provisional two-team baseline from the already captured pre-match table."""
    rates = {}
    for side in ("home", "away"):
        team = context.get(side) or {}
        try:
            played = team["played_games"]
            scored = team["goals_for"]
            conceded = team["goals_against"]
            if (any(type(value) is not int for value in (played, scored, conceded))
                    or played < 3 or min(scored, conceded) < 0):
                return None
        except (KeyError, TypeError):
            return None
        rates[side] = (scored / played, conceded / played, played)
    home, away = rates["home"], rates["away"]
    # Equal weight to a team's scoring rate and its opponent's concession rate.
    # There is no market price, assumed league mean, or invented venue coefficient.
    expected_home = (home[0] + away[1]) / 2
    expected_away = (away[0] + home[1]) / 2
    if not all(0 < value <= 5 for value in (expected_home, expected_away)):
        return None
    return {
        "expected_home_goals": expected_home,
        "expected_away_goals": expected_away,
        "home_team_matches": home[2],
        "away_team_matches": away[2],
        "model": "independent_poisson_season_aggregate_v1",
        "source": "existing_prematch_fundamental_context",
        "limitations": ["只含赛季汇总，不区分主客场", "未调整对手强度", "少量比赛的进失球均值波动大"],
    }


def score_probabilities(home_goals: float, away_goals: float) -> dict[tuple[int, int], float]:
    """Include the full practical goal tail; report no artificial probability mass."""
    if not all(math.isfinite(x) and 0 < x <= 5 for x in (home_goals, away_goals)):
        raise ValueError("Expected goals must be finite and between zero and five")
    def pmf(mean: float) -> list[float]:
        values = [math.exp(-mean)]
        while len(values) < 35 and 1 - sum(values) > 1e-12:
            values.append(values[-1] * mean / len(values))
        return values
    home, away = pmf(home_goals), pmf(away_goals)
    matrix = {(h, a): hp * ap for h, hp in enumerate(home) for a, ap in enumerate(away)}
    total = sum(matrix.values())
    return {score: probability / total for score, probability in matrix.items()}


def expected_asian_return(
    matrix: dict[tuple[int, int], float], home_handicap: float, selection: Selection, price: float
) -> dict[str, float]:
    if not math.isfinite(price) or price <= 1:
        raise ValueError("Decimal odds must exceed one")
    if not math.isfinite(home_handicap) or not (home_handicap * 4).is_integer():
        raise ValueError("Asian handicap must use quarter-goal increments")
    if selection == Selection.DRAW:
        raise ValueError("Asian handicap has no draw selection")
    line = AsianHandicapLine(home_handicap)
    probabilities = {1.0: 0.0, 0.5: 0.0, 0.0: 0.0, -0.5: 0.0, -1.0: 0.0}
    for (home, away), probability in matrix.items():
        result = settle_asian_handicap(MatchScore(home, away), line, selection)
        probabilities[result] += probability
    # One unit staked: win receives price-1, loss loses the stake.
    expected = sum(p * (result * (price - 1) if result > 0 else result)
                   for result, p in probabilities.items())
    return {
        "expected_profit_per_unit": expected,
        "full_win": probabilities[1.0],
        "half_win": probabilities[0.5],
        "push": probabilities[0.0],
        "half_loss": probabilities[-0.5],
        "full_loss": probabilities[-1.0],
    }


def expected_sporttery_return(
    matrix: dict[tuple[int, int], float], handicap: int, selection: Selection, price: float
) -> float:
    if type(handicap) is not int or not math.isfinite(price) or price <= 1:
        raise ValueError("Sporttery requires an integer handicap and valid decimal odds")
    line = ChineseLotteryLine(handicap)
    return sum(probability * (price - 1 if settle_chinese_lottery(MatchScore(h, a), line) == selection else -1)
               for (h, a), probability in matrix.items())


def shadow_match(match: dict[str, Any], fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    """Research output only: no recommendation, stake, checker, or confidence changes."""
    snapshot = match.get("football_data_snapshot") or {}
    context = match.get("fundamental_context") or {}
    asian = match.get("asian_handicap")
    if not snapshot.get("utc_date") or not asian:
        return {"status": "unavailable", "reason": "缺少开球时间或亚盘报价"}
    try:
        home_id = (context.get("home") or {}).get("team_id")
        away_id = (context.get("away") or {}).get("team_id")
        fitted = (fit_goals(fixtures, snapshot["competition_code"], snapshot["utc_date"], home_id, away_id)
                  if type(home_id) is int and type(away_id) is int and fixtures else None)
        if fitted is None:
            fitted = fit_from_standings(context)
        if fitted is None:
            return {"status": "unavailable", "reason": "缺少可用的赛前逐场或赛季进失球样本"}
        matrix = score_probabilities(fitted["expected_home_goals"], fitted["expected_away_goals"])
        asian_result = {}
        for side, selection in (("home", Selection.HOME), ("away", Selection.AWAY)):
            asian_result[side] = expected_asian_return(
                matrix, float(asian["handicap"]), selection, float(asian[f"{side}_odds"])
            )
        result: dict[str, Any] = {
            "status": "shadow_aggregate" if fitted["model"].endswith("aggregate_v1") else "shadow",
            **fitted,
            "asian_handicap": asian_result,
        }
        lottery = match.get("chinese_lottery") or {}
        if lottery.get("handicap") is not None and lottery.get("handicap_odds"):
            result["sporttery_handicap"] = {
                side: expected_sporttery_return(matrix, int(lottery["handicap"]), selection,
                                                 float(lottery["handicap_odds"][side]))
                for side, selection in (("home", Selection.HOME), ("draw", Selection.DRAW), ("away", Selection.AWAY))
            }
        return result
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return {"status": "unavailable", "reason": f"输入数据无效：{type(exc).__name__}"}
