"""Repeatable qualification matrix for the complete governed trading desk."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import subprocess
import sys


@dataclass(frozen=True)
class QualificationScenario:
    name: str
    node_ids: tuple[str, ...]


@dataclass(frozen=True)
class QualificationResult:
    name: str
    passed: bool
    detail: str
    node_ids: tuple[str, ...]
    evidence: Mapping[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "node_ids": list(self.node_ids),
            "evidence": dict(self.evidence or {}),
        }


@dataclass(frozen=True)
class DeskQualificationReport:
    generated_at: datetime
    results: tuple[QualificationResult, ...]
    valid_until: datetime
    environment: Mapping[str, object]

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(result.passed for result in self.results)

    @property
    def failed_scenarios(self) -> tuple[str, ...]:
        return tuple(result.name for result in self.results if not result.passed)

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "valid_until": self.valid_until.isoformat(),
            "environment": dict(self.environment),
            "passed": self.passed,
            "failed_scenarios": list(self.failed_scenarios),
            "results": [result.to_dict() for result in self.results],
        }


DEFAULT_SCENARIOS = (
    QualificationScenario(
        "nine_agent_orchestration",
        ("tests/test_desk_runtime.py", "tests/test_desk_roles.py"),
    ),
    QualificationScenario(
        "l1_l4_committee",
        (
            "tests/test_trade_committee_gate.py",
            "tests/test_committee_verdict_authority.py",
            "tests/test_chain.py",
        ),
    ),
    QualificationScenario(
        "strategy_governance",
        (
            "tests/test_strategy_autopilot.py",
            "tests/test_governed_migration.py",
            "tests/test_shadow_trial_automation.py",
            "tests/test_accelerated_paper_gate.py",
        ),
    ),
    QualificationScenario(
        "surveillance_and_trust",
        (
            "tests/test_surveillance_preflight.py",
            "tests/test_runtime_activation.py",
        ),
    ),
    QualificationScenario(
        "scheduler_and_ingestion",
        (
            "tests/test_production_scheduler_composition.py",
            "tests/test_scheduler_liveness.py",
            "tests/test_scheduler_paper_sessions.py",
            "tests/test_shadow_market_ingestion.py",
        ),
    ),
    QualificationScenario(
        "entry_execution_and_restart",
        (
            "tests/test_governed_entry_end_to_end.py",
            "tests/test_governed_paper_coordinator.py",
            "tests/test_recording_paper_gateway_durability.py",
            "tests/test_trading_kernel.py",
        ),
    ),
    QualificationScenario(
        "exit_settlement_and_reconciliation",
        (
            "tests/test_governed_exit.py",
            "tests/test_legacy_position_reconciliation.py",
            "tests/test_legacy_risk_containment.py",
        ),
    ),
    QualificationScenario(
        "learning_memory_and_reporting",
        (
            "tests/test_trade_episodes_learning.py",
            "tests/test_operations_drift.py",
            "tests/test_research_examiner.py",
            "tests/test_research_lab.py",
            "tests/test_operational_reporting.py",
            "tests/test_desk_reporting.py",
        ),
    ),
    QualificationScenario(
        "production_rehearsal_and_certification",
        (
            "tests/test_entry_rehearsal.py",
            "tests/test_prelive_certification.py",
        ),
    ),
)


class DeskQualificationRunner:
    """Execute bounded fault suites independently so failures stay attributable."""

    def __init__(
        self,
        *,
        repo_root: Path,
        scenarios: Sequence[QualificationScenario] = DEFAULT_SCENARIOS,
        execute: Callable[[tuple[str, ...]], tuple[int, str]] | None = None,
        current_runtime_check: (
            Callable[[], tuple[bool, str, Mapping[str, object]]] | None
        ) = None,
        enforce_manifest: bool = True,
    ) -> None:
        self._repo_root = Path(repo_root)
        self.scenarios = tuple(scenarios)
        self._execute = execute or self._run_pytest
        self._current_runtime_check = current_runtime_check
        self._enforce_manifest = enforce_manifest

    def run(self) -> DeskQualificationReport:
        results = []
        manifest_errors = (
            self.validate_manifest() if self._enforce_manifest else ()
        )
        if manifest_errors:
            results.append(QualificationResult(
                name="qualification_manifest",
                passed=False,
                detail="\n".join(manifest_errors),
                node_ids=(),
            ))
        for scenario in self.scenarios:
            if manifest_errors:
                break
            try:
                code, output = self._execute(scenario.node_ids)
            except subprocess.TimeoutExpired as exc:
                code, output = 124, (
                    f"QUALIFICATION_SCENARIO_TIMED_OUT after {exc.timeout}s"
                )
            except OSError as exc:
                code, output = 126, (
                    f"QUALIFICATION_SCENARIO_COULD_NOT_START: {exc}"
                )
            results.append(QualificationResult(
                name=scenario.name,
                passed=code == 0,
                detail=_last_output(output),
                node_ids=scenario.node_ids,
            ))
        if self._current_runtime_check is not None:
            try:
                passed, detail, evidence = self._current_runtime_check()
            except Exception as exc:
                passed, detail, evidence = (
                    False,
                    f"CURRENT_RUNTIME_QUALIFICATION_FAILED: "
                    f"{type(exc).__name__}: {exc}",
                    {},
                )
            results.append(QualificationResult(
                name="current_runtime_evidence",
                passed=passed,
                detail=detail,
                node_ids=(),
                evidence=evidence,
            ))
        generated_at = datetime.now(timezone.utc)
        return DeskQualificationReport(
            generated_at=generated_at,
            results=tuple(results),
            valid_until=generated_at + timedelta(hours=12),
            environment=self._environment_identity(),
        )

    def validate_manifest(self) -> tuple[str, ...]:
        errors: list[str] = []
        seen: set[str] = set()
        for scenario in self.scenarios:
            if not scenario.node_ids:
                errors.append(f"{scenario.name}: scenario has no tests")
            for node_id in scenario.node_ids:
                path = node_id.split("::", 1)[0]
                if node_id in seen:
                    errors.append(f"{scenario.name}: duplicate node id {node_id}")
                seen.add(node_id)
                if not (self._repo_root / path).is_file():
                    errors.append(f"{scenario.name}: missing {path}")
        return tuple(errors)

    def _run_pytest(self, node_ids: tuple[str, ...]) -> tuple[int, str]:
        completed = subprocess.run(
            (sys.executable, "-m", "pytest", "-q", *node_ids),
            cwd=self._repo_root,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        output = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr)
            if part.strip()
        )
        return completed.returncode, output

    def _environment_identity(self) -> Mapping[str, object]:
        lock = self._repo_root / "uv.lock"
        try:
            revision = subprocess.run(
                ("git", "rev-parse", "HEAD"),
                cwd=self._repo_root,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            revision = "unavailable"
        return {
            "git_revision": revision,
            "python_version": sys.version.split()[0],
            "dependency_lock_sha256": (
                hashlib.sha256(lock.read_bytes()).hexdigest()
                if lock.is_file() else None
            ),
        }


def _last_output(output: str, *, lines: int = 12) -> str:
    values = output.strip().splitlines()
    return "\n".join(values[-lines:]) if values else "no output"


__all__ = [
    "DeskQualificationReport",
    "DeskQualificationRunner",
    "QualificationResult",
    "QualificationScenario",
]
