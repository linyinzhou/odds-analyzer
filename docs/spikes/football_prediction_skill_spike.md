# football-prediction-skill Spike

Date: 2026-08-21

## Goal

Evaluate whether `JetQiao/football-prediction-skill` can help this project fetch Chinese Sports Lottery football data.

## Result

The spike is useful for the Chinese lottery data layer.

Confirmed capabilities:

- It contains a `SportteryProvider` adapter.
- It targets the public Sporttery endpoint:
  `https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry`
- It parses these official pools:
  - `had`: 胜平负
  - `hhad`: 让球胜平负
  - `crs`: 比分
  - `ttg`: 总进球
  - `hafu`: 半全场
- It supports the fallback concept of `SportteryAPI` via `SPORTTERY_API_URL`.
- It explicitly models source warnings and stale-cache fallback.

## Live Check

Business date: `2026-08-21`

The provider returned `9` official football matches from `sporttery-official`.

Target match found:

```text
周五010 英超 阿森纳 vs 考文垂
Kickoff: 2026-08-22T03:00:00
HHAD line: 阿森纳 -2
HHAD odds: 让胜 2.32 / 让平 3.80 / 让负 2.30
```

Available official pools for this match:

```text
hhad: 让球胜平负, line -2, 3 outcomes
crs: 比分, 31 outcomes
ttg: 总进球, 8 outcomes
hafu: 半全场, 9 outcomes
```

Important observation:

`had` 胜平负 was not present for this match in the live response. The project data model must support matches where only `hhad` and other pools are available.

## Local Constraints

The full `football-predict` CLI did not run in the current environment because `scipy` is missing.

This does not block reusing the Sporttery adapter concept because direct imports of `football_prediction.providers.sporttery.SportteryProvider` worked without the model dependencies.

## Recommendation

Do not merge the skill wholesale.

Use it as a reference implementation for a local `sporttery` source adapter:

- Keep this project's lighter dashboard and report pipeline.
- Reuse the endpoint, pool parsing ideas, market labels, and strict no-silent-drop behavior.
- Implement our own normalized output shape for:
  - match number
  - league
  - kickoff time
  - home/away teams
  - HAD if present
  - HHAD line and odds
  - other lottery pools if needed later
- Preserve warnings when a pool is missing.

## Risks

- The Sporttery endpoint is undocumented and can change.
- Some network exits may be blocked by the upstream WAF.
- Official response can omit `had` while keeping `hhad`; missing pools must not be treated as parser failure.
- Chinese lottery odds should remain a target market, not a source for independently proving value.
