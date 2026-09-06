import json
from datetime import date, timedelta

import httpx
import pandas as pd
import pytest

from sensei.data.kite_history import (
    KiteDataError, KiteHistoryClient, KiteRawStore, KiteRequestError, AUTHORITY,
    build_plan, date_windows, digest, download, encoded, history_frame,
    master_equities, normalize, probe, verify_plan, equity_scope, private_write,
)


MASTER = b'instrument_token,tradingsymbol,exchange,segment,instrument_type\n1,TCS,NSE,NSE,EQ\n2,OTHER,NSE,NSE,EQ\n3,FUT,NFO,NFO-FUT,FUT\n'
MASTER_REQUEST = {'kind': 'master', 'as_of': '2026-09-06'}


def request(start='2024-01-19', end='2024-01-23'):
    return {'kind': 'history', 'symbol': 'TCS', 'instrument_token': 1,
            'start': start, 'end': end, 'master_sha256': digest(MASTER)}


def candles(days=('2024-01-19', '2024-01-20', '2024-01-23')):
    return encoded({'status': 'success', 'data': {'candles': [
        [d + 'T00:00:00+05:30', 100, 102, 98, 101, 500] for d in days]}})


class FixtureClient:
    def __init__(self):
        self.calls = []

    def fetch(self, req):
        self.calls.append(req)
        return MASTER if req['kind'] == 'master' else candles([req['end']])


def test_windows_cover_every_date_once_and_never_exceed_server_limit():
    start, end = date(1996, 1, 1), date(2026, 9, 4)
    windows = date_windows(start, end)
    observed = []
    for a, b in sorted(windows):
        assert (b - a).days < 2000
        observed.extend(a + timedelta(days=i) for i in range((b-a).days + 1))
    assert observed == [start + timedelta(days=i) for i in range((end-start).days+1)]


def test_master_filters_derivatives_but_does_not_claim_stock_classification():
    assert [r['symbol'] for r in master_equities(MASTER)] == ['OTHER', 'TCS']
    with pytest.raises(KiteDataError):
        master_equities(MASTER + b'4,TCS,NSE,NSE,EQ\n')


def test_plan_prioritizes_recent_history_retains_all_cash_and_unmatched_symbols(tmp_path):
    plan = build_plan(MASTER, master_request=MASTER_REQUEST, start=date(1996,1,1),
                      end=date(2026,9,4), priority_symbols=['TCS', 'RETIRED'])
    reqs = plan['identity']['requests']
    assert len(reqs) == 12
    assert reqs[0]['symbol'] == 'TCS' and reqs[0]['start'] == '2022-01-01'
    assert reqs[1]['symbol'] == 'OTHER'
    assert plan['identity']['missing_priority_symbols'] == ['RETIRED']
    assert plan['admissible'] is False


@pytest.mark.parametrize('mutation', ['duplicate', 'range', 'ohlc', 'volume', 'boolean', 'error', 'timezone'])
def test_bad_candles_fail_instead_of_becoming_data(mutation):
    payload = json.loads(candles())
    rows = payload['data']['candles']
    if mutation == 'duplicate': rows.append(rows[0])
    elif mutation == 'range': rows[0][0] = '2023-01-01T00:00:00+05:30'
    elif mutation == 'ohlc': rows[0][2] = 90
    elif mutation == 'volume': rows[0][5] = -1
    elif mutation == 'boolean': rows[0][1] = True
    elif mutation == 'error': payload = {'status': 'error', 'message': 'not entitled'}
    elif mutation == 'timezone': rows[0][0] = '2024-01-19'
    with pytest.raises(KiteDataError): history_frame(encoded(payload), request())


def test_special_weekend_session_is_preserved_and_empty_is_honest():
    assert pd.Timestamp('2024-01-20') in history_frame(candles(), request()).index
    assert history_frame(candles([]), request()).empty


