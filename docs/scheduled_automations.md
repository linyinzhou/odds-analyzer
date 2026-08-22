# Scheduled Automations

Two local Codex cron automations keep the deployed dashboard fresh.

## Evening Slate Refresh

- Name: `Odds Analyzer evening slate refresh`
- Time: daily 18:00 local Beijing-time machine schedule
- Automation id: `odds-analyzer-evening-slate-refresh`
- Purpose: query fixtures from tonight through the next early morning, refresh `current_matches`, refresh `next_matchday`, upsert new `mismatch_history`, upsert the daily top 5-8 concrete predictions to `checker_history`, test, commit, push, and refresh GitHub Pages.

## Morning Result Review

- Name: `Odds Analyzer morning result review`
- Time: daily 08:00 local Beijing-time machine schedule
- Automation id: `odds-analyzer-morning-result-review`
- Purpose: check final scores from the previous evening slate, settle the exact stored `prediction.market` and `prediction.pick`, update checker review fields, test, commit, push, and refresh GitHub Pages.


## Manual Trigger

A manual GitHub Actions workflow is available for ad hoc refreshes:

```text
https://github.com/linyinzhou/odds-analyzer/actions/workflows/manual-report.yml
```

Use `Run workflow` and choose:

- `evening-report` to refresh the current slate report batch.
- `result-review` to run the checker review path.

Current limitation: the workflow validates and redeploys the dashboard payload. It is the stable manual entry point, but the real report-generation command still needs to be wired after live data source adapters can generate `dashboard/data/daily_matches.json` deterministically.
## Data Rules

- `current_matches` is replaced on every evening refresh.
- `mismatch_history` is never cleared by the daily refresh, but entries with the same `batch_date + id` are overwritten by the newest run.
- `checker_history` is never cleared by the daily refresh, but entries with the same `batch_date + id` are overwritten by the newest run.
- `next_matchday` must include the five major leagues plus Champions League proper; Champions League qualifiers/preliminary/playoffs are excluded.
- Checker candidates must be concrete predictions, not vague match-direction notes.
- Each prediction must include `market`, `pick`, `confidence`, and `detail`.
- Morning review must not evaluate a different market than the one originally recommended.

## Current Limitation

These automations still depend on live source availability and agent-side research. A later milestone should replace this with deterministic source adapters and a repeatable data job.


## Next Matchday Display


`next_matchday` is schedule-only: competition, fixture, and date/time. Do not add analysis or predictions until those fixtures enter current_matches on their match day.


## checker_history sorting rule

Checker entries should include batch_date when generated. Display newest batches first; within the same batch, sort by prediction.confidence descending. If the same match already exists in the same batch, overwrite it with the newest run data instead of appending a duplicate.

## next_matchday must not duplicate current_matches

The Next Matchday panel must show the fixtures after the current detail slate. Do not repeat any fixture already present in current_matches. The frontend also filters accidental duplicates, but the data generator should avoid writing them.

## Next Matchday Selection Rule

The Next Matchday panel should show the nearest unplayed fixtures for each competition by actual kickoff time after the current query time. Do not prioritize round number over time: if a newer round starts before postponed lower-round fixtures, show the newer round first, then show postponed fixtures when they become the next upcoming fixtures. Do not duplicate fixtures already present in `current_matches`.

