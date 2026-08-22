from __future__ import annotations

from odds_analyzer.models import AsianHandicapLine, ChineseLotteryLine, MatchScore, Selection


def settle_chinese_lottery(score: MatchScore, line: ChineseLotteryLine) -> Selection:
    """Settle Chinese handicap win/draw/loss from the home-team perspective."""

    adjusted_margin = score.home_margin + line.home_handicap
    if adjusted_margin > 0:
        return Selection.HOME
    if adjusted_margin == 0:
        return Selection.DRAW
    return Selection.AWAY


def settle_asian_handicap(score: MatchScore, line: AsianHandicapLine, selection: Selection) -> float:
    """Return Asian handicap stake result: 1 win, 0 push, -1 lose, +/-0.5 half result."""

    if selection == Selection.DRAW:
        raise ValueError("Asian handicap has no draw selection")

    handicap = line.home_handicap if selection == Selection.HOME else -line.home_handicap
    margin = score.home_margin if selection == Selection.HOME else -score.home_margin
    adjusted_margin = margin + handicap

    return _settle_adjusted_margin(adjusted_margin)


def _settle_adjusted_margin(adjusted_margin: float) -> float:
    quarter_units = round(adjusted_margin * 4)
    if quarter_units % 2 == 0:
        return _settle_half_line(adjusted_margin)

    # Quarter-ball lines split the stake across the adjacent half-ball lines.
    lower_half = adjusted_margin - 0.25
    upper_half = adjusted_margin + 0.25
    return (_settle_half_line(lower_half) + _settle_half_line(upper_half)) / 2


def _settle_half_line(adjusted_margin: float) -> float:
    if adjusted_margin > 0:
        return 1.0
    if adjusted_margin == 0:
        return 0.0
    return -1.0
