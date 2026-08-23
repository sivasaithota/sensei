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
    scheduler_health_p = sub.add_parser("scheduler-health")
    scheduler_health_p.add_argument("--journal", default="data/operations.sqlite3")
    scheduler_health_p.add_argument("--config", default="config/scheduler.json")
    scheduler_health_p.add_argument("--heartbeat", default="data/scheduler-heartbeat.json")
    scheduler_health_p.add_argument("--lock", default="data/scheduler.lock")
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
    audit_p = sub.add_parser("backtest-audit")
    audit_p.add_argument("--strategy", default=None, help="adopted strategy name; omit = all")
    audit_p.add_argument("--capital", type=float, default=300000.0)
    audit_p.add_argument("--max-positions", type=int, default=5)
    audit_p.add_argument("--folds", type=int, default=5)
    audit_p.add_argument("--report", default="data/reports/backtest-audit-latest.json")
    monitor_p = sub.add_parser("shadow-monitor")
    monitor_p.add_argument("--journal", default="data/operations.sqlite3")
    monitor_p.add_argument("--config", default="config/scheduler.json")
    readiness_p = sub.add_parser("paper-readiness")
    readiness_p.add_argument("--journal", default="data/operations.sqlite3")
    readiness_p.add_argument("--config", default="config/scheduler.json")
    rehearsal_p = sub.add_parser("rehearse-entry")
    rehearsal_p.add_argument("--journal", default="data/operations.sqlite3")
    rehearsal_p.add_argument("--config", default="config/scheduler.json")
    rehearsal_p.add_argument(
        "--report", default="data/reports/entry-rehearsal-latest.json"
    )
    certify_p = sub.add_parser("prelive-certify")
    certify_p.add_argument("--journal", default="data/operations.sqlite3")
    certify_p.add_argument(
        "--report", default="data/reports/prelive-certification-latest.json"
    )
    certify_p.add_argument(
        "--rehearsal",
        default="data/reports/entry-rehearsal-latest.json",
    )
    certify_p.add_argument("--config", default="config/scheduler.json")
    certify_p.add_argument(
        "--target", choices=("paper", "real"), default="paper"
    )
    certify_p.add_argument(
        "--trusted-market-data-manifest-id",
        action="append",
        default=[],
        help="independently approved canonical market-data manifest SHA-256 ID",
    )
    certify_p.add_argument(
        "--trusted-market-data-issuer",
        action="append",
        default=[],
        help="independently approved market-data manifest issuer",
    )
    qualify_p = sub.add_parser("qualify-desk")
    qualify_p.add_argument(
        "--report", default="data/reports/desk-qualification-latest.json"
    )
    qualify_p.add_argument("--journal", default="data/operations.sqlite3")
    qualify_p.add_argument("--config", default="config/scheduler.json")
    replay_p = sub.add_parser("replay-desk")
    replay_p.add_argument("--journal", default="data/operations.sqlite3")
    replay_p.add_argument("--config", default="config/scheduler.json")
    replay_p.add_argument("--rules", default="data/studied_rules.json")
    replay_p.add_argument("--sessions", type=int, default=60)
    replay_p.add_argument("--capital", type=float, default=None)
    replay_p.add_argument(
        "--report", default="data/reports/historical-desk-replay-latest.json"
    )
    validate_p = sub.add_parser("validate-strategies")
    validate_p.add_argument("--prices-dir", default="data/prices")
    validate_p.add_argument("--playbook", default="data/playbook/current.json")
    validate_p.add_argument("--folds", type=int, default=5)
    validate_p.add_argument("--cost-pct", type=float, default=0.25)
    validate_p.add_argument("--consume-locked", action="store_true")
    validate_p.add_argument(
        "--locked-ledger",
        default="data/research/strategy-validation-locks.json",
    )
    validate_p.add_argument(
        "--report", default="data/reports/strategy-validation-latest.json"
    )
    cycle_p = sub.add_parser("research-cycle")
    cycle_p.add_argument("--folds", type=int, default=5)
    cycle_p.add_argument(
        "--costs", type=float, nargs="+", default=(0.25, 0.50, 1.00)
    )
    cycle_p.add_argument("--maximum-variants", type=int, default=30)
    cycle_p.add_argument("--cycle-id", default=None)
    cycle_p.add_argument(
        "--report", default="data/reports/research-cycle-latest.json"
    )
    portfolio_p = sub.add_parser("portfolio-campaign")
    portfolio_p.add_argument("--capital", type=float, default=300000)
    portfolio_p.add_argument("--sessions", type=int, default=756)
    portfolio_p.add_argument("--cost-pct", type=float, default=0.25)
    portfolio_p.add_argument(
        "--report", default="data/reports/portfolio-campaign-latest.json"
    )
    snapshot_p = sub.add_parser("bhavcopy-capture")
    snapshot_p.add_argument("--date", help="single session YYYY-MM-DD (default: today)")
    snapshot_p.add_argument("--start", help="range start YYYY-MM-DD (with --end)")
    snapshot_p.add_argument("--end", help="range end YYYY-MM-DD (with --start)")
    snapshot_p.add_argument("--catch-up", action="store_true",
                            help="manually retry unresolved dates in the recent "
                                 "lookback window (internal gaps included)")
    snapshot_p.add_argument("--max-lookback-days", type=int, default=30,
                            help="cap how far --catch-up reaches back (default 30)")
    snapshot_p.add_argument("--overwrite", action="store_true",
                            help="re-download sessions already on disk")

    matrix_p = sub.add_parser("diagnose-strategies")
    matrix_p.add_argument("--capital", type=float, default=300000)
    matrix_p.add_argument(
        "--windows", type=int, nargs="+", default=(252, 756, 1260)
    )
    matrix_p.add_argument(
        "--costs", type=float, nargs="+", default=(0.25, 0.50, 1.00)
    )
    matrix_p.add_argument(
        "--report", default="data/reports/strategy-diagnostic-matrix-latest.json"
    )
    args = parser.parse_args()

    if args.cmd == "bhavcopy-capture":
        from sensei.data import bhavcopy

        def _summarize(days: dict[str, str]) -> dict:
            counts: dict[str, int] = {}
            for status in days.values():
                counts[status] = counts.get(status, 0) + 1
            return counts

        # exactly one mode
        modes = [bool(args.date), bool(args.start or args.end), bool(args.catch_up)]
        if sum(modes) > 1:
            parser.error("choose exactly one of --date, --start/--end, or --catch-up")
        if args.max_lookback_days < 0:
            parser.error("--max-lookback-days must be non-negative")

        if args.catch_up:
            result = bhavcopy.catch_up(max_lookback_days=args.max_lookback_days,
                                       overwrite=args.overwrite)
            print(json.dumps({
                "base_dir": str(bhavcopy.base_dir()),
                "stamp": bhavcopy.STAMP,
                "mode": "catch-up",
                "sessions_attempted": len(result),
                "status_counts": _summarize(result),
                "days": result,
            }, indent=2, sort_keys=True))
            raise SystemExit(0)

        if args.start or args.end:
            if not (args.start and args.end):
                parser.error("--start and --end must be given together")
            try:
                start = date.fromisoformat(args.start)
                end = date.fromisoformat(args.end)
            except ValueError:
                parser.error("--start/--end must be valid YYYY-MM-DD dates")
            if end < start:
                parser.error("--end must not precede --start")
            result = bhavcopy.snapshot_range(start, end, overwrite=args.overwrite)
            print(json.dumps({
                "base_dir": str(bhavcopy.base_dir()),
                "stamp": bhavcopy.STAMP,
                "range": [args.start, args.end],
                "sessions_attempted": len(result),
                "status_counts": _summarize(result),
                "days": result,
            }, indent=2, sort_keys=True))
            raise SystemExit(0)

        try:
            day = date.fromisoformat(args.date) if args.date else date.today()
        except ValueError:
            parser.error("--date must be a valid YYYY-MM-DD date")
        status = bhavcopy.snapshot_day(day, overwrite=args.overwrite)
        out = {
            "date": day.isoformat(),
            "status": status.value,
            "stamp": bhavcopy.STAMP,
            "base_dir": str(bhavcopy.base_dir()),
        }
        if status is bhavcopy.FetchStatus.OK:
            out["path"] = str(bhavcopy.snapshot_path(day))
            out["manifest"] = json.loads(bhavcopy.manifest_path(day).read_text())
        print(json.dumps(out, indent=2, sort_keys=True))
        raise SystemExit(0)

    if args.cmd == "diagnose-strategies":
        from pathlib import Path
        import pandas as pd

        from sensei.backtest.playbook import all_strategies
        from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig
        from sensei.backtest.strategy_diagnostic_matrix import (
            adopted_strategy_scenarios,
            run_strategy_diagnostic_matrix,
        )

        root = Path(__file__).resolve().parents[2]
        scenarios = adopted_strategy_scenarios()
        names = {name for scenario in scenarios for name in scenario.strategies}
        available = all_strategies()
        strategies = {name: available[name] for name in names}
        frames = {
            path.stem: pd.read_parquet(path).sort_index()
            for path in sorted((root / "data/prices").glob("*.parquet"))
        }
        report = run_strategy_diagnostic_matrix(
            frames=frames,
            strategies=strategies,
            scenarios=scenarios,
            windows=tuple(args.windows),
            costs=tuple(args.costs),
            base_config=PortfolioCampaignConfig(
                capital=args.capital,
                max_position_pct=20,
                max_risk_per_trade_pct=2,
                max_open_positions=5,
                cost_pct=args.costs[0],
            ),
        )
        destination = Path(args.report)
        report_root = (root / "data/reports").resolve()
        if report_root not in destination.resolve().parents:
            parser.error("strategy diagnostic report must stay under data/reports")
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = report.to_dict()
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        raise SystemExit(0)

    if args.cmd == "portfolio-campaign":
        from pathlib import Path
        import pandas as pd

        from sensei.backtest.playbook import all_strategies
        from sensei.backtest.portfolio_campaign import (
            PortfolioCampaignConfig,
            run_portfolio_campaign,
        )

        if args.sessions <= 0:
            parser.error("portfolio campaign sessions must be positive")
        root = Path(__file__).resolve().parents[2]
        names = (
            "minervini_breakout_volume",
            "minervini_trend_template",
            "schwager_trend_with_pullback_strength",
        )
        available = all_strategies()
        strategies = {name: available[name] for name in names}
        frames = {}
        for path in sorted((root / "data/prices").glob("*.parquet")):
            frame = pd.read_parquet(path).sort_index()
            frames[path.stem] = frame
        sessions = sorted({date for frame in frames.values() for date in frame.index})
        if not sessions:
            parser.error("portfolio campaign requires price sessions")
        evaluation_start = sessions[-min(args.sessions, len(sessions))]
        report = run_portfolio_campaign(
            frames=frames,
            strategies=strategies,
            config=PortfolioCampaignConfig(
                capital=args.capital,
                max_position_pct=20,
                max_risk_per_trade_pct=2,
                max_open_positions=5,
                cost_pct=args.cost_pct,
            ),
            evaluation_start=evaluation_start,
        )
        destination = Path(args.report)
        report_root = (root / "data/reports").resolve()
        if report_root not in destination.resolve().parents:
            parser.error("portfolio campaign report must stay under data/reports")
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = report.to_dict()
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        raise SystemExit(0)

    if args.cmd == "research-cycle":
        import hashlib
        import subprocess
        from dataclasses import asdict
        from pathlib import Path

        import pandas as pd

        from sensei.backtest.campaign import (
            ValidationThresholds,
            run_validation_campaign,
            validation_campaign_id,
        )
        from sensei.backtest.playbook import all_strategies
        from sensei.backtest.research_cycle import (
            ResearchCycleLedger,
            assess_research_cycle,
            strategy_variant_ids,
        )

        if len(set(args.costs)) < 2:
            parser.error("research-cycle requires at least two unique costs")
        if any(cost < 0 for cost in args.costs):
            parser.error("research-cycle costs must be non-negative")
        strategies = all_strategies()
        if len(strategies) > args.maximum_variants:
            parser.error(
                f"{len(strategies)} hypotheses exceed the "
                f"{args.maximum_variants}-variant research budget"
            )
        root = Path(__file__).resolve().parents[2]
        prices_path = root / "data/prices"
        frames = {
            path.stem: pd.read_parquet(path)
            for path in sorted(prices_path.glob("*.parquet"))
        }
        if not frames:
            parser.error("research-cycle price directory contains no parquet data")
        git_status = subprocess.check_output(
            ("git", "status", "--porcelain=v1"), cwd=root, text=True
        )
        git_diff = subprocess.check_output(
            ("git", "diff", "--binary", "HEAD"), cwd=root
        )
        provenance = {
            "pyproject_sha256": hashlib.sha256(
                (root / "pyproject.toml").read_bytes()
            ).hexdigest(),
            "uv_lock_sha256": hashlib.sha256(
                (root / "uv.lock").read_bytes()
            ).hexdigest(),
            "git_head": subprocess.check_output(
                ("git", "rev-parse", "HEAD"), cwd=root, text=True
            ).strip(),
            "git_worktree_state_sha256": hashlib.sha256(
                git_status.encode() + git_diff
            ).hexdigest(),
        }
        costs = tuple(sorted(args.costs))
        thresholds = ValidationThresholds()
        cycle_id = args.cycle_id or (
            "research-cycle-" + datetime.now(timezone.utc).date().isoformat()
        )
        preregistered_campaign_ids = tuple(
            validation_campaign_id(
                frames=frames,
                strategies=strategies,
                folds=args.folds,
                cost_pct=cost,
                thresholds=thresholds,
                provenance=provenance,
            )
            for cost in costs
        )
        declaration_fingerprint = hashlib.sha256(
            json.dumps(preregistered_campaign_ids).encode()
        ).hexdigest()
        family_id = "current-strategy-library"
        ledger = ResearchCycleLedger(root / "data/research/research-cycle-ledger.json")
        ledger.preregister(
            family_id=family_id,
            cycle_id=cycle_id,
            variant_ids=strategy_variant_ids(
                strategies,
                universe_id="sha256:" + hashlib.sha256(
                    json.dumps(sorted(frames)).encode()
                ).hexdigest(),
            ),
            maximum_variants=args.maximum_variants,
            costs_pct=costs,
            folds=args.folds,
            input_fingerprint="sha256:" + declaration_fingerprint,
            execution_fingerprint="sha256:" + provenance["git_worktree_state_sha256"],
            campaign_ids=preregistered_campaign_ids,
            success_criteria=asdict(thresholds),
        )
        campaigns = tuple(
            run_validation_campaign(
                frames=frames,
                strategies=strategies,
                folds=args.folds,
                cost_pct=cost,
                thresholds=thresholds,
                progress=lambda name, cost=cost: print(
                    f"[{cost:.2f}%] validating {name}...",
                    file=sys.stderr,
                    flush=True,
                ),
                provenance=provenance,
            )
            for cost in costs
        )
        report = assess_research_cycle(
            cycle_id=cycle_id,
            campaigns=campaigns,
            maximum_variants=args.maximum_variants,
        )
        payload = report.to_dict()
        payload["campaigns"] = [campaign.to_dict() for campaign in campaigns]
        destination = Path(args.report)
        report_root = (root / "data/reports").resolve()
        if report_root not in destination.resolve().parents:
            parser.error("research-cycle report must stay under data/reports")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        ledger.complete(family_id, cycle_id)
        print(json.dumps(payload, indent=2, sort_keys=True))
        raise SystemExit(0)

    if args.cmd == "validate-strategies":
        import hashlib
        import subprocess
        from pathlib import Path

        import pandas as pd

        from sensei.backtest.campaign import (
            LockedConfirmationLedger,
            run_validation_campaign,
            validation_campaign_id,
        )
        from sensei.backtest.playbook import all_strategies

        playbook_path = Path(args.playbook)
        playbook = json.loads(playbook_path.read_text(encoding="utf-8"))
        adopted_names = tuple(
            str(item["name"])
            for item in playbook.get("strategies", ())
            if item.get("adopted") is True
        )
        available = all_strategies()
        missing = sorted(set(adopted_names) - set(available))
        if not adopted_names:
            parser.error("playbook contains no adopted strategy evidence")
        if missing:
            parser.error(
                "adopted strategies have no executable rules: "
                + ", ".join(missing)
            )
        prices_path = Path(args.prices_dir)
        frames = {
            path.stem: pd.read_parquet(path)
            for path in sorted(prices_path.glob("*.parquet"))
        }
        root = Path(__file__).resolve().parents[2]
        git_status = subprocess.check_output(
            ("git", "status", "--porcelain=v1"), cwd=root, text=True
        )
        git_diff = subprocess.check_output(
            ("git", "diff", "--binary", "HEAD"), cwd=root
        )
        provenance = {
            "playbook_sha256": hashlib.sha256(playbook_path.read_bytes()).hexdigest(),
            "pyproject_sha256": hashlib.sha256(
                (root / "pyproject.toml").read_bytes()
            ).hexdigest(),
            "uv_lock_sha256": hashlib.sha256(
                (root / "uv.lock").read_bytes()
            ).hexdigest(),
            "git_head": subprocess.check_output(
                ("git", "rev-parse", "HEAD"), cwd=root, text=True
            ).strip(),
            "git_worktree_state_sha256": hashlib.sha256(
                git_status.encode() + git_diff
            ).hexdigest(),
        }
        selected = {name: available[name] for name in adopted_names}
        campaign_kwargs = dict(
            frames=frames,
            strategies=selected,
            folds=args.folds,
            cost_pct=args.cost_pct,
            progress=lambda name: print(
                f"validating {name}...", file=sys.stderr, flush=True
            ),
            provenance=provenance,
            locked_confirmation_consumed=args.consume_locked,
        )
        ledger = None
        registration_id = None
        if args.consume_locked:
            registration_id = validation_campaign_id(
                frames=frames,
                strategies=selected,
                folds=args.folds,
                cost_pct=args.cost_pct,
                provenance=provenance,
                locked_confirmation_consumed=True,
            )
            ledger = LockedConfirmationLedger(Path(args.locked_ledger))
            ledger.preregister(
                registration_id, registered_at=datetime.now(timezone.utc)
            )
        try:
            report = run_validation_campaign(**campaign_kwargs)
        except BaseException:
            if ledger is not None and registration_id is not None:
                ledger.consume(
                    registration_id,
                    consumed_at=datetime.now(timezone.utc),
                    status="FAILED_CONSUMED",
                )
            raise
        if ledger is not None and registration_id is not None:
            if report.campaign_id != registration_id:
                raise RuntimeError("locked registration identity changed during run")
            ledger.consume(
                registration_id,
                consumed_at=datetime.now(timezone.utc),
                status="COMPLETED",
            )
        destination = Path(args.report)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = report.to_dict()
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        raise SystemExit(0)

    if args.cmd == "replay-desk":
        import tempfile
        from pathlib import Path
        from sensei.automation import SchedulerApplicationConfig
        from sensei.runtime.production_replay import (
            complete_market_sessions,
            production_artifact_fingerprints,
            ProductionHistoricalDeskReplay,
        )

        config_path = Path(args.config)
        journal_path = Path(args.journal)
        config = SchedulerApplicationConfig.from_json(config_path)
        source_sessions = complete_market_sessions(
            prices_path=config.prices_path,
            required_sessions=args.sessions + 1,
            minimum_completeness=0.99,
        )

        def fingerprints():
            return production_artifact_fingerprints(
                config_path=config_path,
                journal_path=journal_path,
            )

        with tempfile.TemporaryDirectory(
            prefix="sensei-historical-desk-replay-"
        ) as workspace:
            report = ProductionHistoricalDeskReplay(
                source_config_path=config_path,
                rules_path=Path(args.rules),
                source_sessions=source_sessions,
                workspace=Path(workspace),
                production_fingerprints=fingerprints,
                capital=args.capital,
            ).run()
        payload = report.to_dict()
        if args.capital is None:
            import yaml
            effective_capital = float(
                yaml.safe_load(config.risk_path.read_text(encoding="utf-8"))["capital"]
            )
        else:
            effective_capital = args.capital
        payload["requested_capital"] = args.capital
        payload["effective_capital"] = effective_capital
        payload["replay_kind"] = (
            "CURRENT_PLAN_COUNTERFACTUAL_WITH_SIMULATION_ASSUMPTIONS"
        )
        payload["limitations"] = [
            (
                "SIMULATED_PAPER_AUTHORIZATION_WITHOUT_SHADOW_TRIAL; "
                "does not validate SHADOW-to-PAPER promotion"
            ),
            "neutral surveillance assumption; not historical NSE surveillance",
            "no historical earnings blackout calendar",
            "historical price paths only; current plans preregistered before replay",
        ]
        destination = Path(args.report)
        report_root = (Path(__file__).resolve().parents[2] / "data/reports").resolve()
        if report_root not in destination.resolve().parents:
            parser.error("replay report must stay under data/reports")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(payload, indent=2))
        raise SystemExit(0 if report.certified else 2)

    if args.cmd == "qualify-desk":
        from pathlib import Path
        from sensei.automation import SchedulerApplicationConfig
        from sensei.reporting.prelive import PreLiveCertifier
        from sensei.reporting.qualification import DeskQualificationRunner
        from sensei.runtime.rehearsal import PaperEntryRehearsal

        root = Path(__file__).resolve().parents[2]
        scheduler_config = SchedulerApplicationConfig.from_json(
            Path(args.config)
        )

        def current_runtime_check():
            rehearsal = PaperEntryRehearsal(
                journal_path=Path(args.journal),
                config_path=Path(args.config),
            ).run(as_of=datetime.now(timezone.utc)).to_dict()
            certification = PreLiveCertifier(
                journal_path=Path(args.journal),
                config_path=Path(args.config),
                playbook_path=scheduler_config.playbook_path,
                rehearsal_run=lambda: rehearsal,
            ).run()
            payload = certification.to_dict()
            diagnostics = rehearsal.get("diagnostics", {})
            roles = set(diagnostics.get("roles_completed", ()))
            levels = {
                item.get("level")
                for item in diagnostics.get("committee_verdicts", ())
            }
            command_kinds = set(
                diagnostics.get("gateway_command_kinds", ())
            )
            fresh_rehearsal_passed = (
                rehearsal.get("state") == "WOULD_TRADE"
                and rehearsal.get("production_state_unchanged") is True
                and {
                    "orchestrator", "historian", "reporter", "crowd-reader",
                    "analyst", "committee", "trader", "coach", "secretary",
                } <= roles
                and {"L1", "L2", "L3", "L4"} <= levels
                and {"ENTRY", "PROTECTION", "EXIT"} <= command_kinds
                and bool(diagnostics.get("closed_learning_episode_ids"))
            )
            blockers = list(certification.blockers)
            if not fresh_rehearsal_passed:
                blockers.append("fresh_production_rehearsal")
            passed = (
                certification.ready_for_unattended_paper
                and fresh_rehearsal_passed
            )
            payload["fresh_rehearsal_passed"] = fresh_rehearsal_passed
            payload["fresh_rehearsal"] = rehearsal
            return (
                passed,
                (
                    "current journal, 500 requested / configured eligible "
                    "symbol replay, and fresh isolated production composition "
                    "passed"
                    if passed else
                    "current runtime blockers: " + ", ".join(blockers)
                ),
                payload,
            )

        report = DeskQualificationRunner(
            repo_root=root,
            current_runtime_check=current_runtime_check,
        ).run()
        payload = report.to_dict()
        destination = Path(args.report)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(payload, indent=2))
        raise SystemExit(0 if report.passed else 2)

    if args.cmd == "prelive-certify":
        from pathlib import Path
        from sensei.reporting.prelive import PreLiveCertifier
        from sensei.runtime.rehearsal import PaperEntryRehearsal

        report = PreLiveCertifier(
            journal_path=Path(args.journal),
            rehearsal_path=Path(args.rehearsal),
            config_path=Path(args.config),
            trusted_market_data_manifest_ids=frozenset(
                args.trusted_market_data_manifest_id
            ),
            trusted_market_data_issuers=frozenset(
                args.trusted_market_data_issuer
            ),
            rehearsal_run=lambda: PaperEntryRehearsal(
                journal_path=Path(args.journal),
                config_path=Path(args.config),
            ).run(as_of=datetime.now(timezone.utc)).to_dict(),
        ).run()
        payload = report.to_dict()
        destination = Path(args.report)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(payload, indent=2))
        ready = (
            report.ready_for_unattended_paper
            if args.target == "paper"
            else report.ready_for_live_capital
        )
        raise SystemExit(0 if ready else 2)

    if args.cmd == "rehearse-entry":
        from pathlib import Path
        from sensei.runtime.rehearsal import PaperEntryRehearsal

        report = PaperEntryRehearsal(
            journal_path=Path(args.journal), config_path=Path(args.config),
        ).run(as_of=datetime.now(timezone.utc))
        payload = report.to_dict()
        destination = Path(args.report)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(payload, indent=2))
        return

    if args.cmd == "paper-readiness":
        from pathlib import Path
        from sensei.reporting.paper_readiness import build_readiness_report

        report = build_readiness_report(
            Path(args.journal), as_of=datetime.now(timezone.utc),
            config_path=Path(args.config),
        )
        print(json.dumps(report.to_dict(), indent=2))
        return

    if args.cmd == "backtest-audit":
        from pathlib import Path
        from sensei.backtest.playbook import load_current_playbook, all_strategies
        from sensei.data.store import available_symbols, load_prices
        from sensei.research.preliminary_audit import PortfolioConfig, audit_strategy

        pb = load_current_playbook()
        adopted = [a for a in pb["strategies"] if a["adopted"]]
        if args.strategy:
            adopted = [a for a in adopted if a["name"] == args.strategy]
        reg = all_strategies()
        frames = {}
        for s in available_symbols():
            try:
                df = load_prices(s)
                if len(df) >= 500:
                    frames[s] = df
            except Exception:
                pass
        cfg = PortfolioConfig(capital=args.capital, max_positions=args.max_positions)
        reports = []
        for a in adopted:
            spec = reg.get(a["name"])
            if spec is None:
                continue
            reports.append(audit_strategy(frames, spec["fn"], a["params"],
                                          name=a["name"], cfg=cfg, n_folds=args.folds))
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(reports, indent=2, default=str))
        print(json.dumps(reports, indent=2, default=str))
        return

    if args.cmd == "shadow-monitor":
        from pathlib import Path
        from sensei.reporting.shadow_monitor import run
        print(json.dumps(
            run(Path(args.journal), config_path=Path(args.config)),
            indent=2,
            default=str,
        ))
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
        from sensei.automation.liveness import (
            SchedulerAlreadyRunning, SchedulerLease, deployed_commit,
        )

        journal_path = Path(args.journal)
        try:
            now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
            if now.tzinfo is None:
                parser.error("--now must include a timezone offset")
            with SchedulerLease(
                heartbeat_path=journal_path.parent / "scheduler-heartbeat.json",
                lock_path=journal_path.parent / "scheduler.lock",
                deployed_commit=deployed_commit(),
            ):
                app = GovernedSchedulerApplication.open(
                    journal_path,
                    config_path=Path(args.config) if args.config else None,
                    wall_clock=lambda: datetime.now(timezone.utc),
                )
                result = app.run_once(now)
        except (SchedulerAlreadyRunning, SchedulerConfigurationError, ValueError) as exc:
            parser.error(str(exc))
        print(json.dumps(result.to_dict(), indent=2))
        return

    if args.cmd == "scheduler-health":
        from pathlib import Path
        from sensei.automation import SchedulerApplicationConfig
        from sensei.automation.liveness import SchedulerWatchdog, deployed_commit
        from sensei.automation.scheduling import SwingSessionPolicy

        try:
            config = SchedulerApplicationConfig.from_json(Path(args.config))
            report = SchedulerWatchdog(
                journal_path=Path(args.journal),
                heartbeat_path=Path(args.heartbeat), lock_path=Path(args.lock),
                expected_commit=deployed_commit(),
                policy=SwingSessionPolicy(closed_dates=config.closed_dates),
            ).inspect(now=datetime.now(timezone.utc))
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            payload = {
                "state": "OFFLINE",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "reason_codes": ["SCHEDULER_CONFIGURATION_INVALID"],
                "heartbeat": {}, "lock_held": False, "detail": str(exc),
            }
            print(json.dumps(payload, indent=2))
            raise SystemExit(2)
        print(json.dumps(report.to_dict(), indent=2))
        raise SystemExit(report.exit_code)

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
