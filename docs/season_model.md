# Season model and daily research loop

To migrate an existing payload and compute only genuinely pre-match forecasts:

```powershell
$env:PYTHONPATH = 'src'
python -m odds_analyzer.jobs.run_season_model --payload dashboard/data/daily_matches.json
```

`season-poisson-features-v1` uses the current July-to-June European league season.
It is a regularized Poisson goal regression, implemented with the Python standard
library. It is a research forecast, not a validated profitable betting strategy.

## Inputs and features

- `season_results` imports scored checker matches with stable football-data team
  IDs, a competition, kickoff and a timezone-aware result observation timestamp.
- Morning review also stores all finished supported-league fixtures returned for
  the queried evening windows, including games without recommendations. This is
  still a partial archive, not a complete league table.
- Goals train joint team attack and opponent defence terms, a league home effect
  and strongly regularized team venue terms. Recent games have a 60-day half-life.
- Rolling recent goal difference and historical handicap performance use at most
  five earlier, already-observed games and shrink sparse histories toward zero.
- Ranking advantage uses saved pre-match rankings. Missing rank data is omitted;
  partial checker results are never used to invent an official league table.
- Historical handicap performance uses goal difference plus the team's handicap,
  only where a pre-kickoff snapshot timestamp is known. Current odds enter return
  calculations, not target goal fitting. Rank and market feature coverage is shown.

The model needs 12 known league games and 3 per target team. These are computation
minimums, not statistical validation gates. Regularization/decay are fixed first
version settings; they have not been selected to maximize historical profits.
The design follows established time-weighted attack/defence goal-model practice;
see [penaltyblog](https://github.com/martineastwood/penaltyblog), without adding it
as a dependency. This implementation does not include Dixon-Coles correction.

## Immutable forecasts and results

Evening refresh and fallback update attach `model_forecast` to non-mismatch games
and append timestamped, hashed `model_forecasts`. No post-kickoff forecast is made.
They give 1X2 probabilities and the most probable outcome, goal means, and an Asian
handicap research selection (the side with the greater model expected return,
which can still be negative). No staking plan or betting eligibility is granted.

`model_reviews` settle the first pre-match snapshot per fixture/model version,
including half wins/losses and pushes at its original line and odds. They record
1X2 accuracy, Brier score, log loss, and unit-stake Asian returns. They do not mix
with the legacy recommendation hit rate. Changed results append a new observation;
only corrections known at the forecast time can enter that forecast's training.

Daily workflows preserve and merge all three ledgers even when replacing today's
slate. The checker displays a separate model research section. New outcomes become
training inputs on the next pre-match run; historical predictions remain fixed.

## Limits

Legacy selections are not a representative league sample. Missing IDs/times are
skipped rather than guessed. This archive needs continued growth and ideally a
complete results feed. Historical forecasts must not be reconstructed using the
present table, later corrections, or data downloaded after their supposed time.
Injuries, confirmed lineups and low-score correlation are not modelled yet.
