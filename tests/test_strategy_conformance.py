from sensei.backtest.rulespec import Condition, RuleSpec
from sensei.strategy import assess_strategy_conformance

from tests.test_strategy_plan import hammer_follow_through_plan


def test_only_a_canonical_strategy_plan_is_conformant():
    canonical = assess_strategy_conformance(hammer_follow_through_plan())

    assert canonical.conformant is True
    assert canonical.plan_id == hammer_follow_through_plan().plan_id
    assert canonical.issues == ()


def test_legacy_rulespec_is_permanently_nonconformant():
    legacy = RuleSpec(
        name="legacy_rule",
        source="free text is not claim lineage",
        principle="A legacy principle",
        conditions=(Condition(left="close", op=">", right="highest_20"),),
        stop_pct=5.0,
        target_pct=10.0,
        max_hold_days=20,
    )

    result = assess_strategy_conformance(legacy)

    assert result.conformant is False
    assert result.plan_id is None
    assert result.issues == ("canonical_strategy_plan_required",)
