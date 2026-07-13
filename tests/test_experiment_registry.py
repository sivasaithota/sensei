from dataclasses import replace
from datetime import datetime, timezone

import pytest

from sensei.operations.journal import OperationalJournal
from sensei.research.registry import (
    ExperimentDeclaration,
    ExperimentPhase,
    ExperimentRegistry,
)


NOW = datetime(2026, 7, 13, 9, 0, tzinfo=timezone.utc)
PLAN_HASH = "sha256:" + "a" * 64


def declaration(
    *,
    variant_id: str,
    phase: ExperimentPhase,
    expected_revision: int,
    command_id: str,
) -> ExperimentDeclaration:
    return ExperimentDeclaration(
        campaign_id="hammer-follow-through-2026q3",
        variant_id=variant_id,
        plan_version_id=f"hammer-plan:{variant_id}:v1",
        plan_content_hash=PLAN_HASH,
        protocol_id="sha256:" + "b" * 64,
        data_policy_id="daily-pit-v1",
        phase=phase,
        minimum_effect_size=0.10,
        minimum_confidence_lower_bound=0.02,
        discovery_snapshot_id=(
            "snapshot:discovery-2026-06-30"
            if phase is ExperimentPhase.DISCOVERY
            else None
        ),
        confirmation_holdout_policy_id=(
            "holdout:2026h2" if phase is ExperimentPhase.CONFIRMATION else None
        ),
        familywise_alpha=0.05,
        expected_campaign_revision=expected_revision,
        command_id=command_id,
        occurred_at=NOW,
    )


def test_registry_preregisters_every_variant_as_a_durable_campaign_trial(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    registry = ExperimentRegistry(journal)

    discovery = registry.preregister(
        declaration(
            variant_id="baseline",
            phase=ExperimentPhase.DISCOVERY,
            expected_revision=0,
            command_id="register-baseline",
        )
    )
    confirmation = registry.preregister(
        declaration(
            variant_id="volume-filter",
            phase=ExperimentPhase.CONFIRMATION,
            expected_revision=1,
            command_id="register-volume-filter",
        )
    )

    assert discovery.trial_number == 1
    assert confirmation.trial_number == 2
    assert confirmation.phase is ExperimentPhase.CONFIRMATION
    assert confirmation.discovery_snapshot_id is None
    assert confirmation.confirmation_holdout_policy_id == "holdout:2026h2"

    rebuilt = ExperimentRegistry(OperationalJournal(tmp_path / "sensei.sqlite3"))
    assert rebuilt.campaign("hammer-follow-through-2026q3").trial_count == 2
    assert rebuilt.preregister(
        declaration(
            variant_id="baseline",
            phase=ExperimentPhase.DISCOVERY,
            expected_revision=0,
            command_id="register-baseline",
        )
    ) == discovery


def test_confirmation_registration_rejects_a_caller_supplied_snapshot():
    with pytest.raises(ValueError, match="confirmation.*snapshot"):
        ExperimentDeclaration(
            campaign_id="campaign-1",
            variant_id="variant-1",
            plan_version_id="plan:v1",
            plan_content_hash=PLAN_HASH,
            protocol_id="sha256:" + "b" * 64,
            data_policy_id="daily-pit-v1",
            phase=ExperimentPhase.CONFIRMATION,
            minimum_effect_size=0.10,
            minimum_confidence_lower_bound=0.02,
            discovery_snapshot_id="caller-picked-snapshot",
            confirmation_holdout_policy_id="holdout:sealed",
            familywise_alpha=0.05,
            expected_campaign_revision=0,
            command_id="register-1",
            occurred_at=NOW,
        )


def test_registration_identity_pins_confirmation_effect_thresholds(tmp_path):
    registry = ExperimentRegistry(OperationalJournal(tmp_path / "sensei.sqlite3"))
    original = declaration(
        variant_id="threshold-candidate",
        phase=ExperimentPhase.CONFIRMATION,
        expected_revision=0,
        command_id="register-original-threshold",
    )

    first = registry.preregister(original)
    revised = registry.preregister(
        replace(
            original,
            minimum_effect_size=0.11,
            minimum_confidence_lower_bound=0.025,
            expected_campaign_revision=1,
            command_id="register-revised-threshold",
        )
    )

    assert first.registration_id != revised.registration_id
    assert revised.trial_number == 2
    assert revised.minimum_effect_size == 0.11
    assert revised.minimum_confidence_lower_bound == 0.025
