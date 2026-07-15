from datetime import date
from types import SimpleNamespace

from sensei.automation.governed_entry import GovernedPaperEntrySession
from sensei.automation.runner import TaskOutcomeState
from sensei.automation.scheduling import SchedulerTaskKind, ScheduledTask, scheduled_task_id
from tests.test_desk_runtime import _authorize_dispatch_for, _runtime_fixture


def test_scheduler_entry_session_crosses_desk_coordinator_kernel_and_gateway(tmp_path):
    runtime, request, _, _, gateway, journal, _ = _runtime_fixture(tmp_path)

    class Planner:
        def build(self, **kwargs):
            return request

    session = GovernedPaperEntrySession(
        planner=Planner(),
        desk=runtime,
        account_and_health=lambda now, command_id: (
            request.account_snapshot,
            request.operational_health,
        ),
        authorize_dispatch=_authorize_dispatch_for(journal),
    )
    policy = "swing-session-v1"
    task = ScheduledTask(
        task_id=scheduled_task_id(
            kind=SchedulerTaskKind.ENTRY_SESSION,
            trading_date=date(2025, 1, 10),
            policy_version=policy,
        ),
        kind=SchedulerTaskKind.ENTRY_SESSION,
        trading_date=date(2025, 1, 10),
        due_at=request.now,
        expires_at=request.now,
        policy_version=policy,
    )
    gateway.queue_entry_fill(cumulative_quantity=1, average_price_paise=10_000)

    outcome = session(task, request.now)

    assert outcome.state is TaskOutcomeState.COMPLETED
    assert outcome.reason_codes == ("GOVERNED_PAPER_DISPATCHED",)
    assert len(gateway.commands) == 2
    assert any(event.event_type == "EpisodeStarted" for event in journal.read_all())
    assert any(
        event.event_type == "BrokerCommandPrepared"
        and event.payload.get("command", {}).get("kind") == "PROTECTION"
        for event in journal.read_all()
    )
