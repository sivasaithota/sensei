"""Sensei's local, read-only trading control room."""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
IST = ZoneInfo("Asia/Kolkata")


def _json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _jsonl(path: Path, limit: int | None = None) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    if limit is not None:
        lines = lines[-limit:]
    result = []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def _positions() -> tuple[float, list[dict]]:
    state = _json(DATA_DIR / "paper" / "positions.json", {})
    return float(state.get("cash", 50_000)), list(state.get("positions", ()))


def _closed() -> list[dict]:
    return _jsonl(DATA_DIR / "paper" / "closed_trades.jsonl")


def _price_snapshot(symbol: str) -> tuple[float | None, str | None]:
    path = DATA_DIR / "prices" / f"{symbol}.parquet"
    if not path.is_file():
        return None, None
    try:
        import pandas as pd

        frame = pd.read_parquet(path, columns=["close"])
        if frame.empty:
            return None, None
        session = pd.Timestamp(frame.index[-1]).date().isoformat()
        return float(frame["close"].iloc[-1]), session
    except (OSError, KeyError, ValueError, TypeError):
        return None, None


def _audit_events(limit: int = 200) -> list[dict]:
    return _jsonl(DATA_DIR / "audit.jsonl", limit)


def _ledger() -> list[dict]:
    return _jsonl(DATA_DIR / "mistake_ledger.jsonl")


def _playbook() -> dict | None:
    value = _json(DATA_DIR / "playbook" / "current.json", None)
    return value if isinstance(value, dict) else None


def _kill_active() -> bool:
    return (DATA_DIR / "KILL").exists()


def _scheduler_config() -> dict:
    value = _json(CONFIG_DIR / "scheduler.json", {})
    return value if isinstance(value, dict) else {}


def _scheduler_liveness(now: datetime) -> dict:
    from sensei.automation import SchedulerApplicationConfig
    from sensei.automation.liveness import SchedulerWatchdog, deployed_commit
    from sensei.automation.scheduling import SwingSessionPolicy

    try:
        config = SchedulerApplicationConfig.from_json(
            CONFIG_DIR / "scheduler.json"
        )
        return SchedulerWatchdog(
            journal_path=DATA_DIR / "operations.sqlite3",
            heartbeat_path=DATA_DIR / "scheduler-heartbeat.json",
            lock_path=DATA_DIR / "scheduler.lock",
            expected_commit=deployed_commit(),
            policy=SwingSessionPolicy(closed_dates=config.closed_dates),
        ).inspect(now=now).to_dict()
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {
            "state": "OFFLINE", "checked_at": now.isoformat(),
            "reason_codes": ["SCHEDULER_HEALTH_UNAVAILABLE"],
            "heartbeat": {}, "lock_held": False, "detail": str(exc),
        }


def _minimum_completeness() -> float:
    return float(_scheduler_config().get("shadow_trial", {}).get(
        "minimum_data_completeness", 0.99
    ))


def _shadow_session_target() -> int:
    return int(_scheduler_config().get("shadow_trial", {}).get("minimum_sessions", 5))


def _display_time(value: datetime | str) -> str:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return parsed.astimezone(IST).strftime("%d %b · %H:%M IST")


def _governance_status() -> dict:
    journal_path = DATA_DIR / "operations.sqlite3"
    if not journal_path.is_file():
        return {
            "available": False, "plans": [], "alerts": ["Governed journal missing"],
            "timeline": [], "ingestion": None, "scheduler": None,
        }
    from sensei.operations import OperationalJournal

    journal = OperationalJournal.open_read_only(journal_path)
    verification = journal.verify()
    events = journal.read_all() if verification.ok else ()
    plans, stages, shadows, signal_counts = {}, {}, {}, {}
    scheduler = ingestion = None
    adopted = reconciled = False
    timeline = []
    for event in events:
        payload = event.payload
        if event.event_type == "StrategyPlanRegistered":
            plans[str(payload["plan_id"])] = str(payload["source_rule_name"])
        elif event.event_type == "StrategyLifecycleTransitioned":
            stages[str(payload["plan_version_id"])] = str(payload["target_stage"])
        elif event.event_type == "ShadowSessionObserved":
            plan_id = str(payload["plan_id"])
            shadows[plan_id] = shadows.get(plan_id, 0) + 1
            evaluations = payload.get("evaluations", ())
            observed_signals = sum(
                1 for item in evaluations
                if isinstance(item, Mapping)
                and isinstance(item.get("trace"), Mapping)
                and item["trace"].get("action") == "enter_long"
            )
            signal_counts[plan_id] = signal_counts.get(plan_id, 0) + int(
                payload.get("signal_count", observed_signals)
            )
        elif event.event_type == "MarketDataIngestionCompleted":
            ingestion = event
        elif event.event_type in {"SchedulerTaskCompleted", "SchedulerTaskHalted"}:
            scheduler = event
        elif event.event_type == "LegacyPaperPositionsAdopted":
            adopted = True
        elif event.event_type == "LegacyPaperPositionsReconciled":
            reconciled = True
        if event.event_type in {
            "SchedulerTaskCompleted", "SchedulerTaskHalted",
            "MarketDataIngestionCompleted", "StrategyLifecycleTransitioned",
            "ShadowSessionObserved",
        }:
            timeline.append({
                "type": event.event_type,
                "occurred_at": event.occurred_at.isoformat(),
                "occurred_at_display": _display_time(event.occurred_at),
                "reason_codes": list(payload.get("reason_codes", ())),
                "session": payload.get("session"),
            })
    alerts = []
    if not verification.ok:
        alerts.append("Operational journal integrity failed")
    if scheduler is not None and scheduler.event_type == "SchedulerTaskHalted":
        alerts.append("Latest scheduler task halted")
    if adopted and not reconciled:
        alerts.append("Legacy positions adopted but not reconciled")
    ingestion_model = None if ingestion is None else {
        "session": ingestion.payload.get("session"),
        "completeness": float(ingestion.payload.get("completeness", 0)),
        "eligible_count": len(ingestion.payload.get("eligible_symbols", ())),
        "failed_symbols": list(ingestion.payload.get("failed_symbols", ())),
        "excluded_symbols": list(ingestion.payload.get("excluded_symbols", ())),
        "occurred_at": ingestion.occurred_at.isoformat(),
    }
    scheduler_model = None if scheduler is None else {
        "state": scheduler.event_type.removeprefix("SchedulerTask").upper(),
        "occurred_at": scheduler.occurred_at.isoformat(),
        "occurred_at_display": _display_time(scheduler.occurred_at),
        "reason_codes": list(scheduler.payload.get("reason_codes", ())),
        "task_kind": scheduler.payload.get("task_kind", "scheduler task"),
    }
    strategy_models = [
        {
            "name": name,
            "plan_id": plan_id,
            "stage": stages.get(plan_id, "registered"),
            "shadow_sessions": shadows.get(plan_id, 0),
            "shadow_target": _shadow_session_target(),
            "signals": signal_counts.get(plan_id, 0),
        }
        for plan_id, name in sorted(plans.items(), key=lambda item: item[1])
    ]
    return {
        "available": True, "journal_ok": verification.ok,
        "events": verification.events_checked, "plans": strategy_models,
        "strategies": strategy_models, "scheduler": scheduler_model,
        "ingestion": ingestion_model, "positions_adopted": adopted,
        "positions_reconciled": reconciled, "alerts": alerts,
        "timeline": list(reversed(timeline[-12:])),
    }


