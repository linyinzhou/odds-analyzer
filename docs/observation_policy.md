# Market observation policy

Non-mismatch Asian handicap directions are observations, not actionable recommendations.
The current engine derives a direction from market prices; it has no independently validated goal-margin distribution or expected-return model.

- Keep the exact market direction and explain integer/quarter-line settlement.
- Report missing samples and conflicting season strength explicitly.
- Do not increase market weights for agreement with European odds or season strength.
- Mark observations with `decision=watch` and `betting_eligible=false`; exclude them from the recommendation checker and eligible frozen forecasts. Do not rewrite historical records.
- Use first-valid-prematch frozen evaluations as the main dashboard strategy statistics. Show older mutable checker statistics separately.
- Calculate ROI from saved prices with half settlements and pushes; label it simulated.

This change prevents unsupported recommendations; it does not establish an improvement in hit rate. All newly generated market-only non-mismatch directions remain observations until a separate, prospectively validated model exists. No new goal-margin model, injury feed, venue split or opponent adjustment is introduced here.

Validation: `python -m unittest discover -s tests -q` and `node --check dashboard/app.js`.
