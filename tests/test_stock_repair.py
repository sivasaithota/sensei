import json
import hashlib
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from sensei.data.stock_repair import (
    MISSING_SESSIONS, MANIFEST_NAME, audit_missing_adjustments,
    build_calendar_clean_snapshot, remove_confirmed_holiday_placeholders,
    verify_repair_snapshot,
)


def bars():
    return pd.DataFrame({"open": [100., 100., 101.], "high": [101., 100., 102.],
        "low": [99., 100., 100.], "close": [100., 100., 101.],
        "volume": [1000, 0, 2000], "turnover": [100000., 0., 202000.]},
        index=pd.to_datetime(["2026-01-14", "2026-01-15", "2026-01-16"]))


def test_only_confirmed_empty_holiday_rows_are_removed():
    source = bars()
    source.loc[pd.Timestamp("2026-01-19")] = source.iloc[1]
    result, exclusions = remove_confirmed_holiday_placeholders(source)
    pd.testing.assert_frame_equal(result, source.drop(pd.Timestamp("2026-01-15")))
    assert len(exclusions) == 1
    assert exclusions[0]["row"]["close"] == 100
    assert pd.Timestamp("2026-01-19") in result.index


@pytest.mark.parametrize("column,value", [("volume", 1), ("high", 101), ("turnover", 1)])
def test_non_placeholder_on_holiday_blocks_repair(column, value):
    source = bars()
    source.loc[pd.Timestamp("2026-01-15"), column] = value
    with pytest.raises(ValueError, match="not an empty flat placeholder"):
        remove_confirmed_holiday_placeholders(source)


def test_snapshot_preserves_sources_and_checks_output_integrity(tmp_path):
    source = tmp_path / "prices"
    source.mkdir()
    bars().to_parquet(source / "A.parquet")
    raw = (source / "A.parquet").read_bytes()
    snapshot = build_calendar_clean_snapshot(prices_path=source, output_directory=tmp_path / "repaired")
    manifest = verify_repair_snapshot(snapshot)
    assert manifest["removed_row_count"] == 1
    assert manifest["inserted_rows"] == 0
    assert manifest["admissible"] is False
    assert (source / "A.parquet").read_bytes() == raw
    assert build_calendar_clean_snapshot(prices_path=source, output_directory=tmp_path / "repaired") == snapshot
    (snapshot / "A.parquet").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="content mismatch"):
        verify_repair_snapshot(snapshot)


def test_invalid_input_does_not_leave_partial_snapshot(tmp_path):
    source = tmp_path / "prices"
    source.mkdir()
    bars().to_parquet(source / "A.parquet")
    bad = bars()
    bad.loc[pd.Timestamp("2026-01-15"), "volume"] = 1
    bad.to_parquet(source / "Z.parquet")
    with pytest.raises(ValueError):
        build_calendar_clean_snapshot(prices_path=source, output_directory=tmp_path / "repaired")
    assert not (tmp_path / "repaired").exists()


@pytest.mark.parametrize("change", ["exclusions", "output"])
def test_changing_manifest_evidence_cannot_preserve_snapshot_identity(tmp_path, change):
    source = tmp_path / "prices"
    source.mkdir()
    bars().to_parquet(source / "A.parquet")
    snapshot = build_calendar_clean_snapshot(prices_path=source, output_directory=tmp_path / "repairs")
    path = snapshot / MANIFEST_NAME
    manifest = json.loads(path.read_text())
    if change == "exclusions":
        manifest["removed_rows"] = {}
        manifest["removed_row_count"] = 0
    else:
        target = snapshot / "A.parquet"
        target.write_bytes(b"replacement")
        manifest["outputs"]["A.parquet"] = hashlib.sha256(target.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="evidence mismatch"):
        verify_repair_snapshot(snapshot)
    # Updating the duplicate evidence in identity still cannot preserve the ID.
    for key in ("outputs", "removed_rows", "removed_row_count"):
        manifest["identity"][key] = manifest[key]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="identity mismatch"):
        verify_repair_snapshot(snapshot)


def test_neighbour_agreement_does_not_authorize_gap_insertion(tmp_path):
    targets = pd.to_datetime(list(MISSING_SESSIONS))
    calendar = pd.DatetimeIndex(sorted([d + offset for d in targets
        for offset in (pd.Timedelta(days=-1), pd.Timedelta(days=0), pd.Timedelta(days=1))]))
    prices = tmp_path / "prices"
    prices.mkdir()
    frame = pd.DataFrame({"open": 50., "high": 51., "low": 49., "close": 50., "volume": 200},
        index=calendar.difference(targets))
    frame.to_parquet(prices / "A.parquet")
    pd.DataFrame({"close": 100.}, index=calendar).to_parquet(tmp_path / "benchmark.parquet")
    pd.DataFrame({"symbol": ["A"], "isin": ["IDENTITY"]}).to_csv(tmp_path / "universe.csv", index=False)

    @dataclass
    class Reference:
        trade_date: date

    class RawStore:
        def verified_session(self, day):
            raw = pd.DataFrame({"symbol": ["A"], "series": ["EQ"], "isin": ["IDENTITY"],
                "instrument_class": ["equity"], "ok": [True], "open": [100.], "high": [102.],
                "low": [98.], "close": [100.], "volume": [100]}, index=[pd.Timestamp(day)])
            return SimpleNamespace(frame=raw, reference=Reference(day))

    report = audit_missing_adjustments(prices_path=prices, universe_path=tmp_path / "universe.csv",
        benchmark_path=tmp_path / "benchmark.parquet", output_path=tmp_path / "audit.json", raw_store=RawStore())
    assert report["counts"] == {"NEIGHBOURS_AGREE_EXACT_FACTOR_UNVERIFIED": 4}
    assert report["inserted_rows"] == report["exact_date_factors_verified"] == 0
    assert all(not row["can_insert"] for row in report["rows"])
    pd.testing.assert_frame_equal(pd.read_parquet(prices / "A.parquet"), frame)
