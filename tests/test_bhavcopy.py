"""Tests for the NSE bhavcopy raw ingestion (PRELIMINARY_RAW, quarantined)."""

import io
import json
import zipfile
from datetime import date, timedelta

import httpx
import pandas as pd
import pytest

from sensei.data import bhavcopy
from sensei.data.bhavcopy import (
    BhavcopySchemaError, FetchStatus, ProvenanceError, QuarantinedRawBhavcopy,
)

_HEADER = (
    "TradDt,BizDt,Sgmt,FinInstrmTp,ISIN,TckrSymb,SctySrs,"
    "OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,"
    "TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd\n"
)
_SAMPLE = _HEADER + (
    "2026-08-14,2026-08-14,CM,STK,INE009A01021,INFY,EQ,"
    "1500,1520,1490,1510,1510,1495,1000000,1510000000,50000\n"
    "2026-08-14,2026-08-14,CM,STK,INE002A01018,RELIANCE,EQ,"
    "2900,2950,2880,2930,2930,2905,2000000,5860000000,80000\n"
    "2026-08-14,2026-08-14,CM,STK,IN0020200070,1018GS2026,GS,"
    "99,99.5,98.9,99.2,99.2,99.1,500,49600,20\n"
    "2026-08-14,2026-08-14,CM,IDX,,NIFTY50,,"
    "24000,24100,23950,24050,24050,23990,0,0,0\n"
    "2026-08-14,2026-08-14,CM,STK,INE999X01099,DELISTEDCO,EQ,"
    "0,0,0,0,0,10,0,0,0\n"
)


def _zip_of(csv_text: str, name: str = "BhavCopy.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, csv_text)
    return buf.getvalue()


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler),
                        headers=bhavcopy._HEADERS, follow_redirects=True)


def _ok_fetch(day: date = date(2026, 8, 14), **over):
    sample = _SAMPLE.replace("2026-08-14", day.isoformat())
    return bhavcopy.FetchResult(
        FetchStatus.OK, csv_bytes=sample.encode(), raw_zip=_zip_of(sample),
        source_uri=bhavcopy.bhavcopy_url(day), http_status=200, **over)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("SENSEI_BHAVCOPY_DIR", str(tmp_path / "derived"))
    monkeypatch.setenv("SENSEI_BHAVCOPY_RAW_DIR", str(tmp_path / "raw"))
    return tmp_path


# ---- parsing / classification / integrity ----

def test_parse_keeps_all_rows_and_classifies():
    df = bhavcopy.parse_bhavcopy(_SAMPLE)
    assert len(df) == 5
    eq = df[df["instrument_class"] == "equity"]
    assert set(eq["symbol"]) == {"INFY", "RELIANCE", "DELISTEDCO"}
    assert set(df[df["instrument_class"] == "non_equity"]["symbol"]) == {"1018GS2026", "NIFTY50"}


def test_integrity_flags_bad_rows():
    df = bhavcopy.parse_bhavcopy(_SAMPLE)
    bad = df[~df["ok"]]
    assert set(bad["symbol"]) == {"DELISTEDCO"}
    assert (bad["issue"] == "nonpositive_price").all()


def test_close_outside_range_is_quarantined():
    row = ("2026-08-14,2026-08-14,CM,STK,INE111A01011,WEIRD,EQ,"
           "100,110,90,200,200,95,10,2000,3\n")
    df = bhavcopy.parse_bhavcopy(_HEADER + row)
    assert not df.iloc[0]["ok"] and df.iloc[0]["issue"] == "close_outside_range"


def test_equities_clean_returns_only_clean_equities():
    clean = bhavcopy.equities_clean(bhavcopy.parse_bhavcopy(_SAMPLE))
    assert set(clean["symbol"]) == {"INFY", "RELIANCE"}
    assert "instrument_class" not in clean.columns


def test_invalid_utf8_fails_closed():
    with pytest.raises(BhavcopySchemaError, match="not valid UTF-8"):
        bhavcopy.parse_bhavcopy(b"\xff\xfe\x00bad")


def test_missing_required_column_fails_closed():
    with pytest.raises(BhavcopySchemaError, match="missing required columns"):
        bhavcopy.parse_bhavcopy(_SAMPLE.replace("ClsPric,", ""))


