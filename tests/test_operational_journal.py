from datetime import datetime, timezone

import pytest

from sensei.operations.journal import (
    EventAppend,
    JournalConflict,
    JournalIntegrityError,
    OperationalJournal,
)


def test_operational_journal_appends_idempotently(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    command = EventAppend(
        stream_id="episode:EP-1",
        event_type="SignalObserved",
        payload={"instrument_id": "INE-ONE", "plan_id": "plan:abc"},
        idempotency_key="signal-1",
        expected_version=0,
        occurred_at=datetime(2026, 7, 13, 9, 15, tzinfo=timezone.utc),
    )

    first = journal.append(command)
    repeated = journal.append(command)

    assert first == repeated
    assert first.stream_sequence == 1
    assert journal.read_stream("episode:EP-1") == (first,)

    conflicting = EventAppend(
        stream_id="episode:EP-1",
        event_type="SignalObserved",
        payload={"instrument_id": "INE-DIFFERENT", "plan_id": "plan:abc"},
        idempotency_key="signal-1",
        expected_version=1,
        occurred_at=command.occurred_at,
    )
    with pytest.raises(JournalIntegrityError, match="idempotency"):
        journal.append(conflicting)


def test_operational_journal_rejects_stale_writers_without_partial_append(tmp_path):
    journal = OperationalJournal(tmp_path / "sensei.sqlite3")
    occurred_at = datetime(2026, 7, 13, 9, 15, tzinfo=timezone.utc)
    journal.append(
        EventAppend(
            stream_id="episode:EP-1",
            event_type="SignalObserved",
            payload={"instrument_id": "INE-ONE"},
            idempotency_key="signal-1",
            expected_version=0,
            occurred_at=occurred_at,
        )
    )

    with pytest.raises(JournalConflict, match="expected 0"):
        journal.append(
            EventAppend(
                stream_id="episode:EP-1",
                event_type="IntentAccepted",
                payload={"quantity": 1},
                idempotency_key="intent-1",
                expected_version=0,
                occurred_at=occurred_at,
            )
        )

    assert len(journal.read_stream("episode:EP-1")) == 1
    assert len(journal.read_all()) == 1


def test_operational_journal_requires_timezone_and_verifies_hash_chains(tmp_path):
    path = tmp_path / "sensei.sqlite3"
    journal = OperationalJournal(path)

    with pytest.raises(ValueError, match="timezone-aware"):
        EventAppend(
            stream_id="episode:EP-1",
            event_type="SignalObserved",
            payload={},
            idempotency_key="signal-1",
            expected_version=0,
            occurred_at=datetime(2026, 7, 13, 9, 15),
        )

    first = journal.append(
        EventAppend(
            stream_id="episode:EP-1",
            event_type="SignalObserved",
            payload={"tags": ["swing", "daily"]},
            idempotency_key="signal-1",
            expected_version=0,
            occurred_at=datetime(2026, 7, 13, 9, 15, tzinfo=timezone.utc),
        )
    )
    second = journal.append(
        EventAppend(
            stream_id="episode:EP-2",
            event_type="SignalObserved",
            payload={"tags": ["intraday"]},
            idempotency_key="signal-2",
            expected_version=0,
            occurred_at=datetime(2026, 7, 13, 9, 16, tzinfo=timezone.utc),
        )
    )

    reopened = OperationalJournal(path)
    assert reopened.read_all() == (first, second)
    verification = reopened.verify()
    assert verification.ok is True
    assert verification.events_checked == 2
    assert verification.errors == ()


def test_operational_journal_backup_and_restore_are_verified_and_non_overwriting(tmp_path):
    source_path = tmp_path / "source.sqlite3"
    source = OperationalJournal(source_path)
    source.append(
        EventAppend(
            stream_id="episode:EP-BACKUP",
            event_type="EpisodeStarted",
            payload={"episode_id": "EP-BACKUP"},
            idempotency_key="backup-event-1",
            expected_version=0,
            occurred_at=datetime(2026, 7, 13, 9, 15, tzinfo=timezone.utc),
        )
    )
    backup_path = tmp_path / "backups" / "sensei.sqlite3"

    backup = source.backup_to(backup_path)

    assert backup.path == backup_path
    assert backup.events == 1
    assert backup.sha256.startswith("sha256:")
    assert OperationalJournal(backup_path).verify().ok is True
    with pytest.raises(FileExistsError):
        source.backup_to(backup_path)

    restored_path = tmp_path / "restored.sqlite3"
    restored = OperationalJournal.restore_from(backup_path, restored_path)
    assert restored.verify().ok is True
    assert restored.read_all() == source.read_all()
    with pytest.raises(FileExistsError):
        OperationalJournal.restore_from(backup_path, restored_path)
