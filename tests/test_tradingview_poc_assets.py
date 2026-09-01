from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PINE = ROOT / "tradingview" / "sensei_strategy_poc.pine"
GUIDE = ROOT / "docs" / "operations" / "tradingview-poc.md"
ADOPTED_NAMES = {
    "minervini_trend_template",
    "minervini_breakout_volume",
    "gujral_trend_alignment_dual_ma",
    "sadekar_hammer_confirmation",
    "schwager_trend_with_pullback_strength",
}


def _ruleset_hash() -> str:
    records = json.loads((ROOT / "data" / "studied_rules.json").read_text())
    selected = [record for record in records if record["name"] in ADOPTED_NAMES]
    payload = json.dumps(
        selected, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_pine_asset_is_pinned_to_the_current_ruleset() -> None:
    pine = PINE.read_text(encoding="utf-8")

    assert pine.startswith("//@version=6")
    assert f"SENSEI_RULESET_SHA256: {_ruleset_hash()}" in pine
    assert "calc_on_order_fills = false" in pine
    assert "use_bar_magnifier = false" in pine
    assert "commission_value = 0.125" in pine
    assert "default_qty_type = strategy.percent_of_equity" in pine
    assert "default_qty_value = 100" in pine
    assert "time < lastEntrySignalDate + oneDayMs" in pine
    assert "time >= lastExitSessionDate" in pine
    assert 'input.time(1546281000000, "Start date")' in pine
    assert 'input.time(1703701800000, "Last entry signal date")' in pine
    assert 'input.time(1703788200000, "Last exit session date")' in pine
    assert "plannedStop := close *" in pine
    assert "plannedTarget := close *" in pine
    assert "strategy.position_avg_price" not in pine
    for name in ADOPTED_NAMES:
        assert name in pine


def test_pine_time_inputs_use_compile_time_constant_defaults() -> None:
    pine = PINE.read_text(encoding="utf-8")

    time_input_lines = [line for line in pine.splitlines() if "input.time(" in line]
    assert len(time_input_lines) == 3
    assert all("timestamp(" not in line for line in time_input_lines)


def test_protocol_pre_registers_costs_windows_and_gates() -> None:
    guide = GUIDE.read_text(encoding="utf-8")

    assert "Development window: 2019-01-01 through 2023-12-31" in guide
    assert "One-use holdout: 2024-01-01" in guide
    assert "0.25% round trip" in guide
    assert "profit factor at least 1.25" in guide
    assert "CANDIDATE_FOR_PORTFOLIO_VALIDATION" in guide
    assert "not permission to trade real money" in guide
