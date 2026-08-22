# Scheduled Automations

Two local Codex cron automations keep the deployed dashboard fresh.

## Evening Slate Refresh

- Name: `Odds Analyzer evening slate refresh`
- Time: daily 18:00 local Beijing-time machine schedule
- Automation id: `odds-analyzer-evening-slate-refresh`
- Purpose: query fixtures from tonight through the next early morning, refresh `current_matches`, refresh `next_matchday`, append new `mismatch_history`, append the daily top 5-8 concrete predictions to `checker_history`, test, commit, push, and refresh GitHub Pages.

## Morning Result Review

- Name: `Odds Analyzer morning result review`
- Time: daily 08:00 local Beijing-time machine schedule
- Automation id: `odds-analyzer-morning-result-review`
- Purpose: check final scores from the previous evening slate, settle the exact stored `prediction.market` and `prediction.pick`, update checker review fields, test, commit, push, and refresh GitHub Pages.

## Data Rules

- `current_matches` is replaced on every evening refresh.
- `mismatch_history` is never cleared by the daily refresh; newest entries should appear first.
- `checker_history` is never cleared by the daily refresh; newest selected recommendations should appear first.
- `next_matchday` must include the five major leagues plus Champions League proper; Champions League qualifiers/preliminary/playoffs are excluded.
- Checker candidates must be concrete predictions, not vague match-direction notes.
- Each prediction must include `market`, `pick`, `confidence`, and `detail`.
- Morning review must not evaluate a different market than the one originally recommended.

## Current Limitation

These automations still depend on live source availability and agent-side research. A later milestone should replace this with deterministic source adapters and a repeatable data job.


## Next Matchday Display


`next_matchday` is schedule-only: competition, fixture, and date/time. Do not add analysis or predictions until those fixtures enter current_matches on their match day.


## checker_history sorting rule

Checker entries should include batch_date when generated. Display newest batches first; within the same batch, sort by prediction.confidence descending. New daily candidates should be prepended or otherwise sorted ahead of older batches.

## next_matchday must not duplicate current_matches

The Next Matchday panel must show the fixtures after the current detail slate. Do not repeat any fixture already present in current_matches. The frontend also filters accidental duplicates, but the data generator should avoid writing them.





