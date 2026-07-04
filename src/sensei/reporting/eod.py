"""Reporting Agent — "The Secretary" (PRD §4.9). EOD markdown report."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sensei.paper.engine import PaperBook, load_closed_trades

REPORTS_DIR = Path(__file__).resolve().parents[3] / "data" / "reports"
AUDIT_LOG = Path(__file__).resolve().parents[3] / "data" / "audit.jsonl"


def _todays_vetoes(today: str) -> list[dict]:
    if not AUDIT_LOG.exists():
        return []
    out = []
    for line in AUDIT_LOG.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("event") == "verdict" and not e.get("approved") \
                and e.get("ts", "").startswith(today):
            out.append(e)
    return out


def generate_eod_report(book: PaperBook, today: date | None = None) -> Path:
    today = today or date.today()
    iso = today.isoformat()
    closed_today = [t for t in load_closed_trades() if t.closed == iso]
    all_closed = load_closed_trades()
    vetoes = _todays_vetoes(iso)

    day_pnl = sum(t.pnl for t in closed_today)
    total_pnl = sum(t.pnl for t in all_closed)
    wins = [t for t in all_closed if t.pnl > 0]
    pm_done = sum(1 for t in all_closed if t.post_mortem)

    lines = [
        f"# EOD Report — {iso}",
        "",
        "## Account",
        f"- Cash: ₹{book.cash:,.0f}",
        f"- Invested: ₹{book.equity_invested:,.0f}",
        f"- Day P&L (closed): ₹{day_pnl:,.0f}",
        f"- Cumulative P&L: ₹{total_pnl:,.0f}",
        "",
        "## Open positions",
    ]
    if book.positions:
        for p in book.positions:
            lines.append(f"- **{p.symbol}** {p.direction} {p.quantity} @ ₹{p.entry_price:.2f} "
                         f"(stop ₹{p.stop_loss:.2f}, opened {p.opened})")
            lines.append(f"  - Thesis: {p.narrative}")
    else:
        lines.append("- None")

    lines += ["", "## Trades closed today"]
    if closed_today:
        for t in closed_today:
            lines.append(f"- **{t.symbol}** exit {t.exit_reason} @ ₹{t.exit_price:.2f} "
                         f"→ P&L ₹{t.pnl:,.0f}")
    else:
        lines.append("- None")

    lines += ["", "## Vetoes today"]
    if vetoes:
        for v in vetoes:
            lines.append(f"- {v['thesis_id']} vetoed at {v['level']} ({v['agent']}): "
                         f"{v['reasoning']}")
    else:
        lines.append("- None")

    lines += [
        "",
        "## Learning metrics",
        f"- Lifetime trades: {len(all_closed)}, hit rate: "
        f"{(len(wins) / len(all_closed) * 100) if all_closed else 0:.0f}%",
        f"- Post-mortem completion: {pm_done}/{len(all_closed)}",
        "",
    ]

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"eod-{iso}.md"
    path.write_text("\n".join(lines))
    return path