def test_wrong_trade_date_fails_closed():
    with pytest.raises(BhavcopySchemaError, match="!= requested"):
        bhavcopy.parse_bhavcopy(_SAMPLE, expected_day=date(2026, 8, 13))


def test_invalid_trade_date_fails_closed_without_expected_day():
    malformed = _SAMPLE.replace("2026-08-14,2026-08-14,CM,STK,INE009A01021", "not-a-date,2026-08-14,CM,STK,INE009A01021", 1)
    with pytest.raises(BhavcopySchemaError, match="invalid TradDt"):
        bhavcopy.parse_bhavcopy(malformed)


def test_malformed_numeric_field_fails_closed():
    malformed = _SAMPLE.replace(",1500,1520,1490,1510,", ",not-a-price,1520,1490,1510,", 1)
    with pytest.raises(BhavcopySchemaError, match="invalid numeric field"):
        bhavcopy.parse_bhavcopy(malformed)


def test_non_finite_numeric_field_fails_closed():
    malformed = _SAMPLE.replace(",1500,1520,1490,1510,", ",inf,1520,1490,1510,", 1)
    with pytest.raises(BhavcopySchemaError, match="invalid numeric field"):
        bhavcopy.parse_bhavcopy(malformed)


def test_blank_last_trade_price_is_allowed_when_required_ohlcv_is_valid():
    historical_variant = _SAMPLE.replace(",1510,1510,1495,", ",1510,,1495,", 1)
    frame = bhavcopy.parse_bhavcopy(historical_variant)
    row = frame[frame["symbol"] == "INFY"].iloc[0]
    assert pd.isna(row["last"])
    assert row["ok"]


def test_equity_row_with_empty_symbol_fails_closed():
    malformed = _SAMPLE.replace(",INE009A01021,INFY,EQ,", ",INE009A01021,,EQ,", 1)
    with pytest.raises(BhavcopySchemaError, match="empty equity symbol"):
        bhavcopy.parse_bhavcopy(malformed)


def test_negative_volume_is_quarantined():
    malformed = _SAMPLE.replace(",1000000,1510000000,", ",-1,1510000000,", 1)
    frame = bhavcopy.parse_bhavcopy(malformed)
    row = frame[frame["symbol"] == "INFY"].iloc[0]
    assert not row["ok"]
    assert row["issue"] == "negative_volume_or_turnover"


def test_too_many_rows_fails_closed(monkeypatch):
    monkeypatch.setattr(bhavcopy, "_MAX_ROWS", 2)
    with pytest.raises(BhavcopySchemaError, match="row count exceeds"):
        bhavcopy.parse_bhavcopy(_SAMPLE)


# ---- typed fetch outcomes, retry, bounds ----

def _handler(cm_response):
    def h(req):
        if "content/cm" in str(req.url):
            return cm_response()
        return httpx.Response(200, text="ok")
    return h


def test_fetch_ok():
    res = bhavcopy.fetch_bhavcopy(date(2026, 8, 14),
                                 client=_mock_client(_handler(lambda: httpx.Response(200, content=_zip_of(_SAMPLE)))))
    assert res.status is FetchStatus.OK and res.raw_zip and res.csv_bytes


def test_fetch_not_published_on_404():
    res = bhavcopy.fetch_bhavcopy(date(2026, 8, 15),
                                 client=_mock_client(_handler(lambda: httpx.Response(404))))
    assert res.status is FetchStatus.NOT_PUBLISHED


def test_fetch_malformed_on_bad_zip():
    res = bhavcopy.fetch_bhavcopy(date(2026, 8, 14),
                                 client=_mock_client(_handler(lambda: httpx.Response(200, content=b"not-a-zip"))))
    assert res.status is FetchStatus.MALFORMED


def test_fetch_empty_when_zip_has_no_csv():
    res = bhavcopy.fetch_bhavcopy(date(2026, 8, 14),
                                 client=_mock_client(_handler(lambda: httpx.Response(200, content=_zip_of("x", name="readme.txt")))))
    assert res.status is FetchStatus.EMPTY


def test_fetch_retries_then_succeeds():
    calls = {"n": 0}
    def cm():
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, content=_zip_of(_SAMPLE))
    slept = []
    res = bhavcopy.fetch_bhavcopy(date(2026, 8, 14), client=_mock_client(_handler(cm)),
                                  max_attempts=3, sleep=slept.append)
    assert res.status is FetchStatus.OK
    assert calls["n"] == 3 and len(slept) == 2       # backed off twice


