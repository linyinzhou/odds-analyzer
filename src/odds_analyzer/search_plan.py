from __future__ import annotations

from dataclasses import dataclass

from odds_analyzer.models import MatchRequest


@dataclass(frozen=True)
class SearchQuery:
    topic: str
    query: str
    purpose: str


def build_match_search_plan(match: MatchRequest) -> list[SearchQuery]:
    """Build search queries for the first manual research pass."""

    name = match.display_name
    teams = f"{match.home_team} {match.away_team}"
    date_hint = f" {match.match_date}" if match.match_date else ""

    return [
        SearchQuery(
            topic="match_context",
            query=f"{name} kickoff time venue weather",
            purpose="Confirm kickoff time, venue, home/away context, and weather risk.",
        ),
        SearchQuery(
            topic="standings_form",
            query=f"{teams}{date_hint} standings recent form xG",
            purpose="Check league position, recent results, and performance trend.",
        ),
        SearchQuery(
            topic="team_news",
            query=f"{teams}{date_hint} injuries suspensions predicted lineups",
            purpose="Find injuries, suspensions, rotation risk, and likely formations.",
        ),
        SearchQuery(
            topic="head_to_head",
            query=f"{teams} head to head results history",
            purpose="Review matchup history without overweighting old results.",
        ),
        SearchQuery(
            topic="european_odds",
            query=f"{name} 1x2 odds european odds",
            purpose="Collect win/draw/loss odds and implied probabilities.",
        ),
        SearchQuery(
            topic="asian_handicap",
            query=f"{name} asian handicap odds",
            purpose="Collect Asian handicap opening and current lines.",
        ),
        SearchQuery(
            topic="china_lottery",
            query=f"{match.home_team} vs {match.away_team} 中国足彩 让球 胜平负 赔率",
            purpose="Collect Chinese Sports Lottery handicap line and odds.",
        ),
    ]
