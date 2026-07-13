import hashlib
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from sensei.operations.journal import OperationalJournal
from sensei.research.registry import (
    CampaignLocked,
    ConfirmationAlreadyConsumed,
    ConfirmationEvidence,
    ConfirmationRequest,
    DependenceMethod,
    ExperimentDeclaration,
    ExperimentPhase,
    ExperimentRegistry,
    ResolvedHoldout,
)


NOW = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)


def confirmation_declaration(
    variant_id: str,
    *,
    expected_revision: int,
    command_id: str,
    campaign_id: str = "confirmation-campaign",
) -> ExperimentDeclaration:
    return ExperimentDeclaration(
        campaign_id=campaign_id,
        variant_id=variant_id,
        plan_version_id=f"plan:{variant_id}:v1",
        plan_content_hash=(
            "sha256:" + hashlib.sha256(variant_id.encode("utf-8")).hexdigest()
        ),
        protocol_id="sha256:" + "f" * 64,
        data_policy_id="point-in-time-daily-v1",
        phase=ExperimentPhase.CONFIRMATION,
        minimum_effect_size=0.10,
        minimum_confidence_lower_bound=0.02,
        confirmation_holdout_policy_id="opaque:holdout-2026h2",
        familywise_alpha=0.05,
        expected_campaign_revision=expected_revision,
        command_id=command_id,
        occurred_at=NOW,
    )


def test_confirmation_burns_access_before_resolution_and_applies_bonferroni(tmp_path):
    journal_path = tmp_path / "sensei.sqlite3"
    journal = OperationalJournal(journal_path)
    registry: ExperimentRegistry
    resolution_observations: list[bool] = []

    def resolve(policy_id: str) -> ResolvedHoldout:
        resolution_observations.append(
            registry.campaign("confirmation-campaign").confirmation_started
        )
        assert policy_id == "opaque:holdout-2026h2"
        return ResolvedHoldout(
            snapshot_id="snapshot:server-selected-sealed-data",
            material={"server_only": True},
        )

    def examine(registered, holdout) -> ConfirmationEvidence:
        assert registered.variant_id == "beta"
        assert holdout == {"server_only": True}
        return ConfirmationEvidence(
            evidence_ref="dossier:confirmation-beta",
            p_value=0.02,
            protocol_passed=True,
            dependence_method=DependenceMethod.PURGED_WALK_FORWARD_FOLDS,
            independent_unit_count=12,
            effect_size=0.12,
            confidence_lower_bound=0.03,
        )

    registry = ExperimentRegistry(
        journal,
        confirmation_resolver=resolve,
        confirmation_examiner=examine,
    )
    registry.preregister(
        confirmation_declaration(
            "alpha", expected_revision=0, command_id="register-alpha"
        )
    )
    beta = registry.preregister(
        confirmation_declaration(
            "beta", expected_revision=1, command_id="register-beta"
        )
    )

    confirmation_request = ConfirmationRequest(
        campaign_id="confirmation-campaign",
        registration_id=beta.registration_id,
        expected_campaign_revision=2,
        command_id="consume-beta-holdout",
        occurred_at=NOW,
    )
    result = registry.confirm(confirmation_request)

    assert resolution_observations == [True]
    assert result.campaign_trial_count == 2
    assert result.adjusted_alpha == 0.025
    assert result.p_value == 0.02
    assert result.dependence_method is DependenceMethod.PURGED_WALK_FORWARD_FOLDS
    assert result.independent_unit_count == 12
    assert result.effect_size == 0.12
    assert result.confidence_lower_bound == 0.03
    assert result.minimum_effect_size == 0.10
    assert result.minimum_confidence_lower_bound == 0.02
    assert result.passed is True
    assert result.snapshot_id == "snapshot:server-selected-sealed-data"
    assert registry.campaign("confirmation-campaign").revision == 4
    assert registry.confirm(confirmation_request) == result
    assert ExperimentRegistry(OperationalJournal(journal_path)).confirm(
        confirmation_request
    ) == result
    assert resolution_observations == [True]

    with pytest.raises(ConfirmationAlreadyConsumed, match="already"):
        registry.confirm(
            ConfirmationRequest(
                campaign_id="confirmation-campaign",
                registration_id=beta.registration_id,
                expected_campaign_revision=4,
                command_id="try-beta-again",
                occurred_at=NOW,
            )
        )

    with pytest.raises(CampaignLocked, match="sealed"):
        registry.preregister(
            confirmation_declaration(
                "gamma", expected_revision=4, command_id="register-too-late"
            )
        )


