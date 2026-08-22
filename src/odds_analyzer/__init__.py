"""Core football odds analysis utilities."""

from odds_analyzer.analysis import check_lottery_asian_mismatch, compare_handicap_markets
from odds_analyzer.dashboard_payload import merge_dashboard_payload, upsert_history
from odds_analyzer.models import (
    AsianHandicapLine,
    AsianHandicapOdds,
    ChineseLotteryLine,
    ChineseLotteryOdds,
    HandicapMismatchCheck,
    HandicapSignal,
    MatchReport,
    MatchRequest,
    MatchSlateWindow,
    MatchScore,
    Selection,
    ThreeWayOdds,
)
from odds_analyzer.report import render_match_report
from odds_analyzer.search_plan import SearchQuery, build_match_search_plan
from odds_analyzer.slate import build_today_slate_window
from odds_analyzer.settlement import (
    settle_asian_handicap,
    settle_chinese_lottery,
)

__all__ = [
    "AsianHandicapLine",
    "AsianHandicapOdds",
    "ChineseLotteryLine",
    "ChineseLotteryOdds",
    "HandicapMismatchCheck",
    "HandicapSignal",
    "merge_dashboard_payload",
    "MatchReport",
    "MatchRequest",
    "MatchSlateWindow",
    "MatchScore",
    "SearchQuery",
    "Selection",
    "ThreeWayOdds",
    "build_match_search_plan",
    "build_today_slate_window",
    "check_lottery_asian_mismatch",
    "compare_handicap_markets",
    "render_match_report",
    "settle_asian_handicap",
    "upsert_history",
    "settle_chinese_lottery",
]

