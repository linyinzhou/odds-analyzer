# Codex Fallback Result Contract

The API refresh is authoritative. Codex fallback research may only fill fields listed in a pending `fallback_requests` entry. It must never edit `daily_matches.json` directly.

## Result file

Create a temporary UTF-8 JSON file with this shape:

```json
{
  "results": [
    {
      "request_id": "daily:2026-08-22:match-id",
      "home_team": "Home Team",
      "away_team": "Away Team",
      "queried_at": "2026-08-22T18:24:00+08:00",
      "fields": {
        "european_odds": {"home": 2.10, "draw": 3.30, "away": 3.45},
        "asian_handicap": {
          "provider": "Provider name",
          "handicap": -0.5,
          "home_odds": 1.95,
          "away_odds": 1.95
        },
        "sporttery": {
          "standard": {"home": 2.05, "draw": 3.15, "away": 3.20},
          "handicap": -1,
          "handicap_odds": {"home": 3.60, "draw": 3.55, "away": 1.76}
        }
      },
      "sources": {
        "european_odds": [
          {
            "name": "Source name",
            "url": "https://example.com/match",
            "tier": "primary",
            "queried_at": "2026-08-22T18:23:00+08:00"
          }
        ],
        "asian_handicap": [
          {
            "name": "Source name",
            "url": "https://example.com/match",
            "tier": "primary",
            "queried_at": "2026-08-22T18:23:00+08:00"
          }
        ],
        "sporttery": [
          {
            "name": "China Sports Lottery",
            "url": "https://example.com/match",
            "tier": "primary",
            "queried_at": "2026-08-22T18:23:00+08:00"
          }
        ]
      },
      "unresolved_reason": "Optional explanation when requested fields remain missing."
    }
  ]
}
```

`fundamentals` uses this field value:

```json
{
  "fundamental_context": {
    "home": {"position": 4, "form": "W-D-W-W-L"},
    "away": {"position": 12, "form": "L-D-W-L-D"}
  },
  "fundamentals": [
    {"label": "Standings and form", "home": "4th, W-D-W-W-L", "away": "12th, L-D-W-L-D"}
  ],
  "venue": "Optional verified venue"
}
```

Every supplied field needs at least one source with an HTTP(S) URL, source tier, and timezone-aware query timestamp. Omit fields that could not be verified and explain them in `unresolved_reason`.

## Apply

Run from the repository root:

```bash
PYTHONPATH=src python -m odds_analyzer.jobs.apply_fallback_results \
  --results path/to/fallback-results.json \
  --payload dashboard/data/daily_matches.json
```

On Windows PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m odds_analyzer.jobs.apply_fallback_results --results path/to/fallback-results.json --payload dashboard/data/daily_matches.json
```

The importer rejects team mismatches, unrequested fields, overwriting API-backed values, malformed odds, non-integer Sporttery handicaps, invalid source URLs, and timestamps without timezones. Successful imports regenerate analysis, bilingual reports, mismatch history, checker candidates, queue status, and `last_fallback_import`.
