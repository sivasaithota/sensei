from pathlib import Path

from sensei.reporting.qualification import (
    DeskQualificationRunner,
    QualificationScenario,
)


def test_qualification_runs_every_scenario_and_reports_exact_failure(tmp_path):
    calls = []

    def execute(node_ids):
        calls.append(node_ids)
        if node_ids == ("tests/test_b.py",):
            return 1, "assertion failed"
        return 0, "3 passed"

    runner = DeskQualificationRunner(
        repo_root=tmp_path,
        scenarios=(
            QualificationScenario("agents", ("tests/test_a.py",)),
            QualificationScenario("settlement", ("tests/test_b.py",)),
        ),
        execute=execute,
    )

    report = runner.run()

    assert calls == [
        ("tests/test_a.py",),
        ("tests/test_b.py",),
    ]
    assert report.passed is False
    assert report.failed_scenarios == ("settlement",)
    assert report.results[0].passed is True
    assert report.results[1].detail == "assertion failed"


def test_default_matrix_covers_the_whole_governed_desk(tmp_path):
    runner = DeskQualificationRunner(
        repo_root=tmp_path,
        execute=lambda _node_ids: (0, "passed"),
    )

    names = {scenario.name for scenario in runner.scenarios}

    assert names == {
        "nine_agent_orchestration",
        "l1_l4_committee",
        "strategy_governance",
        "surveillance_and_trust",
        "scheduler_and_ingestion",
        "entry_execution_and_restart",
        "exit_settlement_and_reconciliation",
        "learning_memory_and_reporting",
        "production_rehearsal_and_certification",
    }


def test_qualification_report_is_json_serializable(tmp_path):
    report = DeskQualificationRunner(
        repo_root=Path(tmp_path),
        scenarios=(QualificationScenario("agents", ("tests/test_a.py",)),),
        execute=lambda _node_ids: (0, "2 passed in 0.1s"),
    ).run()

    payload = report.to_dict()

    assert payload["passed"] is True
    assert payload["failed_scenarios"] == []
    assert payload["results"][0]["name"] == "agents"
    assert payload["results"][0]["passed"] is True
