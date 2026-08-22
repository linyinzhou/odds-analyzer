"""Data source registry and adapters."""

from odds_analyzer.sources.odds_api import (
    LEAGUE_SPORT_KEYS,
    OddsApiEvent,
    fetch_evening_odds_api_events,
    fetch_odds_api_events,
    parse_odds_api_events,
)
from odds_analyzer.sources.registry import (
    DataSourceCandidate,
    DataSourcePurpose,
    ReliabilityTier,
    get_data_source_candidates,
    get_sources_by_purpose,
)
from odds_analyzer.sources.sporttery import (
    SportteryMarket,
    SportteryMatch,
    SportteryOutcome,
    fetch_official_sporttery_matches,
    parse_official_sporttery,
)

__all__ = [
    "DataSourceCandidate",
    "DataSourcePurpose",
    "LEAGUE_SPORT_KEYS",
    "OddsApiEvent",
    "ReliabilityTier",
    "SportteryMarket",
    "SportteryMatch",
    "SportteryOutcome",
    "fetch_evening_odds_api_events",
    "fetch_odds_api_events",
    "fetch_official_sporttery_matches",
    "get_data_source_candidates",
    "get_sources_by_purpose",
    "parse_odds_api_events",
    "parse_official_sporttery",
]
