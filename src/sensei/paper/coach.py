"""Learning & Reflection Agent — "The Coach" (PRD §4.8).

Post-mortem for every closed trade, categorized on the two axes that
matter: was the THESIS right, and was the OUTCOME right? Plus the
Mistake Ledger — the permanent memory of failure patterns that every
new proposal is checked against.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sensei.llm import structured_call
from sensei.paper.engine import ClosedTrade

LEDGER_FILE = Path(__file__).resolve().parents[3] / "data" / "mistake_ledger.jsonl"

POST_MORTEM_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": ["right-thesis/right-outcome", "right-thesis/wrong-outcome",
                     "wrong-thesis/right-outcome", "wrong-thesis/wrong-outcome"],
            "description": "wrong-thesis/right-outcome is the DANGEROUS one — luck rewarded",
        },
        "thesis_assessment": {"type": "string"},
        "execution_assessment": {"type": "string"},
        "lesson": {"type": "string",
                   "description": "One transferable lesson, phrased as a rule"},
        "mistake_pattern": {
            "type": ["string", "null"],
            "description": "If a repeatable failure pattern is visible, name it "
                           "for the Mistake Ledger; null if none.",
        },
    },
    "required": ["category", "thesis_assessment", "execution_assessment",
                 "lesson", "mistake_pattern"],
}

COACH_SYSTEM = """You are the Coach — the self-improvement engine of a trading system.
For each closed trade you receive the original thesis narrative and the outcome.
Judge the THESIS on its reasoning quality at the time it was made (not hindsight),
and the OUTCOME separately. A profitable trade with sloppy reasoning is
wrong-thesis/right-outcome — flag it as dangerous. A well-reasoned trade stopped
out by noise is right-thesis/wrong-outcome — the process worked. Extract one
transferable lesson per trade. Only report a mistake_pattern when the same class
of error could plausibly recur."""


def run_post_mortem(trade: ClosedTrade, client=None) -> dict:
    pm = structured_call(
        system=COACH_SYSTEM, name="post_mortem", schema=POST_MORTEM_SCHEMA,
        user=(f"Post-mortem this closed trade:\n"
              f"{json.dumps({k: v for k, v in trade.__dict__.items() if k != 'post_mortem'}, indent=2)}"),
        client=client)
    if pm.get("mistake_pattern"):
        record_mistake(pm["mistake_pattern"], trade.thesis_id)
    return pm


def record_mistake(pattern: str, thesis_id: str) -> None:
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_FILE.open("a") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                            "pattern": pattern, "thesis_id": thesis_id}) + "\n")


def load_mistake_ledger() -> list[dict]:
    if not LEDGER_FILE.exists():
        return []
    return [json.loads(line) for line in LEDGER_FILE.read_text().splitlines()
            if line.strip()]


def ledger_summary() -> str:
    """Compact ledger text to inject into new-proposal checks (Analyst + L2)."""
    entries = load_mistake_ledger()
    if not entries:
        return "Mistake ledger is empty."
    return "\n".join(f"- {e['pattern']} (trade {e['thesis_id']})" for e in entries)