def test_fetch_retryable_after_exhausting_attempts():
    res = bhavcopy.fetch_bhavcopy(date(2026, 8, 14),
                                  client=_mock_client(_handler(lambda: httpx.Response(429))),
                                  max_attempts=2, sleep=lambda _: None)
    assert res.status is FetchStatus.RETRYABLE and res.retryable
    assert res.http_status == 429


def test_fetch_oversize_zip_is_malformed(monkeypatch):
    monkeypatch.setattr(bhavcopy, "_MAX_ZIP_BYTES", 10)
    res = bhavcopy.fetch_bhavcopy(date(2026, 8, 14),
                                  client=_mock_client(_handler(lambda: httpx.Response(200, content=_zip_of(_SAMPLE)))))
    assert res.status is FetchStatus.MALFORMED and "size" in res.detail


# ---- transactional persistence + provenance verification ----

def test_snapshot_writes_verified_artifact_set(store):
    day = date(2026, 8, 14)
    assert bhavcopy.snapshot_day(day, client=_mock_client(_handler(lambda: httpx.Response(200, content=_zip_of(_SAMPLE))))) is FetchStatus.OK
    assert bhavcopy.snapshot_path(day).exists()
    assert bhavcopy.raw_zip_path(day).exists()
    assert bhavcopy.manifest_path(day).exists()
    assert bhavcopy.verify_snapshot(day) is True
    man = json.loads(bhavcopy.manifest_path(day).read_text())
    assert man["rows_total"] == 5 and man["rows_equity"] == 3
    assert man["rows_equity_clean"] == 2 and man["rows_quarantined"] == 1
    assert not list(bhavcopy.snapshot_path(day).parent.glob("*.tmp"))


def test_verify_rejects_empty_manifest(store):
    day = date(2026, 8, 14)
    bhavcopy.snapshot_day(day, client=_mock_client(_handler(lambda: httpx.Response(200, content=_zip_of(_SAMPLE)))))
    bhavcopy.manifest_path(day).write_text("{}")          # schema now invalid
    assert bhavcopy.verify_snapshot(day) is False


def test_verify_rejects_tampered_parquet(store):
    day = date(2026, 8, 14)
    bhavcopy.snapshot_day(day, client=_mock_client(_handler(lambda: httpx.Response(200, content=_zip_of(_SAMPLE)))))
    bhavcopy.snapshot_path(day).write_bytes(b"tampered")   # hash no longer matches
    assert bhavcopy.verify_snapshot(day) is False


def test_verify_rejects_zip_whose_csv_does_not_match_manifest(store):
    day = date(2026, 8, 14)
    bhavcopy.snapshot_day(day, client=_mock_client(_handler(lambda: httpx.Response(200, content=_zip_of(_SAMPLE)))))
    changed = _SAMPLE.replace("1510,1510,1495", "1511,1511,1495", 1)
    bhavcopy.raw_zip_path(day).write_bytes(_zip_of(changed))
    manifest = json.loads(bhavcopy.manifest_path(day).read_text())
    manifest["sha256_zip"] = bhavcopy._sha256(bhavcopy.raw_zip_path(day).read_bytes())
    bhavcopy.manifest_path(day).write_text(json.dumps(manifest))
    assert bhavcopy.verify_snapshot(day) is False


def test_verify_requires_retained_raw_zip(store):
    day = date(2026, 8, 14)
    bhavcopy.snapshot_day(
        day,
        client=_mock_client(
            _handler(lambda: httpx.Response(200, content=_zip_of(_SAMPLE)))
        ),
    )
    bhavcopy.raw_zip_path(day).unlink()
    assert bhavcopy.verify_snapshot(day) is False


def test_verify_rejects_manifest_row_count_mismatch(store):
    day = date(2026, 8, 14)
    bhavcopy.snapshot_day(
        day,
        client=_mock_client(
            _handler(lambda: httpx.Response(200, content=_zip_of(_SAMPLE)))
        ),
    )
    manifest = json.loads(bhavcopy.manifest_path(day).read_text())
    manifest["rows_total"] += 1
    bhavcopy.manifest_path(day).write_text(json.dumps(manifest))
    assert bhavcopy.verify_snapshot(day) is False