def _position_model(position: dict, *, expected_session: str | None) -> dict:
    entry = float(position["entry_price"])
    quantity = int(position["quantity"])
    stop = float(position["stop_loss"])
    targets = position.get("targets") or []
    target = float(targets[0]) if targets else None
    mark, data_session = _price_snapshot(str(position["symbol"]))
    sign = -1 if str(position.get("direction", "BUY")).upper() == "SELL" else 1
    pnl = None if mark is None else sign * (mark - entry) * quantity
    sessions_held = int(position.get("sessions_held", 1))
    max_hold = int(position.get("max_hold_days", 0))
    remaining = max(0, max_hold - sessions_held) if max_hold else None
    stop_distance = ((mark - stop) / mark * 100) if mark else None
    target_distance = ((target - mark) / mark * 100) if mark and target else None
    parts = [f"Stop ₹{stop:,.2f}"]
    if target is not None:
        parts.append(f"Target ₹{target:,.2f}")
    if remaining is not None:
        parts.append(f"Time exit in {remaining} sessions")
    return {
        **position, "mark": mark, "data_session": data_session,
        "unrealized_pnl": None if pnl is None else round(pnl, 2),
        "unrealized_pct": None if mark is None else round((mark - entry) / entry * sign * 100, 2),
        "market_value": None if mark is None else round(mark * quantity, 2),
        "stop_distance_pct": None if stop_distance is None else round(stop_distance, 2),
        "target": target,
        "target_distance_pct": None if target_distance is None else round(target_distance, 2),
        "sessions_remaining": remaining, "exit_plan": " · ".join(parts),
        "mark_state": (
            "MISSING" if data_session is None else
            "STALE" if expected_session and data_session < expected_session else
            "CURRENT"
        ),
    }


def _promotion_eta(sessions_done: int, target: int, now: datetime) -> str | None:
    """Expected PAPER-eligibility date given remaining forward sessions."""
    remaining = target - sessions_done
    if remaining <= 0:
        return None
    closed = {date.fromisoformat(v)
              for v in _scheduler_config().get("closed_dates", ())}
    d = now.astimezone(IST).date()
    # today's session counts only if the EOD hasn't happened yet
    if now.astimezone(IST).time() >= time(18, 30):
        d += timedelta(days=1)
    counted = 0
    while counted < remaining:
        if d.weekday() < 5 and d not in closed:
            counted += 1
            if counted == remaining:
                break
        d += timedelta(days=1)
    return d.strftime("%a %d %b")


def _next_scheduled_action(now: datetime) -> dict:
    local = now.astimezone(IST)
    closed = {
        date.fromisoformat(value)
        for value in _scheduler_config().get("closed_dates", ())
    }

    def trading_day(value: date) -> bool:
        return value.weekday() < 5 and value not in closed

    candidate = local.date()
    if trading_day(candidate) and local.time() < time(9, 20):
        label, at = "Entry session", time(9, 20)
    elif trading_day(candidate) and local.time() < time(18, 30):
        label, at = "End-of-day session", time(18, 30)
    elif trading_day(candidate) and local.time() < time(19, 30):
        label, at = "Passive shadow monitor", time(19, 30)
    else:
        candidate += timedelta(days=1)
        while not trading_day(candidate):
            candidate += timedelta(days=1)
        label, at = "Entry session", time(9, 20)
    scheduled = datetime.combine(candidate, at, tzinfo=IST)
    return {
        "label": label, "at": scheduled.isoformat(),
        "when": scheduled.strftime("%a %d %b · %H:%M IST"),
    }


def dashboard_model(*, now: datetime | None = None) -> dict:
    now = now or datetime.now().astimezone()
    cash, raw_positions = _positions()
    governance = _governance_status()
    ingestion = governance.get("ingestion")
    expected_session = ingestion.get("session") if ingestion else None
    positions = [
        _position_model(position, expected_session=expected_session)
        for position in raw_positions
    ]
    closed = _closed()
    realized = sum(float(trade.get("pnl", 0)) for trade in closed)
    unrealized = sum(
        position["unrealized_pnl"] for position in positions
        if position["unrealized_pnl"] is not None
    )
    invested = sum(float(position["entry_price"]) * int(position["quantity"])
                   for position in positions)
    market_value = sum(
        position["market_value"] for position in positions
        if position["market_value"] is not None
    )
    alerts = list(governance.get("alerts", ()))
    if _kill_active():
        alerts.insert(0, "Kill switch active — new trading is halted")
    missing = [p["symbol"] for p in positions if p["mark_state"] == "MISSING"]
    stale = [p["symbol"] for p in positions if p["mark_state"] == "STALE"]
    if missing:
        alerts.append("Missing market marks: " + ", ".join(missing))
    if stale:
        alerts.append("Stale market marks: " + ", ".join(stale))
    if ingestion and ingestion["completeness"] < _minimum_completeness():
        alerts.append(
            f'Market ingestion is {ingestion["completeness"]:.1%}; '
            f'policy requires {_minimum_completeness():.1%}'
        )
    from sensei.reporting.paper_readiness import build_readiness_report
    readiness = build_readiness_report(
        DATA_DIR / "operations.sqlite3", as_of=now,
        config_path=CONFIG_DIR / "scheduler.json",
        kill_switch_path=DATA_DIR / "KILL",
    ).to_dict()
    return {
        "as_of": now.astimezone(IST).isoformat(),
        "mode": "PAPER", "kill_active": _kill_active(), "alerts": alerts,
        "summary": {
            "equity": round(cash + market_value, 2), "cash": round(cash, 2),
            "invested": round(invested, 2), "market_value": round(market_value, 2),
            "unrealized": round(unrealized, 2), "realized": round(realized, 2),
            "open_positions": len(positions), "closed_trades": len(closed),
            "unpriced_positions": sum(p["market_value"] is None for p in positions),
        },
        "positions": positions, "closed": list(reversed(closed[-20:])),
        "strategies": governance.get("strategies", ()), "operations": governance,
        "next_action": _next_scheduled_action(now),
        "playbook": _playbook(), "verdicts": [
            event for event in reversed(_audit_events()) if event.get("event") == "verdict"
        ][:12],
        "mistakes": _ledger()[-8:],
        "readiness": readiness,
        "rehearsal": _json(
            DATA_DIR / "reports" / "entry-rehearsal-latest.json", None
        ),
        "scheduler_liveness": _scheduler_liveness(now),
    }


