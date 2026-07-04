"""Pre-market scanner (PRD §5.1 step 1, market-hours step 2 trigger).

Runs only ADOPTED Playbook strategies over the freshest daily bars and
emits signal candidates. Position sizing is computed here, in code,
from the risk config — the Analyst writes the thesis, it doesn't pick
the numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sensei.backtest.playbook import adopted_strategies
from sensei.backtest.strategies import SEED_STRATEGIES
from sensei.data.store import available_symbols, avg_daily_turnover, load_prices
from sensei.risk.rails import RiskConfig


@dataclass
class SignalCandidate:
    symbol: str
    strategy: str
    close: float                # last close (signal day)
    stop_pct: float
    target_pct: float
    max_hold_days: int
    quantity: int
    avg_daily_turnover_inr: float
    oos_stats: dict             # the Playbook citation payload
    facts: dict                 # computed evidence for the Analyst

    @property
    def stop_loss(self) -> float:
        return round(self.close * (1 - self.stop_pct / 100), 2)

    @property
    def target(self) -> float:
        return round(self.close * (1 + self.target_pct / 100), 2)


def size_position(price: float, stop: float, cfg: RiskConfig) -> int:
    """Max quantity satisfying both the risk-per-trade and position-size rails."""
    risk_per_share = price - stop
    if risk_per_share <= 0:
        return 0
    by_risk = cfg.capital * cfg.max_risk_per_trade_pct / 100 / risk_per_share
    by_notional = cfg.capital * cfg.max_position_pct / 100 / price
    return max(0, math.floor(min(by_risk, by_notional)))


def _facts(df, symbol: str) -> dict:
    """Objective, citable numbers the Analyst builds its narrative from.

    Includes exact levels (200-DMA, 55-day breakout, 52w high) so the
    thesis can reconcile its stop with its invalidation conditions —
    the gap the Devil's Advocate exposed on day one.
    """
    close = df["close"]
    last = df.iloc[-1]
    dma200 = float(close.rolling(200).mean().iloc[-1]) if len(df) >= 200 else None
    high_52w = float(df["high"].tail(250).max())
    high_55d = float(df["close"].rolling(55).max().shift(1).iloc[-1])
    return {
        "date": str(df.index[-1].date()),
        "close": round(float(last["close"]), 2),
        "high_52w": round(high_52w, 2),
        "pct_from_52w_high": round(float(last["close"] / high_52w - 1) * 100, 1),
        "breakout_level_55d": round(high_55d, 2),
        "dma_200": round(dma200, 2) if dma200 else None,
        "pct_above_200dma": round(float(last["close"] / dma200 - 1) * 100, 1) if dma200 else None,
        "ret_1m_pct": round(float(close.iloc[-1] / close.iloc[-21] - 1) * 100, 1) if len(df) > 21 else None,
        "ret_6m_pct": round(float(close.iloc[-1] / close.iloc[-126] - 1) * 100, 1) if len(df) > 126 else None,
        "volume_vs_20d_avg": round(float(last["volume"] / df["volume"].tail(20).mean()), 2),
    }


def scan(symbols: list[str] | None = None,
         cfg: RiskConfig | None = None) -> list[SignalCandidate]:
    """Run adopted strategies over the latest bar of each symbol."""
    cfg = cfg or RiskConfig.load("config/risk.yaml")
    symbols = symbols or available_symbols()
    adopted = adopted_strategies()
    candidates: list[SignalCandidate] = []

    for entry in adopted:
        name = entry["name"]
        spec = SEED_STRATEGIES[name]
        p = entry["params"]
        for sym in symbols:
            try:
                df = load_prices(sym)
            except FileNotFoundError:
                continue
            if len(df) < 260:
                continue
            sig = spec["fn"](df)
            if not bool(sig.iloc[-1]):
                continue
            turnover = avg_daily_turnover(sym)
            if turnover < cfg.min_avg_daily_turnover_inr:
                continue
            close = float(df["close"].iloc[-1])
            stop = close * (1 - p["stop_pct"] / 100)
            qty = size_position(close, stop, cfg)
            if qty == 0:
                continue
            candidates.append(SignalCandidate(
                symbol=sym, strategy=name, close=close,
                stop_pct=p["stop_pct"], target_pct=p["target_pct"],
                max_hold_days=p["max_hold_days"], quantity=qty,
                avg_daily_turnover_inr=turnover,
                oos_stats=entry["out_of_sample"], facts=_facts(df, sym)))
    return candidates
