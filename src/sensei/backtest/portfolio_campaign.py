"""Fast, research-only cash portfolio simulation over frozen daily strategies."""

from __future__ import annotations

import math
import hashlib
import inspect
import json
from dataclasses import asdict, dataclass
from typing import Mapping

import pandas as pd

from sensei.backtest.daily_execution import (
    DAILY_EXECUTION_POLICY, intraday_exit, opening_exit,
)
from sensei.strategy.selection import (
    RankingEvidence, SignalRankingPolicy, return_correlation, selection_tie_breaker,
    average_turnover,
)
from sensei.backtest.costs import delivery_charge, delivery_quantity

SELECTION_POLICY = SignalRankingPolicy()


@dataclass(frozen=True)
class PortfolioCampaignConfig:
    capital: float = 300_000
    max_position_pct: float = 20
    max_risk_per_trade_pct: float = 2
    max_open_positions: int = 5
    cost_pct: float = 0.25
    max_positions_per_strategy: int = 1
    liquidate_at_end: bool = False
    cost_model: str = "flat_round_trip"
    dp_charge_inr: float = 15.34
    entry_slippage_bps: float = 0.0


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
    experiment_id: str = ""
    preceding_session: str | None = None

    def to_dict(self):
        return {
            "execution_policy": DAILY_EXECUTION_POLICY,
            "selection_policy": asdict(SELECTION_POLICY),
            "experiment_id": self.experiment_id,
            "preceding_session": self.preceding_session,
            "parity_scope": "shared ranking/correlation and daily bracket semantics; not governed execution certification",
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
    round_trip_cost: float
    held: int = 1
    cost_model: str = "flat_round_trip"
    dp_charge_inr: float = 15.34


def run_portfolio_campaign(*, frames: Mapping[str, pd.DataFrame],
                           strategies: Mapping[str, Mapping[str, object]],
                           config: PortfolioCampaignConfig,
                           evaluation_start: pd.Timestamp | None = None,
                           evaluation_end: pd.Timestamp | None = None,
                           prepared_signals: Mapping[
                               tuple[str, str], pd.Series
                           ] | None = None,
                           entry_eligibility: Mapping[str, pd.Series] | None = None,
                           ) -> PortfolioCampaignReport:
    values = (config.capital, config.max_position_pct,
              config.max_risk_per_trade_pct, config.cost_pct)
    if any(isinstance(v, bool) or not math.isfinite(v) for v in values):
        raise ValueError("portfolio configuration must be finite")
    if config.capital <= 0 or config.max_position_pct <= 0 or config.max_risk_per_trade_pct <= 0:
        raise ValueError("capital and risk limits must be positive")
    if config.cost_pct < 0 or type(config.max_open_positions) is not int or config.max_open_positions <= 0:
        raise ValueError("cost must be nonnegative and position limit positive")
    if type(config.max_positions_per_strategy) is not int or config.max_positions_per_strategy < 1:
        raise ValueError("max_positions_per_strategy must be a positive integer")
    if config.cost_model not in {"flat_round_trip", "current_delivery_schedule"}:
        raise ValueError("unknown cost model")
    if any(not math.isfinite(v) or v < 0 for v in (config.dp_charge_inr, config.entry_slippage_bps)):
        raise ValueError("DP charges and slippage must be finite and nonnegative")
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
    for symbol, frame in normalized.items():
        if frame.empty or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.has_duplicates:
            raise ValueError(f"invalid price calendar: {symbol}")
        values = frame[["open", "high", "low", "close", "volume"]].astype(float)
        if (not values.map(math.isfinite).all(axis=None) or (values.iloc[:, :4] <= 0).any(axis=None)
                or (values["volume"] < 0).any()):
            raise ValueError(f"invalid prices: {symbol}")
    if entry_eligibility is not None and set(normalized) - set(entry_eligibility):
        raise ValueError("entry eligibility must cover every instrument")
    if entry_eligibility is not None:
        for series in entry_eligibility.values():
            if series.index.has_duplicates or not pd.api.types.is_bool_dtype(series.dtype):
                raise ValueError("entry eligibility must have unique dates and boolean values")
    sessions = sorted({date for frame in normalized.values() for date in frame.index})
    previous_session = {session: sessions[i - 1] for i, session in enumerate(sessions) if i}
    required_signal_keys = {
        (name, symbol) for name in strategies for symbol in normalized
    }
    if prepared_signals is None:
        signals = {
            (name, symbol): spec["fn"](frame).fillna(False)
            for name, spec in strategies.items()
            for symbol, frame in normalized.items()
        }
    else:
        missing = required_signal_keys - set(prepared_signals)
        if missing:
            raise ValueError(f"prepared signals missing {len(missing)} series")
        signals = {
            key: prepared_signals[key].fillna(False)
            for key in required_signal_keys
        }
    if evaluation_start is not None:
        start = pd.Timestamp(evaluation_start)
        sessions = [session for session in sessions if session >= start]
    if evaluation_end is not None:
        end = pd.Timestamp(evaluation_end)
        sessions = [session for session in sessions if session <= end]
    cash = config.capital
    positions: list[_Position] = []
    trades: list[PortfolioTrade] = []
    curve: list[EquityPoint] = []
    turnover = 0.0
    for session_index, session in enumerate(sessions):
        blocked_symbols: set[str] = set()
        blocked_strategies: set[str] = set()
        # Resolve known opening exits before spending available cash.
        survivors = []
        for position in positions:
            frame = normalized[position.symbol]
            if session not in frame.index:
                raise ValueError(
                    f"missing held-position bar: {position.symbol}:{session.date()}"
                )
            bar = frame.loc[session]
            outcome = opening_exit(float(bar.open), position.stop, position.target)
            if outcome is not None:
                cash, turnover = _close(position, session, outcome.price,
                    outcome.reason, cash, turnover, trades)
                blocked_symbols.add(position.symbol); blocked_strategies.add(position.strategy)
            else:
                position.held += 1; survivors.append(position)
        positions = survivors
        # Opening admissions use only cash available at the open.
        if session in previous_session:
            prior = previous_session[session]
            held_symbols = {p.symbol for p in positions}
            held_strategies = {p.strategy for p in positions}
            candidates = []
            for name, spec in strategies.items():
                if sum(p.strategy == name for p in positions) >= config.max_positions_per_strategy or name in blocked_strategies:
                    continue
                for symbol, frame in normalized.items():
                    if symbol in held_symbols or symbol in blocked_symbols or prior not in frame.index or session not in frame.index:
                        continue
                    if entry_eligibility is not None:
                        eligible = entry_eligibility[symbol].get(session, False)
                        if pd.isna(eligible) or not bool(eligible):
                            continue
                    if bool(signals[(name, symbol)].get(prior, False)):
                        observed = frame.loc[:prior]
                        evidence = spec.get("ranking_evidence", RankingEvidence())
                        if not isinstance(evidence, RankingEvidence):
                            raise ValueError("ranking_evidence must be dated RankingEvidence")
                        score = SELECTION_POLICY.score(
                            frame=observed, average_turnover_inr=average_turnover(observed),
                            stop_pct=float(spec["stop_pct"]), target_pct=float(spec["target_pct"]),
                            as_of=prior.date(), evidence=evidence,
                        )
                        tie = selection_tie_breaker(str(spec.get("plan_id", name)), symbol)
                        candidates.append((score.total, tie, name, symbol, spec))
            for _, _, name, symbol, spec in sorted(candidates, key=lambda x: (-x[0], x[1])):
                if len(positions) >= config.max_open_positions or sum(p.strategy == name for p in positions) >= config.max_positions_per_strategy or symbol in {p.symbol for p in positions}:
                    continue
                if any(return_correlation(
                    normalized[symbol].loc[:prior], normalized[p.symbol].loc[:prior],
                    lookback=SELECTION_POLICY.correlation_lookback_sessions,
                ) >= SELECTION_POLICY.maximum_pairwise_correlation for p in positions):
                    continue
                entry = float(normalized[symbol].loc[session, "open"]) * (1 + config.entry_slippage_bps / 10_000)
                stop = entry * (1 - float(spec["stop_pct"]) / 100)
                fee_rate = config.cost_pct / 100
                by_risk = config.capital * config.max_risk_per_trade_pct / 100 / (
                    entry - stop + entry * fee_rate
                )
                by_size = config.capital * config.max_position_pct / 100 / entry
                quantity = math.floor(min(by_risk, by_size, cash / (entry * (1 + fee_rate))))
                if config.cost_model == "current_delivery_schedule":
                    quantity = delivery_quantity(
                        price=entry, stop=stop, cash=cash,
                        size_budget=config.capital * config.max_position_pct / 100,
                        risk_budget=config.capital * config.max_risk_per_trade_pct / 100,
                        dp_charge_inr=config.dp_charge_inr,
                    )
                if quantity <= 0:
                    continue
                # `cost_pct` is one total round-trip stress proxy, not a
                # per-side rate. Reserve it at entry so unavailable cash can
                # never be reused while the position remains open.
                round_trip_cost = entry * quantity * fee_rate
                if config.cost_model == "current_delivery_schedule":
                    round_trip_cost = delivery_charge(entry * quantity, "BUY", dp_charge_inr=config.dp_charge_inr)
                cash -= entry * quantity + round_trip_cost
                turnover += entry * quantity
                positions.append(_Position(name, symbol, session, entry, quantity, stop,
                    entry * (1 + float(spec["target_pct"]) / 100),
                    int(spec["max_hold_days"]), round_trip_cost,
                    cost_model=config.cost_model, dp_charge_inr=config.dp_charge_inr))
        # Intraday/close phase, including positions opened today; stop first.
        survivors = []
        for position in positions:
            frame = normalized[position.symbol]
            if session not in frame.index:
                survivors.append(position); continue
            bar = frame.loc[session]; reason = None; price = None
            outcome = intraday_exit(
                float(bar.low), float(bar.high), position.stop, position.target,
            )
            if outcome is not None:
                reason, price = outcome.reason, outcome.price
            elif position.held >= position.max_hold_days:
                reason, price = "time", float(bar.close)
            if reason:
                cash, turnover = _close(position, session, price, reason,
                    cash, turnover, trades)
            else:
                survivors.append(position)
        positions = survivors
        if config.liquidate_at_end and session == sessions[-1]:
            for position in positions:
                cash, turnover = _close(position, session,
                    float(normalized[position.symbol].loc[session, "close"]),
                    "final_session", cash, turnover, trades)
            positions = []
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
              - p.round_trip_cost for p in positions if p.strategy == name), 2)
        for name in strategies}
    utilization = sum(point.invested / point.equity for point in curve if point.equity) / max(1, len(curve)) * 100
    identity = _experiment_identity(normalized, signals, strategies, config, entry_eligibility, sessions)
    return PortfolioCampaignReport(config, tuple(trades), tuple(curve), round(final, 2),
        round(final - config.capital, 2), round((final / config.capital - 1) * 100, 3),
        round(max_dd, 3), round(turnover, 2), round(utilization, 2), attribution, len(positions), identity,
        str(previous_session[sessions[0]].date()) if sessions and sessions[0] in previous_session else None)


