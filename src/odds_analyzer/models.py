from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Selection(str, Enum):
    HOME = "home"
    DRAW = "draw"
    AWAY = "away"


@dataclass(frozen=True)
class MatchScore:
    home_goals: int
    away_goals: int

    @property
    def home_margin(self) -> int:
        return self.home_goals - self.away_goals


@dataclass(frozen=True)
class MatchRequest:
    home_team: str
    away_team: str
    match_date: str | None = None
    competition: str | None = None

    @property
    def display_name(self) -> str:
        parts = [self.home_team, "vs", self.away_team]
        if self.match_date:
            parts.append(self.match_date)
        if self.competition:
            parts.append(self.competition)
        return " ".join(parts)


@dataclass(frozen=True)
class MatchSlateWindow:
    """A betting-day match window, usually afternoon through next early morning."""

    starts_at: datetime
    ends_at: datetime
    timezone: str

    def contains(self, kickoff: datetime) -> bool:
        return self.starts_at <= kickoff < self.ends_at


@dataclass(frozen=True)
class ChineseLotteryLine:
    """Chinese handicap win/draw/loss line from the home-team perspective."""

    home_handicap: int


@dataclass(frozen=True)
class AsianHandicapLine:
    """Asian handicap line from the home-team perspective."""

    home_handicap: float


@dataclass(frozen=True)
class HandicapSignal:
    selection: Selection
    confidence: float
    reason: str
    risk: str


@dataclass(frozen=True)
class HandicapMismatchCheck:
    status: str
    line_gap: float
    preferred_selections: tuple[Selection, ...]
    reason: str
    risk: str


@dataclass(frozen=True)
class ThreeWayOdds:
    home: float
    draw: float
    away: float


@dataclass(frozen=True)
class ChineseLotteryOdds:
    standard: ThreeWayOdds | None = None
    handicap: int | None = None
    handicap_odds: ThreeWayOdds | None = None


@dataclass(frozen=True)
class AsianHandicapOdds:
    handicap: float
    home_odds: float
    away_odds: float
    provider: str


@dataclass(frozen=True)
class MatchReport:
    match: MatchRequest
    kickoff_time: str
    venue: str | None
    weather: str | None
    fundamentals: tuple[str, ...]
    european_odds: ThreeWayOdds | None
    asian_handicap: AsianHandicapOdds | None
    chinese_lottery: ChineseLotteryOdds | None
    signal: HandicapSignal | None
    recommendation: str
    risks: tuple[str, ...]
    standings: tuple[str, ...] = ()
    form: tuple[str, ...] = ()
    team_news: tuple[str, ...] = ()
    tactical_notes: tuple[str, ...] = ()
    head_to_head: tuple[str, ...] = ()
    data_sources: tuple[str, ...] = ()
