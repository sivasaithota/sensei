import json
from datetime import date

import pandas as pd
import pytest

from sensei.data.kite_history import (
    KiteDataError, KiteRawStore, KiteRejectedResponse, build_plan, encoded, private_write,
)
from sensei.data.kite_validation import (
    audit_capture, build_priority_snapshot, diagnose_rejection, verify_priority_snapshot,
)


MASTER = b'instrument_token,tradingsymbol,exchange,segment,instrument_type\n1,TCS,NSE,NSE,EQ\n2,OTHER,NSE,NSE,EQ\n'
MASTER_REQUEST = {'kind': 'master', 'as_of': '2026-09-06'}


class Client:
    def fetch(self, request):
        if request['kind'] == 'master':
            return MASTER
        return encoded({'status': 'success', 'data': {'candles': [
            [request['end'] + 'T00:00:00+0530', 100, 102, 98, 101, 500]]}})


def fixture(tmp_path):
    store = KiteRawStore(tmp_path / 'store')
    store.capture(MASTER_REQUEST, Client())
    plan = build_plan(MASTER, master_request=MASTER_REQUEST,
                      start=date(2021,1,1), end=date(2026,9,4))
    plan_path = tmp_path / 'plan.json'
    private_write(plan_path, encoded(plan))
    universe = tmp_path / 'universe.csv'
    universe.write_text('symbol\nTCS\nUNMAPPED\n')
    for request in plan['identity']['requests']:
        store.capture(request, Client())
    return store, plan, plan_path, universe


def test_rejection_diagnosis_preserves_every_conflict_and_defect():
    rows = [['2024-01-02T00:00:00+0530', 0, 0, 0, 0, 200],
            ['2024-01-03T00:00:00+0530', 100, 101, 99, 100, 20],
            ['2024-01-03T00:00:00+0530', 100, 102, 99, 101, 50]]
    raw = encoded({'status': 'success', 'data': {'candles': rows}})
    result = diagnose_rejection(raw)
    assert result['duplicate_sessions'][0]['rows'] == rows[1:]
    assert result['duplicate_sessions'][0]['classification'] == 'conflicting'
    assert result['invalid_rows'][0]['row'] == rows[0]
    assert 'nonpositive_price' in result['invalid_rows'][0]['defects']
    assert json.loads(raw)['data']['candles'] == rows


@pytest.mark.parametrize('value', [10**400, float('inf')])
def test_diagnosis_reports_numeric_overflow_and_out_of_window_rows(value):
    raw = json.dumps({'status':'success','data':{'candles':[
        ['2023-12-31T00:00:00+0530', value, value, 1, 2, 30]]}}).encode()
    result = diagnose_rejection(raw, request={'start':'2024-01-01','end':'2024-01-31'})
    assert 'outside_requested_window' in result['invalid_rows'][0]['defects']
    assert 'nonfinite_or_unrepresentable_numeric_value' in result['invalid_rows'][0]['defects']
    encoded(result)  # all diagnostics, including malformed numbers, remain strict JSON


def test_snapshot_retains_scope_gaps_lineage_and_unmapped_symbols(tmp_path):
    store, plan, plan_path, universe = fixture(tmp_path)
    path = build_priority_snapshot(plan_path, store, universe, start=date(2022,1,1),
                                   end=date(2026,9,4), output=tmp_path/'snapshots')
    manifest = verify_priority_snapshot(path)
    assert manifest['identity']['unmapped_symbols'] == ['UNMAPPED']
    assert manifest['identity']['can_trade'] is False
    assert sorted(p.name for p in path.glob('*.parquet')) == ['TCS.parquet']
    frame = pd.read_parquet(path/'TCS.parquet')
    assert len(frame) == 1  # the sparse history is retained, not filled or excluded
    assert build_priority_snapshot(plan_path, store, universe, start=date(2022,1,1),
                                   end=date(2026,9,4), output=tmp_path/'snapshots') == path
    (path/'TCS.parquet').write_bytes(b'corrupt')
    with pytest.raises(KiteDataError, match='content'):
        verify_priority_snapshot(path)


def test_recent_snapshot_does_not_reclassify_a_rejected_older_window(tmp_path):
    store, plan, plan_path, universe = fixture(tmp_path)
    old = next(r for r in plan['identity']['requests'] if r['symbol']=='TCS' and r['start']=='2021-01-01')
    for p in store.paths(old): p.unlink()
    store.paths(old)[0].parent.rmdir()
    class Bad(Client):
        def fetch(self, req):
            payload = json.loads(super().fetch(req))
            payload['data']['candles'][0][1:5] = [0,0,0,0]
            return encoded(payload)
    with pytest.raises(KiteRejectedResponse): store.capture(old, Bad())
    path = build_priority_snapshot(plan_path, store, universe, start=date(2022,1,1),
                                   end=date(2026,9,4), output=tmp_path/'snapshots')
    assert verify_priority_snapshot(path)['identity']['scope_start']=='2022-01-01'
    assert store.verified_rejection(old) is not None
    with pytest.raises(KiteDataError, match='rejected'):
        build_priority_snapshot(plan_path, store, universe, start=date(2021,1,1),
                                end=date(2026,9,4), output=tmp_path/'blocked')
    assert not (tmp_path/'blocked').exists()


def test_audit_distinguishes_missing_empty_rejected_and_actual_crisis_coverage(tmp_path):
    store, plan, _, _ = fixture(tmp_path)
    request = plan['identity']['requests'][0]
    for p in store.paths(request): p.unlink()
    report = audit_capture(plan, store, progress=lambda *a, **k:None)
    # A partial pair is an integrity error, not a missing request.
    assert report['counts']['missing_windows'] == 1
    assert report['counts']['accepted_windows'] == 3
    assert report['crisis_coverage']['covid_2020_2021']['instruments_with_some_bars'] == 2
    assert report['crisis_coverage']['dotcom_2000_2002']['instruments_with_some_bars'] == 0
    assert report['admissible'] is False
    private_write(store.paths(request)[0], b'incomplete')
    with pytest.raises(KiteDataError, match='Incomplete'):
        audit_capture(plan, store, progress=lambda *a, **k:None)


def test_snapshot_verification_rejects_changed_raw_sources_and_extra_files(tmp_path):
    store, plan, plan_path, universe = fixture(tmp_path)
    path = build_priority_snapshot(plan_path, store, universe, start=date(2022,1,1),
                                   end=date(2026,9,4), output=tmp_path/'snapshots')
    (path/'EXTRA.parquet').write_bytes(b'fake')
    with pytest.raises(KiteDataError, match='instrument set'):
        verify_priority_snapshot(path)
    (path/'EXTRA.parquet').unlink()
    request = next(r for r in plan['identity']['requests'] if r['symbol']=='TCS' and r['start']=='2022-01-01')
    store.paths(request)[0].write_bytes(b'corrupt')
    with pytest.raises(KiteDataError, match='integrity|source'):
        verify_priority_snapshot(path)
