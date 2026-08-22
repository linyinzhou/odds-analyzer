from __future__ import annotations

from odds_analyzer.models import MatchReport, ThreeWayOdds


def render_match_report(report: MatchReport) -> str:
    """Render a compact Markdown match report."""

    lines = [
        f"# {report.match.home_team} vs {report.match.away_team}",
        "",
        "## Match",
        "",
        f"- Competition: {report.match.competition or 'Unknown'}",
        f"- Kickoff: {report.kickoff_time}",
        f"- Venue: {report.venue or 'Unknown'}",
        f"- Weather: {report.weather or 'Unknown'}",
        "",
        "## Fundamentals",
        "",
        f"- Ranking: {_inline_items(report.standings)}",
        f"- Form: {_inline_items(report.form)}",
        f"- Team news: {_inline_items(report.team_news)}",
        f"- Tactics: {_inline_items(report.tactical_notes)}",
        f"- H2H: {_inline_items(report.head_to_head)}",
        f"- Notes: {_inline_items(report.fundamentals)}",
        "",
        "## Odds",
        "",
        f"- European 1X2: {_format_three_way(report.european_odds)}",
        f"- Asian handicap: {_format_asian(report)}",
        f"- Chinese lottery: {_format_chinese_lottery(report)}",
        "",
        "## Verdict",
        "",
    ]

    if report.signal:
        lines.append(f"- Signal: {report.signal.selection.value}")
        lines.append(f"- Confidence: {report.signal.confidence:.0%}")
        lines.append(f"- Reason: {report.signal.reason}")
        lines.append(f"- Signal risk: {report.signal.risk}")
    else:
        lines.append("- Signal: Not available")

    lines.extend(["", f"- Recommendation: {report.recommendation}", f"- Risks: {_inline_items(report.risks)}"])

    if report.data_sources:
        lines.append(f"- Sources: {_inline_items(report.data_sources)}")

    return "\n".join(lines).strip() + "\n"


def _format_three_way(odds: ThreeWayOdds | None) -> str:
    if not odds:
        return "not available"
    return f"{odds.home:.2f} / {odds.draw:.2f} / {odds.away:.2f}"


def _format_asian(report: MatchReport) -> str:
    asian = report.asian_handicap
    if not asian:
        return "not available"
    return f"{asian.provider} {asian.handicap:+g}, home {asian.home_odds:.2f}, away {asian.away_odds:.2f}"


def _format_chinese_lottery(report: MatchReport) -> str:
    lottery = report.chinese_lottery
    if not lottery:
        return "not available"

    standard = _format_three_way(lottery.standard)
    if lottery.handicap is None:
        return f"SPF {standard}; handicap not available"

    handicap_odds = _format_three_way(lottery.handicap_odds)
    return f"SPF {standard}; HHAD {lottery.handicap:+d} {handicap_odds}"


def _inline_items(items: tuple[str, ...]) -> str:
    if not items:
        return "pending"
    return "; ".join(items)
