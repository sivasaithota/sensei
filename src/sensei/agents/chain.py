"""Approval chain (PRD §4.6): L1 Risk → L2 Devil's Advocate → L3 Compliance → L4 Orchestrator.

Any level can veto; all levels must pass. L1 is pure code (RiskRails).
L2–L4 are LLM agents, each with a narrow brief and a forced structured
verdict. Every verdict is appended to the immutable audit log.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sensei.agents.thesis import ApprovalRecord, TradeThesis, Verdict
from sensei.llm import structured_call
from sensei.risk.rails import PortfolioState, RiskRails, TradeProposal

AUDIT_LOG = Path(__file__).resolve().parents[3] / "data" / "audit.jsonl"

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "approved": {"type": "boolean"},
        "reasoning": {"type": "string",
                      "description": "Concise reasoning for the verdict, citing thesis specifics."},
    },
    "required": ["approved", "reasoning"],
}

L2_SYSTEM = """You are the Devil's Advocate on a trading desk's approval committee.
Your ONLY job is to attack the trade thesis: hunt for disconfirming evidence, weak
reasoning, missing invalidation conditions, statistics cited without context, or
theses that would fail under the strongest counter-argument. Approve ONLY if the
thesis survives your best attack. A thesis with vague evidence, uncited claims, or
a stop that doesn't match the invalidation logic must be vetoed. Be adversarial;
false approvals cost real money, false vetoes only cost an opportunity."""

L3_SYSTEM = """You are the Compliance Agent for a retail algo trading system in India
(SEBI-regulated, trading only the owner's own capital via Zerodha Kite Connect).
Check the thesis for: banned/GSM/ASM-listed instruments, patterns resembling market
manipulation (circular trading, spoofing-like behavior), trading on what could be
material non-public information (evidence must cite PUBLIC sources), and no-trade
windows around results if the strategy doesn't explicitly target them. Approve only
if compliant. When ambiguous, veto — conservative default."""

L4_SYSTEM = """You are the Orchestrator (desk head) giving final sign-off.
The thesis has passed risk, devil's-advocate, and compliance checks. Your check is
coherence: does this trade fit the current portfolio (concentration, correlated
exposure), the stated market regime, and the learning agenda? Would you stake your
reputation on the REASONING (not the outcome)? Veto if the trade is redundant with
existing exposure or the thesis conflicts with the regime view supplied."""


def _audit(event: str, payload: dict) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                            "event": event, **payload}) + "\n")


def _llm_verdict(client, level: str, agent: str,
                 system: str, user_content: str) -> Verdict:
    args = structured_call(system=system, user=user_content,
                           schema=VERDICT_SCHEMA, name="verdict", client=client)
    return Verdict(level=level, agent=agent, approved=args["approved"],
                   reasoning=args["reasoning"])


class ApprovalChain:
    def __init__(self, rails: RiskRails, client=None,
                 portfolio_context: str = "", regime_context: str = ""):
        self.rails = rails
        self.client = client
        self.portfolio_context = portfolio_context
        self.regime_context = regime_context

    def _l1(self, thesis: TradeThesis, state: PortfolioState,
            turnover: float, surveillance_stage: int) -> Verdict:
        proposal = TradeProposal(
            symbol=thesis.symbol, side=thesis.direction.value,
            entry_price=thesis.mid_entry, stop_loss=thesis.stop_loss,
            quantity=thesis.quantity, avg_daily_turnover_inr=turnover,
            surveillance_stage=surveillance_stage,
        )
        res = self.rails.check(proposal, state)
        return Verdict(level="L1", agent="risk-officer",
                       approved=res.ok,
                       reasoning="all rails pass" if res.ok else "; ".join(res.violations))

    def run(self, thesis: TradeThesis, state: PortfolioState, *,
            turnover: float, surveillance_stage: int = 0) -> ApprovalRecord:
        record = ApprovalRecord(thesis=thesis)
        _audit("thesis_submitted", {"thesis": thesis.model_dump(mode="json")})
        thesis_json = thesis.model_dump_json(indent=2)

        # L1 — pure code, always first, cheap and unconditional
        v1 = self._l1(thesis, state, turnover, surveillance_stage)
        record.verdicts.append(v1)
        _audit("verdict", {"thesis_id": thesis.id, **v1.model_dump(mode="json")})
        if not v1.approved:
            return record

        # L2 + L3 in sequence (parallelizable later; correctness first)
        v2 = _llm_verdict(self.client, "L2", "devils-advocate", L2_SYSTEM,
                          f"Attack this trade thesis:\n{thesis_json}")
        record.verdicts.append(v2)
        _audit("verdict", {"thesis_id": thesis.id, **v2.model_dump(mode="json")})
        if not v2.approved:
            return record

        v3 = _llm_verdict(self.client, "L3", "compliance", L3_SYSTEM,
                          f"Compliance-check this trade thesis:\n{thesis_json}\n"
                          f"GSM/ASM surveillance stage: {surveillance_stage}")
        record.verdicts.append(v3)
        _audit("verdict", {"thesis_id": thesis.id, **v3.model_dump(mode="json")})
        if not v3.approved:
            return record

        v4 = _llm_verdict(
            self.client, "L4", "orchestrator", L4_SYSTEM,
            f"Final sign-off on this trade thesis:\n{thesis_json}\n\n"
            f"Current portfolio:\n{self.portfolio_context or 'flat, no open positions'}\n\n"
            f"Regime view:\n{self.regime_context or 'no regime view supplied'}")
        record.verdicts.append(v4)
        _audit("verdict", {"thesis_id": thesis.id, **v4.model_dump(mode="json")})
        _audit("chain_complete", {"thesis_id": thesis.id, "approved": record.approved})
        return record