def test_resume_verifies_bytes_and_does_not_redownload_empty_windows(tmp_path, monkeypatch):
    monkeypatch.setattr('sensei.data.kite_history.probe', lambda *args: {'coverage_passed': True})
    store, client = KiteRawStore(tmp_path), FixtureClient()
    store.capture(MASTER_REQUEST, client)
    plan = build_plan(MASTER, master_request=MASTER_REQUEST, start=date(2024,1,1), end=date(2024,1,23))
    report = download(plan, store, client, progress=lambda *a, **k: None)
    assert report['new_requests'] == 2
    calls = len(client.calls)
    assert download(plan, store, client, progress=lambda *a, **k: None)['cached'] == 2
    assert len(client.calls) == calls
    output, result = normalize(plan, store)
    assert result['total_rows'] == 2 and result['can_trade'] is False
    assert len(list(output.glob('*.parquet'))) == 2
    raw, _ = store.paths(plan['identity']['requests'][0])
    raw.write_bytes(b'corrupt')
    with pytest.raises(KiteDataError, match='integrity'):
        download(plan, store, client)
    assert len(client.calls) == calls


def test_plan_cannot_request_token_not_in_the_captured_master(tmp_path):
    store = KiteRawStore(tmp_path)
    store.capture(MASTER_REQUEST, FixtureClient())
    plan = build_plan(MASTER, master_request=MASTER_REQUEST, start=date(2024,1,1), end=date(2024,1,23))
    plan['identity']['requests'][0]['instrument_token'] = 999
    plan['plan_id'] = digest(encoded(plan['identity']))
    with pytest.raises(KiteDataError, match='does not match'):
        verify_plan(plan, store)


