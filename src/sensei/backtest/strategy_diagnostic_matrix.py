"""Research-only portfolio matrix for diagnosing frozen strategy plans."""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, replace
from typing import Mapping, Sequence

import pandas as pd

from sensei.backtest.portfolio_campaign import (
    PortfolioCampaignConfig,
    run_portfolio_campaign,
)


@dataclass(frozen=True)
class DiagnosticScenario:
    name: str
    strategies: tuple[str, ...]


@dataclass(frozen=True)
class DiagnosticResult:
    scenario: str
    strategies: tuple[str, ...]
    requested_sessions: int
    evaluated_sessions: int
    evaluation_start: str
    evaluation_end: str
    universe_size: int
    eligible_symbols: int
    excluded_symbols: int
    cost_pct: float
    final_equity: float
    net_pnl: float
    return_pct: float
    max_drawdown_pct: float
    completed_trades: int
    win_rate_pct: float
    profit_factor: float | None
    average_trade_pnl: float
    average_capital_utilization_pct: float
    turnover: float
    open_positions: int
    strategy_pnl: dict[str, float]
    experiment_id: str = ""


@dataclass(frozen=True)
class DiagnosticRanking:
    rank: int
    scenario: str
    positive_cells: int
    total_cells: int
    median_return_pct: float
    worst_return_pct: float
    worst_drawdown_pct: float
    total_completed_trades: int


@dataclass(frozen=True)
class StrategyDiagnosticReport:
    results: tuple[DiagnosticResult, ...]
    rankings: tuple[DiagnosticRanking, ...]

    def to_dict(self) -> dict:
        from sensei.backtest.daily_execution import DAILY_EXECUTION_POLICY

        return {
            "results": [asdict(result) for result in self.results],
            "rankings": [asdict(ranking) for ranking in self.rankings],
            "methodology": {
                "execution_policy": DAILY_EXECUTION_POLICY,
                "signal_warmup": "full history before evaluation_start",
                "trade_window": "evaluation_start through evaluation_end only",
                "cost_model": (
                    "cost_pct is one total round-trip stress proxy as a "
                    "percentage of entry not a per-side fee; reserved at entry"
                ),
                "ranking": (
                    "positive cells descending, median return descending, "
                    "worst drawdown ascending"
                ),
                "warning": (
                    "Diagnostic reuse of the same history; not independent "
                    "confirmation or lifecycle promotion evidence. Instruments "
                    "are not filtered by future bar completeness; missing held "
                    "bars block the run. Stored universe is not point-in-time membership."
                ),
            },
            "authority": "RESEARCH_ONLY",
            "can_trade": False,
        }


def adopted_strategy_scenarios() -> tuple[DiagnosticScenario, ...]:
    """Frozen single-plan and deliberately simple combination diagnostics."""
    breakout = "minervini_breakout_volume"
    trend = "minervini_trend_template"
    gujral = "gujral_trend_alignment_dual_ma"
    sadekar = "sadekar_hammer_confirmation"
    schwager = "schwager_trend_with_pullback_strength"
    return (
        DiagnosticScenario("minervini_breakout_only", (breakout,)),
        DiagnosticScenario("minervini_trend_only", (trend,)),
        DiagnosticScenario("gujral_trend_only", (gujral,)),
        DiagnosticScenario("sadekar_hammer_only", (sadekar,)),
        DiagnosticScenario("schwager_pullback_only", (schwager,)),
        DiagnosticScenario("minervini_pair", (breakout, trend)),
        DiagnosticScenario("momentum_plus_hammer", (breakout, trend, sadekar)),
        DiagnosticScenario("current_three", (breakout, trend, schwager)),
        DiagnosticScenario(
            "all_adopted",
            (breakout, trend, gujral, sadekar, schwager),
        ),
    )