def test_verified_read_rejects_parquet_decode_budget(store, monkeypatch):
    day = date(2026, 8, 14)
    bhavcopy.snapshot_day(
        day,
        client=_mock_client(
            _handler(lambda: httpx.Response(200, content=_zip_of(_SAMPLE)))
        ),
    )
    monkeypatch.setattr(bhavcopy, "_MAX_PARQUET_DECODED_BYTES", 1)
    with pytest.raises(ProvenanceError):
        QuarantinedRawBhavcopy().raw_session(day)


def test_verify_rejects_parser_version_drift(store, monkeypatch):
    day = date(2026, 8, 14)
    bhavcopy.snapshot_day(day, client=_mock_client(_handler(lambda: httpx.Response(200, content=_zip_of(_SAMPLE)))))
    monkeypatch.setattr(bhavcopy, "PARSER_VERSION", "bhavcopy-parser/999")
    assert bhavcopy.verify_snapshot(day) is False


def test_snapshot_idempotent_and_overwrite(store, monkeypatch):
    calls = {"n": 0}
    def fake(day, *, client=None, **k):
        calls["n"] += 1
        return _ok_fetch(day)
    monkeypatch.setattr(bhavcopy, "fetch_bhavcopy", fake)
    day = date(2026, 8, 14)
    bhavcopy.snapshot_day(day)
    bhavcopy.snapshot_day(day)               # verified -> no fetch
    assert calls["n"] == 1
    bhavcopy.snapshot_day(day, overwrite=True)
    assert calls["n"] == 2


def test_rebuild_from_raw_upgrades_stale_parser_without_network(store):
    day = date(2026, 8, 14)
    _seed(day)
    manifest = json.loads(bhavcopy.manifest_path(day).read_text())
    manifest["parser_version"] = "bhavcopy-parser/old"
    bhavcopy.manifest_path(day).write_text(json.dumps(manifest))

    assert bhavcopy.verify_snapshot(day) is False
    assert bhavcopy.rebuild_from_raw(day) is FetchStatus.OK
    assert bhavcopy.verify_snapshot(day) is True
    rebuilt = json.loads(bhavcopy.manifest_path(day).read_text())
    assert rebuilt["parser_version"] == bhavcopy.PARSER_VERSION


def test_rebuild_from_raw_rejects_tampered_archive(store):
    day = date(2026, 8, 14)
    _seed(day)
    bhavcopy.raw_zip_path(day).write_bytes(_zip_of(_SAMPLE + "\n"))
    assert bhavcopy.rebuild_from_raw(day) is FetchStatus.MALFORMED


def test_non_ok_fetch_writes_nothing(store, monkeypatch):
    monkeypatch.setattr(bhavcopy, "fetch_bhavcopy",
                        lambda day, *, client=None, **k: bhavcopy.FetchResult(FetchStatus.RETRYABLE))
    assert bhavcopy.snapshot_day(date(2026, 8, 15)) is FetchStatus.RETRYABLE
    assert not bhavcopy.snapshot_path(date(2026, 8, 15)).exists()


def test_parse_failure_becomes_malformed_not_raise(store, monkeypatch):
    monkeypatch.setattr(bhavcopy, "fetch_bhavcopy",
                        lambda day, *, client=None, **k: bhavcopy.FetchResult(
                            FetchStatus.OK, csv_bytes=b"garbage,not,udiff\n1,2,3",
                            raw_zip=b"z", source_uri="u", http_status=200))
    assert bhavcopy.snapshot_day(date(2026, 8, 14)) is FetchStatus.MALFORMED


# ---- gap detection, holidays, batch resilience ----

def _seed(day):
    """Write an internally hash-consistent snapshot via the commit path."""
    result = _ok_fetch(day)
    bhavcopy._commit(
        day,
        bhavcopy.parse_bhavcopy(result.csv_bytes, expected_day=day),
        result,
    )
    assert bhavcopy.verify_snapshot(day)


def test_missing_sessions_finds_internal_hole(store):
    _seed(date(2026, 8, 11))
    gaps = bhavcopy.missing_sessions(date(2026, 8, 10), date(2026, 8, 14))
    assert date(2026, 8, 10) in gaps and date(2026, 8, 11) not in gaps
    assert all(g.weekday() < 5 for g in gaps)


