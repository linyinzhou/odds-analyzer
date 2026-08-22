# Dashboard Pipeline

This project should evolve into a GitHub-hosted football odds dashboard with a reproducible daily workflow.

## Scope

1. Import fixtures for the top five European leagues and UEFA Champions League.
2. Build the Beijing-time daily slate from afternoon to next early morning.
3. For every match in the slate, collect basic match data, fundamentals, European odds, Asian handicap, and Sporttery data.
4. Render each match report in the dashboard detail panel.
5. Render only matched handicap-mismatch opportunities in the mismatch panel.
6. Write every daily recommendation to the checker panel for post-match review.

## Dashboard Panels

| Panel | Purpose | Data |
|---|---|---|
| Detail | Full readable match report | Match info, fundamentals, markets, recommendation, risks, sources |
| Mismatch | Only matches that satisfy the mismatch rules | Reason, suggested Sporttery selection, line comparison |
| Checker | Post-match review queue | Pre-match recommendation, pending final score, pending review result |`n| Next Matchday | Upcoming fixture panel | Five major leagues plus Champions League proper; exclude Champions League qualifiers |

## Recommendation Format

Every match recommendation should separate two conclusions:

| Field | Meaning |
|---|---|
| `recommendation.fundamental` | Result from basic strength, form, venue, tactics, and market strength |
| `recommendation.mismatch` | Result from Sporttery integer handicap vs Asian handicap mismatch |

If the match does not satisfy the mismatch rule, the recommendation must say so explicitly.

## Current Static Prototype

The current dashboard is static and reads:

```text
dashboard/data/daily_matches.json
```

The file is split into three lists:

| Field | Behavior |
|---|---|
| `current_matches` | Current queried slate only. Replace this list on the next daily query. |
| `mismatch_history` | Historical matched mismatch opportunities. Append new matches first; do not clear daily. |
| `checker_history` | Historical review queue. Append selected daily recommendations first; do not clear daily. |`n| `next_matchday` | Upcoming fixtures for Premier League, La Liga, Serie A, Bundesliga, Ligue 1, and Champions League proper. Replace on each evening refresh. |

This is enough for GitHub Pages and for validating the UI/data model before adding scheduled data collection.

## Next Automation Step

Add a daily data job that produces the same JSON shape:

```text
fixtures -> market snapshots -> match reports -> current_matches
                                         -> append mismatch_history
                                         -> append checker_history
                                         -> dashboard
```

The first reliable sources to wire in are:

| Need | Initial source |
|---|---|
| Fixtures | football-data.org, Sportmonks, API-Football, or official league feeds if available |
| Sporttery | Sporttery official calculator API |
| Asian handicap | Paid odds API preferred; public pages only as fallback |
| European odds | Paid odds API preferred; public pages only as fallback |
| Weather | Open-Meteo or official weather API |
| Checker result | Football-data result API or official league result feed |

## Next Matchday Rules

- The Next Matchday panel shows Premier League, La Liga, Serie A, Bundesliga, Ligue 1, and UEFA Champions League proper.
- Champions League qualifying, preliminary, and playoff rounds are excluded.
- Champions League fixtures should appear only from the main stage/group-or-league phase onward.
- If a competition has no available fixtures from the current data source, write an explicit status instead of fabricating fixtures.


## Schedule-Only Display Rule

The Next Matchday panel is schedule-only. Show only competition, fixture, and date/time. Do not include analysis, odds, venues, weather, predictions, or reports there; those belong in current_matches on the actual match day.

