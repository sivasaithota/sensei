"""Strategy & Thesis Agent — "The Analyst" (PRD §4.5).

Takes a SignalCandidate (numbers already computed in code) and either
drafts a full TradeThesis or declines. Legacy Coach observations may inform
questions, but only governed lifecycle evidence can constrain a proposal.
"""

from __future__ import annotations

from datetime import date

from sensei.agents.thesis import PlaybookCitation, TradeThesis
from sensei.loop.scanner import SignalCandidate

def draft_thesis(cand: SignalCandidate, seq: int, client=None) -> TradeThesis | str:
    """Map computed legacy facts to a thesis without a live model call.

    Governed admission deliberately rejects this legacy, non-provenance-backed
    evidence. The adapter remains useful for reports and migration only.
    """
    facts = ", ".join(
        f"{key}={value}" for key, value in sorted(cand.facts.items())
    ) or "no computed facts"
    return TradeThesis(
        id=f"TH-{date.today().strftime('%Y%m%d')}-{seq:03d}",
        symbol=cand.symbol, direction="BUY",
        entry_zone_low=round(cand.close * 0.995, 2),
        entry_zone_high=round(cand.close * 1.005, 2),
        quantity=cand.quantity, stop_loss=cand.stop_loss,
        targets=[cand.target], time_horizon_days=cand.max_hold_days,
        invalidation=f"price reaches registered stop {cand.stop_loss}",
        evidence=[f"legacy-observation:{cand.strategy}:{facts}"],
        playbook_citations=[PlaybookCitation(
            strategy=cand.strategy,
            oos_expectancy_pct=cand.oos_stats["expectancy_pct"],
            oos_hit_rate=cand.oos_stats["hit_rate"],
            oos_trades=cand.oos_stats["trades"],
            oos_detail=cand.oos_stats)],
        narrative=(
            f"Deterministic {cand.strategy} candidate for {cand.symbol}; "
            f"entry={cand.close}, stop={cand.stop_loss}, target={cand.target}."
        ),
    )
