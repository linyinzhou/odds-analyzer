# Odds Analyzer

Odds Analyzer is a football betting analysis tool focused on comparing three views of the same match:

- European odds / 1X2 market
- Asian handicap market
- Chinese Sports Lottery handicap win/draw/loss market

The first milestone is intentionally small: define a reliable settlement and comparison core before connecting live data providers. This keeps the analysis rules testable while data sources, API keys, and scraping constraints are still undecided.

## Project Scope

The long-term workflow is:

1. Collect match context: kickoff time, venue, weather, league, and teams.
2. Collect fundamentals: standings, squad strength, formations, tactical notes, injuries, and head-to-head history.
3. Collect market data:
   - European 1X2 odds
   - Asian handicap lines and odds
   - Chinese Sports Lottery handicap win/draw/loss lines
4. Compare the markets and produce a recommendation with confidence and risk notes.

## Current Milestone

This version implements the core handicap logic:

- A match input model for home team, away team, date, and competition.
- A betting-day slate window for today's matches, from afternoon to next early morning.
- A first-pass search plan for match context, fundamentals, and market data.
- Chinese handicap win/draw/loss settlement.
- Asian handicap settlement, including quarter-ball lines.
- A simple cross-market signal detector.

Example idea:

If Team A gives Team B `-0.5` in Asian handicap, but the Chinese Sports Lottery line is Team A `-1`, and the estimated winning margin is around exactly one goal, then the Chinese handicap draw can become interesting because Team A winning by exactly one goal settles as draw on the lottery handicap market.

## Repository Layout

```text
src/odds_analyzer/
  analysis.py      # Cross-market signal logic
  models.py        # Typed data models
  search_plan.py   # Search query plan for manual research
  slate.py         # Betting-day match window helpers
  settlement.py    # Handicap settlement functions
tests/
  test_handicap_analysis.py
```

## Today's Match Scope

For this project, "today's matches" means the betting-day slate, not the calendar day.

Default Beijing-time window:

```text
Today 12:00 -> Tomorrow 06:00
```

For example, the 2026-08-08 slate covers:

```text
2026-08-08 12:00 Asia/Shanghai -> 2026-08-09 06:00 Asia/Shanghai
```

This keeps afternoon Asian matches and late-night/early-morning European matches in the same research batch.

## First Research Step

Start with a match request:

```python
from odds_analyzer import MatchRequest, build_match_search_plan

match = MatchRequest(
    home_team="Inter Milan",
    away_team="Juventus",
    match_date="2026-09-20",
    competition="Serie A",
)

for item in build_match_search_plan(match):
    print(item.topic, item.query)
```

The generated plan covers:

- Match time, venue, and weather.
- Standings, form, and performance indicators.
- Injuries, suspensions, predicted lineups, formations, and tactical notes.
- Head-to-head history.
- European odds, Asian handicap, and Chinese Sports Lottery handicap data.

## Match Report

The report layer renders a compact Markdown report from normalized match data:

Reporting rules:

- Use only data available at query time.
- If official starting lineups are not published yet, do not fill predicted lineups as facts.
- Odds are query-time snapshots; do not present later line movement as known unless it has been queried and timestamped.
- Separate facts, source-backed reports, and tactical interpretation.
- Prefer compact tables for match reports: match info, home-vs-away comparison, odds, judgment, and sources.
- Keep table cells concise but not one-word summaries; preserve enough context to explain the recommendation.

```python
from odds_analyzer import MatchReport, MatchRequest, render_match_report

report = MatchReport(
    match=MatchRequest("NEC Nijmegen", "Telstar", "2026-08-08", "Eredivisie"),
    kickoff_time="2026-08-08 22:30 Asia/Shanghai",
    venue="Goffertstadion",
    weather="Cloudy",
    standings=("NEC has stronger league positioning.",),
    form=("Telstar enters as the weaker side.",),
    team_news=("Lineups pending.",),
    tactical_notes=("Watch whether NEC can convert wide pressure into clear chances.",),
    head_to_head=("Recent H2H needs source validation.",),
    fundamentals=("Market shape favors NEC, but one-goal win remains plausible.",),
    european_odds=None,
    asian_handicap=None,
    chinese_lottery=None,
    signal=None,
    recommendation="Wait for verified Chinese lottery and Asian handicap data.",
    risks=("Market data is incomplete.",),
    data_sources=("Manual pre-spike placeholder.",),
)

print(render_match_report(report))
```

