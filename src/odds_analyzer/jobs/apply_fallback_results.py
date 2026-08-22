from __future__ import annotations

import argparse
from pathlib import Path

from odds_analyzer.fallback_results import apply_fallback_results
from odds_analyzer.jobs.refresh_evening_slate import DEFAULT_PAYLOAD_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and apply Codex fallback research results."
    )
    parser.add_argument("--results", required=True, help="Structured fallback results JSON file.")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD_PATH))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = apply_fallback_results(Path(args.payload), Path(args.results))
    summary = payload["last_fallback_import"]
    print(
        "Applied fallback results: "
        f"results={summary['result_count']} fields={summary['field_count']} "
        f"resolved={summary['resolved_count']}"
    )


if __name__ == "__main__":
    main()
