from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone, timedelta
from threading import Barrier

import pytest

from sensei.operations import OperationalJournal
from sensei.research.exposure import EXPOSURE_STREAM, ResearchDataAlreadyExposed, ResearchExposureLedger


@pytest.mark.parametrize("purpose,same_campaign", [("discovery", False), ("discovery", True), ("confirmation", False)])
def test_colliding_exposures_preserve_records_and_holdout_exclusivity(tmp_path, purpose, same_campaign):
    path = tmp_path / "journal.sqlite3"
    journals = [OperationalJournal(path), OperationalJournal(path)]
    barrier = Barrier(2)

    def synchronize_first_read(journal):
        read = journal.read_stream
        first = True
        def synchronized(stream):
            nonlocal first
            result = read(stream)
            if first:
                first = False
                barrier.wait(timeout=5)
            return result
        journal.read_stream = synchronized

    for journal in journals:
        synchronize_first_read(journal)

    def record(i):
        try:
            ResearchExposureLedger(journals[i]).record(
                start=date(2027, 1, 1), end=date(2027, 2, 1),
                campaign_id="same" if same_campaign else f"campaign-{i}",
                snapshot_id="snapshot", purpose=purpose,
                now=datetime(2028, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=i))
        except ResearchDataAlreadyExposed:
            return "exposed"
        return "recorded"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(record, range(2)))
    events = OperationalJournal(path).read_stream(EXPOSURE_STREAM)
    if purpose == "confirmation":
        assert sorted(results) == ["exposed", "recorded"]
        assert len(events) == 1
    else:
        assert results == ["recorded", "recorded"]
        assert len(events) == (1 if same_campaign else 2)
    assert [event.stream_sequence for event in events] == list(range(1, len(events) + 1))
