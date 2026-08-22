# Scheduled Automations

Two local Codex cron automations keep the deployed dashboard fresh.

## Evening Slate Refresh

- Name: `Odds Analyzer evening slate refresh`
- Time: daily 18:00 local Beijing-time machine schedule
- Automation id: `odds-analyzer-evening-slate-refresh`
- Purpose: query fixtures from tonight through the next early morning, refresh `current_matches`, append new `mismatch_history`, append the daily top 5-8 concrete predictions to `checker_history`, test, commit, push, and refresh GitHub Pages.

## Morning Result Review

- Name: `Odds Analyzer morning result review`
- Time: daily 08:00 local Beijing-time machine schedule
- Automation id: `odds-analyzer-morning-result-review`
- Purpose: check final scores from the previous evening slate, settle the exact stored `prediction.market` and `prediction.pick`, update checker review fields, test, commit, push, and refresh GitHub Pages.

## Data Rules

- `current_matches` is replaced on every evening refresh.
- `mismatch_history` is never cleared by the daily refresh; newest entries should appear first.
- `checker_history` is never cleared by the daily refresh; newest selected recommendations should appear first.
- Checker candidates must be concrete predictions, not vague match-direction notes.
- Each prediction must include `market`, `pick`, `confidence`, and `detail`.
- Morning review must not evaluate a different market than the one originally recommended.

## Current Limitation

These automations still depend on live source availability and agent-side research. A later milestone should replace this with deterministic source adapters and a repeatable data job.
