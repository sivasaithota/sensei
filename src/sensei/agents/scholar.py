"""Literature-study agent — "The Scholar" (Coach's study arm, PRD §4.8).

Reads material the owner feeds in (book summaries, articles, transcripts,
the owner's own hunches) and extracts TESTABLE rules in the RuleSpec
grammar. Every extracted rule then faces the same backtest gate as any
other hypothesis: no rule enters the live Playbook without passing.
"""

from __future__ import annotations

import json

from sensei.backtest.rulespec import RuleSpec
from sensei.llm import structured_call

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string",
                             "description": "snake_case, 3-50 chars, e.g. minervini_trend_template"},
                    "source": {"type": "string"},
                    "principle": {"type": "string",
                                  "description": "The principle as the source states it"},
                    "conditions": {
                        "type": "array", "minItems": 1, "maxItems": 8,
                        "items": {
                            "type": "object",
                            "properties": {
                                "left": {"type": "string"},
                                "op": {"type": "string", "enum": [">", "<", ">=", "<="]},
                                "right": {"anyOf": [{"type": "string"}, {"type": "number"}]},
                                "factor": {"type": "number"},
                            },
                            "required": ["left", "op", "right"],
                        },
                    },
                    "stop_pct": {"type": "number"},
                    "target_pct": {"type": "number"},
                    "max_hold_days": {"type": "integer"},
                },
                "required": ["name", "source", "principle", "conditions",
                             "stop_pct", "target_pct", "max_hold_days"],
            },
        },
        "untestable_notes": {
            "type": "array", "items": {"type": "string"},
            "description": "Principles in the material that CANNOT be expressed "
                           "in the indicator grammar — noted honestly, not forced.",
        },
    },
    "required": ["rules", "untestable_notes"],
}

SCHOLAR_SYSTEM = """You are the Scholar on a systematic trading desk for Indian
equities (daily bars, long-only swing trades). You read trading literature and
extract principles as TESTABLE rules in a constrained indicator grammar.

Available indicators (daily): close, open, high, low, volume, sma_N, vol_sma_N,
highest_N (prior N-day high of close), lowest_N, rsi_N, ret_N (% return over N
days), high_52w, range_ratio_N (today's range vs N-day avg range).
Candlestick patterns as 1.0/0.0 series (require with `> 0.5`, exclude with
`< 0.5`): bullish_engulfing, hammer (long lower shadow after a dip),
strong_close (close in top quartile of range), inside_day_breakout.
Conditions compare left OP right*factor and are AND-ed.

Rules:
- Express the SOURCE's idea faithfully. Do not invent numbers the source doesn't
  imply; where the source gives ranges, pick the canonical value.
- Long-only entries. stop_pct 1-15, target_pct 2-40, max_hold_days 3-120,
  chosen to match the source's holding style (momentum: wider targets, longer
  holds; mean reversion: tighter, shorter).
- If a principle cannot be expressed in this grammar (fundamentals, chart
  patterns, market internals we don't have), put it in untestable_notes instead
  of forcing a bad translation.
- Prefer 2-4 rules capturing the material's core over 6 shallow variants."""


def extract_rules(material: str, client=None) -> tuple[list[RuleSpec], list[str]]:
    """Returns (valid rule specs, untestable notes)."""
    out = structured_call(
        system=SCHOLAR_SYSTEM, name="extract_rules", schema=EXTRACT_SCHEMA,
        user=f"Extract testable rules from this material:\n\n{material[:30000]}",
        client=client)
    specs: list[RuleSpec] = []
    notes = list(out.get("untestable_notes", []))
    for raw in out["rules"]:
        try:
            specs.append(RuleSpec.model_validate(raw))
        except Exception as e:
            notes.append(f"rule '{raw.get('name', '?')}' rejected by validator: {e}")
    return specs, notes
