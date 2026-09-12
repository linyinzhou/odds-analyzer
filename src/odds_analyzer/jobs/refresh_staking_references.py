"""Refresh ratio displays from saved odds without regenerating forecasts."""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from odds_analyzer.learning import now_iso
from odds_analyzer.staking import build_staking_plan
from odds_analyzer.jobs.refresh_evening_slate import _attach_bilingual_reports


def refresh_staking_references(payload: dict) -> dict:
    updated = deepcopy(payload)
    refreshed_at = now_iso()
    current_ids = {match["id"] for match in updated.get("current_matches", [])}
    slate_date = str((updated.get("slate") or {}).get("date") or "")
    count = 0
    for collection in ("current_matches", "mismatch_history"):
        for index, match in enumerate(updated.get(collection, [])):
            if collection != "current_matches" and (match.get("id") not in current_ids or str(match.get("batch_date") or "") != slate_date):
                continue
            lottery = match.get("chinese_lottery")
            match["staking_references"] = [build_staking_plan(lottery, pair) for pair in
                (["home", "draw"], ["home", "away"], ["draw", "away"])] if lottery else []
            prediction = match.get("prediction") or {}
            old = prediction.get("staking_plan") or (match.get("mismatch") or {}).get("staking_plan")
            if old:
                new = build_staking_plan(lottery, prediction.get("selection_keys") or [])
                prediction["staking_plan"] = new
                if match.get("mismatch") is not None:
                    match["mismatch"]["staking_plan"] = new
                # Change display prose only. Selection, confidence and eligibility remain saved values.
                for container, key, language in ((prediction, "detail", "zh"), (prediction, "detail_en", "en"),
                    (match.get("recommendation") or {}, "mismatch", "zh"),
                    (match.get("recommendation") or {}, "mismatch_en", "en"), (match, "checker", "zh")):
                    before = old.get("note_" + language)
                    if before and isinstance(container.get(key), str):
                        container[key] = container[key].replace(before, new["note_" + language])
            match["staking_refreshed_at"] = refreshed_at
            updated[collection][index] = _attach_bilingual_reports([match])[0]
            if collection == "current_matches":
                count += 1
    updated["last_staking_refresh"] = {"refreshed_at": refreshed_at, "match_count": count,
        "basis": "saved_odds_and_selections", "forecasts_regenerated": False}
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", required=True)
    args = parser.parse_args()
    path = Path(args.payload)
    updated = refresh_staking_references(json.loads(path.read_text(encoding="utf-8")))
    path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(updated["last_staking_refresh"]))


if __name__ == "__main__":
    main()
