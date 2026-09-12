from __future__ import annotations

import argparse
import json
from pathlib import Path

from odds_analyzer.learning import evaluate_archive


def render_report(report: dict) -> str:
    overall = report["overall"]
    lines = ["# Frozen prediction evaluation", "", f"Selection policy: `{report['selection_policy']}`.",
             f"Snapshots: {report['snapshot_count']}; selected fixtures: {report['selected_fixtures']}; "
             f"settled comparisons: {overall['settled']}; pending: {report['pending_results']}.", "",
             "Confidence scores are heuristic. These probability scores are diagnostics, not proof of predictive skill.",
             "Base and calibration share identical picks, hit rate and unit-stake ROI.", "",
             "| Version | Non-push samples | Brier (lower is better) | Log loss (lower is better) |",
             "|---|---:|---:|---:|"]
    for name in ("base", "calibrated"):
        score = overall[name]
        lines.append(f"| {name} | {score['n']} | {score['brier']} | {score['log_loss']} |")
    lines += ["", "## Weekly walk-forward comparison", "",
              "| Week starting | Settled | Base Brier | Calibrated Brier | Delta (negative is better) |",
              "|---|---:|---:|---:|---:|"]
    for period in report["weekly_walk_forward"]:
        lines.append(f"| {period['week_start']} | {period['settled']} | {period['base']['brier']} | {period['calibrated']['brier']} | {period['brier_delta']} |")
    lines += ["", "## Paired market baseline", "",
              "Only identical events are compared; integer/quarter Asian lines are excluded from this subset.", ""]
    for name, score in overall["market_paired"].items():
        lines.append(f"- {name}: n={score['n']}, Brier={score['brier']}, log loss={score['log_loss']}")
    lines += ["", "## Settlement and exclusions", "",
              f"- Outcomes: {overall['outcomes']}", f"- Unit-stake ROI (quoted matches only): {overall['roi']}",
              f"- Exclusions: {report['exclusions']}",
              f"- Additional eligible versions excluded: {report['duplicate_versions_excluded']}",
              f"- Mutable checker rows not used as training evidence: {report['mutable_checker_rows_not_used']}", "",
              "## Limits", "", *[f"- {note}" for note in report["limitations"]]]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate frozen forecasts without modifying the input payload.")
    parser.add_argument("--payload", default="dashboard/data/daily_matches.json")
    parser.add_argument("--output", help="Optional JSON output; otherwise print JSON.")
    parser.add_argument("--markdown", help="Optional readable Markdown report.")
    args = parser.parse_args()
    source = Path(args.payload).resolve()
    targets = [Path(value).resolve() for value in (args.output, args.markdown) if value]
    if source in targets or len(set(targets)) != len(targets):
        parser.error("Output paths must differ from the payload and each other.")
    report = evaluate_archive(json.loads(source.read_text(encoding="utf-8-sig")))
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    if args.markdown:
        Path(args.markdown).write_text(render_report(report), encoding="utf-8")


if __name__ == "__main__":
    main()
