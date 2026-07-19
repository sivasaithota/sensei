"""Deterministic trade admission checks.

The historical L1-L4 labels remain in durable evidence for compatibility, but
no conversational model runs in the entry path. Slow agents may prepare facts
ahead of time; this module only applies registered policy to exact inputs.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from sensei.agents.thesis import ApprovalRecord, TradeThesis, Verdict
from sensei.risk.rails import PortfolioState, RiskRails, TradeProposal

AUDIT_LOG = Path(__file__).resolve().parents[3] / "data" / "audit.jsonl"

def _audit(event: str, payload: dict) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                            "event": event, **payload}) + "\n")


class ApprovalChain:
    def __init__(self, rails: RiskRails, client=None,
                 portfolio_context: str = "", regime_context: str = ""):
        self.rails = rails
        self.client = client
        self.portfolio_context = portfolio_context
        self.regime_context = regime_context

    def _l1(self, thesis: TradeThesis, state: PortfolioState,
            turnover: float, surveillance_stage: int | None) -> Verdict:
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
            turnover: float, surveillance_stage: int | None = None) -> ApprovalRecord:
        record = ApprovalRecord(thesis=thesis)
        _audit("thesis_submitted", {"thesis": thesis.model_dump(mode="json")})
        # L1 — pure code, always first, cheap and unconditional
        v1 = self._l1(thesis, state, turnover, surveillance_stage)
        record.verdicts.append(v1)
        _audit("verdict", {"thesis_id": thesis.id, **v1.model_dump(mode="json")})
        if not v1.approved:
            return record

        # These are deterministic policy checks. Asynchronous agents can add
        # signed facts to the supplied thesis/context, but cannot improvise an
        # approval or make entry depend on model availability.
        v2 = self._l2(thesis)
        record.verdicts.append(v2)
        _audit("verdict", {"thesis_id": thesis.id, **v2.model_dump(mode="json")})
        if not v2.approved:
            return record

        v3 = self._l3(thesis, surveillance_stage)
        record.verdicts.append(v3)
        _audit("verdict", {"thesis_id": thesis.id, **v3.model_dump(mode="json")})
        if not v3.approved:
            return record

        v4 = self._l4(thesis, state)
        record.verdicts.append(v4)
        _audit("verdict", {"thesis_id": thesis.id, **v4.model_dump(mode="json")})
        _audit("chain_complete", {"thesis_id": thesis.id, "approved": record.approved})
        return record

    @staticmethod
    def _l2(thesis: TradeThesis) -> Verdict:
        violations = []
        if not thesis.evidence or len(set(thesis.evidence)) != len(thesis.evidence):
            violations.append("thesis evidence is missing or duplicated")
        if not thesis.invalidation.strip():
            violations.append("thesis invalidation is missing")
        if (
            not all(math.isfinite(value) for value in (
                thesis.entry_zone_low, thesis.entry_zone_high, thesis.stop_loss,
            ))
            or thesis.entry_zone_low > thesis.entry_zone_high
            or thesis.stop_loss >= thesis.entry_zone_low
            or not thesis.targets
            or any(
                not math.isfinite(target) or target <= thesis.entry_zone_high
                for target in thesis.targets
            )
        ):
            violations.append("entry, stop, and target geometry is incoherent")
        if not thesis.playbook_citations or any(
            item.oos_trades <= 0 for item in thesis.playbook_citations
        ):
            violations.append("out-of-sample strategy evidence is missing")
        return Verdict(
            level="L2", agent="devils-advocate", approved=not violations,
            reasoning="deterministic thesis checks pass" if not violations
            else "; ".join(violations),
        )

    @staticmethod
    def _l3(thesis: TradeThesis, surveillance_stage: int | None) -> Verdict:
        approved = surveillance_stage == 0 and all(
            re.fullmatch(r"claim:[0-9a-f]{64}", str(item)) is not None
            for item in thesis.evidence
        )
        return Verdict(
            level="L3", agent="compliance", approved=approved,
            reasoning=(
                "public provenance and surveillance checks pass"
                if approved else
                "compliance requires public content-addressed evidence and clear surveillance"
            ),
        )

    def _l4(self, thesis: TradeThesis, state: PortfolioState) -> Verdict:
        # L4 aggregates; it never adds a discretionary model opinion.
        approved = bool(
            thesis.narrative.strip()
            and self.regime_context.strip()
            and not state.halted
            and math.isfinite(state.equity)
            and state.equity > 0
        )
        return Verdict(
            level="L4", agent="orchestrator", approved=approved,
            reasoning=(
                "required deterministic evidence package is complete"
                if approved else "portfolio or market-regime evidence is invalid"
            ),
        )