def _e(value) -> str:
    return html.escape(str(value))


def _money(value: float, signed: bool = False) -> str:
    sign = "+" if signed and value >= 0 else ""
    return f"{sign}₹{value:,.0f}"


def _tone(value: float) -> str:
    return "positive" if value >= 0 else "negative"


def _status_label(model: dict) -> tuple[str, str]:
    if model["kill_active"]:
        return "Trading halted", "danger"
    if model["alerts"]:
        return "Attention needed", "warn"
    scheduler = model["operations"].get("scheduler")
    if scheduler and scheduler["state"] == "COMPLETED":
        return "Desk operational", "good"
    return "Desk observing", "neutral"


def _svg_equity(closed: list[dict], capital: float = 50_000.0) -> str:
    points = [capital]
    for trade in sorted(closed, key=lambda t: str(t.get("closed", ""))):
        points.append(points[-1] + float(trade.get("pnl", 0)))
    if len(points) < 2:
        return '<p class="quiet-note">Equity curve appears after the first closed trade.</p>'
    w, h, pad = 560, 120, 8
    lo, hi = min(points), max(points)
    rng = (hi - lo) or 1.0
    step = (w - 2 * pad) / (len(points) - 1)
    pts = " ".join(
        f"{pad + i * step:.1f},{h - pad - (v - lo) / rng * (h - 2 * pad):.1f}"
        for i, v in enumerate(points))
    color = "var(--green)" if points[-1] >= points[0] else "var(--red)"
    return (f'<svg viewBox="0 0 {w} {h}" class="equity-curve" role="img" '
            f'aria-label="Realized equity curve">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" '
            f'stroke-width="2" stroke-linejoin="round"/></svg>')


def _risk_meter(position: dict) -> str:
    """Where the mark sits between stop (0%) and target (100%)."""
    mark, stop, target = position["mark"], float(position["stop_loss"]), position["target"]
    if mark is None or target is None or target <= stop:
        return ""
    frac = max(0.0, min(1.0, (mark - stop) / (target - stop)))
    entry_frac = max(0.0, min(1.0, (float(position["entry_price"]) - stop) / (target - stop)))
    tone = "meter-danger" if frac < 0.2 else "meter-ok"
    return (f'<div class="risk-meter" title="stop → target">'
            f'<span class="rm-label">stop</span>'
            f'<div class="rm-track"><i class="rm-entry" style="left:{entry_frac*100:.1f}%"></i>'
            f'<b class="rm-mark {tone}" style="left:{frac*100:.1f}%"></b></div>'
            f'<span class="rm-label">target</span></div>')


