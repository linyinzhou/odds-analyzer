# Review Learning Loop

The dashboard should use post-match review data to improve future analysis. This is not automatic model training yet; it is a structured feedback loop that records outcomes and measures which rules worked.

## Required Review Fields

Each reviewed match should store:

| Field | Purpose |
|---|---|
| `match_id` | Stable match identifier |
| `kickoff_time` | Used for daily and historical ordering |
| `league` | Segment results by competition |
| `home_team` / `away_team` | Human-readable context |
| `final_score` | Settles ordinary result and handicap result |
| `recommended_pick` | The pre-match recommendation |
| `hit` | Whether the recommendation won |
| `review_note` | Human explanation for miss or hit |
| `european_odds` | Pre-match odds snapshot |
| `asian_handicap` | Pre-match Asian line and odds |
| `sporttery_handicap` | Pre-match Sporttery integer handicap and odds |
| `mismatch_status` | Whether the mismatch rule matched |
| `line_gap` | Difference between Sporttery handicap and Asian handicap |

## Learning Metrics

The first useful metrics are:

| Metric | Use |
|---|---|
| Overall hit rate | Baseline for all recommendations |
| Mismatch-rule hit rate | Whether the core mismatch idea has edge |
| Non-mismatch hit rate | Whether ordinary analysis is adding value |
| Hit rate by `line_gap` | Find which handicap gaps are meaningful |
| Hit rate by league | Detect league-specific bias |
| Hit rate by odds band | Avoid overrating low-return favorites |
| Miss reasons | Separate bad data, late line movement, team-news misses, and model logic errors |

## How It Should Affect Future Picks

Use review data to adjust rule weights:

| Finding | Future adjustment |
|---|---|
| Mismatch hit rate is high when `line_gap >= 0.5` | Raise confidence for similar future matches |
| Misses cluster after late Asian line movement | Require a newer odds snapshot before recommending |
| Favorites below 1.30 underperform | Lower value score for low-return favorites |
| One league has poor hit rate | Reduce league weight until more samples confirm |
| Notes often mention injuries or rotation | Increase penalty for missing team-news data |

## Current Prototype

The dashboard persists automated result reviews in `dashboard/data/daily_matches.json`; browser `localStorage` remains available for manual notes. Persistent JSON reviews take precedence and feed the learning summary:

```text
全部建议 / 错盘命中规则 / 非错盘建议
```

This provides a cross-device historical review ledger. It is a measurement loop, not automatic model training; future weighting changes should require enough settled samples by rule, league, and line gap.
