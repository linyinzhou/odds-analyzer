# Scheduled Automations

GitHub Actions runs both the evening refresh and the morning result settlement.

## Evening Slate Refresh

- Name: `Manual report refresh`
- Time: daily 18:00 Beijing time (`0 10 * * *` UTC)
- Runtime: GitHub Actions
- Purpose: query fixtures from tonight through the next early morning, refresh `current_matches`, refresh `next_matchday`, upsert new `mismatch_history`, upsert the daily top 5-8 concrete predictions to `checker_history`, test, commit, push, and refresh GitHub Pages.

## Analysis Scope

The scheduled evening refresh defaults to `PL`, so only Premier League matches enter Detail, Mismatch, and Checker. The Next Matchday schedule remains the full five-major-leagues plus Champions League view.

Use the repository variable `ANALYSIS_COMPETITIONS` for the scheduled default, or the manual `analysis_competitions` input for a one-run override. Enable all supported competitions with:

```text
PL,PD,SA,BL1,FL1,CL
```

## Morning Result Review

- Status: active
- Time: daily 08:00 Beijing time (`0 0 * * *` UTC)
- Runtime: GitHub Actions
- Purpose: check final scores from the previous evening slate, settle the exact stored `prediction.market` and `prediction.pick`, update checker review fields, test, commit, push, and refresh GitHub Pages.


## Manual Trigger

A manual GitHub Actions workflow is available for ad hoc refreshes:

```text
https://github.com/linyinzhou/odds-analyzer/actions/workflows/manual-report.yml
```

Use `Run workflow` and choose:

- `evening-report` to refresh the current slate report batch.
- `result-review` to run the checker review path.
- `adhoc-report` to generate one independently requested match report from `adhoc_date`, `home_team`, and `away_team`.

The `evening-report` option runs the deterministic refresh and prediction job before publishing. The `result-review` option fetches final scores from football-data.org and settles the exact stored prediction.

For `adhoc-report`, optionally provide `competition_label`, `kickoff_time`, and an Odds API `odds_sport_key`. This flow appends or replaces the same `match date + teams` entry in `adhoc_history`; it does not modify the current daily slate or its historical mismatch/checker lists.

## Visible Run Status

The dashboard displays the latest workflow status from `dashboard/data/run_status.json`. Manual and Pages workflows write this file before publishing to `gh-pages`, including status, run type, run id, commit, actor, branch, and timestamp.
## Data Rules

- `current_matches` is replaced on every evening refresh.
- `mismatch_history` is never cleared by the daily refresh, but entries with the same `batch_date + id` are overwritten by the newest run.
- `checker_history` is never cleared by the daily refresh, but entries with the same `batch_date + id` are overwritten by the newest run.
- `next_matchday` must include the five major leagues plus Champions League proper; Champions League qualifiers/preliminary/playoffs are excluded.
- `adhoc_history` preserves manual one-match reports and replaces a duplicate `match date + teams` request with the newest snapshot.
- Checker candidates must be concrete predictions, not vague match-direction notes.
- Each prediction must include `market`, `pick`, `confidence`, and `detail`.
- Morning review must not evaluate a different market than the one originally recommended.

## Current Limitation

The evening job depends on football-data.org, The Odds API, the public Sporttery endpoint, and Open-Meteo. Weather is matched to the football-data fixture and sampled near kickoff; unresolved locations remain missing. Injuries and confirmed lineups are not connected yet. Morning settlement requires football-data.org to publish a final score.

Every report refresh now rebuilds structured `fallback_requests` for missing fundamentals, European odds, Asian handicap, and Sporttery data. Daily refreshes replace only daily-scope tasks and preserve ad hoc tasks. Weather and unpublished lineup data do not create fallback tasks. The workflow writes the pending count and fields to the GitHub Actions step summary.

## Codex Fallback Passes

- 18:00 Beijing: GitHub Actions queries structured APIs and creates `fallback_requests`.
- 18:20 Beijing: Codex reads the live queue and researches only pending fields; an empty queue is a no-op.
- 08:00 Beijing: GitHub Actions settles checker results through football-data.org.
- 08:20 Beijing: Codex researches only checker matches that remain unreviewed.

The Codex passes read the live `gh-pages` payload, preserve API-backed values, require source URLs and query timestamps for supplements, and do not fabricate unresolved data.


## Next Matchday Display


`next_matchday` is schedule-only: competition, fixture, and date/time. Do not add analysis or predictions until those fixtures enter current_matches on their match day.


## checker_history sorting rule

Checker entries should include batch_date when generated. Display newest batches first; within the same batch, sort by prediction.confidence descending. If the same match already exists in the same batch, overwrite it with the newest run data instead of appending a duplicate.

## next_matchday must not duplicate current_matches

The Next Matchday panel must show the fixtures after the current detail slate. Do not repeat any fixture already present in current_matches. The frontend also filters accidental duplicates, but the data generator should avoid writing them.

## Next Matchday Selection Rule

The Next Matchday panel should show the nearest unplayed fixtures for each competition by actual kickoff time after the current query time. Do not prioritize round number over time: if a newer round starts before postponed lower-round fixtures, show the newer round first, then show postponed fixtures when they become the next upcoming fixtures. Do not duplicate fixtures already present in `current_matches`.
