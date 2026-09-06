"""Reproducible stock-development runs with explicit settings and input scope."""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
from importlib.metadata import version
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign
from sensei.data.stock_repair import MANIFEST_NAME, verify_repair_snapshot
from sensei.research.exposure import record_development_frames
from sensei.research.stock_evaluation import EvaluationProtocol, audit_stock_data, evaluate_stock_portfolio


@dataclass(frozen=True)
class StockRunSettings:
    name: str
    start: date
    end: date
    warmup_sessions: int
    strategy_name: str
    strategy_parameters: dict
    portfolio: PortfolioCampaignConfig
    evaluation: EvaluationProtocol
    prices_path: Path
    benchmark_path: Path
    benchmark_name: str
    output_directory: Path

    def __post_init__(self):
        if self.start > self.end:
            raise ValueError("start must not follow end")
        if type(self.warmup_sessions) is not int or self.warmup_sessions < 252:
            raise ValueError("at least 252 warmup sessions are required for shared ranking")
        if not self.name.strip() or not self.strategy_name.strip():
            raise ValueError("run and strategy names are required")
        if set(self.strategy_parameters) != {"stop_pct", "target_pct", "max_hold_days"}:
            raise ValueError("freeze stop_pct, target_pct and max_hold_days explicitly")

    def identity_payload(self):
        return json.loads(json.dumps(asdict(self), default=str))


def load_run_settings(path: Path, *, maximum_drawdown_pct: float | None = None) -> StockRunSettings:
    raw = json.loads(path.read_text())
    allowed = {"name", "start", "end", "warmup_sessions", "strategy_name", "strategy_parameters",
               "portfolio", "evaluation", "prices_path", "benchmark_path", "benchmark_name", "output_directory"}
    if not isinstance(raw, dict) or set(raw) != allowed:
        raise ValueError("run configuration must contain exactly the documented settings")
    for key in ("prices_path", "benchmark_path", "output_directory"):
        raw[key] = (path.resolve().parent / raw[key]).resolve()
    raw["start"], raw["end"] = date.fromisoformat(raw["start"]), date.fromisoformat(raw["end"])
    raw["portfolio"] = PortfolioCampaignConfig(**raw["portfolio"])
    raw["evaluation"] = EvaluationProtocol(**raw["evaluation"])
    if maximum_drawdown_pct is not None:
        raw["evaluation"] = replace(raw["evaluation"], maximum_drawdown_pct=maximum_drawdown_pct)
    return StockRunSettings(**raw)


def scope_price_frames(frames, *, start: date, end: date, warmup_sessions: int):
    """Restrict dates, preserving every instrument and all evaluation gaps."""
    scoped = {}
    for symbol, frame in frames.items():
        frame = frame.sort_index()
        preceding = frame.loc[frame.index.date < start].tail(warmup_sessions)
        window = frame.loc[(frame.index.date >= start) & (frame.index.date <= end)]
        scoped[symbol] = pd.concat((preceding, window))
    return scoped


def _frame_digest(frame):
    metadata = json.dumps({"columns": list(frame.columns), "dtypes": [str(v) for v in frame.dtypes]}, sort_keys=True)
    return hashlib.sha256(metadata.encode() + pd.util.hash_pandas_object(frame, index=True).values.tobytes()).hexdigest()


def _signal_identity(signal):
    from sensei.backtest.rulespec import RuleSpec

    captured = {}
    for key, value in inspect.getclosurevars(signal).nonlocals.items():
        if not isinstance(value, RuleSpec):
            raise ValueError("frozen runs require a declared RuleSpec for captured strategy state")
        captured[key] = value.model_dump(mode="json")
    module = inspect.getmodule(signal)
    if module is None:
        raise ValueError("signal implementation module is unavailable")
    return {"captured_rules": captured,
            "module_sha256": hashlib.sha256(inspect.getsource(module).encode()).hexdigest(),
            "function_sha256": hashlib.sha256(inspect.getsource(signal).encode()).hexdigest()}


