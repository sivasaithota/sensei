"""Sensei CLI — the owner's control surface.

    sensei run-day        # one full trading day (refresh, scan, approve, fill, report)
    sensei scan           # dry-run: show today's signal candidates, no LLM, no trades
    sensei report         # regenerate today's EOD report
    sensei kill           # OWNER KILL-SWITCH: halt all trading immediately
    sensei resume         # clear the kill-switch
    sensei status         # account snapshot
    sensei playbook       # rebuild the Signal Playbook from historical data
    sensei research-lab-status  # latest governed research lab verdicts
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone


def main() -> None:
    parser = argparse.ArgumentParser(prog="sensei")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run-day")
    sub.add_parser("execute-open")
    study_p = sub.add_parser("study")
    study_p.add_argument("file", nargs="?", help="path to material; omit to read stdin")
    scan_p = sub.add_parser("scan")
    scan_p.add_argument("--no-refresh", action="store_true")
    sub.add_parser("report")
    sub.add_parser("kill")
    sub.add_parser("resume")
    sub.add_parser("status")
    sub.add_parser("playbook")
    desk_p = sub.add_parser("desk-status")
    desk_p.add_argument(
        "--journal",
        default="data/operations.sqlite3",
        help="existing governed operational journal",
    )
    desk_p.add_argument("--limit", type=int, default=10)
    lab_p = sub.add_parser("research-lab-status")
    lab_p.add_argument(
        "--journal",
        default="data/operations.sqlite3",
        help="existing governed operational journal",
    )
    lab_p.add_argument("--limit", type=int, default=10)
    scheduler_p = sub.add_parser("scheduler-run-once")
    scheduler_p.add_argument("--journal", default="data/operations.sqlite3")
    scheduler_p.add_argument("--config", default=None)
    scheduler_p.add_argument("--now", default=None, help="aware ISO timestamp (test/manual)")
    scheduler_status_p = sub.add_parser("scheduler-status")
    scheduler_status_p.add_argument("--journal", default="data/operations.sqlite3")
    scheduler_bootstrap_p = sub.add_parser("scheduler-bootstrap")
    scheduler_bootstrap_p.add_argument("--journal", default="data/operations.sqlite3")
    scheduler_bootstrap_p.add_argument("--config", default="config/scheduler.json")
    scheduler_bootstrap_p.add_argument(
        "--secrets", default="data/runtime-secrets.json",
        help="owner-only runtime signing material (created with mode 0600)",
    )
    scheduler_migrate_p = sub.add_parser("scheduler-migrate-governance")
    scheduler_migrate_p.add_argument("--journal", default="data/operations.sqlite3")
    scheduler_migrate_p.add_argument("--config", default="config/scheduler.json")
    scheduler_migrate_p.add_argument("--playbook", default="data/playbook/current.json")
    scheduler_migrate_p.add_argument("--rules", default="data/studied_rules.json")
    scheduler_migrate_p.add_argument("--positions", default="data/paper/positions.json")
    scheduler_migrate_p.add_argument("--prices-dir", default="data/prices")
    ui_p = sub.add_parser("ui")
    ui_p.add_argument("--port", type=int, default=8642)
    monitor_p = sub.add_parser("shadow-monitor")
    monitor_p.add_argument("--journal", default="data/operations.sqlite3")
    args = parser.parse_args()

    if args.cmd == "shadow-monitor":
        from pathlib import Path
        from sensei.reporting.shadow_monitor import run
        print(json.dumps(run(Path(args.journal)), indent=2, default=str))
        return

    if args.cmd == "scheduler-migrate-governance":
        from pathlib import Path
        from sensei.automation import GovernedSchedulerApplication
        from sensei.automation.migration import (
            adopt_legacy_positions,
            migrate_adopted_strategies,
            publish_pre_shadow_evidence,
        )
        from sensei.governance.lifecycle import EvidenceKind

        journal_path = Path(args.journal)
        if not journal_path.is_file():
            parser.error(f"governed journal does not exist: {journal_path}")
        app = GovernedSchedulerApplication.open(
            journal_path, config_path=Path(args.config)
        )
        now = datetime.now(timezone.utc)
        provenance_root = journal_path.parent / "provenance"
        result = migrate_adopted_strategies(
            app.journal,
            playbook_path=Path(args.playbook),
            rules_path=Path(args.rules),
            artifact_root=provenance_root,
            occurred_at=now,
        )
        publish_pre_shadow_evidence(
            app.journal,
            app.dossiers,
            records=result.registered,
            playbook_path=Path(args.playbook),
            provenance_root=provenance_root,
            artifact_root=journal_path.parent / "governance-artifacts",
            issuer_id=app.config.dossier_issuer_id,
            producer_ids_by_kind={
                kind: next(iter(app.config.producers_by_kind[kind]))
                for kind in (
                    EvidenceKind.EXAMINATION_DOSSIER,
                    EvidenceKind.CONFORMANCE_DOSSIER,
                    EvidenceKind.SHADOW_READINESS,
                    EvidenceKind.LOCKED_CONFIRMATION,
                )
            },
            occurred_at=now,
        )
        positions = adopt_legacy_positions(
            app.journal,
            positions_path=Path(args.positions),
            occurred_at=now,
        )
        from sensei.runtime import LegacyPositionAdoptionRegistry
        import pandas as pd

        marks = {
            item.symbol: round(float(pd.read_parquet(
                Path(args.prices_dir) / f"{item.symbol}.parquet",
                columns=["close"],
            )["close"].iloc[-1]) * 100)
            for item in positions
        }
        position_truth = LegacyPositionAdoptionRegistry(
            app.journal, positions_path=Path(args.positions)
        ).reconcile(
            mark_prices_paise=marks,
            captured_at=now,
            command_id="governance-migration:legacy-position-reconciliation",
        )
        reports = [
            app.autopilot.reconcile(now=now, command_id=f"governance-migration:{index}")
            for index in range(3)
        ]
        print(json.dumps({
            "registered_plans": [item.plan_id for item in result.registered],
            "skipped_rules": list(result.skipped_names),
            "adopted_positions": [item.symbol for item in positions],
            "legacy_position_reconciliation_event_id": (
                position_truth.reconciliation_event_id
            ),
            "legacy_account_snapshot_id": position_truth.account_snapshot.snapshot_id,
            "stages": [
                {item.plan_id: item.stage.value for item in report.results}
                for report in reports
            ],
        }, indent=2))
        return

    if args.cmd == "scheduler-bootstrap":
        from pathlib import Path
        from sensei.operations import OperationalJournal
        from sensei.automation import GovernedSchedulerApplication
        from sensei.runtime import RuntimeSecretStore, RuntimeTrustError

        journal_path = Path(args.journal)
        config_path = Path(args.config)
        if journal_path.exists():
            parser.error(f"governed journal already exists: {journal_path}")
        if not config_path.is_file():
            parser.error(f"scheduler config does not exist: {config_path}")
        secrets_path = Path(args.secrets)
        try:
            RuntimeSecretStore.bootstrap(secrets_path)
        except RuntimeTrustError as exc:
            parser.error(str(exc))
        journal = OperationalJournal(journal_path)
        verification = journal.verify()
        if not verification.ok:
            parser.error("new governed journal failed integrity verification")
        GovernedSchedulerApplication.open(journal_path, config_path=config_path)
        print(json.dumps({
            "journal": str(journal_path),
            "config": str(config_path),
            "runtime_secrets": str(secrets_path),
            "runtime_secrets_mode": "0600",
            "verified": True,
            "execution_backend": "governed_paper",
        }, indent=2))
        return

    if args.cmd == "scheduler-run-once":
        from pathlib import Path
        from sensei.automation import GovernedSchedulerApplication, SchedulerConfigurationError

        journal_path = Path(args.journal)
        try:
            now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
            if now.tzinfo is None:
                parser.error("--now must include a timezone offset")
            app = GovernedSchedulerApplication.open(
                journal_path,
                config_path=Path(args.config) if args.config else None,
            )
            result = app.run_once(now)
        except (SchedulerConfigurationError, ValueError) as exc:
            parser.error(str(exc))
        print(json.dumps(result.to_dict(), indent=2))
        return

    if args.cmd == "scheduler-status":
        from pathlib import Path
        from sensei.operations import OperationalJournal
        from sensei.automation.scheduling import SchedulerLedger

        journal_path = Path(args.journal)
        if not journal_path.is_file():
            parser.error(f"governed journal does not exist: {journal_path}")
        journal = OperationalJournal(journal_path)
        verification = journal.verify()
        print(json.dumps({
            "journal": {
                "ok": verification.ok,
                "events_checked": verification.events_checked,
                "errors": list(verification.errors),
            },
            "resolved_task_ids": sorted(SchedulerLedger(journal).resolved_task_ids()),
        }, indent=2))
        return

    if args.cmd == "research-lab-status":
        from pathlib import Path

        from sensei.operations import OperationalJournal
        from sensei.reporting.research_lab import ResearchLabReporter

        journal_path = Path(args.journal)
        if not journal_path.is_file():
            parser.error(f"governed journal does not exist: {journal_path}")
        summaries = ResearchLabReporter(
            OperationalJournal(journal_path)
        ).latest(limit=args.limit)
        print(json.dumps([item.to_dict() for item in summaries], indent=2))
        return

    if args.cmd == "desk-status":
        from pathlib import Path

        from sensei.operations import OperationalJournal
        from sensei.reporting.desk import DeskStatusReporter

        journal_path = Path(args.journal)
        if not journal_path.is_file():
            parser.error(f"governed journal does not exist: {journal_path}")
        summaries = DeskStatusReporter(
            OperationalJournal(journal_path)
        ).latest(limit=args.limit)
        print(json.dumps([item.to_dict() for item in summaries], indent=2))
        return

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

    if args.cmd == "study":
        from pathlib import Path
        from sensei.loop.study import study
        material = Path(args.file).read_text() if args.file else sys.stdin.read()
        print(json.dumps(study(material), indent=2))
        return

    if args.cmd == "execute-open":
        from sensei.loop.openexec import execute_pending
        print(json.dumps(execute_pending(), indent=2))
        return

    if args.cmd == "ui":
        from sensei.ui.server import serve
        serve(port=args.port)
        return

    if args.cmd == "run-day":
        from sensei.loop.daily import run_day
        summary = run_day()
        print(json.dumps(summary, indent=2))
        return


if __name__ == "__main__":
    main()
