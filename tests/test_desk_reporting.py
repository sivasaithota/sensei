import json
from dataclasses import replace

import pytest

from sensei.cli import main
from sensei.orchestration import DeskCycleFailed
from sensei.reporting.desk import DeskStatusReporter
from tests.test_desk_runtime import _authorize_dispatch_for, _runtime_fixture


def test_desk_status_reports_role_use_and_cycle_outcome(tmp_path):
    runtime, request, _, _, _, journal, _ = _runtime_fixture(tmp_path)
    result = runtime.run_cycle(
        request,
        authorize_dispatch=_authorize_dispatch_for(journal),
    )

    status = DeskStatusReporter(journal).latest(limit=1)[0]

    assert status.cycle_id == result.cycle_id
    assert status.status == "PAPER_DISPATCHED"
    assert status.intent_id == result.intent_id
    assert set(status.completed_roles) == {
        "historian",
        "reporter",
        "crowd-reader",
        "analyst",
        "committee",
        "trader",
        "coach",
        "secretary",
        "orchestrator",
    }
    assert status.skipped_roles == ()


def test_desk_status_cli_reads_existing_journal_without_creating_one(
    tmp_path, monkeypatch, capsys
):
    runtime, request, _, _, _, journal, _ = _runtime_fixture(tmp_path)
    runtime.run_cycle(
        request,
        authorize_dispatch=_authorize_dispatch_for(journal),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "sensei",
            "desk-status",
            "--journal",
            str(tmp_path / "sensei.sqlite3"),
            "--limit",
            "1",
        ],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["status"] == "PAPER_DISPATCHED"
    assert "trader" in payload[0]["completed_roles"]


def test_desk_status_includes_failed_closed_cycles(tmp_path):
    runtime, request, _, _, _, journal, _ = _runtime_fixture(tmp_path)

    class BrokenReporter:
        def report(self, instrument_id, *, as_of, memory_context=None):
            raise RuntimeError("news unavailable")

    runtime.reporter = BrokenReporter()
    with pytest.raises(DeskCycleFailed):
        runtime.run_cycle(replace(request, command_id="failed-status-cycle"))

    status = DeskStatusReporter(journal).latest(limit=1)[0]
    assert status.status == "FAILED"
    assert status.reason == "news unavailable"
    assert status.intent_id is None
