"""Deployment-neutral scheduler lease, heartbeat, and passive watchdog."""

from __future__ import annotations

import fcntl
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time as wall_time, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo

from sensei.operations import OperationalJournal

from .scheduling import SchedulerLedger, SwingSessionPolicy

IST = ZoneInfo("Asia/Kolkata")


class SchedulerAlreadyRunning(RuntimeError):
    """A second scheduler process attempted to enter the execution lease."""


class SchedulerHealthState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"


@dataclass(frozen=True)
class SchedulerHealthReport:
    state: SchedulerHealthState
    checked_at: datetime
    reason_codes: tuple[str, ...]
    heartbeat: dict[str, object]
    lock_held: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "checked_at": self.checked_at.isoformat(),
            "reason_codes": list(self.reason_codes),
            "heartbeat": self.heartbeat,
            "lock_held": self.lock_held,
        }

    @property
    def exit_code(self) -> int:
        return {
            SchedulerHealthState.HEALTHY: 0,
            SchedulerHealthState.DEGRADED: 1,
            SchedulerHealthState.OFFLINE: 2,
        }[self.state]


class SchedulerLease:
    """Enforce one scheduler process and publish atomic wakeup heartbeats."""

    def __init__(
        self, *, heartbeat_path: Path, lock_path: Path,
        now=lambda: datetime.now(timezone.utc),
        deployed_commit: str = "unknown",
    ) -> None:
        self._heartbeat_path = Path(heartbeat_path)
        self._lock_path = Path(lock_path)
        self._now = now
        self._commit = deployed_commit.strip() or "unknown"
        self._handle = None
        self._instance_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"

    def __enter__(self) -> "SchedulerLease":
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._lock_path.open("a+")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._handle.close()
            self._handle = None
            raise SchedulerAlreadyRunning(
                "another scheduler instance owns the process lease"
            ) from exc
        try:
            self._write("RUNNING")
        except Exception:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None
            raise
        return self

    def __exit__(self, exception_type, _exception, _traceback) -> None:
        if self._handle is None:
            return
        try:
            self._write("FAILED" if exception_type else "IDLE")
        finally:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None

    def _write(self, phase: str) -> None:
        observed_at = self._now()
        _aware(observed_at)
        existing = _read_json(self._heartbeat_path) or {}
        payload = {
            "schema_version": "1.0",
            "instance_id": self._instance_id,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "phase": phase,
            "observed_at": observed_at.isoformat(),
            "first_observed_at": existing.get(
                "first_observed_at", observed_at.isoformat()
            ),
            "timezone": "Asia/Kolkata",
            "runtime_timezone": os.environ.get("TZ") or time.tzname[0],
            "runtime_utc_offset_minutes": int(
                (datetime.now().astimezone().utcoffset() or timedelta()).total_seconds()
                // 60
            ),
            "deployed_commit": self._commit,
        }
        _atomic_json(self._heartbeat_path, payload)


