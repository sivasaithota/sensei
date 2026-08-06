"""Fast, research-only cash portfolio simulation over frozen daily strategies."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Mapping

import pandas as pd


@dataclass(frozen=True)
class PortfolioCampaignConfig:
    capital: float = 300_000
    max_position_pct: float = 20
    max_risk_per_trade_pct: float = 2
    max_open_positions: int = 5
    cost_pct: float = 0.25


@dataclass(frozen=True)
class PortfolioTrade:
    strategy: str
    symbol: str
    entry_date: str
    exit_date: str
    quantity: int
    entry_price: float
    exit_price: float
    exit_reason: str
    gross_pnl: float
    costs: float
    net_pnl: float


@dataclass(frozen=True)
class EquityPoint:
    session: str
    equity: float
    cash: float
    invested: float
    open_positions: int


@dataclass(frozen=True)
class PortfolioCampaignReport:
    config: PortfolioCampaignConfig
    trades: tuple[PortfolioTrade, ...]
    equity_curve: tuple[EquityPoint, ...]
    final_equity: float
    net_pnl: float
    return_pct: float
    max_drawdown_pct: float
    turnover: float
    average_capital_utilization_pct: float
    strategy_pnl: dict[str, float]
    open_positions: int

    def to_dict(self):
        return {
            "config": asdict(self.config),
            "trades": [asdict(value) for value in self.trades],
            "equity_curve": [asdict(value) for value in self.equity_curve],
            "final_equity": self.final_equity,
            "net_pnl": self.net_pnl,
            "return_pct": self.return_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "turnover": self.turnover,
            "average_capital_utilization_pct": self.average_capital_utilization_pct,
            "strategy_pnl": self.strategy_pnl,
            "open_positions": self.open_positions,
            "authority": "RESEARCH_ONLY",
            "can_trade": False,
        }


@dataclass
class _Position:
    strategy: str
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    quantity: int
    stop: float
    target: float
    max_hold_days: int
    entry_cost: float
    held: int = 1


def run_portfolio_campaign(*, frames: Mapping[str, pd.DataFrame],
                           strategies: Mapping[str, Mapping[str, object]],
                           config: PortfolioCampaignConfig) -> PortfolioCampaignReport:
    values = (config.capital, config.max_position_pct,
              config.max_risk_per_trade_pct, config.cost_pct)
    if any(isinstance(v, bool) or not math.isfinite(v) for v in values):
        raise ValueError("portfolio configuration must be finite")
    if config.capital <= 0 or config.max_position_pct <= 0 or config.max_risk_per_trade_pct <= 0:
        raise ValueError("capital and risk limits must be positive")
    if config.cost_pct < 0 or config.max_open_positions <= 0:
        raise ValueError("cost must be nonnegative and position limit positive")
    if not frames or not strategies:
        raise ValueError("frames and strategies are required")
    for spec in strategies.values():
        stop, target, hold = spec["stop_pct"], spec["target_pct"], spec["max_hold_days"]
        if (isinstance(stop, bool) or isinstance(target, bool)
                or not math.isfinite(float(stop)) or not math.isfinite(float(target))
                or float(stop) <= 0 or float(target) <= 0
                or isinstance(hold, bool) or not isinstance(hold, int) or hold <= 0):
            raise ValueError("strategy exits must be positive")
    normalized = {symbol: frame.sort_index() for symbol, frame in frames.items()}
    sessions = sorted({date for frame in normalized.values() for date in frame.index})
    signals = {
        (name, symbol): spec["fn"](frame).fillna(False)
        for name, spec in strategies.items() for symbol, frame in normalized.items()
    }
    cash = config.capital
    positions: list[_Position] = []
    trades: list[PortfolioTrade] = []
    curve: list[EquityPoint] = []
    turnover = 0.0
    for session_index, session in enumerate(sessions):
        blocked_symbols: set[str] = set()
        blocked_strategies: set[str] = set()
        # Opening phase: only gap stops are knowable before new admissions.
        survivors = []
        for position in positions:
            frame = normalized[position.symbol]
            if session not in frame.index:
                raise ValueError(
                    f"missing held-position bar: {position.symbol}:{session.date()}"
                )
            bar = frame.loc[session]
            if float(bar.open) <= position.stop:
                cash, turnover = _close(position, session, float(bar.open),
                    "stop_gap", cash, turnover, trades)
                blocked_symbols.add(position.symbol); blocked_strategies.add(position.strategy)
            else:
                position.held += 1; survivors.append(position)
        positions = survivors
        # Opening admissions use only cash available at the open.
        if session_index > 0:
            prior = sessions[session_index - 1]
            held_symbols = {p.symbol for p in positions}
            held_strategies = {p.strategy for p in positions}
            candidates = []
            for name, spec in strategies.items():
                if name in held_strategies or name in blocked_strategies:
                    continue
                for symbol, frame in normalized.items():
                    if symbol in held_symbols or symbol in blocked_symbols or prior not in frame.index or session not in frame.index:
                        continue
                    if bool(signals[(name, symbol)].get(prior, False)):
                        candidates.append((_score(frame.loc[:prior]), name, symbol, spec))
            for _, name, symbol, spec in sorted(candidates, key=lambda x: (-x[0], x[1], x[2])):
                if len(positions) >= config.max_open_positions or name in {p.strategy for p in positions} or symbol in {p.symbol for p in positions}:
                    continue
                entry = float(normalized[symbol].loc[session, "open"])
                stop = entry * (1 - float(spec["stop_pct"]) / 100)
                fee_rate = config.cost_pct / 100
                by_risk = config.capital * config.max_risk_per_trade_pct / 100 / (
                    entry - stop + entry * fee_rate
                )
                by_size = config.capital * config.max_position_pct / 100 / entry
                quantity = math.floor(min(by_risk, by_size, cash / (entry * (1 + fee_rate))))
                if quantity <= 0:
                    continue
                entry_cost = entry * quantity * fee_rate
                cash -= entry * quantity + entry_cost
                turnover += entry * quantity
                positions.append(_Position(name, symbol, session, entry, quantity, stop,
                    entry * (1 + float(spec["target_pct"]) / 100),
                    int(spec["max_hold_days"]), entry_cost))
        # Intraday/close phase, including positions opened today; stop first.
        survivors = []
        for position in positions:
            frame = normalized[position.symbol]
            if session not in frame.index:
                survivors.append(position); continue
            bar = frame.loc[session]; reason = None; price = None
            if float(bar.low) <= position.stop:
                reason, price = "stop", position.stop
            elif float(bar.high) >= position.target:
                reason, price = "target", position.target
            elif position.held >= position.max_hold_days:
                reason, price = "time", float(bar.close)
            if reason:
                cash, turnover = _close(position, session, price, reason,
                    cash, turnover, trades)
            else:
                survivors.append(position)
        positions = survivors
        invested = sum(
            p.quantity * _mark(normalized[p.symbol], session) for p in positions
        )
        curve.append(EquityPoint(str(session.date()), round(cash + invested, 2),
            round(cash, 2), round(invested, 2), len(positions)))
    equities = [point.equity for point in curve]
    peak = config.capital; max_dd = 0.0
    for equity in equities:
        peak = max(peak, equity); max_dd = max(max_dd, (peak - equity) / peak * 100)
    final = equities[-1] if equities else config.capital
    attribution = {name: round(
        sum(t.net_pnl for t in trades if t.strategy == name)
        + sum((_mark(normalized[p.symbol], sessions[-1]) - p.entry_price) * p.quantity
              - p.entry_cost for p in positions if p.strategy == name), 2)
        for name in strategies}
    utilization = sum(point.invested / point.equity for point in curve if point.equity) / max(1, len(curve)) * 100
    return PortfolioCampaignReport(config, tuple(trades), tuple(curve), round(final, 2),
        round(final - config.capital, 2), round((final / config.capital - 1) * 100, 3),
        round(max_dd, 3), round(turnover, 2), round(utilization, 2), attribution, len(positions))


def _close(position, session, price, reason, cash, turnover, trades):
    gross = (price - position.entry_price) * position.quantity
    net = gross - position.entry_cost
    cash += price * position.quantity
    turnover += price * position.quantity
    trades.append(PortfolioTrade(position.strategy, position.symbol,
        str(position.entry_date.date()), str(session.date()), position.quantity,
        position.entry_price, round(price, 2), reason, round(gross, 2),
        round(position.entry_cost, 2), round(net, 2)))
    return cash, turnover


def _mark(frame: pd.DataFrame, session: pd.Timestamp) -> float:
    available = frame.loc[:session, "close"]
    if available.empty:
        raise ValueError("open position has no point-in-time mark")
    return float(available.iloc[-1])


def _score(frame: pd.DataFrame) -> float:
    close = frame["close"].astype(float)
    ret20 = float(close.iloc[-1] / close.iloc[-min(21, len(close))] - 1)
    ret63 = float(close.iloc[-1] / close.iloc[-min(64, len(close))] - 1)
    volume = float(frame["volume"].iloc[-1] / max(1.0, frame["volume"].tail(20).mean()))
    return ret20 + ret63 + min(volume, 3) / 10
