"""Market-open execution (PRD §5.1 step 2, paper edition).

The EOD run decides (approval chain) and queues; this module executes
the queue at the next market open using live quotes. Mirrors the
backtest's no-look-ahead semantics: signal on day T's close, fill at
day T+1's open.

Guards:
- price-drift: skip if the live price has gapped outside the thesis's
  entry zone (widened by GAP_TOLERANCE_PCT) — the approved trade is
  not the trade on offer any more.
- staleness: pending orders expire after MAX_PENDING_DAYS.
- kill-switch and L1 breakers re-checked at execution time.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from sensei.agents.thesis import ApprovalRecord
from sensei.paper.engine import PaperBook
from sensei.risk.rails import RiskConfig, RiskRails

PENDING_FILE = Path(__file__).resolve().parents[3] / "data" / "pending_orders.json"
GAP_TOLERANCE_PCT = 1.0     # entry zone widened by this much before skipping
MAX_PENDING_DAYS = 3        # approved theses go stale


def queue_order(record: ApprovalRecord) -> None:
    if not record.approved:
        raise ValueError(f"thesis {record.thesis.id} not fully approved — refusing to queue")
    pending = load_pending()
    pending.append({"queued": date.today().isoformat(),
                    "record": record.model_dump(mode="json")})
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps(pending, indent=2))


def load_pending() -> list[dict]:
    if not PENDING_FILE.exists():
        return []
    return json.loads(PENDING_FILE.read_text())


def live_price(symbol: str) -> float | None:
    """Best-effort live/latest quote. Yahoo NSE quotes are near-real-time
    (sufficient for P1 paper fills; P2 uses Kite websocket)."""
    import yfinance as yf
    try:
        info = yf.Ticker(f"{symbol}.NS").fast_info
        p = info.get("last_price") or info.get("lastPrice")
        return float(p) if p else None
    except Exception:
        return None


def execute_pending(
    today: date | None = None,
    *,
    allowed_strategy_names: frozenset[str] | None = None,
) -> dict:
    """Fill queued orders at live prices. Returns execution summary."""
    today = today or date.today()
    cfg = RiskConfig.load("config/risk.yaml")
    rails = RiskRails(cfg)
    book = PaperBook(cfg.capital)
    from sensei.loop.daily import kill_switch_active, _portfolio_state

    summary: dict = {"date": today.isoformat(), "filled": [], "skipped": []}
    remaining: list[dict] = []

    for item in load_pending():
        rec = ApprovalRecord.model_validate(item["record"])
        t = rec.thesis
        age = (today - date.fromisoformat(item["queued"])).days

        if allowed_strategy_names is not None:
            cited = {citation.strategy for citation in t.playbook_citations}
            if not cited or not cited <= allowed_strategy_names:
                summary["skipped"].append({
                    "id": t.id,
                    "reason": "strategy is not authorized at governed PAPER — dropped",
                })
                continue

        if kill_switch_active():
            summary["skipped"].append({"id": t.id, "reason": "kill-switch active"})
            remaining.append(item)
            continue
        if age > MAX_PENDING_DAYS:
            summary["skipped"].append({"id": t.id, "reason": f"stale ({age}d old) — dropped"})
            continue
        if any(p.symbol == t.symbol for p in book.positions):
            summary["skipped"].append({"id": t.id, "reason": "already holding symbol — dropped"})
            continue

        # earnings window can open between approval and fill (calendar updates)
        from sensei.data.events import in_no_trade_window
        blocked, why = in_no_trade_window(t.symbol, on=today)
        if blocked:
            summary["skipped"].append({"id": t.id, "reason": f"events guard: {why} — dropped"})
            continue

        price = live_price(t.symbol)
        if price is None:
            summary["skipped"].append({"id": t.id, "reason": "no live quote — retained"})
            remaining.append(item)
            continue

        lo = t.entry_zone_low * (1 - GAP_TOLERANCE_PCT / 100)
        hi = t.entry_zone_high * (1 + GAP_TOLERANCE_PCT / 100)
        if not (lo <= price <= hi):
            summary["skipped"].append(
                {"id": t.id, "reason": f"gapped outside entry zone: live {price:.2f} "
                                       f"not in [{lo:.2f}, {hi:.2f}] — dropped"})
            continue

        # re-check hard rails with live state (breakers may have tripped overnight,
        # and earlier fills in THIS run consume cash and position slots)
        state = _portfolio_state(book, cfg)
        breakers = rails.breaker_status(state)
        if breakers:
            summary["skipped"].append({"id": t.id, "reason": "; ".join(breakers)})
            remaining.append(item)
            continue
        if len(book.positions) >= cfg.max_open_positions:
            summary["skipped"].append({"id": t.id, "reason": "max positions reached — retained"})
            remaining.append(item)
            continue
        if price * t.quantity > book.cash:
            summary["skipped"].append(
                {"id": t.id, "reason": f"insufficient cash ({book.cash:.0f} < "
                                       f"{price * t.quantity:.0f}) — retained"})
            remaining.append(item)
            continue

        try:
            pos = book.open_from(rec, fill_price=price, today=today)
        except ValueError as e:
            summary["skipped"].append({"id": t.id, "reason": f"fill refused: {e} — retained"})
            remaining.append(item)
            continue
        summary["filled"].append({"symbol": pos.symbol, "qty": pos.quantity,
                                  "fill": round(price, 2), "stop": pos.stop_loss})

    PENDING_FILE.write_text(json.dumps(remaining, indent=2))
    return summary
