from __future__ import annotations

import argparse
import json
import os
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from odds_analyzer.learning import (
    available_results,
    evaluate_archive,
    record_result,
    selected_snapshots,
    timestamp,
    training_performance,
)
from odds_analyzer.jobs.refresh_evening_slate import (
    ALLOWED_ANALYSIS_COMPETITIONS,
    BEIJING,
    COMPETITION_LABEL_BY_CODE,
    DEFAULT_PAYLOAD_PATH,
    _build_next_matchday,
    _dashboard_match_key,
    _football_data_fixture_key,
)
from odds_analyzer.models import MatchScore
from odds_analyzer.prediction_settlement import settle_saved_prediction
from odds_analyzer.sources import (
    FootballDataFixture,
    fetch_evening_fixtures,
    fetch_upcoming_fixtures,
)
from odds_analyzer.sources.football_data import fetch_fixture_by_id


FINISHED_STATUSES = {"FINISHED"}


def refresh_next_matchday(
    payload: dict[str, Any],
    api_key: str,
    query_time: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Refresh the 14-day schedule independently for each supported competition."""

    updated = deepcopy(payload)
    query_time = query_time or datetime.now(BEIJING)
    queried_at = query_time.isoformat(timespec="seconds")
    schedule = deepcopy(updated.get("next_matchday") or {})

    if not api_key:
        schedule["last_attempt_at"] = queried_at
        schedule["refresh_status"] = "skipped"
        schedule["refresh_error"] = "missing FOOTBALL_DATA_API_KEY"
        updated["next_matchday"] = schedule
        return updated, {"status": "skipped", "successful": 0, "failed": 0}

    fixtures: list[FootballDataFixture] = []
    successful_codes: list[str] = []
    errors: dict[str, str] = {}
    start_date = query_time.date().isoformat()
    for code in ALLOWED_ANALYSIS_COMPETITIONS:
        try:
            fixtures.extend(
                fetch_upcoming_fixtures(
                    api_key,
                    start_date,
                    competition_codes=(code,),
                )
            )
            successful_codes.append(code)
        except Exception as exc:
            errors[code] = type(exc).__name__

    if not successful_codes:
        schedule["last_attempt_at"] = queried_at
        schedule["refresh_status"] = "unavailable"
        schedule["refresh_errors"] = {
            COMPETITION_LABEL_BY_CODE[code]: error for code, error in errors.items()
        }
        updated["next_matchday"] = schedule
        return updated, {
            "status": "unavailable",
            "successful": 0,
            "failed": len(errors),
        }

    schedule = _build_next_matchday(
        tuple(fixtures),
        updated.get("current_matches", []),
        query_time,
        {},
        use_fallback_when_empty=False,
    )
    schedule["last_attempt_at"] = queried_at
    schedule["refresh_status"] = "partial" if errors else "success"
    if errors:
        schedule["refresh_errors"] = {
            COMPETITION_LABEL_BY_CODE[code]: error for code, error in errors.items()
        }
        by_name = {
            competition.get("name"): competition
            for competition in schedule.get("competitions", [])
        }
        for code, error in errors.items():
            competition = by_name.get(COMPETITION_LABEL_BY_CODE[code])
            if competition is not None and not competition.get("fixtures"):
                competition["status"] = f"football-data.org 查询失败：{error}。"

    updated["next_matchday"] = schedule
    return updated, {
        "status": schedule["refresh_status"],
        "successful": len(successful_codes),
        "failed": len(errors),
        "fixture_count": len(fixtures),
    }


def review_checker_results(
    payload: dict[str, Any],
    slate_date: str,
    fixtures: tuple[FootballDataFixture, ...],
    reviewed_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    updated = deepcopy(payload)
    reviewed_at = reviewed_at or datetime.now(BEIJING).isoformat(timespec="seconds")
    fixtures_by_id = {fixture.match_id: fixture for fixture in fixtures if fixture.match_id}
    fixtures_by_key = {_football_data_fixture_key(fixture): fixture for fixture in fixtures}
    counts = {"reviewed": 0, "pending": 0, "unsupported": 0, "not_found": 0}

    history = []
    for match in updated.get("checker_history", []):
        copied = deepcopy(match)
        if str(copied.get("batch_date", "")) != slate_date:
            history.append(copied)
            continue

        fixture = _fixture_for_match(copied, fixtures_by_id, fixtures_by_key)
        if fixture is None:
            counts["not_found"] += 1
            history.append(copied)
            continue
        if (
            fixture.status not in FINISHED_STATUSES
            or fixture.home_score is None
            or fixture.away_score is None
        ):
            counts["pending"] += 1
            history.append(copied)
            continue

        decision = settle_saved_prediction(
            copied,
            MatchScore(home_goals=fixture.home_score, away_goals=fixture.away_score),
        )
        if decision is None:
            counts["unsupported"] += 1
            copied["review_error"] = "无法识别已保存的具体市场；未自动判定命中或未中。"
            history.append(copied)
            continue

        copied.pop("review_error", None)
        copied["review"] = {
            "final_score": f"{fixture.home_score}-{fixture.away_score}",
            "reviewed": True,
            "hit": decision["hit"],
            "void": decision["void"],
            "outcome": decision["outcome"],
            "settlement": decision.get("settlement"),
            "review_note": decision["note"],
            "reviewed_at": reviewed_at,
            "source": "football-data.org",
        }
        copied["result_snapshot"] = {
            "match_id": fixture.match_id,
            "status": fixture.status,
            "source": "football-data.org",
        }
        counts["reviewed"] += 1
        history.append(copied)

    updated["checker_history"] = history
    # Settle the immutable selection, including forecasts outside the checker top-N.
    for snapshot in selected_snapshots(updated):
        if snapshot["batch_date"] != slate_date:
            continue
        fixture = _fixture_for_match(snapshot["match"], fixtures_by_id, fixtures_by_key)
        if fixture is not None:
            record_result(updated, snapshot, fixture.home_score, fixture.away_score,
                          reviewed_at, status=fixture.status)
    # Summary includes this review; future predictions still require strictly earlier observations.
    summary_time = (timestamp(reviewed_at) + timedelta(microseconds=1)).isoformat()
    updated["strategy_performance"] = training_performance(updated, summary_time)
    updated["learning_evaluation"] = evaluate_archive(updated)
    updated["last_result_review"] = {
        "batch_date": slate_date,
        "reviewed_at": reviewed_at,
        "source": "football-data.org",
        "fixture_count": len(fixtures),
        **counts,
    }
    return updated, counts


def review_results(path: Path, slate_date: str, api_key: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    review_date = slate_date or _latest_review_batch(payload)
    reviewed_at = datetime.now(BEIJING).isoformat(timespec="seconds")
    if not api_key:
        payload["last_result_review"] = {
            "batch_date": review_date,
            "reviewed_at": reviewed_at,
            "status": "skipped",
            "source": "football-data.org",
            "error": "missing FOOTBALL_DATA_API_KEY",
        }
        counts = {"reviewed": 0, "pending": 0, "unsupported": 0, "not_found": 0}
    else:
        dates = {review_date}
        results = available_results(payload)
        for snapshot in selected_snapshots(payload):
            kickoff = timestamp(snapshot["match"].get("kickoff_time"), kickoff=True)
            if snapshot["fixture_key"] not in results and kickoff and kickoff < timestamp(reviewed_at):
                dates.add(snapshot["batch_date"])
        counts = {"reviewed": 0, "pending": 0, "unsupported": 0, "not_found": 0}
        errors = {}
        successful_batches = 0
        for batch_date in sorted(dates):
            try:
                fixtures = fetch_evening_fixtures(api_key, batch_date)
            except Exception as exc:
                errors[batch_date] = type(exc).__name__
                continue
            fixtures = list(fixtures)
            present_ids = {fixture.match_id for fixture in fixtures}
            for snapshot in selected_snapshots(payload):
                if snapshot["batch_date"] != batch_date or (snapshot["fixture_key"] in results and batch_date != review_date):
                    continue
                match_id = (snapshot["match"].get("football_data_snapshot") or {}).get("match_id")
                if match_id and match_id not in present_ids:
                    try:
                        fixture = fetch_fixture_by_id(api_key, int(match_id))
                    except Exception as exc:
                        errors[f"fixture:{match_id}"] = type(exc).__name__
                    else:
                        if fixture is not None:
                            fixtures.append(fixture)
                            present_ids.add(fixture.match_id)
            payload, batch_counts = review_checker_results(payload, batch_date, tuple(fixtures), reviewed_at)
            successful_batches += 1
            for key in counts:
                counts[key] += batch_counts[key]
        payload["last_result_review"] = {
            "batch_date": review_date, "reviewed_at": reviewed_at,
            "status": "unavailable" if not successful_batches else "partial" if errors else "success",
            "source": "football-data.org", "attempted_batches": sorted(dates), "errors": errors, **counts,
        }

    payload, schedule_counts = refresh_next_matchday(payload, api_key)
    _write_payload(path, payload)
    print(
        f"Reviewed {counts['reviewed']} checker entries for {review_date}; "
        f"pending={counts['pending']} unsupported={counts['unsupported']} not_found={counts['not_found']}; "
        f"next_matchday={schedule_counts['status']} "
        f"successful={schedule_counts['successful']} failed={schedule_counts['failed']}"
    )
    return payload


def _fixture_for_match(
    match: dict[str, Any],
    fixtures_by_id: dict[int, FootballDataFixture],
    fixtures_by_key: dict[tuple[str, str, str, str], FootballDataFixture],
) -> FootballDataFixture | None:
    match_id = (match.get("football_data_snapshot") or {}).get("match_id")
    try:
        fixture = fixtures_by_id.get(int(match_id)) if match_id is not None else None
    except (TypeError, ValueError):
        fixture = None
    return fixture or fixtures_by_key.get(_dashboard_match_key(match))


def _latest_review_batch(payload: dict[str, Any]) -> str:
    batches = [str(match.get("batch_date")) for match in payload.get("checker_history", []) if match.get("batch_date")]
    if batches:
        return max(batches)
    return (datetime.now(BEIJING).date() - timedelta(days=1)).isoformat()


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Settle stored checker predictions from final scores.")
    parser.add_argument("--date", default="", help="Checker batch date in Asia/Shanghai YYYY-MM-DD.")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD_PATH))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    slate_date = args.date.strip()
    if slate_date:
        datetime.fromisoformat(slate_date)
    review_results(
        Path(args.payload),
        slate_date,
        os.environ.get("FOOTBALL_DATA_API_KEY", "").strip(),
    )


if __name__ == "__main__":
    main()