def test_confirmation_remains_consumed_when_holdout_resolution_crashes(tmp_path):
    journal_path = tmp_path / "sensei.sqlite3"
    journal = OperationalJournal(journal_path)

    def crash(_policy_id: str) -> ResolvedHoldout:
        raise RuntimeError("sealed store unavailable")

    never_called = lambda _registration, _material: ConfirmationEvidence(
        evidence_ref="impossible",
        p_value=0.01,
        protocol_passed=True,
        dependence_method=DependenceMethod.MOVING_BLOCK_BOOTSTRAP,
        independent_unit_count=10,
        effect_size=0.20,
        confidence_lower_bound=0.10,
    )
    registry = ExperimentRegistry(
        journal,
        confirmation_resolver=crash,
        confirmation_examiner=never_called,
    )
    registered = registry.preregister(
        confirmation_declaration(
            "crash", expected_revision=0, command_id="register-crash",
            campaign_id="crash-campaign",
        )
    )
    request = ConfirmationRequest(
        campaign_id="crash-campaign",
        registration_id=registered.registration_id,
        expected_campaign_revision=1,
        command_id="burn-before-crash",
        occurred_at=NOW,
    )

    with pytest.raises(RuntimeError, match="unavailable"):
        registry.confirm(request)

    rebuilt = ExperimentRegistry(
        OperationalJournal(journal_path),
        confirmation_resolver=lambda _policy: ResolvedHoldout(
            snapshot_id="snapshot:late", material={}
        ),
        confirmation_examiner=never_called,
    )
    with pytest.raises(ConfirmationAlreadyConsumed, match="already"):
        rebuilt.confirm(request)
    with pytest.raises(ConfirmationAlreadyConsumed, match="already"):
        rebuilt.confirm(
            ConfirmationRequest(
                campaign_id="crash-campaign",
                registration_id=registered.registration_id,
                expected_campaign_revision=2,
                command_id="retry-after-crash",
                occurred_at=NOW,
            )
        )


def test_confirmation_result_survives_an_interleaved_confirmation(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    registry: ExperimentRegistry
    beta_registration_id = ""

    def examine(registered, _material) -> ConfirmationEvidence:
        if registered.variant_id == "alpha":
            registry.confirm(
                ConfirmationRequest(
                    campaign_id="interleaved-campaign",
                    registration_id=beta_registration_id,
                    expected_campaign_revision=3,
                    command_id="consume-interleaved-beta",
                    occurred_at=NOW,
                )
            )
        return ConfirmationEvidence(
            evidence_ref=f"dossier:{registered.variant_id}",
            p_value=0.01,
            protocol_passed=True,
            dependence_method=DependenceMethod.CLUSTER_ROBUST,
            independent_unit_count=20,
            effect_size=0.15,
            confidence_lower_bound=0.04,
        )

    registry = ExperimentRegistry(
        journal,
        confirmation_resolver=lambda _policy: ResolvedHoldout(
            snapshot_id="snapshot:sealed", material={}
        ),
        confirmation_examiner=examine,
    )
    alpha = registry.preregister(
        confirmation_declaration(
            "alpha",
            expected_revision=0,
            command_id="register-interleaved-alpha",
            campaign_id="interleaved-campaign",
        )
    )
    beta = registry.preregister(
        confirmation_declaration(
            "beta",
            expected_revision=1,
            command_id="register-interleaved-beta",
            campaign_id="interleaved-campaign",
        )
    )
    beta_registration_id = beta.registration_id

    result = registry.confirm(
        ConfirmationRequest(
            campaign_id="interleaved-campaign",
            registration_id=alpha.registration_id,
            expected_campaign_revision=2,
            command_id="consume-interleaved-alpha",
            occurred_at=NOW,
        )
    )

    assert result.campaign_revision == 6
    assert registry.campaign("interleaved-campaign").revision == 6


@pytest.mark.parametrize(
    "evidence_update",
    (
        {"protocol_passed": False},
        {"p_value": 0.03},
        {"effect_size": 0.09},
        {"confidence_lower_bound": 0.01},
    ),
)
def test_confirmation_requires_every_preregistered_statistical_gate(
    tmp_path, evidence_update
):
    base_evidence = ConfirmationEvidence(
        evidence_ref="dossier:candidate",
        p_value=0.02,
        protocol_passed=True,
        dependence_method=DependenceMethod.MOVING_BLOCK_BOOTSTRAP,
        independent_unit_count=16,
        effect_size=0.12,
        confidence_lower_bound=0.03,
    )
    registry = ExperimentRegistry(
        OperationalJournal(tmp_path / "sensei.sqlite3"),
        confirmation_resolver=lambda _policy: ResolvedHoldout(
            snapshot_id="snapshot:sealed", material={}
        ),
        confirmation_examiner=lambda _registered, _material: replace(
            base_evidence, **evidence_update
        ),
    )
    registry.preregister(
        confirmation_declaration(
            "control",
            expected_revision=0,
            command_id="register-gate-control",
            campaign_id="gate-campaign",
        )
    )
    candidate = registry.preregister(
        confirmation_declaration(
            "candidate",
            expected_revision=1,
            command_id="register-gate-candidate",
            campaign_id="gate-campaign",
        )
    )

    result = registry.confirm(
        ConfirmationRequest(
            campaign_id="gate-campaign",
            registration_id=candidate.registration_id,
            expected_campaign_revision=2,
            command_id="confirm-gate-candidate",
            occurred_at=NOW,
        )
    )

    assert result.passed is False


def test_confirmation_rejects_naive_iid_uncertainty_metadata():
    with pytest.raises(ValueError, match="DependenceMethod"):
        ConfirmationEvidence(
            evidence_ref="dossier:naive",
            p_value=0.01,
            protocol_passed=True,
            dependence_method="naive_iid",  # type: ignore[arg-type]
            independent_unit_count=100,
            effect_size=0.20,
            confidence_lower_bound=0.10,
        )


def test_confirmation_requires_an_integer_independent_unit_count():
    with pytest.raises(ValueError, match="integer"):
        ConfirmationEvidence(
            evidence_ref="dossier:fractional-units",
            p_value=0.01,
            protocol_passed=True,
            dependence_method=DependenceMethod.MOVING_BLOCK_BOOTSTRAP,
            independent_unit_count=2.5,  # type: ignore[arg-type]
            effect_size=0.20,
            confidence_lower_bound=0.10,
        )