def render(path: str = "/") -> str:
    model = dashboard_model()
    summary = model["summary"]
    status, status_tone = _status_label(model)
    ingestion = model["operations"].get("ingestion")
    scheduler = model["operations"].get("scheduler")
    next_action = model["next_action"]
    readiness = model["readiness"]
    rehearsal = model["rehearsal"]
    liveness = model["scheduler_liveness"]
    alerts = "".join(
        f'<div class="alert"><span>!</span><div>{_e(message)}</div></div>'
        for message in model["alerts"]
    ) or '<div class="quiet-note">No active operational alerts.</div>'
    readiness_checks = "".join(
        f'<li class="readiness-check {"pass" if check["passed"] else "fail"}">'
        f'<i>{"✓" if check["passed"] else "!"}</i><div><strong>{_e(check["label"])}</strong>'
        f'<small>{_e(check["detail"])}</small></div></li>'
        for check in readiness["checks"]
    )
    readiness_html = f'''
      <article class="panel readiness-panel {readiness["state"].lower()}">
        <div class="section-head"><div><p class="eyebrow">Pre-flight certificate</p>
          <h2>{"READY FOR PAPER ENTRY" if readiness["state"] == "READY" else "BLOCKED FROM PAPER ENTRY"}</h2></div>
          <span>{_e(readiness["state"])}</span></div>
        <p class="readiness-next">Next entry window · {_e(_display_time(readiness["next_entry_at"]))}</p>
        <ul class="readiness-list">{readiness_checks}</ul>
      </article>'''
    rehearsal_diagnostics = (
        rehearsal.get("diagnostics", {}) if isinstance(rehearsal, dict) else {}
    )
    rehearsal_intent = rehearsal_diagnostics.get("intent") or {}
    proposed_trade = "No executable trade intent reached risk admission"
    if rehearsal_intent:
        proposed_trade = (
            f'{rehearsal_intent.get("instrument_id", "?")} · '
            f'{rehearsal_intent.get("quantity", 0)} shares · entry '
            f'₹{int(rehearsal_intent.get("limit_price_paise", 0)) / 100:,.2f} · '
            f'stop ₹{int(rehearsal_intent.get("stop_price_paise", 0)) / 100:,.2f} · '
            f'target ₹{int(rehearsal_intent.get("target_price_paise", 0)) / 100:,.2f}'
        )
    rehearsal_verdicts = "".join(
        f'<li><b>{_e(item.get("level", "?"))} · {_e(item.get("agent", "?"))}</b> '
        f'{"approved" if item.get("approved") else "vetoed"} — '
        f'{_e(item.get("reasoning", "No reason recorded"))}</li>'
        for item in rehearsal_diagnostics.get("committee_verdicts", ())
    ) or '<li>No committee stage was reached.</li>'
    rehearsal_html = (
        '<article class="panel"><div class="section-head"><div><p class="eyebrow">Entry rehearsal</p>'
        '<h2>No rehearsal recorded</h2></div></div><p class="quiet-note">Run <span class="mono">sensei rehearse-entry</span> to exercise the disposable production path.</p></article>'
        if not isinstance(rehearsal, dict) else f'''
        <article class="panel rehearsal {str(rehearsal.get("state", "BLOCKED")).lower()}">
          <div class="section-head"><div><p class="eyebrow">Entry rehearsal</p>
            <h2>{_e(rehearsal.get("state", "BLOCKED").replace("_", " "))}</h2></div>
            <span>NO REAL ORDER</span></div>
          <p>{_e(rehearsal.get("detail", "No diagnostic detail"))}</p>
          <p class="rehearsal-proposal"><b>Proposed trade</b> {_e(proposed_trade)}</p>
          <div class="rehearsal-facts"><span><b>{_e(", ".join(rehearsal.get("reason_codes", ())) or "none")}</b> outcome</span>
            <span><b>{int(rehearsal.get("sandbox_events_added", 0))}</b> sandbox events</span>
            <span><b>{int(rehearsal_diagnostics.get("risk_reservations", 0))}</b> risk reservations</span>
            <span><b>{len(rehearsal_diagnostics.get("committee_verdicts", ()))}</b> committee verdicts</span>
            <span><b>{int(rehearsal_diagnostics.get("sandbox_gateway_commands", 0))}</b> sandbox gateway commands</span>
            <span><b>{0 if rehearsal.get("production_state_unchanged") else "!"}</b> production changes</span></div>
          <details><summary>Committee and risk trace</summary><ul class="rehearsal-trace">{rehearsal_verdicts}</ul>
            <p>Risk outcome: {_e(rehearsal.get("detail", "No risk outcome"))}</p></details>
          <small>Evaluated {_e(_display_time(rehearsal.get("as_of")))} · effective window {_e(_display_time(rehearsal.get("effective_entry_at"))) if rehearsal.get("effective_entry_at") else "unavailable"}</small>
        </article>'''
    )
    heartbeat = liveness.get("heartbeat", {})
    liveness_reasons = ", ".join(liveness.get("reason_codes", ())) or "No active liveness faults"
    liveness_html = f'''
      <article class="panel liveness {str(liveness.get("state", "OFFLINE")).lower()}">
        <div class="section-head"><div><p class="eyebrow">Deployment watchdog</p>
          <h2>Scheduler {_e(liveness.get("state", "OFFLINE"))}</h2></div>
          <span>{"LOCKED · RUNNING" if liveness.get("lock_held") else _e(heartbeat.get("phase", "NO HEARTBEAT"))}</span></div>
        <p>{_e(liveness_reasons)}</p>
        <div class="rehearsal-facts"><span><b>{_e(heartbeat.get("hostname", "unknown"))}</b> host</span>
          <span><b>{_e(str(heartbeat.get("deployed_commit", "unknown"))[:12])}</b> deployed commit</span>
          <span><b>{_e(heartbeat.get("timezone", "unknown"))}</b> timezone</span>
          <span><b>{_e(_display_time(heartbeat["observed_at"]) if heartbeat.get("observed_at") else "never")}</b> last wake</span></div>
        <small>Passive only · missed entry windows are reported, never retried.</small>
      </article>'''

    position_cards = []
    for position in model["positions"]:
        priced = position["mark"] is not None
        target_text = (
            "No target" if position["target"] is None else
            "Unavailable" if not priced else
            f'{position["target_distance_pct"]:+.1f}% away'
        )
        data_text = position["data_session"] or "mark unavailable"
        mark_warning = (
            f'<span class="mark-warning">{_e(position["mark_state"])}</span>'
            if position["mark_state"] != "CURRENT" else ""
        )
        pnl_text = "Unavailable" if not priced else _money(position["unrealized_pnl"], True)
        pnl_pct = "No current valuation" if not priced else f'{position["unrealized_pct"]:+.2f}%'
        mark_text = "—" if not priced else f'₹{position["mark"]:,.2f}'
        stop_buffer = "Unavailable" if not priced else f'{position["stop_distance_pct"]:.1f}%'
        position_cards.append(f'''
        <article class="position-card">
          <div class="position-head">
            <div><span class="symbol">{_e(position["symbol"])}</span>
              <span class="pill">{_e(position.get("direction", "BUY"))} · {position["quantity"]} shares</span></div>
            <div class="pnl {'muted' if not priced else _tone(position["unrealized_pnl"])}">{pnl_text}
              <small>{pnl_pct}</small></div>
          </div>
          <div class="price-grid">
            <div><label>Entry</label><strong>₹{position["entry_price"]:,.2f}</strong></div>
            <div><label>Latest mark {mark_warning}</label><strong>{mark_text}</strong><small>{_e(data_text)}</small></div>
            <div><label>Stop buffer</label><strong>{stop_buffer}</strong><small>stop ₹{position["stop_loss"]:,.2f}</small></div>
            <div><label>Target</label><strong>{_e(target_text)}</strong><small>{'—' if position['target'] is None else f'₹{position["target"]:,.2f}'}</small></div>
          </div>
          {_risk_meter(position)}
          <div class="exit-strip"><span>Exit plan</span><strong>{_e(position["exit_plan"])}</strong></div>
          <details><summary>Why this position is open</summary><p>{_e(position.get("narrative", "No thesis narrative recorded."))}</p></details>
        </article>''')
    positions_html = "".join(position_cards) or '<div class="empty">No open positions.</div>'

    strategy_cards = []
    now_dt = datetime.now().astimezone()
    for strategy in model["strategies"]:
        progress = min(100, strategy["shadow_sessions"] / strategy["shadow_target"] * 100)
        eta = (_promotion_eta(strategy["shadow_sessions"], strategy["shadow_target"], now_dt)
               if strategy["stage"] == "shadow" else None)
        eta_text = (f' · PAPER-eligible ~{eta}' if eta else
                    '' if strategy["stage"] != "shadow" else ' · eligibility pending')
        strategy_cards.append(f'''
        <article class="strategy-row">
          <div><strong>{_e(strategy["name"].replace("_", " "))}</strong><small class="mono">{_e(strategy["plan_id"][:18])}…</small></div>
          <span class="stage">{_e(strategy["stage"]).upper()}</span>
          <div class="progress-wrap"><div class="progress"><i style="width:{progress:.0f}%"></i></div>
            <small>{strategy["shadow_sessions"]} / {strategy["shadow_target"]} sessions · {strategy["signals"]} signals{_e(eta_text)}</small></div>
        </article>''')
    strategies_html = "".join(strategy_cards) or '<div class="empty">No governed strategies registered.</div>'

    timeline = "".join(f'''
      <li><i></i><div><strong>{_e(item["type"].replace("SchedulerTask", "Scheduler ").replace("MarketData", "Market data ").replace("ShadowSession", "Shadow session "))}</strong>
      <small>{_e(item["occurred_at_display"])}</small>
      <p>{_e(", ".join(item["reason_codes"]) or item.get("session") or "Recorded successfully")}</p></div></li>'''
      for item in model["operations"].get("timeline", ())) or '<li class="empty">No operational events yet.</li>'

    ingestion_bad = bool(
        ingestion and ingestion["completeness"] < _minimum_completeness()
    )
    failed_preview = [] if not ingestion else ingestion["failed_symbols"][:5]
    excluded_preview = [] if not ingestion else ingestion["excluded_symbols"][:5]
    ingestion_html = '<span class="muted">No ingestion recorded</span>' if not ingestion else f'''
      <div class="ingestion-health {'bad' if ingestion_bad else 'good'}">
        <strong>{ingestion["completeness"]:.1%}</strong><span>complete</span>
        <small>{ingestion["eligible_count"]} eligible · {len(ingestion["failed_symbols"])} failed · session {_e(ingestion["session"])}</small>
        <p><b>Failed ({len(ingestion["failed_symbols"])})</b> {_e(", ".join(failed_preview) or "None")}{"…" if len(ingestion["failed_symbols"]) > 5 else ""}</p>
        <p><b>Excluded ({len(ingestion["excluded_symbols"])})</b> {_e(", ".join(excluded_preview) or "None")}{"…" if len(ingestion["excluded_symbols"]) > 5 else ""}</p>
        <details><summary>Complete symbol detail</summary><p>{_e(", ".join(ingestion["failed_symbols"] + ingestion["excluded_symbols"]) or "No failures or exclusions")}</p></details>
      </div>'''
    scheduler_html = "No scheduler result" if not scheduler else (
        f'{_e(scheduler["state"])} · {_e(scheduler["task_kind"])} · '
        f'{_e(scheduler["occurred_at_display"])}'
    )

    verdict_rows = "".join(f'''
      <article class="verdict {'approved' if v.get('approved') else 'vetoed'}">
        <div class="verdict-head"><span class="verdict-badge">{'✓ APPROVED' if v.get('approved') else '✕ VETO'}</span>
          <strong>{_e(v.get('level', '?'))} · {_e(v.get('agent', '?'))}</strong>
          <small>{_e(str(v.get('thesis_id', ''))[:22])} · {_e(str(v.get('ts', ''))[:16])}</small></div>
        <p>{_e(str(v.get('reasoning', ''))[:340])}{'…' if len(str(v.get('reasoning', ''))) > 340 else ''}</p>
      </article>''' for v in model["verdicts"]) or '<div class="empty">No committee verdicts recorded yet.</div>'

    mistake_items = "".join(
        f'<li><p>{_e(m.get("pattern", ""))}</p><small class="mono">{_e(m.get("thesis_id", ""))} · {_e(str(m.get("ts", ""))[:10])}</small></li>'
        for m in reversed(model["mistakes"])
    ) or '<li class="empty">No repeated mistake patterns logged — the ledger fills as the Coach reviews closed trades.</li>'

    closed_rows = "".join(f'''<tr><td><strong>{_e(trade.get("symbol", "—"))}</strong></td>
      <td>{_e(trade.get("closed", "—"))}</td><td>{_e(trade.get("exit_reason", "—"))}</td>
      <td class="num {_tone(float(trade.get('pnl', 0)))}">{_money(float(trade.get("pnl", 0)), True)}</td></tr>'''
      for trade in model["closed"]) or '<tr><td colspan="4" class="empty">No closed trades yet.</td></tr>'
    valuation_complete = summary["unpriced_positions"] == 0
    cash_share = (
        f'{summary["cash"] / summary["equity"]:.0%} of equity'
        if valuation_complete and summary["equity"] > 0 else "Percentage unavailable"
    )
    exposure_value = _money(summary["market_value"]) if valuation_complete else "Unavailable"
    exposure_note = (
        f'{summary["open_positions"]} positions'
        if valuation_complete else f'Cost basis {_money(summary["invested"])}'
    )
    unrealized_value = _money(summary["unrealized"], True) if valuation_complete else "Unavailable"
    unrealized_note = (
        f'Realized {_money(summary["realized"], True)}'
        if valuation_complete else "One or more holdings are unpriced"
    )

    # ---- playbook evidence table (Research page) ----
    pb = model["playbook"] or {}
    pb_rows = "".join(f'''<tr><td><strong>{_e(s["name"].replace("_", " "))}</strong><br>
      <small class="mono muted">{_e(s.get("source", "seed strategy"))}</small></td>
      <td><span class="stage {'stage-adopted' if s.get('adopted') else 'stage-muted'}">{'ADOPTED' if s.get('adopted') else 'rejected'}</span></td>
      <td class="num">{s["out_of_sample"].get("trades", 0):,}</td>
      <td class="num {_tone(s["out_of_sample"].get("expectancy_pct", 0))}">{s["out_of_sample"].get("expectancy_pct", 0):+.2f}%</td>
      <td class="num">{s["out_of_sample"].get("hit_rate", 0):.0%}</td></tr>'''
      for s in sorted(pb.get("strategies", ()),
                      key=lambda s: (-bool(s.get("adopted")),
                                     -s["out_of_sample"].get("expectancy_pct", 0)))
    ) or '<tr><td colspan="5" class="empty">No playbook evidence.</td></tr>'
    playbook_html = f'''<div class="section-title"><div><p class="eyebrow">Historical evidence</p><h2>Signal playbook</h2></div>
      <p>Out-of-sample verdicts over ~30 years of NSE data · version {_e(pb.get("version", "—"))} · universe {pb.get("universe_size", "—")}</p></div>
      <article class="panel"><table><thead><tr><th>Strategy · source</th><th>Verdict</th><th class="num">OOS trades</th><th class="num">Expectancy</th><th class="num">Hit rate</th></tr></thead>
      <tbody>{pb_rows}</tbody></table></article>'''

    # ---- page composition ----
    hero = f'''<section class="hero"><div><p class="eyebrow">Trading control room</p><h1>Know what the desk is doing.<br><span>Understand why.</span></h1>
    <p class="lede">A read-only command view of capital, exit risk, governed strategies and unattended operations.</p></div>
    <div class="hero-side"><div class="desk-state {status_tone}"><i></i><div><small>Desk state</small><strong>{_e(status)}</strong><span>Updated {_e(model["as_of"][11:19])} IST</span></div></div>
      <div class="next-action"><small>Next scheduled action</small><strong>{_e(next_action["label"])}</strong><span>{_e(next_action["when"])}</span></div></div></section>'''
    statebar = f'''<section class="statebar"><div class="desk-state {status_tone}"><i></i><div><small>Desk state</small><strong>{_e(status)}</strong><span>Updated {_e(model["as_of"][11:19])} IST</span></div></div>
      <div class="next-action"><small>Next scheduled action</small><strong>{_e(next_action["label"])}</strong><span>{_e(next_action["when"])}</span></div></section>'''

    pages = {
        "/": ("Desk", f'''{hero}{readiness_html}
  <section class="metrics">
    <article><label>Marked equity</label><strong>{_money(summary["equity"])}</strong><span>Cash + priced holdings · {summary["unpriced_positions"]} unpriced</span></article>
    <article><label>Cash available</label><strong>{_money(summary["cash"])}</strong><span>{cash_share}</span></article>
    <article><label>Open exposure</label><strong>{exposure_value}</strong><span>{exposure_note}</span></article>
    <article><label>Unrealized P&amp;L</label><strong class="{'muted' if not valuation_complete else _tone(summary['unrealized'])}">{unrealized_value}</strong><span>{unrealized_note}</span></article>
  </section>
  <section class="two-col"><article class="panel"><div class="section-head"><div><p class="eyebrow">Attention</p><h2>What needs watching</h2></div><span>{len(model["alerts"])} active</span></div>{alerts}</article>
    <article class="panel ingestion"><div class="section-head"><div><p class="eyebrow">Market data</p><h2>Latest ingestion</h2></div></div>{ingestion_html}</article></section>
  <section id="positions"><div class="section-title"><div><p class="eyebrow">Risk first</p><h2>Position &amp; exit command center</h2></div><p>Every holding shows the mechanical path out—not just the path in.</p></div>{positions_html}</section>'''),
        "/research": ("Research", f'''{statebar}
  <section id="strategies"><div class="section-title"><div><p class="eyebrow">Governed research</p><h2>Strategy control room</h2></div><p>Known strategies are not tradable until evidence earns authorization.</p></div><div class="panel strategy-list">{strategies_html}</div></section>
  <section id="playbook">{playbook_html}</section>'''),
        "/operations": ("Operations", f'''{statebar}<div class="two-col">{liveness_html}{rehearsal_html}</div>
  <section id="operations" class="ops-grid"><article class="panel"><div class="section-head"><div><p class="eyebrow">Automation</p><h2>Operations timeline</h2></div></div><p class="scheduler-line">{scheduler_html}</p><ol class="timeline" tabindex="0" aria-label="Scrollable operations timeline">{timeline}</ol></article>
    <article class="panel"><div class="section-head"><div><p class="eyebrow">Outcomes</p><h2>Recently closed</h2></div></div>{_svg_equity(model["closed"])}<table><thead><tr><th>Symbol</th><th>Closed</th><th>Reason</th><th class="num">P&amp;L</th></tr></thead><tbody>{closed_rows}</tbody></table>
      <div class="integrity"><span>Journal integrity</span><strong>{'Verified' if model['operations'].get('journal_ok') else 'Unavailable'}</strong><small>{model['operations'].get('events', 0)} immutable events checked</small></div></article></section>'''),
        "/judgment": ("Judgment", f'''{statebar}
  <section id="judgment" class="ops-grid"><article class="panel"><div class="section-head"><div><p class="eyebrow">Explainability</p><h2>Committee verdicts</h2></div><span>last {len(model["verdicts"])}</span></div><div class="verdict-list">{verdict_rows}</div></article>
    <article class="panel"><div class="section-head"><div><p class="eyebrow">Learning</p><h2>Mistake ledger</h2></div></div><ul class="mistakes">{mistake_items}</ul></article></section>'''),
    }
    page_name, content = pages.get(path, pages["/"])
    nav = "".join(
        f'<a href="{href}"{" class=\"active\"" if href == path else ""}>{label}</a>'
        for href, label in (("/", "Desk"), ("/research", "Research"),
                            ("/operations", "Operations"), ("/judgment", "Judgment")))

    tab_title = ("⛔ Sensei · HALTED" if model["kill_active"] else
                 f"Sensei · {page_name} · {len(model['alerts'])} alert{'s' if len(model['alerts']) != 1 else ''}"
                 if model["alerts"] else f"Sensei · {page_name}")
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(tab_title)}</title><style>{_CSS}</style></head><body>
<header><a class="brand" href="/"><span>千</span><div>Sensei<small>Indian equities · paper desk</small></div></a>
  <nav>{nav}</nav>
  <div class="mode"><i></i>PAPER</div></header>
