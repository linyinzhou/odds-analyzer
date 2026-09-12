# Frozen prediction learning loop — phase 1

Phase 1 measures whether confidence calibration improves future forecasts. It does
not introduce a trained outcome model, change selection rules, or automatically
promote an experiment. It uses only the Python standard library.

## What is saved

Daily refreshes, ad hoc reports, and validated fallback imports append to
`prediction_archive` in the existing dashboard JSON. Each snapshot contains the
actual recording timestamp, kickoff, fixture identity, complete input/odds and
prediction snapshot, base/calibrated confidence, rule version, calibration cutoff,
and a SHA-256 content identifier. Re-running a batch can still refresh dashboard
cards; it cannot overwrite the archive. Imports use the actual import time, not
a submitted research timestamp. No secret or environment variable is archived.

The archive is application-immutable, not an externally signed audit log. Hash
checks detect accidental edits; an operator with file access can replace content
and recompute hashes. Changes to forecasting rules must bump `RULE_VERSION`.

Completed results append to `result_archive`, with the time this system first
observed the result. An identical re-review does not move that timestamp. A score
correction adds an observation, retaining the earlier value and when it was known.
Deployment restoration unions both archives regardless of which branch supplies
the displayed slate. Conflicting records fail instead of being silently replaced.

## Fixed selection and training policy

- Evaluate the **first valid pre-kickoff recommendation per fixture**, independent
  of confidence ranking, checker top-N, later pick changes, or later results.
- Keep subsequent versions for audit; do not count them as additional matches.
- Use the football-data fixture ID across daily/ad hoc requests where available.
  Without it, use team names and kickoff. Aliases or kickoff changes without a
  provider ID can remain distinct; no fuzzy automatic merging is performed.
- Missing kickoff, post-kickoff recording, existing result fields, and unsupported
  recommendations are explicitly excluded. A no-recommendation snapshot does not
  prevent a later valid pre-match recommendation from becoming the fixed choice.
- Train only on selected frozen predictions with a non-push result observation
  strictly earlier than the prediction's calibration cutoff. Batch dates alone
  are never sufficient. The same result cannot count twice through multiple runs.
- Keep the existing 20-sample gate, shrinkage formula, and ±5 percentage-point cap.
  Training snapshots/results are identified in the saved performance object;
  each prediction retains the cutoff and training-set digest for replay checks.
- Old mutable `checker_history` entries remain visible, but are **not** retroactively
  converted to frozen evidence. Existing adjustments can return to zero while
  the first 20 eligible frozen outcomes accumulate in each strategy.

## Settlement and market comparability

Settlement uses the saved selection and handicap, not the latest displayed pick.
Asian lines distinguish win, half win, push, half loss and loss. Invalid fractional
lottery lines and non-quarter Asian lines are rejected instead of rounded.

All supported markets use 90-minute results, including stoppage time. The
football-data API's `fullTime` may include extra time/penalties: when duration is
not REGULAR, the parser requires `regularTime`. Missing scores remain pending;
awarded/uncompleted fixtures do not train the system. See the
[provider's score documentation](https://docs.football-data.org/general/v4/overtime.html).
Archived pending batches are retried. Known fixture IDs missing from the daily
window are queried individually, covering postponed and out-of-scope ad hoc games.
Fixtures outside provider coverage, or without a resolvable identity, stay pending.

For each priced recommendation, simulated stake is **one unit total**. Asian
positive returns use decimal odds: full win = odds − 1, half win = (odds − 1)/2;
loss/half loss = −1/−0.5, push = 0. Lottery multiple selections use the frozen staking-plan proportions when present;
legacy snapshots without a plan split that unit equally. A covered outcome can still lose money with multiple selections. Missing
or mismatched market quotes yield unavailable ROI, not invented odds. These are
hypothetical single-match returns, not evidence that a wager was available/placed.

## Evaluation

The evaluator joins frozen forecasts to observed final results and reproduces
calibration using only outcomes known at the saved cutoff. Unverifiable calibration
is excluded explicitly. It reports:

- Snapshot/fixture coverage, later versions excluded, pending results and reasons.
- Base vs calibrated Brier and log loss on the identical non-push sample; scores
  are lower-is-better. A negative calibrated-minus-base Brier difference is better.
- Weekly chronological summaries and strategy/rule-version summaries.
- Win/half-win/push/half-loss/loss counts and ROI with priced/missing-quote counts.
- De-vigged same-market baseline on an **identical paired subset**. Three-way
  lottery selections sum the probabilities of their covered outcomes. Asian
  half-goal lines have a compatible binary event; integer/quarter Asian lines do
  not, because refunded stakes change the interpretation of inverse odds.

Existing `confidence` is a heuristic score, not an established probability. The
Brier/log-loss comparison diagnoses interpreting it as the probability of a
positive settlement conditional on no push. Half wins count as positive, half
losses as negative. This is not a new home/draw/away probability model. Brier and
log loss evaluate probability forecast quality, not calibration alone. See
[scikit-learn's calibration guide](https://scikit-learn.org/stable/modules/calibration.html).

Base and calibrated variants use **identical selections**. They necessarily have
the same hit rate and unit-stake ROI; only score quality can change. Small samples,
correlated matches, or one favorable week do not establish an improvement. There
is no automatic promotion or claim of an edge. Future weight changes need a
separate untouched chronological evaluation period.

## Run and acceptance

From the project root in PowerShell:

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests
python -m odds_analyzer.jobs.evaluate_predictions --payload dashboard/data/daily_matches.json --output tmp/learning-evaluation.json --markdown tmp/learning-evaluation.md
```

The evaluator is offline/read-only with respect to the input. Output paths must
not overwrite the input. The Checker panel displays a compact frozen comparison;
its scope includes all archived competitions and ad hoc reports, independent of
the current daily competition filter. The older hit-rate cards remain descriptive
and can include manual browser notes; those notes never train the frozen loop.

Acceptance: run a pre-match refresh twice, verify two immutable versions but one
selected fixture; review the final score, verify one outcome and paired scores;
re-review unchanged results, verify the observation timestamp stays unchanged;
replay evaluation and verify future results cannot change past calibration.
Tests exercise these cases, score/ROI arithmetic, delayed results, missing quotes,
legacy exclusion, and archive preservation across deployment restoration.

No historical feature reconstruction or new data subscription is required.
Storage grows with every archived refresh. Replay currently favors transparency
and has quadratic work in settled sample count; if volume grows materially,
cache training prefixes or move the archive to a database in a separate change.

External reference considered: [football-prediction-skill](https://github.com/JetQiao/football-prediction-skill)
for walk-forward/calibration design. No external code or dependencies were added.