def test_catch_up_heals_internal_gap(store, monkeypatch):
    _seed(date(2026, 8, 11))
    attempted = []
    monkeypatch.setattr(bhavcopy, "snapshot_day",
                        lambda d, *, client=None, overwrite=False: attempted.append(d) or FetchStatus.OK)
    bhavcopy.catch_up(through=date(2026, 8, 14), max_lookback_days=10)
    assert date(2026, 8, 10) in attempted and date(2026, 8, 11) not in attempted


def test_old_not_published_remains_an_unresolved_gap(store, monkeypatch):
    monkeypatch.setattr(bhavcopy, "fetch_bhavcopy",
                        lambda day, *, client=None, **k: bhavcopy.FetchResult(FetchStatus.NOT_PUBLISHED))
    old = date.today() - timedelta(days=30)
    bhavcopy.snapshot_day(old)
    assert old in bhavcopy.missing_sessions(old, old)


def test_recent_not_published_not_recorded(store, monkeypatch):
    monkeypatch.setattr(bhavcopy, "fetch_bhavcopy",
                        lambda day, *, client=None, **k: bhavcopy.FetchResult(FetchStatus.NOT_PUBLISHED))
    recent = date.today()
    bhavcopy.snapshot_day(recent)
    assert recent in bhavcopy.missing_sessions(recent, recent)


def test_catch_up_rejects_negative_lookback(store):
    with pytest.raises(ValueError, match="non-negative"):
        bhavcopy.catch_up(max_lookback_days=-1)


def test_snapshot_range_rejects_reversed(store):
    with pytest.raises(ValueError, match="precede"):
        bhavcopy.snapshot_range(date(2026, 8, 14), date(2026, 8, 1))


# ---- quarantined interface ----

def test_quarantined_source_is_non_admissible(store):
    _seed(date(2026, 8, 14))
    src = QuarantinedRawBhavcopy()
    assert src.ADMISSIBLE is False
    assert src.sessions() == [date(2026, 8, 14)]
    eq = src.equities(date(2026, 8, 14))
    assert set(eq["symbol"]) == {"INFY", "RELIANCE"}


def test_verified_session_capability_cannot_be_publicly_constructed(store):
    day = date(2026, 8, 14)
    reference = bhavcopy.BhavcopySessionReference(
        trade_date=day,
        parser_version=bhavcopy.PARSER_VERSION,
        manifest_sha256="a" * 64,
        zip_sha256="b" * 64,
        csv_sha256="c" * 64,
        parquet_sha256="d" * 64,
        source_uri=bhavcopy.bhavcopy_url(day),
    )
    with pytest.raises(TypeError, match="verifier-issued"):
        bhavcopy.VerifiedBhavcopySession(
            bhavcopy.parse_bhavcopy(_SAMPLE),
            reference,
            _token=object(),
        )


def test_quarantined_read_fails_on_bad_provenance(store):
    _seed(date(2026, 8, 14))
    bhavcopy.snapshot_path(date(2026, 8, 14)).write_bytes(b"tampered")
    with pytest.raises(ProvenanceError):
        QuarantinedRawBhavcopy().equities(date(2026, 8, 14))


# ---- config ----

def test_base_dir_env_overridable(tmp_path, monkeypatch):
    monkeypatch.setenv("SENSEI_BHAVCOPY_DIR", str(tmp_path))
    assert bhavcopy.base_dir() == tmp_path
    monkeypatch.delenv("SENSEI_BHAVCOPY_DIR")
    assert bhavcopy.base_dir() == bhavcopy._DEFAULT_DIR


def test_snapshot_path_partitions_by_year(tmp_path, monkeypatch):
    monkeypatch.setenv("SENSEI_BHAVCOPY_DIR", str(tmp_path))
    assert bhavcopy.snapshot_path(date(2026, 8, 14)) == tmp_path / "2026" / "BhavCopy_20260814.parquet"


def test_snapshot_range_attempts_weekend_sessions(store, monkeypatch):
    """NSE holds live Saturday (budget/DR) and even Sunday sessions. Skipping
    weekends drops real sessions and breaks prev_close continuity, which shows
    up downstream as phantom corporate actions."""
    seen = []
    monkeypatch.setattr(bhavcopy, "_attempt",
                        lambda d, http, overwrite: seen.append(d) or "not_published")
    # 2026-01-31 Sat, 2026-02-01 Sun
    bhavcopy.snapshot_range(date(2026, 1, 30), date(2026, 2, 2))
    assert date(2026, 1, 31) in seen and date(2026, 2, 1) in seen