def _close(position, session, price, reason, cash, turnover, trades):
    gross = (price - position.entry_price) * position.quantity
    exit_cost = (delivery_charge(price * position.quantity, "SELL", dp_charge_inr=position.dp_charge_inr)
                 if position.cost_model == "current_delivery_schedule" else 0)
    total_cost = position.round_trip_cost + exit_cost
    net = gross - total_cost
    cash += price * position.quantity - exit_cost
    turnover += price * position.quantity
    trades.append(PortfolioTrade(position.strategy, position.symbol,
        str(position.entry_date.date()), str(session.date()), position.quantity,
        position.entry_price, round(price, 2), reason, round(gross, 2),
        round(total_cost, 2), round(net, 2)))
    return cash, turnover


def _mark(frame: pd.DataFrame, session: pd.Timestamp) -> float:
    available = frame.loc[:session, "close"]
    if available.empty:
        raise ValueError("open position has no point-in-time mark")
    return float(available.iloc[-1])


def _experiment_identity(frames, signals, strategies, config, eligibility, sessions):
    from sensei.backtest import daily_execution
    from sensei.strategy import selection
    from sensei.backtest import costs
    from sensei.execution import nse

    def digest(value):
        return hashlib.sha256(pd.util.hash_pandas_object(value, index=True).values.tobytes()).hexdigest()

    payload = {
        "config": asdict(config), "execution_policy": DAILY_EXECUTION_POLICY,
        "delivery_charge_schedule": asdict(costs.IndianDeliveryChargeSchedule()),
        "charge_implementation": hashlib.sha256(inspect.getsource(nse).encode()).hexdigest(),
        "selection_policy": asdict(SELECTION_POLICY),
        "implementation": hashlib.sha256((inspect.getsource(run_portfolio_campaign)
            + inspect.getsource(daily_execution) + inspect.getsource(selection) + inspect.getsource(costs)
            + inspect.getsource(_close) + inspect.getsource(_mark)).encode()).hexdigest(),
        "frames": {key: digest(frame) for key, frame in sorted(frames.items())},
        "signals": {str(key): digest(value) for key, value in sorted(signals.items())},
        "strategies": {name: {key: (asdict(value) if isinstance(value, RankingEvidence) else value)
            for key, value in spec.items() if key != "fn"} for name, spec in sorted(strategies.items())},
        "eligibility": None if eligibility is None else {key: digest(value) for key, value in sorted(eligibility.items())},
        "sessions": [str(value) for value in sessions],
    }
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