<main id="top">
{content}
</main><footer>Sensei control room · read-only · live-updates every 45 seconds · local data</footer>
<script>
(function () {{
  async function refresh() {{
    try {{
      const res = await fetch(location.href, {{cache: "no-store"}});
      if (!res.ok) return;
      const doc = new DOMParser().parseFromString(await res.text(), "text/html");
      const next = doc.querySelector("main");
      const cur = document.querySelector("main");
      if (next && cur) {{
        const open = new Set([...document.querySelectorAll("details[open]")].map((d, i) => i));
        cur.replaceWith(next);
        [...document.querySelectorAll("details")].forEach((d, i) => {{ if (open.has(i)) d.open = true; }});
      }}
      if (doc.title) document.title = doc.title;
    }} catch (e) {{ /* transient — next tick retries */ }}
  }}
  setInterval(refresh, 45000);
}})();
</script></body></html>'''


_CSS = r'''
:root{--bg:#0b0f0e;--surface:#111715;--surface2:#161e1b;--line:#25302c;--text:#f2f5f3;--muted:#94a19b;--green:#62d394;--red:#ff7b72;--amber:#f2c66d;--cyan:#71c4c2;--shadow:0 18px 55px rgba(0,0,0,.24)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 76% -10%,rgba(51,118,89,.14),transparent 34%),var(--bg);color:var(--text);font:15px/1.55 Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}body:before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.025;background-image:linear-gradient(rgba(255,255,255,.6) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.6) 1px,transparent 1px);background-size:40px 40px}header{height:72px;padding:0 max(24px,calc((100vw - 1240px)/2));display:flex;align-items:center;border-bottom:1px solid var(--line);background:rgba(11,15,14,.88);backdrop-filter:blur(18px);position:sticky;top:0;z-index:10}.brand{display:flex;align-items:center;gap:12px;color:var(--text);text-decoration:none;font-weight:700;letter-spacing:.02em}.brand>span{display:grid;place-items:center;width:37px;height:37px;border:1px solid #375346;border-radius:10px;color:var(--green);font-family:serif;font-size:20px;background:#142019}.brand div{line-height:1.1}.brand small{display:block;color:var(--muted);font-size:10px;font-weight:500;margin-top:5px;text-transform:uppercase;letter-spacing:.12em}nav{display:flex;gap:8px;margin:auto}nav a{color:var(--muted);text-decoration:none;font-size:13px;padding:8px 14px;border-radius:999px;border:1px solid transparent}nav a:hover{color:var(--text)}nav a.active{color:var(--text);border-color:var(--line);background:var(--surface2)}
.statebar{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:26px}.statebar .desk-state,.statebar .next-action{margin:0}
.stage-adopted{color:var(--green);border-color:#2c4a3a;background:#12211a}.stage-muted{color:var(--muted);border-color:var(--line);background:transparent}.mode{font:700 11px/1 ui-monospace,monospace;letter-spacing:.12em;border:1px solid var(--line);border-radius:999px;padding:9px 12px;color:var(--green)}.mode i{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--green);margin-right:7px;box-shadow:0 0 10px var(--green)}main{max-width:1240px;margin:auto;padding:58px 24px 80px}.hero{display:flex;justify-content:space-between;align-items:flex-end;gap:40px;margin-bottom:42px}.eyebrow{margin:0 0 10px;color:var(--green);font:700 10px/1.2 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.18em}.hero h1{font-size:clamp(34px,5vw,62px);line-height:1.02;letter-spacing:-.055em;margin:0;max-width:800px;font-weight:650}.hero h1 span{color:#7e8b85}.lede{color:var(--muted);font-size:16px;max-width:610px;margin:22px 0 0}.hero-side{display:grid;gap:10px;min-width:250px}.desk-state,.next-action{border:1px solid var(--line);border-radius:16px;padding:16px 18px;background:var(--surface);box-shadow:var(--shadow)}.desk-state{display:flex;gap:12px}.desk-state>i{width:9px;height:9px;border-radius:50%;margin-top:7px;background:var(--muted)}.desk-state.good>i{background:var(--green);box-shadow:0 0 14px var(--green)}.desk-state.warn>i{background:var(--amber)}.desk-state.danger>i{background:var(--red)}.desk-state small,.desk-state span,.next-action small,.next-action span{display:block;color:var(--muted);font-size:11px}.desk-state strong,.next-action strong{display:block;margin:2px 0;font-size:16px}.next-action{border-color:#294438}.next-action small{color:var(--green);text-transform:uppercase;letter-spacing:.08em;font-size:9px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--line);border-radius:18px;overflow:hidden;background:var(--surface);box-shadow:var(--shadow);margin-bottom:22px}.metrics article{padding:22px 24px;border-right:1px solid var(--line)}.metrics article:last-child{border:0}label{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}.metrics strong{display:block;font-size:25px;letter-spacing:-.03em;margin:7px 0 2px}.metrics span{color:var(--muted);font-size:11px}.positive{color:var(--green)!important}.negative{color:var(--red)!important}.two-col,.ops-grid{display:grid;grid-template-columns:1.5fr 1fr;gap:22px;margin-bottom:66px}.panel{border:1px solid var(--line);border-radius:18px;background:var(--surface);padding:24px;box-shadow:var(--shadow)}.section-head,.section-title{display:flex;align-items:flex-start;justify-content:space-between;gap:24px}.section-head h2,.section-title h2{margin:0;font-size:19px;letter-spacing:-.02em}.section-head>span{color:var(--muted);font-size:11px;border:1px solid var(--line);padding:5px 9px;border-radius:999px}.alert{display:flex;align-items:flex-start;gap:12px;margin-top:14px;background:#201b12;border:1px solid #3b321f;border-radius:10px;padding:12px;color:#e7d6ae;font-size:13px}.alert>span{display:grid;place-items:center;flex:0 0 20px;height:20px;border-radius:50%;background:var(--amber);color:#1c160a;font-weight:800}.quiet-note,.empty{color:var(--muted);padding:20px 0}.ingestion-health>strong{font-size:40px;letter-spacing:-.04em;margin-top:16px;display:inline-block}.ingestion-health.good>strong{color:var(--green)}.ingestion-health.bad>strong{color:var(--red)}.ingestion-health>span{color:var(--muted);margin-left:8px}.ingestion-health>small{display:block;color:var(--muted);margin-top:6px}.ingestion-health p{margin:8px 0 0;color:var(--muted);font-size:11px}.ingestion-health b{color:var(--text);margin-right:6px}.section-title{align-items:flex-end;margin:0 0 20px}.section-title h2{font-size:27px}.section-title>p{color:var(--muted);max-width:420px;margin:0;font-size:13px;text-align:right}#positions,#strategies{scroll-margin-top:100px;margin-bottom:66px}.position-card{border:1px solid var(--line);border-radius:18px;background:linear-gradient(135deg,var(--surface),#101613);padding:24px;margin-bottom:14px;box-shadow:var(--shadow)}.position-head{display:flex;justify-content:space-between;align-items:flex-start}.symbol{font-size:22px;font-weight:750;letter-spacing:-.02em}.pill,.stage{font:700 10px/1 ui-monospace,monospace;letter-spacing:.08em;color:var(--cyan);border:1px solid #264b49;background:#11201f;border-radius:999px;padding:7px 9px;margin-left:10px}.pnl{text-align:right;font-size:20px;font-weight:700}.pnl small{display:block;font-size:11px;margin-top:2px}.price-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0}.price-grid>div{border-left:1px solid var(--line);padding-left:16px}.price-grid label{margin-bottom:5px}.price-grid strong{display:block;font-size:15px}.price-grid small{display:block;color:var(--muted);font-size:10px;margin-top:2px}.mark-warning{color:var(--amber);font-size:8px;border:1px solid #5b4826;border-radius:4px;padding:2px 4px;margin-left:4px}.exit-strip{display:flex;gap:16px;align-items:center;background:#0c1210;border:1px solid var(--line);border-radius:10px;padding:12px 14px;font-size:12px}.exit-strip span{color:var(--green);font:700 10px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.1em}.exit-strip strong{font-weight:550}details{border-top:1px solid var(--line);margin-top:18px;padding-top:14px}summary{color:var(--muted);font-size:12px;cursor:pointer}details p{color:#bdc7c2;font-size:13px;max-width:980px}.strategy-list{padding:5px 24px}.strategy-row{display:grid;grid-template-columns:1.5fr .4fr 1fr;align-items:center;gap:20px;padding:18px 0;border-bottom:1px solid var(--line)}.strategy-row:last-child{border:0}.strategy-row strong{display:block;text-transform:capitalize}.strategy-row small{display:block;color:var(--muted);font-size:10px;margin-top:4px}.strategy-row .stage{justify-self:start;margin:0}.progress{height:5px;border-radius:9px;background:#26302c;overflow:hidden;margin-bottom:6px}.progress i{display:block;height:100%;background:var(--green);border-radius:9px}.ops-grid{grid-template-columns:1.2fr .8fr;margin:0;scroll-margin-top:100px}.scheduler-line{color:var(--muted);font-size:12px;border-bottom:1px solid var(--line);padding-bottom:14px}.timeline{list-style:none;padding:0;margin:18px 0 0}.timeline li{display:flex;gap:14px;position:relative;padding-bottom:18px}.timeline li>i{flex:0 0 8px;height:8px;border-radius:50%;background:var(--green);margin-top:7px;box-shadow:0 0 0 4px rgba(98,211,148,.08)}.timeline li:not(:last-child):before{content:"";position:absolute;left:3px;top:17px;bottom:0;border-left:1px solid var(--line)}.timeline strong{display:block;font-size:12px}.timeline small{color:var(--muted);font-size:10px}.timeline p{margin:2px 0;color:#b4c0ba;font-size:11px}table{width:100%;border-collapse:collapse;margin-top:12px;font-size:12px}th{color:var(--muted);font-weight:500;text-align:left;padding:9px 6px;border-bottom:1px solid var(--line)}td{padding:12px 6px;border-bottom:1px solid var(--line)}.num{text-align:right}.integrity{margin-top:20px;border-radius:10px;background:#0d1311;padding:14px}.integrity span,.integrity small{display:block;color:var(--muted);font-size:10px}.integrity strong{display:block;color:var(--green);margin:2px 0}footer{border-top:1px solid var(--line);color:#617069;text-align:center;padding:24px;font-size:10px;text-transform:uppercase;letter-spacing:.1em}.muted{color:var(--muted)}.mono{font-family:ui-monospace,monospace}
.risk-meter{display:flex;align-items:center;gap:10px;margin:0 0 14px}.rm-label{color:var(--muted);font:700 9px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.1em}.rm-track{position:relative;flex:1;height:6px;border-radius:9px;background:linear-gradient(90deg,rgba(255,123,114,.35),#26302c 30%,rgba(98,211,148,.35))}.rm-entry{position:absolute;top:-3px;width:1px;height:12px;background:var(--muted);opacity:.7}.rm-mark{position:absolute;top:-3px;width:12px;height:12px;border-radius:50%;transform:translateX(-6px);border:2px solid var(--bg)}.rm-mark.meter-ok{background:var(--green);box-shadow:0 0 10px rgba(98,211,148,.5)}.rm-mark.meter-danger{background:var(--red);box-shadow:0 0 10px rgba(255,123,114,.6)}
.equity-curve{width:100%;margin:14px 0 4px;background:#0c1210;border:1px solid var(--line);border-radius:10px;padding:8px}
.verdict-list{max-height:560px;overflow-y:auto;overscroll-behavior:contain;padding-right:10px;margin-top:14px}.verdict{border:1px solid var(--line);border-left:3px solid var(--muted);border-radius:10px;padding:14px 16px;margin-bottom:12px;background:#0e1412}.verdict.approved{border-left-color:var(--green)}.verdict.vetoed{border-left-color:var(--red)}.verdict-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}.verdict-badge{font:800 9px ui-monospace,monospace;letter-spacing:.1em;padding:4px 7px;border-radius:5px}.verdict.approved .verdict-badge{color:var(--green);background:rgba(98,211,148,.1)}.verdict.vetoed .verdict-badge{color:var(--red);background:rgba(255,123,114,.1)}.verdict-head strong{font-size:12px}.verdict-head small{color:var(--muted);font-size:10px;margin-left:auto}.verdict p{margin:8px 0 0;color:#b4c0ba;font-size:12px;line-height:1.5}
.mistakes{list-style:none;padding:0;margin:14px 0 0}.mistakes li{border-bottom:1px solid var(--line);padding:14px 0}.mistakes li:last-child{border:0}.mistakes p{margin:0 0 6px;color:#d8c9a3;font-size:13px;line-height:1.5}.mistakes small{color:var(--muted);font-size:10px}
#judgment{margin-top:22px;scroll-margin-top:100px}
.timeline{max-height:520px;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable;padding-right:12px}.timeline:focus-visible{outline:1px solid var(--green);outline-offset:6px;border-radius:4px}.timeline::-webkit-scrollbar{width:8px}.timeline::-webkit-scrollbar-track{background:#0d1311;border-radius:8px}.timeline::-webkit-scrollbar-thumb{background:#34443d;border-radius:8px}.timeline::-webkit-scrollbar-thumb:hover{background:#466054}
.readiness-panel{margin-bottom:22px;border-left:3px solid var(--red)}.readiness-panel.ready{border-left-color:var(--green)}.readiness-next{color:var(--muted);font-size:12px}.readiness-list{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;list-style:none;padding:0;margin:18px 0 0}.readiness-check{display:flex;gap:10px;padding:12px;border:1px solid var(--line);border-radius:10px;background:#0d1311}.readiness-check>i{display:grid;place-items:center;flex:0 0 20px;height:20px;border-radius:50%;font-style:normal;font-weight:800;background:var(--red);color:#1b0c0a}.readiness-check.pass>i{background:var(--green);color:#07130c}.readiness-check strong,.readiness-check small{display:block}.readiness-check strong{font-size:11px}.readiness-check small{color:var(--muted);font-size:9px;margin-top:3px}
.rehearsal{margin-bottom:22px;border-left:3px solid var(--amber)}.rehearsal.would_trade{border-left-color:var(--green)}.rehearsal>p,.rehearsal>small{color:var(--muted)}.rehearsal-proposal{background:#0d1311;border:1px solid var(--line);border-radius:8px;padding:10px}.rehearsal-proposal b{color:var(--text);margin-right:8px}.rehearsal-facts{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}.rehearsal-facts span{border:1px solid var(--line);border-radius:8px;padding:8px 10px;color:var(--muted);font-size:10px}.rehearsal-facts b{color:var(--text);display:block;font-size:11px}.rehearsal-trace{color:var(--muted);font-size:11px}.rehearsal-trace b{color:var(--text)}
.liveness{border-left:3px solid var(--red)}.liveness.healthy{border-left-color:var(--green)}.liveness.degraded{border-left-color:var(--amber)}.liveness>p,.liveness>small{color:var(--muted)}
@media(max-width:850px){header nav{display:none}.mode{margin-left:auto}.hero{display:block}.desk-state{margin-top:28px}.metrics{grid-template-columns:repeat(2,1fr)}.metrics article:nth-child(2){border-right:0}.metrics article:nth-child(-n+2){border-bottom:1px solid var(--line)}.two-col,.ops-grid{grid-template-columns:1fr}.price-grid{grid-template-columns:repeat(2,1fr)}.strategy-row{grid-template-columns:1fr auto}.strategy-row .progress-wrap{grid-column:1/-1}.section-title>p{display:none}}
@media(max-width:520px){main{padding:34px 14px 60px}header{padding:0 14px}.hero h1{font-size:36px}.metrics{grid-template-columns:1fr}.metrics article{border-right:0!important;border-bottom:1px solid var(--line)!important}.metrics article:last-child{border-bottom:0!important}.position-head{display:block}.pnl{text-align:left;margin-top:12px}.price-grid{grid-template-columns:1fr 1fr}.exit-strip{display:block}.exit-strip span{display:block;margin-bottom:5px}.panel,.position-card{padding:18px}.section-title h2{font-size:23px}.timeline{max-height:440px}.readiness-list{grid-template-columns:1fr}}
'''


class _Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    ROUTES = ("/", "/research", "/operations", "/judgment")

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path not in self.ROUTES:
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return
        body = render(path).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def create_server(port: int = 8642) -> ThreadingHTTPServer:
    """Create a concurrent local server; idle clients cannot block the desk UI."""

    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    server.daemon_threads = True
    return server


def serve(port: int = 8642) -> None:
    print(f"Sensei control room → http://localhost:{port}  (Ctrl-C to stop)")
    create_server(port).serve_forever()


__all__ = ["create_server", "dashboard_model", "render", "serve"]
