"""Data source registry and adapters."""

from odds_analyzer.sources.football_data import (
    COMPETITION_CODES,
    FootballDataFixture,
    FootballDataForm,
    FootballDataSnapshot,
    FootballDataStanding,
    fetch_evening_football_data,
    fixture_dashboard_id,
    parse_football_data_fixtures,
    parse_football_data_forms,
    parse_football_data_standing_forms,
    parse_football_data_standings,
)
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
    "COMPETITION_CODES",
    "DataSourceCandidate",
    "DataSourcePurpose",
    "FootballDataFixture",
    "FootballDataForm",
    "FootballDataSnapshot",
    "FootballDataStanding",
    "LEAGUE_SPORT_KEYS",
    "OddsApiEvent",
    "ReliabilityTier",
    "SportteryMarket",
    "SportteryMatch",
    "SportteryOutcome",
    "fetch_evening_football_data",
    "fetch_evening_odds_api_events",
    "fetch_odds_api_events",
    "fetch_official_sporttery_matches",
    "fixture_dashboard_id",
    "get_data_source_candidates",
    "get_sources_by_purpose",
    "parse_football_data_fixtures",
    "parse_football_data_forms",
    "parse_football_data_standing_forms",
    "parse_football_data_standings",
    "parse_odds_api_events",
    "parse_official_sporttery",
]