class SchedulerWatchdog:
    """Passively derive scheduler health; never runs or retries a task."""

    def __init__(
        self, *, journal_path: Path, heartbeat_path: Path, lock_path: Path,
        expected_commit: str | None = None,
        maximum_heartbeat_age: timedelta = timedelta(minutes=7),
        maximum_task_runtime: timedelta = timedelta(minutes=10),
        policy: SwingSessionPolicy | None = None,
    ) -> None:
        if maximum_heartbeat_age <= timedelta(0):
            raise ValueError("maximum heartbeat age must be positive")
        if maximum_task_runtime <= maximum_heartbeat_age:
            raise ValueError("maximum task runtime must exceed heartbeat age")
        self._journal_path = Path(journal_path)
        self._heartbeat_path = Path(heartbeat_path)
        self._lock_path = Path(lock_path)
        self._expected_commit = expected_commit
        self._maximum_age = maximum_heartbeat_age
        self._maximum_task_runtime = maximum_task_runtime
        self._policy = policy or SwingSessionPolicy()

    def inspect(self, *, now: datetime) -> SchedulerHealthReport:
        _aware(now)
        heartbeat = _read_json(self._heartbeat_path)
        if heartbeat is None:
            reason = (
                "SCHEDULER_HEARTBEAT_INVALID"
                if self._heartbeat_path.exists()
                else "SCHEDULER_HEARTBEAT_MISSING"
            )
            return self._report(
                SchedulerHealthState.OFFLINE, now,
                (reason,), {}, False,
            )
        reasons: list[str] = []
        try:
            observed_at = datetime.fromisoformat(str(heartbeat["observed_at"]))
            first_observed_at = datetime.fromisoformat(
                str(heartbeat["first_observed_at"])
            )
            _aware(observed_at)
            _aware(first_observed_at)
        except (KeyError, TypeError, ValueError):
            return self._report(
                SchedulerHealthState.OFFLINE, now,
                ("SCHEDULER_HEARTBEAT_INVALID",), heartbeat, False,
            )
        if (
            heartbeat.get("schema_version") != "1.0"
            or heartbeat.get("phase") not in {"RUNNING", "IDLE", "FAILED"}
            or not str(heartbeat.get("instance_id", "")).strip()
            or not str(heartbeat.get("hostname", "")).strip()
            or not isinstance(heartbeat.get("pid"), int)
            or not str(heartbeat.get("deployed_commit", "")).strip()
            or not isinstance(heartbeat.get("runtime_utc_offset_minutes"), int)
        ):
            return self._report(
                SchedulerHealthState.OFFLINE, now,
                ("SCHEDULER_HEARTBEAT_INVALID",), heartbeat, False,
            )
        age = now.astimezone(timezone.utc) - observed_at.astimezone(timezone.utc)
        lock_held = _lock_is_held(self._lock_path)
        local_pid_alive = (
            heartbeat.get("hostname") != socket.gethostname()
            or _pid_exists(int(heartbeat["pid"]))
        )
        coherent_running = (
            heartbeat.get("phase") == "RUNNING"
            and lock_held
            and local_pid_alive
        )
        if age > self._maximum_age and not coherent_running:
            reasons.append("SCHEDULER_HEARTBEAT_STALE")
        if coherent_running and age > self._maximum_task_runtime:
            reasons.append("SCHEDULER_TASK_RUNTIME_EXCEEDED")
        if age < -timedelta(seconds=30):
            reasons.append("SCHEDULER_CLOCK_AHEAD")
        if heartbeat.get("timezone") != "Asia/Kolkata":
            reasons.append("SCHEDULER_TIMEZONE_INVALID")
        if (
            heartbeat.get("runtime_timezone") not in {"Asia/Kolkata", "IST"}
            or heartbeat.get("runtime_utc_offset_minutes") != 330
        ):
            reasons.append("SCHEDULER_RUNTIME_TIMEZONE_INVALID")
        if (
            self._expected_commit
            and heartbeat.get("deployed_commit") != self._expected_commit
        ):
            reasons.append("SCHEDULER_COMMIT_MISMATCH")
        if heartbeat.get("deployed_commit") == "unknown":
            reasons.append("SCHEDULER_COMMIT_UNKNOWN")
        if heartbeat.get("phase") == "RUNNING" and not lock_held:
            reasons.append("SCHEDULER_ORPHANED_RUN")
        if heartbeat.get("phase") != "RUNNING" and lock_held:
            reasons.append("SCHEDULER_LOCK_HELD_WITHOUT_RUNNING_HEARTBEAT")
        if heartbeat.get("phase") == "FAILED":
            reasons.append("SCHEDULER_LAST_WAKE_FAILED")
        if (
            heartbeat.get("phase") == "RUNNING"
            and heartbeat.get("hostname") == socket.gethostname()
            and not _pid_exists(int(heartbeat["pid"]))
        ):
            reasons.append("SCHEDULER_PROCESS_NOT_FOUND")
        if not self._journal_path.is_file():
            reasons.append("GOVERNED_JOURNAL_MISSING")
        else:
            try:
                journal = OperationalJournal.open_read_only(self._journal_path)
                verified = journal.verify().ok
                resolved = (
                    SchedulerLedger(journal).resolved_task_ids()
                    if verified else frozenset()
                )
            except (OSError, ValueError, sqlite3.DatabaseError):
                verified = False
                resolved = frozenset()
            if not verified:
                reasons.append("JOURNAL_INTEGRITY_FAILED")
            else:
                decision = self._policy.due_tasks(
                    now,
                    resolved_task_ids=resolved,
                )
                reasons.extend(halt.reason.value for halt in decision.halts)
                previous = _previous_trading_day(
                    now.astimezone(IST).date(), self._policy
                )
                first_observed = first_observed_at.astimezone(IST).date()
                if first_observed <= previous:
                    previous_close = datetime.combine(
                        previous, wall_time(23, 59), tzinfo=IST
                    )
                    prior_decision = self._policy.due_tasks(
                        previous_close, resolved_task_ids=resolved,
                    )
                    reasons.extend(
                        "PREVIOUS_SESSION_" + halt.reason.value
                        for halt in prior_decision.halts
                    )
        offline_reasons = {
            "SCHEDULER_HEARTBEAT_STALE", "SCHEDULER_ORPHANED_RUN",
            "SCHEDULER_PROCESS_NOT_FOUND", "GOVERNED_JOURNAL_MISSING",
            "JOURNAL_INTEGRITY_FAILED",
        }
        state = (
            SchedulerHealthState.OFFLINE
            if offline_reasons.intersection(reasons)
            else SchedulerHealthState.DEGRADED if reasons
            else SchedulerHealthState.HEALTHY
        )
        return self._report(state, now, tuple(dict.fromkeys(reasons)), heartbeat, lock_held)

    @staticmethod
    def _report(state, now, reasons, heartbeat, lock_held):
        return SchedulerHealthReport(state, now, tuple(reasons), heartbeat, lock_held)


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _lock_is_held(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("r") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return False


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _previous_trading_day(day: date, policy: SwingSessionPolicy) -> date:
    candidate = day - timedelta(days=1)
    while not policy.is_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")


def deployed_commit(root: Path = Path.cwd()) -> str:
    """Resolve immutable deployment identity from environment or Git."""

    configured = os.environ.get("SENSEI_DEPLOYED_COMMIT", "").strip()
    if configured:
        return configured
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root,
            check=True, capture_output=True, text=True, timeout=2,
        ).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


__all__ = [
    "SchedulerAlreadyRunning", "SchedulerHealthReport", "SchedulerHealthState",
    "SchedulerLease", "SchedulerWatchdog",
    "deployed_commit",
]
