# Non-mismatch Poisson baseline: phase 1

The evening-report workflow writes `dashboard/data/poisson_shadow.json` from finished
football-data.org league results. It includes only matches completed **before each
fixture's kickoff**. A separately saved training JSON can be used offline:

```powershell
$env:PYTHONPATH = 'src'
python -m odds_analyzer.jobs.run_poisson_shadow --payload dashboard/data/daily_matches.json --training training.json --output reports/poisson-shadow.json
```

Training JSON uses `{"matches":[{"competition_code":"PL","utc_date":"2025-08-01T12:00:00Z","home_team_id":1,"away_team_id":2,"home_score":2,"away_score":1,"status":"FINISHED"}]}`.

The independent Poisson baseline shrinks team goals scored and conceded toward
the competition mean, retaining the observed league home advantage. It requires
at least 100 completed league matches and eight completed matches per involved
team. Promoted teams or restricted API seasons can therefore be unavailable.
The model has no recent weighting, opponent adjustment in training, injury or
lineup feature, or Dixon–Coles low-score correction. These are known limits of
this first baseline.

For available fixtures it emits expected home and away goals, the training
sample count, Asian handicap full/half win, push and loss probabilities, plus
expected profit for **one unit staked** at the recorded home and away prices.
It also evaluates each Sporttery handicap outcome when the snapshot exists.
Quarter-ball returns use the same settlement function as the live checker.

These are point estimates from an unvalidated model, **not** recommendations.
The report does not change `prediction`, checker entries or staking plans. The
next phase needs forward chronological testing, calibration, and uncertainty
limits before any selection can become betting eligible.
