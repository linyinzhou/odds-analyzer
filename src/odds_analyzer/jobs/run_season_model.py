"""Import checker history and record current pre-match model forecasts."""
import argparse
import json
from pathlib import Path

from odds_analyzer.season_model import update_predictions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, default=Path("dashboard/data/daily_matches.json"))
    args = parser.parse_args()
    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    update_predictions(payload)
    args.payload.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"season_observations": len(payload.get("season_results", [])),
                      "model_evaluation": payload["model_evaluation"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
