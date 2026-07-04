"""Strategy & Thesis Agent — "The Analyst" (PRD §4.5).

Takes a SignalCandidate (numbers already computed in code) and either
drafts a full TradeThesis or declines. The Analyst is mistake-ledger
aware: the Coach's failure patterns are injected into its prompt and
it must decline signals matching a known pattern.
"""

from __future__ import annotations

from datetime import date

from sensei.agents.thesis import PlaybookCitation, TradeThesis
from sensei.llm import structured_call
from sensei.loop.scanner import SignalCandidate
from sensei.paper.coach import ledger_summary

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "proceed": {"type": "boolean",
                    "description": "false = decline this signal entirely"},
        "decline_reason": {"type": ["string", "null"]},
        "narrative": {"type": ["string", "null"],
                      "description": "Plain-language thesis the owner can read: "
                                     "what we're buying, why now, what kills the idea."},
        "invalidation": {"type": ["string", "null"],
                         "description": "Conditions under which the thesis is dead "
                                        "even before the stop is hit."},
        "evidence": {"type": ["array", "null"], "items": {"type": "string"},
                     "description": "Each item cites a specific fact WITH its source/date."},
    },
    "required": ["proceed", "decline_reason", "narrative", "invalidation", "evidence"],
}

ANALYST_SYSTEM = """You are the Analyst on a systematic swing-trading desk for Indian
equities. You receive a signal candidate whose numbers (entry, stop, target, size)
were computed by the system from a backtested Playbook strategy — you do NOT change
the numbers. Your job is judgment: given the computed facts, is this specific
instance of the signal worth taking?

Decline when: the facts contradict the strategy's premise, the setup matches a
pattern in the Mistake Ledger, or the evidence is too thin to write an honest
thesis. Otherwise write the thesis. Every evidence item must cite a concrete
number from the supplied facts with its date. Never invent facts not supplied."""


def draft_thesis(cand: SignalCandidate, seq: int, client=None) -> TradeThesis | str:
    """Returns a TradeThesis, or a decline-reason string."""
    user = f"""Signal candidate:
- Symbol: {cand.symbol}
- Strategy: {cand.strategy} (out-of-sample: {cand.oos_stats})
- Last close: {cand.close}, stop: {cand.stop_loss} (-{cand.stop_pct}%), target: {cand.target} (+{cand.target_pct}%)
- Quantity (pre-sized by risk rails): {cand.quantity}
- Max hold: {cand.max_hold_days} days
- Computed facts: {cand.facts}

Mistake Ledger (decline anything matching these patterns):
{ledger_summary()}"""
    args = structured_call(system=ANALYST_SYSTEM, user=user,
                           schema=DRAFT_SCHEMA, name="draft_thesis", client=client)
    if not args["proceed"]:
        return args["decline_reason"] or "declined without reason"

    return TradeThesis(
        id=f"TH-{date.today().strftime('%Y%m%d')}-{seq:03d}",
        symbol=cand.symbol, direction="BUY",
        entry_zone_low=round(cand.close * 0.995, 2),
        entry_zone_high=round(cand.close * 1.005, 2),
        quantity=cand.quantity, stop_loss=cand.stop_loss,
        targets=[cand.target], time_horizon_days=cand.max_hold_days,
        invalidation=args["invalidation"] or "stop-loss",
        evidence=args["evidence"] or [],
        playbook_citations=[PlaybookCitation(
            strategy=cand.strategy,
            oos_expectancy_pct=cand.oos_stats["expectancy_pct"],
            oos_hit_rate=cand.oos_stats["hit_rate"],
            oos_trades=cand.oos_stats["trades"])],
        narrative=args["narrative"] or "",
    )
