"""The daily loop (PRD §5.1) — P1 paper-trading edition.

    refresh data → mark existing positions → scan → Analyst drafts
    → approval chain → paper fill → post-mortems → EOD report

One invocation = one trading day. Run after market close (bars are
daily); fills simulate at the last close, exits process against the
day's bar with stop-first semantics.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import anthropic

from sensei.agents.analyst import draft_thesis
from sensei.agents.chain import ApprovalChain
from sensei.data.store import available_symbols, download_symbol, load_prices
from sensei.loop.scanner import scan
from sensei.paper.coach import run_post_mortem
from sensei.paper.engine import CLOSED_FILE, PaperBook, load_closed_trades
from sensei.reporting.eod import generate_eod_report
from sensei.risk.rails import PortfolioState, RiskConfig, RiskRails

KILL_FILE = Path(__file__).resolve().parents[3] / "data" / "KILL"
MAX_NEW_POSITIONS_PER_DAY = 2   # deliberate pace during P1


def kill_switch_active() -> bool:
    return KILL_FILE.exists()


def refresh_data(symbols: list[str] | None = None) -> int:
    """Re-download recent bars for the universe. Returns symbols refreshed."""
    n = 0
    for sym in symbols or available_symbols():
        try:
            if download_symbol(sym) is not None:
                n += 1
        except Exception:
            pass
    return n


def _portfolio_state(book: PaperBook, cfg: RiskConfig) -> PortfolioState:
    closed = load_closed_trades()
    today = date.today()
    day_pnl = sum(t.pnl for t in closed if t.closed == today.isoformat())
    week_pnl = sum(t.pnl for t in closed
                   if (today - date.fromisoformat(t.closed)).days <= 7)
    equity = book.cash + book.equity_invested
    total_pnl = sum(t.pnl for t in closed)
    peak = max(cfg.capital, cfg.capital + total_pnl)
    return PortfolioState(cash=book.cash, open_positions=len(book.positions),
                          day_pnl=day_pnl, week_pnl=week_pnl,
                          peak_equity=peak, equity=equity,
                          halted=kill_switch_active())


def _todays_bars(symbols: list[str]) -> dict[str, dict]:
    bars = {}
    for sym in symbols:
        df = load_prices(sym)
        last = df.iloc[-1]
        bars[sym] = {
            k: float(last[k])
            for k in ("open", "high", "low", "close", "volume")
        }
    return bars


def run_day(*, refresh: bool = True, client: anthropic.Anthropic | None = None,
            today: date | None = None,
            adopted_entries: tuple[dict, ...] | list[dict] | None = None) -> dict:
    """One full trading day. Returns a summary dict."""
    today = today or date.today()
    cfg = RiskConfig.load("config/risk.yaml")
    from sensei.execution.nse import NseExecutionModel
    book = PaperBook(
        cfg.capital,
        execution_model=NseExecutionModel(
            max_volume_participation_bps=100,
            base_impact_bps=5,
        ),
    )
    summary: dict = {"date": today.isoformat(), "closed": [], "opened": [],
                     "declined": [], "vetoed": [], "signals": 0}

    if kill_switch_active():
        summary["halted"] = "owner kill-switch active — no trading, monitoring only"

    if refresh:
        summary["refreshed"] = refresh_data()

    # 1. mark existing positions against today's bars
    if book.positions:
        bars = _todays_bars([p.symbol for p in book.positions])
        for t in book.mark_to_market(bars, today=today):
            pm = None
            if client is not False:  # allow tests to skip LLM
                try:
                    pm = run_post_mortem(t, client=client)
                    from sensei.paper.engine import attach_post_mortem
                    attach_post_mortem(t.thesis_id, pm)
                except Exception as e:
                    pm = {"error": f"post-mortem failed: {e}"}
            summary["closed"].append({"symbol": t.symbol, "pnl": t.pnl,
                                      "reason": t.exit_reason, "post_mortem": pm})

    # 2. scan for new signals (skip entirely if halted)
    if not kill_switch_active():
        candidates = scan(cfg=cfg, adopted_entries=adopted_entries)
        summary["signals"] = len(candidates)

        # earnings no-trade windows — code-level guard, not agent judgment
        from sensei.data.events import in_no_trade_window
        kept = []
        for cand in candidates:
            blocked, reason = in_no_trade_window(cand.symbol, on=today)
            if blocked:
                summary["declined"].append({"symbol": cand.symbol,
                                            "reason": f"events guard: {reason}"})
            else:
                cand.facts["earnings"] = reason  # date or 'unknown' — for the agents
                kept.append(cand)
        candidates = kept

        # regime context for the L4 Orchestrator
        from sensei.data.regime import compute_regime
        regime = compute_regime()
        summary["regime"] = regime.summary()
        # strongest strategies first, then liquidity
        candidates.sort(key=lambda c: (-c.oos_stats["expectancy_pct"],
                                       -c.avg_daily_turnover_inr))
        from sensei.loop.openexec import load_pending
        chain = ApprovalChain(RiskRails(cfg), client=client,
                              regime_context=regime.summary())
        opened = 0
        for i, cand in enumerate(candidates):
            if opened >= MAX_NEW_POSITIONS_PER_DAY:
                break
            pending_syms = {p["record"]["thesis"]["symbol"] for p in load_pending()}
            if any(p.symbol == cand.symbol for p in book.positions) \
                    or cand.symbol in pending_syms:
                continue  # already exposed or already queued
            # refresh portfolio context per approval — L4 must see positions
            # and queued orders from earlier in this same loop
            held = [f"- {p.symbol} {p.direction} {p.quantity} @ {p.entry_price} "
                    f"(opened {p.opened})" for p in book.positions]
            queued = [f"- {s} (approved, queued for next open)" for s in pending_syms]
            chain.portfolio_context = "\n".join(held + queued) or "flat, no open positions"
            result = draft_thesis(cand, seq=i + 1, client=client)
            if isinstance(result, str):
                summary["declined"].append({"symbol": cand.symbol, "reason": result})
                continue
            state = _portfolio_state(book, cfg)
            record = chain.run(result, state, turnover=cand.avg_daily_turnover_inr)
            if not record.approved:
                summary["vetoed"].append({"symbol": cand.symbol,
                                          "by": record.vetoed_by,
                                          "reason": record.verdicts[-1].reasoning})
                continue
            # decide now, execute at next open (matches backtest semantics:
            # signal on close T, fill at open T+1 via `sensei execute-open`)
            from sensei.loop.openexec import queue_order
            queue_order(record)
            opened += 1
            summary["opened"].append({"symbol": record.thesis.symbol,
                                      "qty": record.thesis.quantity,
                                      "queued_for_open": True,
                                      "entry_zone": [record.thesis.entry_zone_low,
                                                     record.thesis.entry_zone_high],
                                      "stop": record.thesis.stop_loss})

    # 3. EOD report
    summary["report"] = str(generate_eod_report(book, today=today))
    return summary
