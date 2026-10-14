"""Chronological season goal model and immutable research forecasts (stdlib only)."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from copy import deepcopy
from datetime import timedelta

from odds_analyzer.learning import digest, fixture_identity, now_iso, timestamp, verify_record
from odds_analyzer.models import MatchScore, Selection
from odds_analyzer.poisson_baseline import score_probabilities, expected_asian_return
from odds_analyzer.settlement import settle_asian_handicap

VERSION = "season-poisson-features-v1"
LEAGUES = {"PL", "PD", "SA", "BL1", "FL1"}
HALF_LIFE_DAYS = 60


def season(value):
    dt = timestamp(value, kickoff=True)
    return dt.year if dt.month >= 7 else dt.year - 1


def append_record(payload, collection, record, key):
    record = deepcopy(record)
    record[key] = digest(record)
    rows = payload.setdefault(collection, [])
    if not any(row[key] == record[key] for row in rows):
        rows.append(record)


def match_metadata(match):
    snapshot = match.get("football_data_snapshot") or {}
    context = match.get("fundamental_context") or {}
    code = snapshot.get("competition_code")
    kickoff = snapshot.get("utc_date") or match.get("kickoff_time")
    teams = [(context.get(side) or {}).get("team_id") for side in ("home", "away")]
    if code not in LEAGUES or not timestamp(kickoff, kickoff=True) or any(type(t) is not int for t in teams) or teams[0] == teams[1]:
        return None
    return {"fixture_key": fixture_identity(match), "competition_code": code,
            "kickoff": timestamp(kickoff, kickoff=True).isoformat(), "season": season(kickoff),
            "home_team_id": teams[0], "away_team_id": teams[1],
            "home_team": match.get("home_team"), "away_team": match.get("away_team")}


def capture_metadata(match):
    """Market/rank evidence needs a provable pre-kickoff timestamp."""
    kickoff = timestamp(match.get("kickoff_time"), kickoff=True)
    odds_time = timestamp((match.get("odds_api_snapshot") or {}).get("updated_at"))
    saved = timestamp(match.get("generated_at"))
    odds = deepcopy(match.get("asian_handicap")) if kickoff and odds_time and odds_time < kickoff else None
    ranks = {s: (match.get("fundamental_context", {}).get(s) or {}).get("position") for s in ("home", "away")}
    # Legacy checker rows often have no timestamp for the standings snapshot.
    if not (kickoff and saved and saved < kickoff):
        ranks = {}
    return {"asian_handicap": odds, "market_recorded_at": odds_time.isoformat() if odds else None,
            "rankings": ranks, "rank_recorded_at": saved.isoformat() if ranks else None}


def import_checker(payload):
    counts = {"imported": 0, "skipped": 0}
    saved = defaultdict(list)
    for snapshot in payload.get("prediction_archive", []):
        verify_record(snapshot, "snapshot_id")
        match = snapshot["match"]
        kickoff = timestamp(match.get("kickoff_time"), kickoff=True)
        if kickoff and timestamp(snapshot["recorded_at"]) < kickoff and not match.get("review"):
            saved[snapshot["fixture_key"]].append(snapshot)
    for match in payload.get("checker_history", []):
        review = match.get("review") or {}
        meta = match_metadata(match)
        score = re.fullmatch(r"(\d+)\s*[-:]\s*(\d+)", str(review.get("final_score", "")))
        observed = timestamp(review.get("reviewed_at"))
        if not meta or not score or review.get("reviewed") is not True or not observed or observed <= timestamp(meta["kickoff"]):
            counts["skipped"] += 1
            continue
        before = len(payload.get("season_results", []))
        evidence = capture_metadata(match)
        if saved.get(meta["fixture_key"]):
            first = min(saved[meta["fixture_key"]], key=lambda s: timestamp(s["recorded_at"]))
            frozen = first["match"]
            evidence = {"asian_handicap": deepcopy(frozen.get("asian_handicap")),
                "market_recorded_at": first["recorded_at"],
                "rankings": {s: ((frozen.get("fundamental_context") or {}).get(s) or {}).get("position") for s in ("home", "away")},
                "rank_recorded_at": first["recorded_at"]}
        previous = [r for r in payload.get("season_results", []) if r["fixture_key"] == meta["fixture_key"]]
        latest = max(previous, key=lambda r: timestamp(r["observed_at"])) if previous else None
        if latest and (latest["home_score"], latest["away_score"]) == (int(score[1]), int(score[2])):
            if all(latest.get(k) == v for k, v in evidence.items()):
                continue
        append_record(payload, "season_results", {**meta, **evidence,
            "home_score": int(score[1]), "away_score": int(score[2]),
            "observed_at": observed.isoformat(), "source": review.get("source") or "legacy_checker"}, "observation_id")
        counts["imported"] += len(payload["season_results"]) - before
    return counts


def ingest_fixtures(payload, fixtures, observed_at):
    observed = timestamp(observed_at)
    for fixture in fixtures:
        if fixture.status != "FINISHED" or fixture.competition_code not in LEAGUES:
            continue
        if any(type(x) is not int or x < 0 for x in (fixture.home_score, fixture.away_score, fixture.home_team_id, fixture.away_team_id)):
            continue
        kickoff = timestamp(fixture.utc_date)
        if not observed or not kickoff or kickoff >= observed:
            continue
        key = f"football-data:{fixture.match_id}"
        evidence = {}
        originals = [s for s in payload.get("prediction_archive", []) if s["fixture_key"] == key
                     and timestamp(s["recorded_at"]) < kickoff]
        if originals:
            first = min(originals, key=lambda s: timestamp(s["recorded_at"]))
            verify_record(first, "snapshot_id")
            original_context = first["match"].get("fundamental_context") or {}
            evidence = {"asian_handicap": first["match"].get("asian_handicap"),
                        "market_recorded_at": first["recorded_at"],
                        "rankings": {s: (original_context.get(s) or {}).get("position") for s in ("home", "away")},
                        "rank_recorded_at": first["recorded_at"]}
        snapshots = [s for s in payload.get("model_forecasts", []) if s["fixture_key"] == key]
        if snapshots:
            first = min(snapshots, key=lambda s: s["recorded_at"])
            evidence = {"asian_handicap": first["match"].get("asian_handicap"),
                        "market_recorded_at": first["recorded_at"],
                        "rankings": first["analysis"].get("rankings", {}), "rank_recorded_at": first["recorded_at"]}
        previous = [r for r in payload.get("season_results", []) if r["fixture_key"] == key]
        latest = max(previous, key=lambda r: timestamp(r["observed_at"])) if previous else None
        if latest and latest["home_score"] == fixture.home_score and latest["away_score"] == fixture.away_score:
            continue
        append_record(payload, "season_results", {"fixture_key": key, "competition_code": fixture.competition_code,
            "kickoff": kickoff.isoformat(), "season": season(fixture.utc_date), "home_team_id": fixture.home_team_id,
            "away_team_id": fixture.away_team_id, "home_team": fixture.home_team, "away_team": fixture.away_team,
            "home_score": fixture.home_score, "away_score": fixture.away_score,
            "observed_at": observed_at, "source": "football-data.org", **evidence}, "observation_id")


def known_results(payload, cutoff):
    selected = {}
    for row in sorted(payload.get("season_results", []), key=lambda r: (timestamp(r["observed_at"]), r["observation_id"])):
        verify_record(row, "observation_id")
        if timestamp(row["observed_at"]) < cutoff and timestamp(row["kickoff"]) < cutoff:
            # Keep richer metadata when the same score is reported by multiple routes.
            previous = selected.get(row["fixture_key"])
            if previous and (previous["home_score"], previous["away_score"]) == (row["home_score"], row["away_score"]):
                if previous.get("asian_handicap") and not row.get("asian_handicap"):
                    continue
            selected[row["fixture_key"]] = row
    return list(selected.values())


def team_form(rows, team, cutoff):
    relevant = [r for r in rows if team in (r["home_team_id"], r["away_team_id"])
                and timestamp(r["observed_at"]) < cutoff and timestamp(r["kickoff"]) < cutoff]
    relevant.sort(key=lambda r: r["kickoff"], reverse=True)
    recent, market = [], []
    for row in relevant:
        sign = 1 if row["home_team_id"] == team else -1
        margin = sign * (row["home_score"] - row["away_score"])
        if len(recent) < 5:
            recent.append(margin)
        line = (row.get("asian_handicap") or {}).get("handicap")
        market_time = timestamp(row.get("market_recorded_at"))
        if (len(market) < 5 and type(line) in (int, float) and math.isfinite(line)
                and market_time and market_time < timestamp(row["kickoff"])):
            market.append(margin + sign * line)
    # Missing samples shrink to zero; counts are exposed for audit.
    return {"recent": sum(recent) / (len(recent) + 3) / 3,
            "market": sum(market) / (len(market) + 3) / 3,
            "recent_count": len(recent), "market_count": len(market)}


def features(team, opponent, home, form, own_rank=None, opponent_rank=None):
    rank = (opponent_rank - own_rank) / 20 if all(type(r) is int and 1 <= r <= 24 for r in (own_rank, opponent_rank)) else 0
    return {"intercept": 1, "home_advantage": .5 if home else -.5,
            f"attack:{team}": 1, f"defence:{opponent}": 1,
            f"venue:{team}:{'home' if home else 'away'}": 1,
            "ranking": rank, "recent_form": max(-1, min(1, form["recent"])),
            "handicap_form": max(-1, min(1, form["market"]))}


def predict(payload, match, recorded_at):
    meta = match_metadata(match)
    now = timestamp(recorded_at)
    if not meta or not now:
        return {"status": "unavailable", "reason": "缺少联赛、球队ID或开球时间"}
    if now >= timestamp(meta["kickoff"]) or match.get("review") or match.get("result_snapshot"):
        return {"status": "unavailable", "reason": "比赛已开球或已取得赛果，不补造赛前预测"}
    rows = [r for r in known_results(payload, now) if r["competition_code"] == meta["competition_code"]
            and r["season"] == meta["season"] and r["fixture_key"] != meta["fixture_key"]]
    counts = {s: sum(meta[f"{s}_team_id"] in (r["home_team_id"], r["away_team_id"]) for r in rows) for s in ("home", "away")}
    if len(rows) < 12 or min(counts.values()) < 3:
        return {"status": "unavailable", "reason": f"本赛季已知样本不足：联赛{len(rows)}场，主/客{counts['home']}/{counts['away']}场；最低12场且各3场"}
    examples = []
    rank_count = 0
    for row in rows:
        ranks = row.get("rankings") or {}
        rank_time = timestamp(row.get("rank_recorded_at"))
        if not rank_time or rank_time >= timestamp(row["kickoff"]):
            ranks = {}
        rank_count += int(all(type(ranks.get(s)) is int for s in ("home", "away")))
        weight = 2 ** (-(now - timestamp(row["kickoff"])).total_seconds() / 86400 / HALF_LIFE_DAYS)
        for side, other in (("home", "away"), ("away", "home")):
            form = team_form(rows, row[f"{side}_team_id"], timestamp(row["kickoff"]))
            x = features(row[f"{side}_team_id"], row[f"{other}_team_id"], side == "home", form, ranks.get(side), ranks.get(other))
            examples.append((x, row[f"{side}_score"], weight))
    total_weight = sum(w for _, _, w in examples)
    base = math.log(max(.2, sum(y*w for _, y, w in examples) / total_weight))
    beta = {key: 0.0 for x, _, _ in examples for key in x}
    beta["intercept"] = base
    # Penalized Poisson regression. Simultaneous attack/defence terms adjust opponents.
    for _ in range(400):
        gradient = defaultdict(float)
        for x, y, w in examples:
            estimate = math.exp(max(-3, min(2, sum(beta[k]*v for k, v in x.items()))))
            for key, value in x.items():
                gradient[key] += w * (estimate - y) * value / total_weight
        for key in beta:
            penalty = 0 if key == "intercept" else .08 if key.startswith("venue:") else .03
            beta[key] -= .12 * (gradient[key] + penalty * beta[key])
    context = match.get("fundamental_context") or {}
    rankings = {s: (context.get(s) or {}).get("position") for s in ("home", "away")}
    forms, goals = {}, {}
    for side, other in (("home", "away"), ("away", "home")):
        forms[side] = team_form(rows, meta[f"{side}_team_id"], now)
        x = features(meta[f"{side}_team_id"], meta[f"{other}_team_id"], side == "home", forms[side], rankings[side], rankings[other])
        goals[side] = math.exp(max(-3, min(math.log(5), sum(beta.get(k, 0)*v for k, v in x.items()))))
    matrix = score_probabilities(goals["home"], goals["away"])
    probabilities = {"home": sum(p for (h,a),p in matrix.items() if h>a),
                     "draw": sum(p for (h,a),p in matrix.items() if h==a),
                     "away": sum(p for (h,a),p in matrix.items() if h<a)}
    result = {"status": "research", "version": VERSION, "expected_home_goals": goals["home"],
              "expected_away_goals": goals["away"], "probabilities": probabilities,
              "outcome_pick": max(probabilities, key=probabilities.get), "rankings": rankings,
              "training_matches": len(rows), "team_samples": counts, "form_features": forms,
              "training_digest": digest(sorted(r["observation_id"] for r in rows)),
              "feature_coverage": {"ranking_training_matches": rank_count,
                  "historical_handicap_matches": sum(bool(r.get("asian_handicap")) for r in rows)},
              "feature_coefficients": {k: beta[k] for k in ("home_advantage", "ranking", "recent_form", "handicap_form")},
              "top_score": list(max(matrix, key=matrix.get)), "betting_eligible": False}
    asian = match.get("asian_handicap") or {}
    try:
        returns = {s: expected_asian_return(matrix, float(asian["handicap"]), Selection(s), float(asian[f"{s}_odds"])) for s in ("home", "away")}
        selected = max(returns, key=lambda s: returns[s]["expected_profit_per_unit"])
        result["asian_handicap"] = returns
        result["selection"] = {"market_type": "asian_handicap", "side": selected,
            "home_handicap": float(asian["handicap"]), "odds": float(asian[f"{selected}_odds"]),
            "expected_profit_per_unit": returns[selected]["expected_profit_per_unit"]}
    except (KeyError, ValueError, TypeError):
        result["market_reason"] = "盘口不完整，仅保存胜平负预测"
    return result


def update_predictions(payload, recorded_at=None):
    recorded_at = recorded_at or now_iso()
    import_checker(payload)
    for match in payload.get("current_matches", []):
        if (match.get("mismatch") or {}).get("matched"):
            continue
        analysis = predict(payload, match, recorded_at)
        match["model_forecast"] = analysis
        if analysis["status"] != "research":
            continue
        key = fixture_identity(match)
        existing = [s for s in payload.get("model_forecasts", []) if s["fixture_key"] == key and s["version"] == VERSION]
        # Save every changed calculation; evaluation selects the first pre-match snapshot.
        if any(s["analysis"] == analysis and s["match"].get("asian_handicap") == match.get("asian_handicap") for s in existing):
            continue
        frozen = {k: deepcopy(match.get(k)) for k in ("id", "kickoff_time", "competition", "home_team", "away_team", "football_data_snapshot", "asian_handicap")}
        append_record(payload, "model_forecasts", {"fixture_key": key, "version": VERSION,
            "recorded_at": recorded_at, "batch_date": (payload.get("slate") or {}).get("date"),
            "match": frozen, "analysis": analysis}, "forecast_id")
    review_predictions(payload, recorded_at)


def first_forecasts(payload):
    selected = {}
    for row in sorted(payload.get("model_forecasts", []), key=lambda r: (timestamp(r["recorded_at"]), r["forecast_id"])):
        verify_record(row, "forecast_id")
        if timestamp(row["recorded_at"]) < timestamp(row["match"]["kickoff_time"], kickoff=True):
            selected.setdefault((row["fixture_key"], row["version"]), row)
    return list(selected.values())


def review_predictions(payload, observed_at=None):
    observed_at = observed_at or now_iso()
    results = {r["fixture_key"]: r for r in known_results(payload, timestamp(observed_at)+timedelta(microseconds=1))}
    for forecast in first_forecasts(payload):
        row = results.get(forecast["fixture_key"])
        if not row:
            continue
        analysis = forecast["analysis"]
        h, a = row["home_score"], row["away_score"]
        actual = "home" if h>a else "away" if a>h else "draw"
        review = {"forecast_id": forecast["forecast_id"], "version": forecast["version"],
                  "result_observation_id": row["observation_id"], "observed_at": row["observed_at"],
                  "final_score": f"{h}-{a}", "outcome_hit": analysis["outcome_pick"] == actual,
                  "brier": sum((p-int(s==actual))**2 for s,p in analysis["probabilities"].items()),
                  "log_loss": -math.log(max(1e-12, analysis["probabilities"][actual]))}
        selection = analysis.get("selection")
        if selection:
            from odds_analyzer.models import AsianHandicapLine
            settled = settle_asian_handicap(MatchScore(h,a), AsianHandicapLine(selection["home_handicap"]), Selection(selection["side"]))
            review["settlement"] = settled
            review["unit_profit"] = settled * (selection["odds"]-1) if settled>0 else settled
        append_record(payload, "model_reviews", review, "model_review_id")
    latest = {}
    for review in sorted(payload.get("model_reviews", []), key=lambda r: timestamp(r["observed_at"])):
        verify_record(review, "model_review_id")
        latest[review["forecast_id"]] = review
    current = [r for r in latest.values() if r["version"] == VERSION]
    profits = [r["unit_profit"] for r in current if "unit_profit" in r]
    payload["model_evaluation"] = {"version": VERSION, "forecasts": sum(f["version"]==VERSION for f in first_forecasts(payload)),
        "reviewed": len(current), "hits": sum(r["outcome_hit"] for r in current),
        "mean_brier": sum(r["brier"] for r in current)/len(current) if current else None,
        "market_reviewed": len(profits), "unit_roi": sum(profits)/len(profits) if profits else None}
