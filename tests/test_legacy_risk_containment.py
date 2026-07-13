import math

from sensei.risk.rails import (
    PortfolioState,
    RiskConfig,
    RiskRails,
    TradeProposal,
)


def rails() -> RiskRails:
    return RiskRails(
        RiskConfig(
            capital=100_000,
            max_risk_per_trade_pct=1,
            max_position_pct=10,
            max_open_positions=3,
            daily_loss_halt_pct=2,
            weekly_loss_halt_pct=4,
            max_drawdown_pct=10,
            stop_loss_mandatory=True,
            min_avg_daily_turnover_inr=1_000,
            leverage=False,
            banned_surveillance_stages=[1, 2, 3],
            allowed_products=["CNC"],
        )
    )


def state() -> PortfolioState:
    return PortfolioState(
        cash=100_000,
        open_positions=0,
        peak_equity=100_000,
        equity=100_000,
    )


def test_legacy_risk_fails_closed_on_invalid_numeric_and_side_values():
    invalid = (
        TradeProposal("X", "BUY", 100, 95, -10, avg_daily_turnover_inr=1_000_000),
        TradeProposal("X", "HOLD", 100, 95, 10, avg_daily_turnover_inr=1_000_000),
        TradeProposal("X", "BUY", math.nan, 95, 10, avg_daily_turnover_inr=1_000_000),
        TradeProposal("X", "BUY", 100, math.inf, 10, avg_daily_turnover_inr=1_000_000),
    )

    for proposal in invalid:
        result = rails().check(proposal, state())
        assert result.ok is False
        assert any("invalid" in violation for violation in result.violations)
