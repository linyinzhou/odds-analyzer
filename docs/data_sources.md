# Data Sources

This document tracks data source candidates for automated football odds analysis.

The first production goal is to automatically build a daily slate and compare:

- Chinese Sports Lottery win/draw/loss and handicap win/draw/loss.
- European 1X2 odds.
- Asian handicap odds.
- Match fundamentals such as fixtures, standings, injuries, lineups, H2H, venue, and weather.

## Reliability Tiers

### Tier A: Primary Sources

| Source | Best For | Notes |
| --- | --- | --- |
| China Sports Lottery / Sporttery | Chinese lottery official match list, SP odds, handicap win/draw/loss | Highest authority for Chinese lottery. Automation feasibility still needs a spike against official web/app data. |
| API-Football | Fixtures, standings, injuries, lineups, H2H, broad league coverage | Strong candidate for Eredivisie, Primeira Liga, J1, and smaller leagues during top-five-league off-season. |
| Sportmonks | Fixtures, lineups, sidelined players, xG, odds, weather, predictions | Commercial API with broad football coverage and rich includes. |

### Tier B: Market Sources

| Source | Best For | Notes |
| --- | --- | --- |
| HKJC Football | Asian handicap, HAD, Handicap HAD | Official bookmaker source. Handicap supports quarter-ball formats such as `-1/-1.5`. Public automation needs validation. |
| The Odds API | European odds, spreads, totals | Structured API. Soccer and Asian handicap coverage must be tested per league and plan. |
| Betfair Exchange API | Exchange prices, liquidity, market sentiment | Useful for market sentiment, not a direct replacement for Asian handicap or Chinese lottery. |

### Tier C: Validation Sources

| Source | Best For | Notes |
| --- | --- | --- |
| 500.com | Chinese lottery odds, odds movement, European odds, Asian handicap display | Practical Chinese-market validation source. Treat as secondary to official lottery data. |
| OddsPortal | Historical European odds and Asian handicap | Strong historical reference. Web automation and terms need review. |
| Oddschecker | European odds and handicap comparison | Useful cross-book odds comparison. Coverage varies by region and competition. |
| Flashscore / Sofascore | Scores, H2H, standings, lineups, basic odds context | Good human-readable validation, not ideal as primary automated source. |

## First Spike

The first data-source spike should answer four questions:

1. Can we automatically fetch today's Chinese lottery football slate?
2. Can we fetch each match's standard SP odds and handicap SP odds?
3. Can we match the same fixtures to an Asian handicap source, preferably HKJC first?
4. Can we match the same fixtures to European 1X2 odds?

Status update:

- `football-prediction-skill` has been evaluated as a reference implementation.
- Its Sporttery adapter successfully fetched the 2026-08-21 official football slate.
- It found `周五010 英超 阿森纳 vs 考文垂`, kickoff `2026-08-22T03:00:00`, with HHAD line `-2` and odds `2.32 / 3.80 / 2.30`.
- For that match, HAD was not present in the response; HHAD, CRS, TTG, and HAFU were present.
- Details are recorded in [spikes/football_prediction_skill_spike.md](spikes/football_prediction_skill_spike.md).

Output target:

```json
{
  "kickoff_time": "2026-08-08T22:30:00+08:00",
  "competition": "Eredivisie",
  "home_team": "NEC Nijmegen",
  "away_team": "Telstar",
  "chinese_lottery": {
    "source": "sporttery",
    "standard": {"home": 1.42, "draw": 4.80, "away": 6.80},
    "handicap": -1,
    "handicap_odds": {"home": 2.15, "draw": 3.55, "away": 2.65}
  },
  "asian_handicap": {
    "source": "hkjc",
    "handicap": -1.25,
    "home_odds": 1.92,
    "away_odds": 1.98
  },
  "european_odds": {
    "source": "the_odds_api",
    "home": 1.42,
    "draw": 4.80,
    "away": 6.80
  }
}
```

## Implementation Notes

- Use official or structured APIs before scraping pages.
- Keep each source behind a small adapter with a shared output model.
- Store the raw source payload during spikes so parser bugs can be replayed.
- Never hard-code one source as the single authority for team names; fixture matching will need aliases.
- Record data timestamps because odds can move quickly before kickoff.
