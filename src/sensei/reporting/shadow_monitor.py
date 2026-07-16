"""Passive daily shadow-trial monitor (owner-facing, read-only).

Runs after the EOD window and inspects ONLY recorded state:
  - journal integrity
  - ingestion completeness and exclusions
  - shadow observations accrued per plan
  - scheduler halt/error reasons
  - expected vs actual observation progress
  - lifecycle promotions

It never runs scheduler tasks, consumes work, promotes plans, or writes
to the journal. Its only outputs are a markdown report under
data/reports/ and a JSON summary on stdout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from sensei.operations import OperationalJournal

REPORTS_DIR = Path(__file__).resolve().parents[3] / "data" / "reports"

# Forward-only observations begin the first session AFTER plan registration.
SHADOW_START = date(2026, 7, 17)
MINIMUM_SESSIONS = 20          # mirrors ShadowTrialPolicy for expectation math
MINIMUM_SIGNALS = 30
MINIMUM_SIGNAL_INSTRUMENTS = 10


@dataclass
class MonitorReport:
    as_of: str
    journal_ok: bool = False
    events: int = 0
    ingestion: dict | None = None
    plans: list[dict] = field(default_factory=list)
    halts: list[dict] = field(default_factory=list)
    promotions: list[dict] = field(default_factory=list)
    expected_sessions: int = 0
    alerts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def _expected_sessions(as_of: date, closed_dates: frozenset[date] = frozenset()) -> int:
    """NSE weekday sessions in [SHADOW_START, as_of]; holidays via closed_dates."""
    n, d = 0, SHADOW_START
    while d <= as_of:
        if d.weekday() < 5 and d not in closed_dates:
            n += 1
        d += timedelta(days=1)
    return n


def build_report(journal_path: Path, as_of: date | None = None) -> MonitorReport:
    as_of = as_of or date.today()
    report = MonitorReport(as_of=as_of.isoformat())

    if not journal_path.is_file():
        report.alerts.append("ALERT: governed journal missing")
        return report

    journal = OperationalJournal(journal_path)
    verification = journal.verify()
    report.journal_ok = verification.ok
    report.events = verification.events_checked
    if not verification.ok:
        report.alerts.append("ALERT: journal integrity verification FAILED")
        return report

    plan_names: dict[str, str] = {}
    stages: dict[str, str] = {}
    observations: dict[str, int] = {}
    signals: dict[str, int] = {}
    signal_instruments: dict[str, set[str]] = {}
    latest_ingestion: dict | None = None

    for ev in journal.read_all():
        et = ev.event_type
        p = ev.payload
        if et == "StrategyPlanRegistered":
            plan_names[str(p["plan_id"])] = str(p.get("source_rule_name", "?"))
        elif et == "StrategyLifecycleTransitioned":
            pid = str(p["plan_version_id"])
            target = str(p["target_stage"])
            stages[pid] = target
            if target in ("paper", "canary", "active"):
                report.promotions.append(
                    {"plan": plan_names.get(pid, pid[:16]), "to": target,
                     "at": ev.occurred_at.isoformat()})
        elif et == "ShadowSessionObserved":
            pid = str(p["plan_id"])
            observations[pid] = observations.get(pid, 0) + 1
            from collections.abc import Mapping
            for ev_item in p.get("evaluations", ()):
                trace = ev_item.get("trace") if isinstance(ev_item, Mapping) else None
                if isinstance(trace, Mapping) and trace.get("action") == "enter_long":
                    signals[pid] = signals.get(pid, 0) + 1
                    signal_instruments.setdefault(pid, set()).add(
                        str(ev_item.get("instrument_id", "?")))
        elif et == "MarketDataIngestionCompleted":
            latest_ingestion = {
                "session": p.get("session"),
                "completeness": p.get("completeness"),
                "eligible": len(p.get("eligible_symbols", ())),
                "failed": list(p.get("failed_symbols", ())),
                "excluded": list(p.get("excluded_symbols", ())),
                "event_at": ev.occurred_at.isoformat(),
            }
        elif et == "SchedulerTaskHalted":
            report.halts.append({
                "task": p.get("task_id", "?"),
                "reasons": list(p.get("reason_codes", ())),
                "at": ev.occurred_at.isoformat(),
            })

    report.ingestion = latest_ingestion
    report.expected_sessions = _expected_sessions(as_of)

    for pid, name in sorted(plan_names.items(), key=lambda kv: kv[1]):
        obs = observations.get(pid, 0)
        report.plans.append({
            "name": name,
            "stage": stages.get(pid, "registered"),
            "observations": obs,
            "expected": report.expected_sessions,
            "signals": signals.get(pid, 0),
            "signal_instruments": len(signal_instruments.get(pid, ())),
            "sessions_remaining_minimum": max(0, MINIMUM_SESSIONS - obs),
        })

    # ---- alerts ----
    if latest_ingestion is None and report.expected_sessions > 0:
        report.alerts.append("ALERT: no market-data ingestion recorded yet")
    elif latest_ingestion is not None:
        comp = latest_ingestion.get("completeness")
        if comp is not None and comp < 0.99:
            report.alerts.append(f"ALERT: ingestion completeness {comp:.3f} < 0.99")
        if latest_ingestion.get("failed"):
            report.alerts.append(
                f"warn: failed symbols last ingestion: {latest_ingestion['failed'][:5]}")
    lag = [p for p in report.plans
           if p["stage"] == "shadow" and p["observations"] < report.expected_sessions]
    if lag and report.expected_sessions > 0:
        worst = min(lag, key=lambda p: p["observations"])
        report.alerts.append(
            f"ALERT: shadow observations lagging — {worst['name']} has "
            f"{worst['observations']}/{report.expected_sessions} expected sessions")
    recent_halts = [h for h in report.halts if h["at"][:10] == as_of.isoformat()]
    if recent_halts:
        report.alerts.append(
            f"ALERT: scheduler halts today: "
            f"{sorted({r for h in recent_halts for r in h['reasons']})}")
    if report.promotions:
        report.alerts.append(
            f"note: promotions recorded: "
            f"{[(p['plan'], p['to']) for p in report.promotions]}")
    return report


def render_markdown(r: MonitorReport) -> str:
    lines = [f"# Shadow-trial monitor — {r.as_of}", ""]
    lines.append(f"- Journal: {'OK' if r.journal_ok else 'FAILED'} ({r.events} events)")
    if r.ingestion:
        i = r.ingestion
        lines.append(f"- Ingestion (session {i['session']}): completeness "
                     f"{i['completeness']}, eligible {i['eligible']}, "
                     f"failed {len(i['failed'])}, excluded {i['excluded'] or 'none'}")
    lines.append(f"- Expected shadow sessions since {SHADOW_START}: {r.expected_sessions}")
    lines += ["", "## Plans", "",
              "| Plan | Stage | Obs / Expected | Signals | Instruments | Sessions to min |",
              "|---|---|---|---|---|---|"]
    for p in r.plans:
        lines.append(f"| {p['name']} | {p['stage']} | {p['observations']}/{p['expected']} "
                     f"| {p['signals']} | {p['signal_instruments']} "
                     f"| {p['sessions_remaining_minimum']} |")
    if r.halts:
        lines += ["", "## Halts (lifetime)", ""]
        for h in r.halts[-10:]:
            lines.append(f"- {h['at']} {h['task']}: {', '.join(h['reasons'])}")
    lines += ["", "## Alerts", ""]
    lines += [f"- {a}" for a in r.alerts] or ["- none"]
    lines.append("")
    return "\n".join(lines)


def run(journal_path: Path, as_of: date | None = None) -> dict:
    report = build_report(journal_path, as_of=as_of)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"shadow-monitor-{report.as_of}.md"
    out.write_text(render_markdown(report))
    payload = report.to_dict()
    payload["report_path"] = str(out)
    return payload
