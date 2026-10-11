"""Produce an auditable pre-match Poisson research report without issuing picks."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from odds_analyzer.poisson_baseline import shadow_match
from odds_analyzer.sources.football_data import _get_json, parse_football_data_fixtures


def load_training(api_key: str, competition_codes: set[str], year: int) -> tuple[list[dict], list[str]]:
    fixtures = []
    errors = []
    for code in sorted(competition_codes):
        if code == "CL":
            continue  # Different competition structure; the league model is not valid here.
        for season in (year - 1, year):
            try:
                response = _get_json(f"/competitions/{code}/matches", api_key,
                                     {"season": str(season), "status": "FINISHED"}, 20)
                parsed = parse_football_data_fixtures(response, code)
                fixtures.extend({
                    "competition_code": fixture.competition_code,
                    "utc_date": fixture.utc_date,
                    "home_team_id": fixture.home_team_id,
                    "away_team_id": fixture.away_team_id,
                    "home_score": fixture.home_score,
                    "away_score": fixture.away_score,
                    "status": fixture.status,
                } for fixture in parsed)
            except Exception as exc:
                errors.append(f"{code}/{season}: {type(exc).__name__}")
            time.sleep(7)  # The free API plan has a small per-minute request allowance.
    return fixtures, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--training", type=Path, help="Saved finished fixtures JSON; avoids network calls")
    args = parser.parse_args()
    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    matches = payload.get("current_matches", [])
    slate_date = (payload.get("slate") or {}).get("date")
    if not slate_date:
        raise ValueError("Payload must include a slate date")
    if args.training:
        data = json.loads(args.training.read_text(encoding="utf-8"))
        fixtures = data["matches"]
        source = str(args.training)
        errors = []
    elif key := os.environ.get("FOOTBALL_DATA_API_KEY", "").strip():
        codes = {str((m.get("football_data_snapshot") or {}).get("competition_code") or "")
                 for m in matches}
        fixtures, errors = load_training(key, codes - {""}, int(slate_date[:4]))
        source = "football-data.org competition finished-match API"
    else:
        fixtures, errors, source = [], ["FOOTBALL_DATA_API_KEY unavailable"], "none"
    output = {
        "slate_date": slate_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "research_only_not_validated",
        "training_source": source,
        "training_errors": errors,
        "training_fixture_count": len(fixtures),
        "matches": [{
            "match_id": m.get("id"),
            "home_team": m.get("home_team"),
            "away_team": m.get("away_team"),
            "mismatch": (m.get("mismatch") or {}).get("matched") is True,
            "market_snapshot": {
                "asian_handicap": m.get("asian_handicap"),
                "chinese_lottery": m.get("chinese_lottery"),
            },
            "analysis": shadow_match(m, fixtures),
        } for m in matches if not (m.get("mismatch") or {}).get("matched")],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Poisson shadow: {sum(m['analysis']['status'].startswith('shadow') for m in output['matches'])} "
          f"analyzed / {len(output['matches'])} non-mismatch matches")


if __name__ == "__main__":
    main()
