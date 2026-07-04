"""Sensei CLI — the owner's control surface.

    sensei run-day        # one full trading day (refresh, scan, approve, fill, report)
    sensei scan           # dry-run: show today's signal candidates, no LLM, no trades
    sensei report         # regenerate today's EOD report
    sensei kill           # OWNER KILL-SWITCH: halt all trading immediately
    sensei resume         # clear the kill-switch
    sensei status         # account snapshot
    sensei playbook       # rebuild the Signal Playbook from historical data
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date


def main() -> None:
    parser = argparse.ArgumentParser(prog="sensei")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run-day")
    scan_p = sub.add_parser("scan")
    scan_p.add_argument("--no-refresh", action="store_true")
    sub.add_parser("report")
    sub.add_parser("kill")
    sub.add_parser("resume")
    sub.add_parser("status")
    sub.add_parser("playbook")
    args = parser.parse_args()

    if args.cmd == "kill":
        from sensei.loop.daily import KILL_FILE
        KILL_FILE.parent.mkdir(parents=True, exist_ok=True)
        KILL_FILE.write_text(date.today().isoformat())
        print("KILL SWITCH ACTIVE — all trading halted. `sensei resume` to clear.")
        return

    if args.cmd == "resume":
        from sensei.loop.daily import KILL_FILE
        KILL_FILE.unlink(missing_ok=True)
        print("Kill-switch cleared. Trading resumes on next run-day.")
        return

    if args.cmd == "status":
        from sensei.paper.engine import PaperBook, load_closed_trades
        from sensei.loop.daily import kill_switch_active
        book = PaperBook()
        closed = load_closed_trades()
        print(f"Cash: ₹{book.cash:,.0f} | Invested: ₹{book.equity_invested:,.0f} "
              f"| Open: {len(book.positions)} | Closed trades: {len(closed)} "
              f"| Lifetime P&L: ₹{sum(t.pnl for t in closed):,.0f}"
              f"{' | ⛔ KILL-SWITCH ACTIVE' if kill_switch_active() else ''}")
        for p in book.positions:
            print(f"  {p.symbol} {p.direction} {p.quantity} @ ₹{p.entry_price:.2f} "
                  f"stop ₹{p.stop_loss:.2f} (opened {p.opened})")
        return

    if args.cmd == "scan":
        from sensei.loop.scanner import scan
        from sensei.loop.daily import refresh_data
        if not args.no_refresh:
            print("Refreshing data...", file=sys.stderr)
            refresh_data()
        cands = scan()
        if not cands:
            print("No signals today.")
        for c in cands:
            print(f"{c.symbol:12s} {c.strategy:25s} close ₹{c.close:.2f} "
                  f"stop ₹{c.stop_loss:.2f} target ₹{c.target:.2f} qty {c.quantity}")
        return

    if args.cmd == "report":
        from sensei.paper.engine import PaperBook
        from sensei.reporting.eod import generate_eod_report
        path = generate_eod_report(PaperBook())
        print(path.read_text())
        return

    if args.cmd == "playbook":
        from sensei.backtest.playbook import build_playbook
        pb = build_playbook()
        for s in pb["strategies"]:
            mark = "ADOPTED " if s["adopted"] else "rejected"
            print(f"[{mark}] {s['name']:30s} oos={s['out_of_sample']}")
        return

    if args.cmd == "run-day":
        from sensei.loop.daily import run_day
        summary = run_day()
        print(json.dumps(summary, indent=2))
        return


if __name__ == "__main__":
    main()
