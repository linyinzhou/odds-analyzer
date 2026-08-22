from __future__ import annotations

from odds_analyzer.models import AsianHandicapLine, ChineseLotteryLine, HandicapMismatchCheck, HandicapSignal, Selection


def compare_handicap_markets(
    asian_line: AsianHandicapLine,
    lottery_line: ChineseLotteryLine,
    estimated_home_margin: float,
) -> HandicapSignal:
    """Detect a simple cross-market value signal from Asian and lottery handicap lines."""

    asian_expected_margin = -asian_line.home_handicap
    lottery_draw_margin = -lottery_line.home_handicap
    line_gap = lottery_draw_margin - asian_expected_margin
    draw_distance = abs(estimated_home_margin - lottery_draw_margin)

    if line_gap >= 0.5 and draw_distance <= 0.25:
        return HandicapSignal(
            selection=Selection.DRAW,
            confidence=0.68,
            reason=(
                "The lottery handicap asks the home team to win by a larger margin than "
                "the Asian line, while the estimated margin is close to the lottery draw point."
            ),
            risk="A late team-news change or market move can invalidate a one-goal-margin estimate.",
        )

    if estimated_home_margin > lottery_draw_margin + 0.5:
        return HandicapSignal(
            selection=Selection.HOME,
            confidence=0.56,
            reason="The estimated margin clears the lottery handicap draw point by more than half a goal.",
            risk="Favorite-heavy picks are sensitive to overvalued public teams.",
        )

    return HandicapSignal(
        selection=Selection.AWAY,
        confidence=0.52,
        reason="The estimated margin does not clear the lottery handicap line.",
        risk="This is a weak default signal until odds, injuries, and tactical context are added.",
    )


def check_lottery_asian_mismatch(
    asian_line: AsianHandicapLine,
    lottery_line: ChineseLotteryLine,
    max_supported_home_margin: float | None,
) -> HandicapMismatchCheck:
    """Check whether integer lottery handicap is meaningfully deeper or shallower than Asian handicap."""

    line_gap = lottery_line.home_handicap - asian_line.home_handicap
    lottery_draw_margin = -lottery_line.home_handicap

    if line_gap <= -0.5:
        if max_supported_home_margin is not None and max_supported_home_margin <= lottery_draw_margin:
            return HandicapMismatchCheck(
                status="lottery_deeper_small_win",
                line_gap=line_gap,
                preferred_selections=(Selection.DRAW, Selection.AWAY),
                reason=(
                    "竞彩让球深于亚盘，且基本面/欧赔/亚盘只支持热门方小胜到让球临界点；"
                    "让平覆盖正好赢盘点，让负覆盖不穿盘路径。"
                ),
                risk="若热门方早早进球并打开比赛，深盘仍可能被打穿。",
            )
        return HandicapMismatchCheck(
            status="lottery_deeper_needs_margin_check",
            line_gap=line_gap,
            preferred_selections=(Selection.DRAW, Selection.AWAY),
            reason="竞彩让球深于亚盘，但还缺少基本面对最大胜差的判断；需重点检查让平/让负。",
            risk="没有胜差约束时，不能直接判断让平+让负更优。",
        )

    if line_gap >= 0.25:
        if max_supported_home_margin is not None and max_supported_home_margin >= lottery_draw_margin:
            return HandicapMismatchCheck(
                status="lottery_shallower_favorite_supported",
                line_gap=line_gap,
                preferred_selections=(Selection.HOME, Selection.DRAW),
                reason=(
                    "竞彩让球浅于亚盘，且基本面/欧赔/亚盘支持热门方至少不低于竞彩让球临界点；"
                    "让胜覆盖打穿竞彩浅盘，让平覆盖正好到让球临界点。"
                ),
                risk="若热门方优势被高估，浅盘仍可能落到让负。",
            )
        return HandicapMismatchCheck(
            status="lottery_shallower",
            line_gap=line_gap,
            preferred_selections=(Selection.HOME,),
            reason="竞彩让球浅于亚盘，若外盘深度可信，竞彩让胜更值得优先检查。",
            risk="需要确认深盘不是诱盘，且热门方具备穿盘基本面。",
        )

    return HandicapMismatchCheck(
        status="aligned",
        line_gap=line_gap,
        preferred_selections=(Selection.DRAW,),
        reason="竞彩让球与亚盘基本一致，重点判断热门方正好赢到让球数，还是进一步打穿。",
        risk="盘口一致时，优势不来自盘口错位，而来自胜差判断。",
    )
