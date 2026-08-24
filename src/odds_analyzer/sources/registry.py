from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReliabilityTier(str, Enum):
    PRIMARY = "primary"
    MARKET = "market"
    VALIDATION = "validation"


class DataSourcePurpose(str, Enum):
    CHINESE_LOTTERY = "chinese_lottery"
    FIXTURES = "fixtures"
    FUNDAMENTALS = "fundamentals"
    EUROPEAN_ODDS = "european_odds"
    ASIAN_HANDICAP = "asian_handicap"
    MARKET_SENTIMENT = "market_sentiment"
    VALIDATION = "validation"


@dataclass(frozen=True)
class DataSourceCandidate:
    key: str
    name: str
    homepage: str
    tier: ReliabilityTier
    purposes: tuple[DataSourcePurpose, ...]
    strengths: str
    automation_risk: str


def get_data_source_candidates() -> tuple[DataSourceCandidate, ...]:
    return (
        DataSourceCandidate(
            key="sporttery",
            name="China Sports Lottery / Sporttery",
            homepage="https://www.sporttery.cn/",
            tier=ReliabilityTier.PRIMARY,
            purposes=(DataSourcePurpose.CHINESE_LOTTERY, DataSourcePurpose.FIXTURES),
            strengths="Official source for Chinese lottery football schedules, SP odds, and handicap rules.",
            automation_risk="Official app/web data access must be validated; public API availability is unclear.",
        ),
        DataSourceCandidate(
            key="football_data_org",
            name="football-data.org",
            homepage="https://www.football-data.org/",
            tier=ReliabilityTier.PRIMARY,
            purposes=(DataSourcePurpose.FIXTURES, DataSourcePurpose.FUNDAMENTALS),
            strengths="Structured fixtures, standings, matchday, venue, and recent result history for major competitions.",
            automation_risk="Requires API token; free-tier request limits mean enrichment should be cached and scoped.",
        ),
        DataSourceCandidate(
            key="api_football",
            name="API-Football",
            homepage="https://www.api-football.com/",
            tier=ReliabilityTier.PRIMARY,
            purposes=(DataSourcePurpose.FIXTURES, DataSourcePurpose.FUNDAMENTALS),
            strengths="Broad football coverage for fixtures, standings, injuries, lineups, and H2H.",
            automation_risk="Requires API key and plan evaluation; lineup coverage varies by competition.",
        ),
        DataSourceCandidate(
            key="sportmonks",
            name="Sportmonks",
            homepage="https://www.sportmonks.com/",
            tier=ReliabilityTier.PRIMARY,
            purposes=(DataSourcePurpose.FIXTURES, DataSourcePurpose.FUNDAMENTALS, DataSourcePurpose.EUROPEAN_ODDS),
            strengths="Structured football API with lineups, sidelined players, xG, weather, odds, and predictions.",
            automation_risk="Commercial plan and league coverage need evaluation.",
        ),
        DataSourceCandidate(
            key="hkjc",
            name="HKJC Football",
            homepage="https://bet.hkjc.com/en/football/home",
            tier=ReliabilityTier.MARKET,
            purposes=(DataSourcePurpose.ASIAN_HANDICAP, DataSourcePurpose.EUROPEAN_ODDS),
            strengths="Official bookmaker source with Handicap, HAD, and Handicap HAD markets.",
            automation_risk="JavaScript app and non-public endpoints may change; access terms must be checked.",
        ),
        DataSourceCandidate(
            key="the_odds_api",
            name="The Odds API",
            homepage="https://theoddsapi.com/",
            tier=ReliabilityTier.MARKET,
            purposes=(DataSourcePurpose.EUROPEAN_ODDS, DataSourcePurpose.ASIAN_HANDICAP),
            strengths="Structured odds API for events, h2h, spreads, totals, and bookmaker comparison.",
            automation_risk="Soccer league and Asian handicap coverage depend on plan and bookmaker availability.",
        ),
        DataSourceCandidate(
            key="betfair",
            name="Betfair Exchange API",
            homepage="https://developer.betfair.com/exchange-api/",
            tier=ReliabilityTier.MARKET,
            purposes=(DataSourcePurpose.MARKET_SENTIMENT, DataSourcePurpose.EUROPEAN_ODDS),
            strengths="Exchange odds and liquidity can reveal market sentiment.",
            automation_risk="Not a direct source for Chinese lottery or standard Asian handicap comparison.",
        ),
        DataSourceCandidate(
            key="polymarket",
            name="Polymarket",
            homepage="https://polymarket.com/sports",
            tier=ReliabilityTier.MARKET,
            purposes=(DataSourcePurpose.MARKET_SENTIMENT, DataSourcePurpose.VALIDATION),
            strengths="Public real-time prediction prices, volume, liquidity, and a -1.5 margin boundary useful for Sporttery checks.",
            automation_risk="Fixture coverage varies and thin order books can be moved by a small number of traders.",
        ),
        DataSourceCandidate(
            key="five_hundred",
            name="500.com",
            homepage="https://trade.500.com/jczq/index.php",
            tier=ReliabilityTier.VALIDATION,
            purposes=(
                DataSourcePurpose.CHINESE_LOTTERY,
                DataSourcePurpose.EUROPEAN_ODDS,
                DataSourcePurpose.ASIAN_HANDICAP,
                DataSourcePurpose.VALIDATION,
            ),
            strengths="Practical Chinese-market pages for lottery odds, movement, European odds, and Asian handicap.",
            automation_risk="Secondary source; page structure and compliance must be reviewed before relying on it.",
        ),
        DataSourceCandidate(
            key="oddsportal",
            name="OddsPortal",
            homepage="https://www.oddsportal.com/",
            tier=ReliabilityTier.VALIDATION,
            purposes=(DataSourcePurpose.EUROPEAN_ODDS, DataSourcePurpose.ASIAN_HANDICAP, DataSourcePurpose.VALIDATION),
            strengths="Strong historical odds reference across European odds, totals, and Asian handicap.",
            automation_risk="Web automation and usage terms need careful review.",
        ),
        DataSourceCandidate(
            key="oddschecker",
            name="Oddschecker",
            homepage="https://www.oddschecker.com/football",
            tier=ReliabilityTier.VALIDATION,
            purposes=(DataSourcePurpose.EUROPEAN_ODDS, DataSourcePurpose.VALIDATION),
            strengths="Cross-book odds comparison for football markets.",
            automation_risk="Coverage depends on region and competition; not ideal as the only data source.",
        ),
    )


def get_sources_by_purpose(purpose: DataSourcePurpose) -> tuple[DataSourceCandidate, ...]:
    return tuple(source for source in get_data_source_candidates() if purpose in source.purposes)
