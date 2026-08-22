"""Data source registry and adapter placeholders."""

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
    "ReliabilityTier",
    "SportteryMarket",
    "SportteryMatch",
    "SportteryOutcome",
    "fetch_official_sporttery_matches",
    "get_data_source_candidates",
    "get_sources_by_purpose",
    "parse_official_sporttery",
]