## Dashboard Prototype

The local dashboard prototype lives in `dashboard/`.

It is intentionally static for the first version:

- `dashboard/data/daily_matches.json` is the normalized slate and history payload.
- `current_matches` is replaced by each new query batch and drives the Detail panel.
- `mismatch_history` is appended over time and drives the Mismatch panel.
- `checker_history` is appended over time and drives the Checker panel.
- Each match should include a concrete `prediction` object with market, pick, and confidence.
- Real source adapters should later write the same JSON shape after fetching Chinese lottery, Asian handicap, and European odds data.

Open `dashboard/index.html` through a local static server so the browser can load the JSON file.

```bash
python -m http.server 8026 -d dashboard
```

Then open:

```text
http://127.0.0.1:8026/
```

The GitHub Pages workflow in `.github/workflows/pages.yml` deploys the `dashboard/` folder.


## Manual Report Trigger

Besides the scheduled 18:00 evening refresh and 08:00 result review, the dashboard exposes a manual trigger entry in the top bar.

Current manual trigger target:

```text
https://github.com/linyinzhou/odds-analyzer/actions/workflows/manual-report.yml
```

The workflow accepts:

- `run_type`: `evening-report` or `result-review`.
- `slate_date`: optional Beijing-time slate date, `YYYY-MM-DD`.
- `note`: optional operator note.

Until deterministic live data adapters are connected, the manual workflow validates and deploys the current dashboard payload. The report-generation command should be wired into this workflow once fixture, odds, Sporttery, and result adapters can produce `dashboard/data/daily_matches.json` without manual research.
## Run Tests

```bash
python -m unittest discover -s tests
```

## Data Source Candidates

See [docs/data_sources.md](docs/data_sources.md) for the current data-source evaluation.

Shortlist:

- China Sports Lottery / Sporttery for official Chinese lottery schedules and SP odds.
- API-Football or Sportmonks for fixtures, standings, injuries, lineups, H2H, and weather.
- HKJC Football for Asian handicap and related football markets.
- The Odds API for structured European odds and spreads where coverage is available.
- 500.com, OddsPortal, and Oddschecker as validation sources.

Chinese Sports Lottery data needs a separate legal and technical evaluation because official availability and redistribution constraints can differ from bookmaker odds APIs.

Current Sporttery progress:

- `football-prediction-skill` was evaluated as an external reference.
- A local lightweight Sporttery adapter now lives in `src/odds_analyzer/sources/sporttery.py`.
- The adapter parses the official football calculator response and supports matches where `HAD` is missing but `HHAD` is available.
- Live spike on 2026-08-21 found `周五010 英超 阿森纳 vs 考文垂`, HHAD line `-2`, odds `2.32 / 3.80 / 2.30`.

Handicap mismatch check:

- Run this check for every match with both Asian handicap and Chinese lottery handicap.
- If the lottery handicap is deeper than the Asian handicap and the favorite is only supported up to a narrow win, flag lottery handicap draw + away.
- If the lottery handicap is shallower than the Asian handicap and the favorite is supported by fundamentals and market structure, flag lottery handicap home + draw.
- Example: Asian `home -0.5`, lottery `home 0`, and home side is favored by fundamentals/odds. Lottery home + draw becomes the high-coverage pair to inspect.


## Codex Skill

A local Codex skill is available at:

```text
C:\Users\zhoul\.codex\skills\football-odds-analyzer
```

Use it for repeatable football odds analysis workflows: fixture research, European odds / Asian handicap / Sporttery comparison, mismatch checks, bilingual Chinese-English reports, dashboard updates, and checker review.

The skill references this repository as the implementation project and does not replace the dashboard. Match reports generated through the skill should include both Chinese and English versions unless a single language is explicitly requested.
## Responsible Use

This project is an analysis assistant, not a guarantee of profit. Recommendations should include uncertainty, bankroll discipline, and data-quality warnings.