@pytest.mark.parametrize('status', [403, 429])
def test_authentication_and_throttling_stop_without_repeated_requests(status):
    calls = []
    def handler(req):
        calls.append(req)
        assert req.method == 'GET'
        assert 'secret' not in str(req.url)
        return httpx.Response(status, json={'message': 'sensitive-server-detail'})
    client = KiteHistoryClient('key', 'secret', http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(KiteRequestError) as error:
        client.fetch(request())
    assert len(calls) == 1
    assert 'sensitive' not in str(error.value) and 'secret' not in str(error.value)


def test_retry_rate_limit_is_shared_by_every_request():
    now, sleeps, calls = [0.0], [], []
    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds
    def handler(req):
        calls.append(now[0])
        return httpx.Response(503 if len(calls) == 1 else 200, content=candles())
    client = KiteHistoryClient('key', 'token', http=httpx.Client(transport=httpx.MockTransport(handler)),
                               sleeper=sleep, clock=lambda: now[0])
    client.fetch(request())
    client.fetch(request())
    assert all(b-a >= .5 for a,b in zip(calls,calls[1:]))


def test_missing_probe_sessions_never_grant_bulk_coverage(tmp_path):
    store, client = KiteRawStore(tmp_path), FixtureClient()
    report = probe(MASTER, MASTER_REQUEST, store, client)
    assert report['coverage_passed'] is False
    assert report['adjustment_factors_verified'] is False
    assert any(row['status'] == 'REQUIRED_SESSION_MISSING' for row in report['checks'])
    store.capture(MASTER_REQUEST, client)
    plan = build_plan(MASTER, master_request=MASTER_REQUEST, start=date(2022,1,1), end=date(2026,9,4))
    calls = len(client.calls)
    with pytest.raises(KiteDataError, match='resume are blocked'):
        download(plan, store, client)
    assert len(client.calls) == calls  # only verified cached probes; no bulk calls


@pytest.mark.parametrize('removal', ['instrument', 'window'])
def test_incomplete_plan_cannot_claim_its_original_scope(tmp_path, removal):
    store = KiteRawStore(tmp_path)
    store.capture(MASTER_REQUEST, FixtureClient())
    plan = build_plan(MASTER, master_request=MASTER_REQUEST, start=date(1996,1,1), end=date(2026,9,4))
    requests = plan['identity']['requests']
    if removal == 'instrument':
        plan['identity']['requests'] = [r for r in requests if r['symbol'] != 'TCS']
    else:
        requests.pop()
    plan['plan_id'] = digest(encoded(plan['identity']))
    with pytest.raises(KiteDataError, match='complete|gap'):
        verify_plan(plan, store)


def test_equity_classification_binds_reference_bytes_and_preserves_unmatched_names(tmp_path):
    reference = tmp_path / 'equities.csv'
    content = b'SYMBOL,SERIES,ISIN NUMBER\nTCS,EQ,INE-TCS\nRETIRED,EQ,INE-RETIRED\n'
    private_write(reference, content)
    private_write(reference.with_suffix('.manifest.json'), encoded({'source': 'fixture', 'sha256': digest(content)}))
    scope = equity_scope(MASTER, [reference])
    assert [r['symbol'] for r in scope['selected']] == ['TCS']
    assert scope['excluded_master_symbols'] == ['OTHER']
    assert scope['unmatched_exchange_symbols'][0]['symbol'] == 'RETIRED'
    store = KiteRawStore(tmp_path / 'store')
    store.capture(MASTER_REQUEST, FixtureClient())
    plan = build_plan(MASTER, master_request=MASTER_REQUEST, start=date(2024,1,1), end=date(2024,1,23), scope=scope)
    verify_plan(plan, store)
    reference.write_bytes(content.replace(b'TCS', b'OTHER'))
    with pytest.raises(KiteDataError, match='classification'):
        verify_plan(plan, store)


def test_empty_windows_are_cached_and_never_filled(tmp_path, monkeypatch):
    monkeypatch.setattr('sensei.data.kite_history.probe', lambda *args: {'coverage_passed': True})
    class EmptyClient(FixtureClient):
        def fetch(self, req):
            self.calls.append(req)
            return MASTER if req['kind'] == 'master' else candles([])
    store, client = KiteRawStore(tmp_path), EmptyClient()
    store.capture(MASTER_REQUEST, client)
    plan = build_plan(MASTER, master_request=MASTER_REQUEST, start=date(2024,1,1), end=date(2024,1,23))
    assert download(plan, store, client, progress=lambda *a, **k: None)['empty_responses'] == 2
    assert download(plan, store, client, progress=lambda *a, **k: None)['cached'] == 2
    assert len(client.calls) == 3
    _, result = normalize(plan, store)
    assert result['total_rows'] == 0 and result['instruments'] == 2


def test_conflicting_vendor_rows_are_preserved_without_stopping_other_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr('sensei.data.kite_history.probe', lambda *args: {'coverage_passed': True})
    payload = json.loads(candles(['2024-01-23']))
    payload['data']['candles'].append(['2024-01-23T00:00:00+05:30', 99, 103, 98, 100, 900])
    conflicting = encoded(payload)

    class ConflictClient(FixtureClient):
        def fetch(self, req):
            if req.get('symbol') == 'OTHER':
                self.calls.append(req)
                return conflicting
            return super().fetch(req)

    store, client = KiteRawStore(tmp_path), ConflictClient()
    store.capture(MASTER_REQUEST, client)
    plan = build_plan(MASTER, master_request=MASTER_REQUEST, start=date(2024,1,1),
                      end=date(2024,1,23), priority_symbols=['TCS'])
    report = download(plan, store, client, progress=lambda *a, **k: None)
    assert report['rejected_responses'] == 1
    assert report['new_requests'] == 2
    good, bad = plan['identity']['requests']
    assert store.verified(good) is not None
    assert store.verified(bad) is None
    assert store.verified_rejection(bad) == conflicting
    calls = len(client.calls)
    assert download(plan, store, client, progress=lambda *a, **k: None)['rejected_responses'] == 1
    assert len(client.calls) == calls
    with pytest.raises(KiteDataError, match='Complete the capture'):
        normalize(plan, store)
    assert not list((tmp_path / 'normalized').rglob('*.parquet'))
    rejection, _ = store.rejection_paths(bad)
    rejection.write_bytes(b'corrupt')
    with pytest.raises(KiteDataError, match='integrity'):
        download(plan, store, client)
    assert len(client.calls) == calls
