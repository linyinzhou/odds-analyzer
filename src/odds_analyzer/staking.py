"""Two-selection Sporttery staking, conditional on one covered result winning."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN

LABELS = {"home": "让胜", "draw": "让平", "away": "让负"}
UNIT = Decimal("2")
CENT = Decimal("0.01")
DEFAULT_MAX_TOTAL = 100


def build_staking_plan(lottery: dict | None, selections: list[str], max_total: int = DEFAULT_MAX_TOTAL) -> dict:
    if type(max_total) is not int or not 4 <= max_total <= 10000:
        raise ValueError("Search cap must be an integer between 4 and 10000 yuan")
    plan = {"version": "sporttery-pair-v2", "status": "missing_data", "max_total": max_total,
            "unit_stake": 2, "single_available": (lottery or {}).get("single_handicap"),
            "allocations": [], "scenarios": [], "equal_stake_scenarios": [],
            "note_zh": "缺少有效的竞彩双选赔率，暂不提供配注建议。",
            "note_en": "Valid two-selection Sporttery odds are missing; no staking suggestion."}
    if len(selections) != 2 or len(set(selections)) != 2 or any(key not in LABELS for key in selections):
        return plan
    keys = [key for key in LABELS if key in selections]
    quotes = (lottery or {}).get("handicap_odds") or {}
    try:
        odds = {key: Decimal(str(quotes[key])) for key in keys}
        if any(not price.is_finite() or not 1 < price <= 10000 for price in odds.values()):
            return plan
    except (KeyError, InvalidOperation, ValueError, TypeError):
        return plan

    def scenarios(units: dict[str, int]) -> list[dict]:
        total = UNIT * sum(units.values())
        rows = []
        for key in LABELS:
            returned = (UNIT * units.get(key, 0) * odds.get(key, 0)).quantize(CENT, rounding=ROUND_DOWN)
            rows.append({"selection": key, "label": LABELS[key], "covered": key in units,
                         "return": float(returned), "net_profit": float(returned - total)})
        return rows

    plan["selection_odds"] = {key: float(price) for key, price in odds.items()}
    plan["inverse_sum"] = float(sum(1 / price for price in odds.values()))
    plan["equal_stake_total"] = 4
    plan["equal_stake_scenarios"] = scenarios({key: 1 for key in keys})
    left, right = (odds[key] for key in keys)
    # Exact decimal inequality; even a break-even boundary is not positive profit.
    if left * right <= left + right:
        plan.update(status="impossible", note_zh="不建议双选（按本场赔率单独测算）：这组赔率无法通过任何金额配比，让两个已覆盖结果命中时都盈利；加倍不能解决。串关是否可行须按完整组合赔率与成本另算。",
                    note_en="Skip this pair: no stake allocation gives positive profit for both covered results. Multiplying stakes cannot fix it. This is a standalone-odds check; parlays require full-ticket odds and costs.")
        return plan
    # Smallest total stake first; among equal totals maximize the worse covered payoff.
    for total_units in range(2, max_total // 2 + 1):
        candidates = []
        # Positive net requires total / odds_left < left_units < total - total / odds_right.
        first = int(Decimal(total_units) / left) + 1
        last = total_units - int(Decimal(total_units) / right) - 1
        for left_units in range(max(1, first), min(total_units - 1, last) + 1):
            units = {keys[0]: left_units, keys[1]: total_units - left_units}
            rows = scenarios(units)
            floor = min(row["net_profit"] for row in rows if row["covered"])
            if floor > 0:
                candidates.append((floor, -abs(rows[list(LABELS).index(keys[0])]["return"] - rows[list(LABELS).index(keys[1])]["return"]), units, rows))
        if not candidates:
            continue
        _, _, units, rows = max(candidates, key=lambda entry: entry[:2])
        total = total_units * 2
        allocations = [{"selection": key, "label": LABELS[key], "odds": float(odds[key]),
                        "units": units[key], "stake": units[key] * 2} for key in keys]
        minimum = min(row["net_profit"] for row in rows if row["covered"])
        detail = "；".join(f"{row['label']} {row['odds']:g} 投{row['units']}注（{row['stake']}元）" for row in allocations)
        payoffs = "；".join(f"{row['label']}开出返{row['return']:g}元、净{'赚' if row['net_profit'] > 0 else '亏'}{abs(row['net_profit']):g}元" for row in rows if row["covered"])
        plan.update(status="feasible", total_stake=total, allocations=allocations, scenarios=rows,
                    minimum_covered_profit=minimum, uncovered_loss=total,
                    purchase_status="ready" if plan["single_available"] is True else "parlay_reference" if plan["single_available"] is False else "confirm_single",
                    note_zh=f"条件配注（先确认让球单关可售及出票赔率）：{detail}，共{total}元。{payoffs}。这是{max_total}元搜索上限内的最小可行投入。两个选项需分别按上述倍数购买；第三种结果开出全亏{total}元，不代表正期望或稳赚。",
                    note_en=f"Conditional staking: confirm handicap singles and ticket odds first. " + "; ".join(f"{row['selection']} at {row['odds']:g}: {row['units']} units / CNY {row['stake']}" for row in allocations) + f". Total CNY {total}; minimum net profit IF a covered outcome wins: CNY {minimum:g}; uncovered outcome loses CNY {total}. Smallest feasible total within CNY {max_total}. Buy selections separately at these multiples. No positive-expectation or guaranteed-profit claim.")
        if plan["single_available"] is False:
            plan["note_zh"] = f"总投入{total}元；本场不支持单关，以下为配比参考，串关收益另算。"
            plan["note_en"] = f"Total CNY {total}; handicap singles unavailable. Ratio reference only; calculate parlay returns separately."
        else:
            plan["note_zh"] = f"总投入{total}元；按当前赔率测算，购买前确认让球单关可售。"
            plan["note_en"] = f"Total CNY {total} at saved odds; confirm handicap singles before purchase."
        return plan
    plan.update(status="over_cap", note_zh=f"赔率结构理论可配，但{max_total}元以内没有两个覆盖结果都净盈利的2元整数倍组合；暂不建议双选，不自动加大投入。",
                note_en=f"The continuous allocation is feasible, but no positive-profit CNY 2-unit pair exists within CNY {max_total}; skip, without increasing the cap.")
    return plan


def recommended_staking_references(lottery: dict | None, prediction: dict) -> list[dict]:
    """Size only the predicted handicap pair; never search alternative selections."""
    keys = prediction.get("selection_keys")
    if (prediction.get("market_type") != "sporttery_handicap" or not isinstance(keys, list)
            or len(keys) != 2 or len(set(keys)) != 2 or any(key not in LABELS for key in keys)):
        return []
    return [build_staking_plan(lottery, keys)]
