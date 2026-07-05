"""Market regime — "The Crowd Reader" v0 (PRD §4.4, Market Mood Index).

Three cheap, robust inputs:
- India VIX (Yahoo ^INDIAVIX) — fear gauge
- Breadth: % of universe above its own 200-DMA (from local parquet)
- Trend: % of universe with 50-DMA above 200-DMA

Output is a plain-language regime summary string fed to the L4
Orchestrator as its regime view, plus the raw numbers for the audit
trail. Deliberately not a trading signal — it's context for judgment.
"""

from __future__ import annotations

from dataclasses import dataclass

from sensei.data.store import available_symbols, load_prices


@dataclass
class Regime:
    india_vix: float | None
    pct_above_200dma: float
    pct_golden_cross: float
    n_symbols: int

    @property
    def label(self) -> str:
        b = self.pct_above_200dma
        if b >= 60:
            base = "risk-on: broad uptrend"
        elif b >= 40:
            base = "mixed: selective market"
        else:
            base = "risk-off: weak breadth"
        if self.india_vix is not None and self.india_vix >= 18:
            base += ", elevated volatility"
        return base

    def summary(self) -> str:
        vix = f"{self.india_vix:.1f}" if self.india_vix is not None else "n/a"
        return (f"Market regime: {self.label}. "
                f"India VIX {vix}; {self.pct_above_200dma:.0f}% of the Nifty 100 "
                f"universe above its 200-DMA; {self.pct_golden_cross:.0f}% with "
                f"50-DMA above 200-DMA (n={self.n_symbols}). "
                f"In weak-breadth regimes, breakout follow-through is historically "
                f"less reliable — weigh marginal theses accordingly.")


def _fetch_vix() -> float | None:
    try:
        import yfinance as yf
        h = yf.Ticker("^INDIAVIX").history(period="5d")["Close"]
        return float(h.iloc[-1]) if len(h) else None
    except Exception:
        return None


def compute_regime() -> Regime:
    above, golden, n = 0, 0, 0
    for sym in available_symbols():
        try:
            df = load_prices(sym)
        except FileNotFoundError:
            continue
        if len(df) < 200:
            continue
        close = df["close"]
        dma50 = close.rolling(50).mean().iloc[-1]
        dma200 = close.rolling(200).mean().iloc[-1]
        n += 1
        if close.iloc[-1] > dma200:
            above += 1
        if dma50 > dma200:
            golden += 1
    return Regime(
        india_vix=_fetch_vix(),
        pct_above_200dma=above / n * 100 if n else 0.0,
        pct_golden_cross=golden / n * 100 if n else 0.0,
        n_symbols=n,
    )