def run_strategy_diagnostic_matrix(
    *,
    frames: Mapping[str, pd.DataFrame],
    strategies: Mapping[str, Mapping[str, object]],
    scenarios: Sequence[DiagnosticScenario],
    windows: Sequence[int],
    costs: Sequence[float],
    base_config: PortfolioCampaignConfig,
) -> StrategyDiagnosticReport:
    """Compare frozen strategies and combinations on identical portfolio rules."""
    if not frames or not strategies or not scenarios or not windows or not costs:
        raise ValueError("matrix inputs must not be empty")
    if base_config.cost_model != "flat_round_trip":
        raise ValueError("cost_pct matrix requires the flat round-trip stress model")
    if any(isinstance(value, bool) or value <= 0 for value in windows):
        raise ValueError("diagnostic windows must be positive")
    if any(isinstance(value, bool) or not math.isfinite(value) or value < 0
           for value in costs):
        raise ValueError("diagnostic costs must be finite and nonnegative")
    known = set(strategies)
    for scenario in scenarios:
        if not scenario.name or not scenario.strategies:
            raise ValueError("diagnostic scenarios require a name and strategies")
        missing = set(scenario.strategies) - known
        if missing:
            raise ValueError(f"unknown strategies in {scenario.name}: {sorted(missing)}")

    sessions = sorted({pd.Timestamp(date) for frame in frames.values()
                       for date in frame.index})
    if not sessions:
        raise ValueError("price frames contain no sessions")
    prepared_signals = {
        (name, symbol): spec["fn"](frame.sort_index()).fillna(False)
        for name, spec in strategies.items()
        for symbol, frame in frames.items()
    }
    results: list[DiagnosticResult] = []
    for scenario in scenarios:
        selected = {name: strategies[name] for name in scenario.strategies}
        for requested_sessions in windows:
            evaluated = min(requested_sessions, len(sessions))
            start = sessions[-evaluated]
            end = sessions[-1]
            eligible_frames = frames
            if not eligible_frames:
                raise ValueError(
                    f"no complete price frames for {requested_sessions}-session window"
                )
            for cost in costs:
                campaign = run_portfolio_campaign(
                    frames=eligible_frames,
                    strategies=selected,
                    config=replace(base_config, cost_pct=float(cost)),
                    evaluation_start=start,
                    evaluation_end=end,
                    prepared_signals={
                        (name, symbol): prepared_signals[(name, symbol)]
                        for name in selected for symbol in eligible_frames
                    },
                )
                wins = [trade.net_pnl for trade in campaign.trades
                        if trade.net_pnl > 0]
                losses = [-trade.net_pnl for trade in campaign.trades
                          if trade.net_pnl < 0]
                factor = None
                if losses:
                    factor = round(sum(wins) / sum(losses), 3)
                results.append(DiagnosticResult(
                    experiment_id=campaign.experiment_id,
                    scenario=scenario.name,
                    strategies=scenario.strategies,
                    requested_sessions=requested_sessions,
                    evaluated_sessions=len(campaign.equity_curve),
                    evaluation_start=str(start.date()),
                    evaluation_end=str(end.date()),
                    universe_size=len(frames),
                    eligible_symbols=len(eligible_frames),
                    excluded_symbols=len(frames) - len(eligible_frames),
                    cost_pct=float(cost),
                    final_equity=campaign.final_equity,
                    net_pnl=campaign.net_pnl,
                    return_pct=campaign.return_pct,
                    max_drawdown_pct=campaign.max_drawdown_pct,
                    completed_trades=len(campaign.trades),
                    win_rate_pct=round(
                        len(wins) / len(campaign.trades) * 100, 2
                    ) if campaign.trades else 0.0,
                    profit_factor=factor,
                    average_trade_pnl=round(
                        sum(trade.net_pnl for trade in campaign.trades)
                        / len(campaign.trades), 2
                    ) if campaign.trades else 0.0,
                    average_capital_utilization_pct=(
                        campaign.average_capital_utilization_pct
                    ),
                    turnover=campaign.turnover,
                    open_positions=campaign.open_positions,
                    strategy_pnl=campaign.strategy_pnl,
                ))

    by_scenario = {
        scenario.name: [result for result in results
                        if result.scenario == scenario.name]
        for scenario in scenarios
    }
    ordered = sorted(by_scenario.items(), key=lambda item: (
        -sum(result.return_pct > 0 for result in item[1]),
        -statistics.median(result.return_pct for result in item[1]),
        max(result.max_drawdown_pct for result in item[1]),
        item[0],
    ))
    rankings = tuple(DiagnosticRanking(
        rank=index,
        scenario=name,
        positive_cells=sum(result.return_pct > 0 for result in cells),
        total_cells=len(cells),
        median_return_pct=round(statistics.median(
            result.return_pct for result in cells
        ), 3),
        worst_return_pct=min(result.return_pct for result in cells),
        worst_drawdown_pct=max(result.max_drawdown_pct for result in cells),
        total_completed_trades=sum(result.completed_trades for result in cells),
    ) for index, (name, cells) in enumerate(ordered, start=1))
    return StrategyDiagnosticReport(tuple(results), rankings)
