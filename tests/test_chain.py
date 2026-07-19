"""Deterministic admission-chain tests."""

from unittest.mock import MagicMock

import pytest

from sensei.agents.chain import ApprovalChain
from sensei.agents.thesis import PlaybookCitation, TradeThesis
from sensei.risk.rails import PortfolioState, RiskConfig, RiskRails

from pathlib import Path

CONFIG = Path(__file__).parent.parent / "config" / "risk.yaml"


@pytest.fixture(autouse=True)
def isolated_audit_log(tmp_path, monkeypatch):
    import sensei.agents.chain as chain_mod
    monkeypatch.setattr(chain_mod, "AUDIT_LOG", tmp_path / "audit.jsonl")


def make_thesis(**over) -> TradeThesis:
    base = dict(
        id="TH-TEST-001", symbol="INFY", direction="BUY",
        entry_zone_low=99.0, entry_zone_high=101.0, quantity=90,
        stop_loss=95.0, targets=[110.0], time_horizon_days=20,
        invalidation="Close below 200 DMA",
        evidence=["claim:" + "a" * 64],
        playbook_citations=[PlaybookCitation(strategy="momentum_breakout_55",
                                             oos_expectancy_pct=0.5,
                                             oos_hit_rate=0.45, oos_trades=100)],
        narrative="Breakout with volume confirmation in an uptrend.",
    )
    base.update(over)
    return TradeThesis(**base)


def mock_client(verdicts: list[bool]) -> MagicMock:
    """Client whose successive calls return the given approved values."""
    client = MagicMock()
    responses = []
    for approved in verdicts:
        block = MagicMock()
        block.type = "tool_use"
        block.input = {"approved": approved, "reasoning": "mocked"}
        resp = MagicMock()
        resp.content = [block]
        responses.append(resp)
    client.messages.create.side_effect = responses
    return client


@pytest.fixture
def rails():
    return RiskRails(RiskConfig.load(CONFIG))


def state():
    return PortfolioState(cash=50000, open_positions=0, peak_equity=50000, equity=50000)


def test_full_approval(rails):
    client = mock_client([])
    chain = ApprovalChain(rails, client=client, regime_context="risk-on")
    rec = chain.run(make_thesis(), state(), turnover=1e9, surveillance_stage=0)
    assert rec.approved
    assert [v.level for v in rec.verdicts] == ["L1", "L2", "L3", "L4"]
    client.messages.create.assert_not_called()


def test_l1_veto_short_circuits(rails):
    chain = ApprovalChain(rails, client=mock_client([]))
    rec = chain.run(make_thesis(stop_loss=None) if False else make_thesis(quantity=500),
                    state(), turnover=1e9, surveillance_stage=0)  # 500 * 100 = 50000 > 20% cap
    assert not rec.approved
    assert len(rec.verdicts) == 1  # never reached the LLM levels
    assert rec.vetoed_by == ["L1:risk-officer"]
    chain.client.messages.create.assert_not_called()


def test_l2_veto_stops_chain(rails):
    chain = ApprovalChain(rails, regime_context="risk-on")
    rec = chain.run(make_thesis(evidence=[]), state(), turnover=1e9, surveillance_stage=0)
    assert not rec.approved
    assert [v.level for v in rec.verdicts] == ["L1", "L2"]
    assert rec.vetoed_by == ["L2:devils-advocate"]


def test_l4_veto_means_not_approved(rails):
    chain = ApprovalChain(rails, regime_context="")
    rec = chain.run(make_thesis(), state(), turnover=1e9, surveillance_stage=0)
    assert not rec.approved
    assert rec.vetoed_by == ["L4:orchestrator"]


def test_banned_surveillance_stage_vetoed_at_l1(rails):
    chain = ApprovalChain(rails, client=mock_client([]))
    rec = chain.run(make_thesis(), state(), turnover=1e9, surveillance_stage=2)
    assert not rec.approved and len(rec.verdicts) == 1


def test_unknown_surveillance_status_vetoes_before_llm(rails):
    chain = ApprovalChain(rails, client=mock_client([]))
    rec = chain.run(make_thesis(), state(), turnover=1e9)
    assert not rec.approved
    assert "surveillance status unknown" in rec.verdicts[0].reasoning
    chain.client.messages.create.assert_not_called()
