# Sporttery mismatch return filter

Matched handicap patterns remain visible for analysis. Each new matched prediction
now has a `staking_plan` and `betting_eligible` flag; the mismatch record also holds
the plan for the dashboard. Unprofitable/missing/unsupported plans are excluded
from checker betting candidates and frozen learning eligibility. They are not
silently replaced by a different bet or a higher stake.

## What the suggestion means

A feasible plan makes **each of the two covered results individually return more
than the total stake**, conditional on that result occurring. It does not cover
the third result and is not a positive expected-value or guaranteed-profit claim.
The third result loses the entire stake. All amounts use the home team's
**handicap result** (handicap home/draw/away), not the ordinary match result.

For decimal odds a and b, continuous positive-profit allocation requires
`a*b > a+b` (equivalently `1/a + 1/b < 1`). Equality is only break-even and fails.
For example, 2.5 / 1.4 fails regardless of allocation or multiples: each option at
2 yuan costs 4 yuan; the 1.4 result returns 2.8 yuan and loses 1.2 yuan.

When the continuous condition passes, search 2-yuan integer units in ascending
order of total stake. The first feasible total is selected; ties maximize the
smaller covered-result net profit, then balance the payouts. The default search
cap is **100 yuan total**, not a suggested expenditure. No solution within that
cap is labelled `over_cap`, not mathematically impossible, and does not increase
the cap automatically. `build_staking_plan(..., max_total=...)` exposes the cap.
Payouts are conservatively truncated to cents before requiring strictly positive
net profit. Decimal arithmetic controls feasibility; float output is display-only.

Examples:

| Two covered odds | Stakes | Total | Net if first wins | Net if second wins | Third result |
|---|---|---:|---:|---:|---:|
| 2.5 / 1.4 | No suggestion | — | — | — | — |
| 3.55 / 1.60 | 1 unit / 2 units (2 / 4 yuan) | 6 | +1.10 | +0.40 | -6 |
| 2.50 / 1.80 | 3 units / 4 units (6 / 8 yuan) | 14 | +1.00 | +0.40 | -14 |

Different multiples must be bought as separate selections. Multiplying a single
compound ticket applies the same multiplier and does not implement unequal stakes.
Always recheck the ticket odds: changed prices require a new calculation.

## Single-match availability

The current official adapter does not supply a verified handicap-single sale flag.
An otherwise feasible plan is therefore labelled `purchase_status=confirm_single`
and displayed as conditional. It must not be treated as executable until handicap
singles are confirmed. These calculations cannot be applied unchanged to parlays.
A verified fallback Sporttery object may include `single_handicap: true/false/null`;
it must carry the importer's existing Sporttery source audit. Explicit `false`
keeps the allocation as `purchase_status=parlay_reference`; unknown stays unknown. No availability is inferred from
merely having odds.

## Output and review

Statuses: `feasible`, `impossible`, `over_cap`, `missing_data`. Legacy records may still contain `single_unavailable`.
The plan saves odds, per-selection unit counts and stakes, total cost, the payout
and net return for **all three** outcomes, the minimum covered profit, and full
uncovered loss. Rejected cases show an equal-2-yuan example only as an explanation.

Detail, Sporttery and Mismatch views display the plan. Chinese and English reports
include the reasoning and downside. Old records without this field say they have
not been screened; they are not presented as staking suggestions. Historical
snapshots are not rewritten.

Frozen evaluation normalizes the actual saved allocation to one total unit when
computing ROI. Older snapshots without a plan retain their equal-stake convention.
The rule version is `market-rules-v2-staking`. Confidence calibration still changes
scores only; it does not optimize stakes or prove that the uncovered outcome is
unlikely.

## Verification and references

```powershell
python -m unittest discover -s tests -p test_staking.py
python -m unittest discover -s tests
node --check dashboard/app.js
```

Tests cover the 2.5/1.4 counterexample, break-even boundaries, minimal integer
allocation, an independent integer-cent enumeration, cent rounding, funding caps,
missing odds, single-sale status, candidate exclusion and saved-allocation ROI.

The [official bonus calculation guide](https://m.sporttery.cn/bzzx/20210207/3273604.html?gid=3)
was checked. External skill/project references considered were
[football-prediction-skill](https://github.com/JetQiao/football-prediction-skill) and
[SportteryAPI](https://github.com/Johnserf-Seed/SportteryAPI); this bounded calculation
uses the standard library and adds no dependency.

## Ratios in every future analysis

Every analysis with Sporttery handicap odds saves `staking_references` for home/draw,
home/away and draw/away, independently of the market prediction or mismatch flag.
Daily, ad hoc and fallback analysis share this behavior; bilingual reports and the
Detail, Sporttery and Mismatch views show it. Missing odds are explicitly reported.
A mathematically feasible pair is not automatically a selection recommendation.

Known unavailable handicap singles still receive the minimum integer-unit ratio,
labelled `parlay_reference`. The displayed standalone returns are a calculation
baseline, not an executable single ticket. Both alternatives must use identical
single selections on the other legs. Only if every other leg wins may their odds
product K multiply the baseline return; subtract the full stake afterwards.
Other-leg losses and the uncovered outcome can lose the whole stake. Multiple
combinations, additional multi-selections and void legs require full-ticket math.
A pair failing the standalone filter is not proof that every possible parlay fails.

Such references remain outside single-bet Checker candidates and learning ROI.
Existing frozen predictions and result archives are never rewritten. To refresh
only ratio displays on an existing slate (including matches already started):

```powershell
$env:PYTHONPATH = "src"
python -m odds_analyzer.jobs.refresh_staking_references --payload path/to/daily_matches.json
```

This command preserves saved selections, confidence, odds, source audits, Checker
history and both frozen archives. It records the actual calculation timestamp in
`last_staking_refresh` and does not claim to fetch new odds or generate forecasts.