def run_stock_development(settings: StockRunSettings, *, journal=None) -> Path:
    from sensei.backtest.playbook import all_strategies
    from sensei.backtest import portfolio_campaign, costs, daily_execution
    from sensei.execution import nse
    from sensei.strategy import selection
    from sensei.research import stock_evaluation

    strategies = all_strategies()
    if settings.strategy_name not in strategies:
        raise ValueError("unknown frozen strategy")
    repair_evidence = None
    if (settings.prices_path / MANIFEST_NAME).exists():
        repair_evidence = verify_repair_snapshot(settings.prices_path)
    original = {path.stem: pd.read_parquet(path) for path in sorted(settings.prices_path.glob("*.parquet"))}
    frames = scope_price_frames(original, start=settings.start, end=settings.end, warmup_sessions=settings.warmup_sessions)
    benchmark_frame = pd.read_parquet(settings.benchmark_path)
    if list(benchmark_frame.columns) != ["close"]:
        raise ValueError("benchmark must contain a single close column")
    benchmark = benchmark_frame.close
    benchmark_hash = hashlib.sha256(settings.benchmark_path.read_bytes()).hexdigest()
    benchmark_manifest_path = settings.benchmark_path.with_suffix(".manifest.json")
    benchmark_evidence = None
    if benchmark_manifest_path.exists():
        raw_manifest = benchmark_manifest_path.read_bytes()
        benchmark_evidence = json.loads(raw_manifest)
        if benchmark_evidence.get("parquet_sha256") != benchmark_hash:
            raise ValueError("benchmark does not match its capture manifest")
    record_development_frames(frames, campaign_id=settings.name, journal=journal)
    record_development_frames({"NIFTY500_TRI": benchmark_frame}, campaign_id=settings.name, journal=journal)
    spec = {**strategies[settings.strategy_name], **settings.strategy_parameters}
    implementation = "".join(inspect.getsource(module) for module in
        (portfolio_campaign, costs, daily_execution, nse, selection, stock_evaluation))
    identity = {"settings": settings.identity_payload(),
                "signal": _signal_identity(spec["fn"]),
                "runtime": {name: version(name) for name in ("numpy", "pandas", "pydantic")},
                "effective_charge_schedule": asdict(costs.IndianDeliveryChargeSchedule()),
                "effective_selection_policy": asdict(portfolio_campaign.SELECTION_POLICY),
                "input_frames": {symbol: _frame_digest(frame) for symbol, frame in sorted(frames.items())},
                "benchmark_sha256": benchmark_hash,
                "benchmark_manifest": benchmark_evidence,
                "repair_manifest": repair_evidence,
                "implementation_sha256": hashlib.sha256((implementation
                    + inspect.getsource(sys.modules[__name__])).encode()).hexdigest()}
    run_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    destination = settings.output_directory / run_id
    destination.mkdir(parents=True, exist_ok=True)
    report_path = destination / "report.json"
    manifest_path = destination / "manifest.json"
    report_hash_path = destination / "report.sha256"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("identity") != identity or manifest.get("run_id") != run_id:
            raise ValueError("frozen run manifest mismatch")
    if report_path.exists():
        if not manifest_path.exists():
            raise ValueError("cached report has no frozen manifest")
        if not report_hash_path.exists() or report_hash_path.read_text().strip() != hashlib.sha256(report_path.read_bytes()).hexdigest():
            raise ValueError("cached report integrity check failed")
        return report_path
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps({"run_id": run_id, "recorded_before_evaluation": datetime.now(timezone.utc).isoformat(),
            "identity": identity, "phase": "REUSED_HISTORY_DEVELOPMENT"}, indent=2) + "\n")
    audit = audit_stock_data(frames)
    if repair_evidence is not None:
        audit["repair"] = {key: repair_evidence[key] for key in
            ("snapshot_id", "removed_row_count", "instrument_count", "inserted_rows", "authority", "admissible", "unresolved")}
    calendar = pd.DatetimeIndex(sorted({stamp for frame in frames.values() for stamp in frame.index
                                       if settings.start <= stamp.date() <= settings.end}))
    expected = benchmark.index[(benchmark.index.date >= settings.start) & (benchmark.index.date <= settings.end)]
    audit["calendar"] = {"benchmark_sessions": len(expected), "portfolio_sessions": len(calendar),
                         "missing_from_all_stocks": [str(d.date()) for d in expected.difference(calendar)],
                         "absent_from_benchmark": [str(d.date()) for d in calendar.difference(expected)]}
    audit["coverage"] = {symbol: {
        "warmup_rows": int((frame.index.date < settings.start).sum()),
        "missing_during_observed_lifetime": [str(d.date()) for d in expected.difference(frame.index)
            if not frame.empty and frame.index.min() <= d <= frame.index.max()],
        "last_available": str(frame.index.max().date()) if not frame.empty else None,
    } for symbol, frame in frames.items()}
    payload = {"run_id": run_id, "settings": settings.identity_payload(), "data": audit,
               "decision": "DATA_BLOCKED", "authority": "RESEARCH_ONLY", "can_trade": False}
    blockers = [issue for issue in audit["content_issues"] if "invalid" in issue or issue == "empty_universe"]
    if not calendar.equals(expected) or expected.empty:
        blockers.append("portfolio_calendar_does_not_match_benchmark")
    if not blockers:
        try:
            campaign = run_portfolio_campaign(frames=frames, strategies={settings.strategy_name: spec},
                config=settings.portfolio, evaluation_start=pd.Timestamp(settings.start), evaluation_end=pd.Timestamp(settings.end))
        except ValueError as exc:
            blockers.append(str(exc))
        else:
            payload.update(evaluate_stock_portfolio(campaign=campaign, protocol=settings.evaluation,
                data_audit=audit, benchmark=benchmark, benchmark_name=settings.benchmark_name))
    payload["simulation_blockers"] = blockers
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    report_hash_path.write_text(hashlib.sha256(report_path.read_bytes()).hexdigest() + "\n")
    return report_path
