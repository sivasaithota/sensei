import hashlib
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from sensei.backtest.rulespec import Condition, RuleSpec
from sensei.research import (
    EvaluationFold,
    EvidenceIssueCode,
    ExaminationProtocol,
    ExaminationRequest,
    HypothesisVersion,
    LegacyYahooCurrentConstituentCatalog,
    ManifestMarketDataCatalog,
    MarketDataSnapshot,
    MembershipInterval,
    Recommendation,
    ResearchExaminer,
    SnapshotIntegrityError,
    SnapshotRequest,
)
from sensei.research.local_artifacts import materialize_daily_bars, read_regular_file


def _sha256(path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


class _ReadProxy:
    def __init__(self, content: bytes, requested_sizes: list[int]) -> None:
        self._content = content
        self._requested_sizes = requested_sizes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, size: int) -> bytes:
        self._requested_sizes.append(size)
        return self._content[:size]


def _manifest_id(manifest) -> str:
    canonical = json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _trusted_catalog(manifest_path):
    manifest = json.loads(manifest_path.read_text())
    return ManifestMarketDataCatalog(
        manifest_path=manifest_path,
        trusted_issuers={manifest["issuer"]},
        trusted_manifest_ids={_manifest_id(manifest)},
    )


def _bars(index: pd.DatetimeIndex, base: float) -> pd.DataFrame:
    close = np.arange(len(index), dtype=float) + base
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": np.full(len(index), 1_000_000),
        },
        index=index,
    )


def _write_single_instrument_catalog(tmp_path, *, issuer="trusted-test-vendor"):
    bars_dir = tmp_path / "bars"
    bars_dir.mkdir()
    bars_path = bars_dir / "INE-ONE.parquet"
    index = pd.bdate_range("2020-01-01", periods=8)
    _bars(index, 90).to_parquet(bars_path)
    membership_path = tmp_path / "membership.csv"
    membership_path.write_text(
        "universe,instrument_id,symbol,effective_from,effective_to\n"
        "NIFTY_TEST,INE-ONE,ONE,2019-01-01,\n"
    )
    manifest = {
        "schema_version": 1,
        "catalog_id": "fixture.single",
        "issuer": issuer,
        "source": {
            "provider": "fixture",
            "dataset": "historical-constituents",
            "uri": "fixture://historical-constituents",
            "retrieved_at": "2020-01-15",
            "usage_rights": "test-only",
        },
        "market": {
            "calendar": "XNSE",
            "timezone": "Asia/Kolkata",
            "currency": "INR",
            "frequency": "1d",
        },
        "membership": {
            "path": "membership.csv",
            "sha256": _sha256(membership_path),
            "bytes": membership_path.stat().st_size,
            "rows": 1,
        },
        "instruments": [
            {
                "instrument_id": "INE-ONE",
                "exchange": "NSE",
                "display_symbol": "ONE",
                "adjustment_policy": "split_adjusted",
                "bars": {
                    "path": "bars/INE-ONE.parquet",
                    "sha256": _sha256(bars_path),
                    "bytes": bars_path.stat().st_size,
                    "rows": 8,
                },
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path, bars_path, manifest, index


def _examine_always_true(snapshot, index):
    strategy = RuleSpec(
        name="always_true_fixture",
        source="Synthetic fixture",
        principle="Create a deterministic signal on every session.",
        conditions=(Condition(left="close", op=">", right=1.0),),
        stop_pct=5,
        target_pct=10,
        max_hold_days=3,
    )
    request = ExaminationRequest(
        hypothesis=HypothesisVersion(
            hypothesis_id="H-MEMBERSHIP",
            version=1,
            strategy=strategy,
            source_claim_ids=("fixture",),
        ),
        snapshot=snapshot,
        protocol=ExaminationProtocol(
            name="membership-boundary",
            version=1,
            folds=(EvaluationFold("oos", index[0].date(), index[-1].date()),),
            min_trades=1,
            min_symbols=1,
            min_expectancy_pct=-100,
        ),
    )
    return ResearchExaminer().examine(request)


def test_manifest_catalog_materializes_removed_and_current_members_with_lineage(
    tmp_path,
):
    bars_dir = tmp_path / "bars"
    bars_dir.mkdir()
    old_path = bars_dir / "INE-OLD.parquet"
    new_path = bars_dir / "INE-NEW.parquet"
    _bars(pd.bdate_range("2020-01-01", "2020-01-10"), 90).to_parquet(old_path)
    _bars(pd.bdate_range("2020-01-06", "2020-01-14"), 100).to_parquet(new_path)

    membership_path = tmp_path / "membership.csv"
    membership_path.write_text(
        "universe,instrument_id,symbol,effective_from,effective_to\n"
        "NIFTY_TEST,INE-OLD,OLD,2019-01-01,2020-01-08\n"
        "NIFTY_TEST,INE-NEW,NEW,2020-01-08,\n"
    )
    manifest = {
        "schema_version": 1,
        "catalog_id": "fixture.nifty-history",
        "issuer": "trusted-test-vendor",
        "source": {
            "provider": "fixture",
            "dataset": "historical-constituents",
            "uri": "fixture://historical-constituents",
            "retrieved_at": "2020-01-15",
            "usage_rights": "test-only",
        },
        "market": {
            "calendar": "XNSE",
            "timezone": "Asia/Kolkata",
            "currency": "INR",
            "frequency": "1d",
        },
        "membership": {
            "path": "membership.csv",
            "sha256": _sha256(membership_path),
            "bytes": membership_path.stat().st_size,
            "rows": 2,
        },
        "instruments": [
            {
                "instrument_id": "INE-OLD",
                "exchange": "NSE",
                "display_symbol": "OLD",
                "adjustment_policy": "split_adjusted",
                "bars": {
                    "path": "bars/INE-OLD.parquet",
                    "sha256": _sha256(old_path),
                    "bytes": old_path.stat().st_size,
                    "rows": 8,
                },
            },
            {
                "instrument_id": "INE-NEW",
                "exchange": "NSE",
                "display_symbol": "NEW",
                "adjustment_policy": "split_adjusted",
                "bars": {
                    "path": "bars/INE-NEW.parquet",
                    "sha256": _sha256(new_path),
                    "bytes": new_path.stat().st_size,
                    "rows": 7,
                },
            },
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    catalog = ManifestMarketDataCatalog(
        manifest_path=manifest_path,
        trusted_issuers={"trusted-test-vendor"},
        trusted_manifest_ids={_manifest_id(manifest)},
    )
    snapshot = catalog.snapshot(
        SnapshotRequest(
            universe="NIFTY_TEST",
            history_start=date(2020, 1, 1),
            as_of=date(2020, 1, 14),
        )
    )

    assert snapshot.instrument_ids == ("INE-NEW", "INE-OLD")
    assert snapshot.point_in_time_universe is True
    assert snapshot.membership_intervals("INE-OLD")[0].effective_to == date(
        2020, 1, 8
    )
    assert snapshot.membership_intervals("INE-NEW")[0].effective_from == date(
        2020, 1, 8
    )
    assert snapshot.lineage.catalog_id == "fixture.nifty-history"
    assert snapshot.lineage.issuer == "trusted-test-vendor"
    assert snapshot.lineage.source_uri == "fixture://historical-constituents"
    assert snapshot.lineage.manifest_id.startswith("sha256:")
    assert snapshot.snapshot_id.startswith("sha256:")


def test_regular_file_read_is_bounded_by_its_initial_size(tmp_path, monkeypatch):
    path = tmp_path / "bounded.bin"
    content = b"bounded-content"
    path.write_bytes(content)
    requested_sizes: list[int] = []
    monkeypatch.setattr(
        "sensei.research.local_artifacts.os.fdopen",
        lambda *args, **kwargs: _ReadProxy(content, requested_sizes),
    )

    assert read_regular_file(path, max_bytes=1_000) == content
    assert requested_sizes == [len(content) + 1]


def test_regular_file_growth_during_read_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "growing.bin"
    initial = b"initial"
    path.write_bytes(initial)
    monkeypatch.setattr(
        "sensei.research.local_artifacts.os.fdopen",
        lambda *args, **kwargs: _ReadProxy(initial + b"x", []),
    )

    with pytest.raises(SnapshotIntegrityError, match="changed while it was read"):
        read_regular_file(path, max_bytes=1_000)


def test_snapshot_returns_a_defensive_verified_instrument_frame(tmp_path):
    manifest_path, _, _, index = _write_single_instrument_catalog(tmp_path)
    snapshot = _trusted_catalog(manifest_path).snapshot(
        SnapshotRequest(
            universe="NIFTY_TEST",
            history_start=index[0].date(),
            as_of=index[-1].date(),
        )
    )

    returned = snapshot.frame("INE-ONE")
    original_close = returned.iloc[0]["close"]
    returned.iloc[0, returned.columns.get_loc("close")] = 1

    assert snapshot.frame("INE-ONE").iloc[0]["close"] == original_close


def test_catalog_capture_consumes_its_privately_owned_frame_without_copying():
    index = pd.bdate_range("2020-01-01", periods=3)
    frame = _bars(index, 90)
    fixture = MarketDataSnapshot._for_testing(
        bars_by_instrument={"INE-ONE": frame},
        as_of=index[-1].date(),
        universe_as_of=index[-1].date(),
        point_in_time_universe=True,
        source="synthetic ownership fixture",
    )
    memberships = {
        "INE-ONE": (
            MembershipInterval(
                universe="TEST",
                instrument_id="INE-ONE",
                symbol="ONE",
                effective_from=index[0].date(),
            ),
        )
    }

    snapshot = MarketDataSnapshot._from_catalog(
        bars_by_instrument={"INE-ONE": frame},
        history_start=index[0].date(),
        as_of=index[-1].date(),
        universe_as_of=index[-1].date(),
        point_in_time_universe=True,
        source="synthetic ownership fixture",
        memberships_by_instrument=memberships,
        lineage=fixture.lineage,
    )
    captured = object.__getattribute__(
        snapshot, "_MarketDataSnapshot__bars_by_instrument"
    )

    assert captured["INE-ONE"] is frame


def test_testing_snapshot_still_defensively_copies_caller_frames():
    index = pd.bdate_range("2020-01-01", periods=3)
    frame = _bars(index, 90)
    snapshot = MarketDataSnapshot._for_testing(
        bars_by_instrument={"INE-ONE": frame},
        as_of=index[-1].date(),
        universe_as_of=index[-1].date(),
        point_in_time_universe=True,
        source="synthetic defensive-copy fixture",
    )
    original_close = snapshot.frame("INE-ONE").iloc[0]["close"]

    frame.iloc[0, frame.columns.get_loc("close")] = 1

    assert snapshot.frame("INE-ONE").iloc[0]["close"] == original_close


def test_snapshot_runtime_hashing_is_chunked(monkeypatch):
    index = pd.date_range("2020-01-01", periods=131_073, freq="D")
    frame = _bars(index, 90)
    original_hash = pd.util.hash_pandas_object
    chunk_sizes: list[int] = []

    def counted_hash(value, *args, **kwargs):
        chunk_sizes.append(len(value))
        return original_hash(value, *args, **kwargs)

    monkeypatch.setattr(pd.util, "hash_pandas_object", counted_hash)

    MarketDataSnapshot._for_testing(
        bars_by_instrument={"INE-ONE": frame},
        as_of=index[-1].date(),
        universe_as_of=index[-1].date(),
        point_in_time_universe=True,
        source="synthetic hashing fixture",
    )

    assert max(chunk_sizes) <= 65_536


def test_catalog_snapshot_identity_does_not_depend_on_dataframe_hashing(
    tmp_path, monkeypatch
):
    manifest_path, _, _, index = _write_single_instrument_catalog(tmp_path)
    request = SnapshotRequest(
        universe="NIFTY_TEST",
        history_start=index[0].date(),
        as_of=index[-1].date(),
    )
    first = _trusted_catalog(manifest_path).snapshot(request)
    monkeypatch.setattr(
        "sensei.research.market_data._runtime_frame_content_id",
        lambda frames: "sha256:" + "f" * 64,
    )

    second = _trusted_catalog(manifest_path).snapshot(request)

    assert second.snapshot_id == first.snapshot_id


def test_snapshot_entry_eligibility_uses_half_open_membership_boundaries():
    index = pd.bdate_range("2020-02-03", periods=4)
    snapshot = MarketDataSnapshot._for_testing(
        bars_by_instrument={"INSTRUMENT-1": _bars(index, 90)},
        as_of=index[-1].date(),
        universe_as_of=index[-1].date(),
        point_in_time_universe=True,
        source="synthetic membership fixture",
        memberships_by_instrument={
            "INSTRUMENT-1": (
                MembershipInterval(
                    universe="TEST",
                    instrument_id="INSTRUMENT-1",
                    symbol="ONE",
                    effective_from=index[1].date(),
                    effective_to=index[3].date(),
                ),
            )
        },
    )

    assert snapshot.entry_eligible_on("INSTRUMENT-1", index[1].date()) is True
    assert snapshot.entry_eligible_on("INSTRUMENT-1", index[3].date()) is False


def test_snapshot_has_no_public_constructor_that_can_self_assert_admissibility():
    assert not hasattr(MarketDataSnapshot, "capture")


def test_daily_snapshot_rejects_multiple_bars_for_one_market_session():
    index = pd.DatetimeIndex(
        [
            "2020-01-02 09:15:00",
            "2020-01-02 15:30:00",
            "2020-01-03 15:30:00",
        ]
    )
    snapshot = MarketDataSnapshot._for_testing(
        bars_by_instrument={"INE-ONE": _bars(index, 90)},
        as_of=index[-1].date(),
        universe_as_of=index[-1].date(),
        point_in_time_universe=True,
        source="synthetic daily-session fixture",
    )

    dossier = _examine_always_true(snapshot, index)

    assert dossier.recommendation is Recommendation.NEEDS_MORE_EVIDENCE
    assert EvidenceIssueCode.INVALID_INDEX in {
        issue.code for issue in dossier.issues
    }


def test_snapshot_rejects_protocol_fold_with_no_universe_membership():
    index = pd.bdate_range("2020-01-01", periods=10)
    membership_end = index[5].date()
    snapshot = MarketDataSnapshot._for_testing(
        bars_by_instrument={"INE-ONE": _bars(index, 90)},
        as_of=index[-1].date(),
        universe_as_of=index[-1].date(),
        point_in_time_universe=True,
        source="synthetic fold-coverage fixture",
        memberships_by_instrument={
            "INE-ONE": (
                MembershipInterval(
                    universe="NIFTY_TEST",
                    instrument_id="INE-ONE",
                    symbol="ONE",
                    effective_from=index[0].date(),
                    effective_to=membership_end,
                ),
            )
        },
    )
    strategy = RuleSpec(
        name="fold_coverage_fixture",
        source="Synthetic fixture",
        principle="Generate deterministic trades before membership ends.",
        conditions=(Condition(left="close", op=">", right=1.0),),
        stop_pct=5,
        target_pct=10,
        max_hold_days=3,
    )
    dossier = ResearchExaminer().examine(
        ExaminationRequest(
            hypothesis=HypothesisVersion(
                hypothesis_id="H-FOLD-COVERAGE",
                version=1,
                strategy=strategy,
                source_claim_ids=("fixture",),
            ),
            snapshot=snapshot,
            protocol=ExaminationProtocol(
                name="two-fold-membership-boundary",
                version=1,
                folds=(
                    EvaluationFold(
                        "member-fold", index[0].date(), index[4].date()
                    ),
                    EvaluationFold(
                        "non-member-fold", index[5].date(), index[-1].date()
                    ),
                ),
                min_trades=1,
                min_symbols=1,
                min_expectancy_pct=-100,
            ),
        )
    )

    assert dossier.aggregate.trades > 0
    assert dossier.recommendation is Recommendation.NEEDS_MORE_EVIDENCE
    assert EvidenceIssueCode.INSUFFICIENT_FOLD_COVERAGE in {
        issue.code for issue in dossier.issues
    }


def test_examiner_does_not_enter_on_membership_effective_to_session():
    index = pd.bdate_range("2020-02-03", periods=8)
    bars = _bars(index, 90)
    entry_boundary = index[1].date()
    snapshot = MarketDataSnapshot._for_testing(
        bars_by_instrument={"INSTRUMENT-1": bars},
        as_of=index[-1].date(),
        universe_as_of=index[-1].date(),
        point_in_time_universe=True,
        source="synthetic membership fixture",
        memberships_by_instrument={
            "INSTRUMENT-1": (
                MembershipInterval(
                    universe="TEST",
                    instrument_id="INSTRUMENT-1",
                    symbol="OLD",
                    effective_from=date(2019, 1, 1),
                    effective_to=entry_boundary,
                ),
            )
        },
    )
    dossier = _examine_always_true(snapshot, index)

    assert dossier.aggregate.trades == 0


def test_entry_on_first_membership_session_can_exit_after_removal():
    index = pd.bdate_range("2020-02-03", periods=8)
    bars = _bars(index, 90)
    snapshot = MarketDataSnapshot._for_testing(
        bars_by_instrument={"INSTRUMENT-1": bars},
        as_of=index[-1].date(),
        universe_as_of=index[-1].date(),
        point_in_time_universe=True,
        source="synthetic membership fixture",
        memberships_by_instrument={
            "INSTRUMENT-1": (
                MembershipInterval(
                    universe="TEST",
                    instrument_id="INSTRUMENT-1",
                    symbol="OLD",
                    effective_from=index[1].date(),
                    effective_to=index[2].date(),
                ),
            )
        },
    )

    dossier = _examine_always_true(snapshot, index)

    assert dossier.aggregate.trades == 1
    assert dossier.aggregate.time_exits == 1


def test_membership_interval_is_part_of_snapshot_identity():
    index = pd.bdate_range("2020-02-03", periods=8)
    bars = _bars(index, 90)

    def capture(effective_to):
        return MarketDataSnapshot._for_testing(
            bars_by_instrument={"INSTRUMENT-1": bars},
            as_of=index[-1].date(),
            universe_as_of=index[-1].date(),
            point_in_time_universe=True,
            source="synthetic membership fixture",
            memberships_by_instrument={
                "INSTRUMENT-1": (
                    MembershipInterval(
                        universe="TEST",
                        instrument_id="INSTRUMENT-1",
                        symbol="OLD",
                        effective_from=date(2019, 1, 1),
                        effective_to=effective_to,
                    ),
                )
            },
        )

    first = capture(index[2].date())
    revised = capture(index[3].date())

    assert first.snapshot_id != revised.snapshot_id


def test_legacy_yahoo_current_constituents_are_permanently_inadmissible(
    tmp_path, monkeypatch
):
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "company,industry,symbol,Series,isin\n"
        "Old Bias Ltd.,Industrials,BIAS,EQ,INE-BIAS\n"
    )
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir()
    index = pd.bdate_range("2020-03-02", periods=8)
    _bars(index, 90).to_parquet(prices_dir / "BIAS.parquet")
    protected_paths = (universe_path, prices_dir / "BIAS.parquet")
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in protected_paths
    }
    monkeypatch.setattr(
        pd,
        "read_csv",
        lambda *args, **kwargs: pytest.fail(
            "legacy universe ingestion must not use pandas.read_csv"
        ),
    )

    catalog = LegacyYahooCurrentConstituentCatalog(
        universe_file=universe_path,
        prices_dir=prices_dir,
        universe_as_of=date(2026, 7, 13),
        universe="NIFTY_500_CURRENT",
    )
    snapshot = catalog.snapshot(
        SnapshotRequest(
            universe="NIFTY_500_CURRENT",
            history_start=index[2].date(),
            as_of=index[-1].date(),
        )
    )

    assert snapshot.instrument_ids == ("INE-BIAS",)
    assert snapshot.point_in_time_universe is False
    assert snapshot.source == "Yahoo Finance/current-constituent backfill"
    assert snapshot.lineage.artifacts[1].row_count == 8
    assert _examine_always_true(snapshot, index).recommendation is (
        Recommendation.NEEDS_MORE_EVIDENCE
    )
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in protected_paths
    } == before
    with pytest.raises(SnapshotIntegrityError, match="named universe"):
        catalog.snapshot(
            SnapshotRequest(
                universe="SOME_OTHER_UNIVERSE",
                history_start=index[2].date(),
                as_of=index[-1].date(),
            )
        )


def test_manifest_catalog_rejects_a_bar_artifact_changed_after_registration(tmp_path):
    manifest_path, bars_path, _, index = _write_single_instrument_catalog(tmp_path)
    bars_path.write_bytes(bars_path.read_bytes() + b"tampered")
    catalog = _trusted_catalog(manifest_path)

    with pytest.raises(SnapshotIntegrityError, match="artifact size"):
        catalog.snapshot(
            SnapshotRequest(
                universe="NIFTY_TEST",
                history_start=index[0].date(),
                as_of=index[-1].date(),
            )
        )


def test_untrusted_manifest_cannot_self_assert_point_in_time_admissibility(tmp_path):
    manifest_path, _, manifest, index = _write_single_instrument_catalog(
        tmp_path, issuer="unknown-vendor"
    )
    manifest["point_in_time_universe"] = True
    manifest_path.write_text(json.dumps(manifest))
    catalog = ManifestMarketDataCatalog(
        manifest_path=manifest_path,
        trusted_issuers={"trusted-test-vendor"},
        trusted_manifest_ids={_manifest_id(manifest)},
    )

    snapshot = catalog.snapshot(
        SnapshotRequest(
            universe="NIFTY_TEST",
            history_start=index[0].date(),
            as_of=index[-1].date(),
        )
    )

    assert snapshot.point_in_time_universe is False


def test_allowlisted_issuer_cannot_impersonate_a_pinned_manifest(tmp_path):
    manifest_path, _, _, index = _write_single_instrument_catalog(tmp_path)
    catalog = ManifestMarketDataCatalog(
        manifest_path=manifest_path,
        trusted_issuers={"trusted-test-vendor"},
        trusted_manifest_ids={"sha256:" + "0" * 64},
    )

    snapshot = catalog.snapshot(
        SnapshotRequest(
            universe="NIFTY_TEST",
            history_start=index[0].date(),
            as_of=index[-1].date(),
        )
    )

    assert snapshot.point_in_time_universe is False


def test_manifest_catalog_rejects_artifact_path_traversal(tmp_path):
    manifest_path, _, manifest, index = _write_single_instrument_catalog(tmp_path)
    manifest["membership"]["path"] = "../membership.csv"
    manifest_path.write_text(json.dumps(manifest))
    catalog = _trusted_catalog(manifest_path)

    with pytest.raises(SnapshotIntegrityError, match="permitted relative path"):
        catalog.snapshot(
            SnapshotRequest(
                universe="NIFTY_TEST",
                history_start=index[0].date(),
                as_of=index[-1].date(),
            )
        )


def test_manifest_catalog_rejects_a_symlinked_artifact_directory(tmp_path):
    manifest_path, bars_path, _, index = _write_single_instrument_catalog(tmp_path)
    real_bars_dir = tmp_path / "real-bars"
    bars_path.parent.rename(real_bars_dir)
    (tmp_path / "bars").symlink_to(real_bars_dir, target_is_directory=True)
    catalog = _trusted_catalog(manifest_path)

    with pytest.raises(SnapshotIntegrityError, match="symlink"):
        catalog.snapshot(
            SnapshotRequest(
                universe="NIFTY_TEST",
                history_start=index[0].date(),
                as_of=index[-1].date(),
            )
        )


def test_manifest_catalog_verifies_referenced_corporate_actions(tmp_path):
    manifest_path, _, manifest, index = _write_single_instrument_catalog(tmp_path)
    actions_path = tmp_path / "corporate-actions.csv"
    actions_path.write_text("instrument_id,effective_on,kind\nINE-ONE,2020-01-06,split\n")
    manifest["instruments"][0]["corporate_actions"] = {
        "path": "corporate-actions.csv",
        "sha256": _sha256(actions_path),
        "bytes": actions_path.stat().st_size,
        "rows": 1,
    }
    manifest_path.write_text(json.dumps(manifest))
    actions_path.write_text(actions_path.read_text() + "tampered")
    catalog = _trusted_catalog(manifest_path)

    with pytest.raises(SnapshotIntegrityError, match="artifact size"):
        catalog.snapshot(
            SnapshotRequest(
                universe="NIFTY_TEST",
                history_start=index[0].date(),
                as_of=index[-1].date(),
            )
        )


def test_manifest_csv_ingestion_does_not_use_pandas_eager_loader(
    tmp_path, monkeypatch
):
    manifest_path, _, manifest, index = _write_single_instrument_catalog(tmp_path)
    actions_path = tmp_path / "corporate-actions.csv"
    actions_path.write_text(
        "instrument_id,effective_on,kind\nINE-ONE,2020-01-06,split\n"
    )
    manifest["instruments"][0]["corporate_actions"] = {
        "path": "corporate-actions.csv",
        "sha256": _sha256(actions_path),
        "bytes": actions_path.stat().st_size,
        "rows": 1,
    }
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(
        pd,
        "read_csv",
        lambda *args, **kwargs: pytest.fail(
            "manifest CSV ingestion must not use pandas.read_csv"
        ),
    )

    snapshot = _trusted_catalog(manifest_path).snapshot(
        SnapshotRequest(
            universe="NIFTY_TEST",
            history_start=index[0].date(),
            as_of=index[-1].date(),
        )
    )

    assert snapshot.point_in_time_universe is True


def test_manifest_catalog_rejects_mixed_adjustment_policies(tmp_path):
    manifest_path, bars_path, manifest, index = _write_single_instrument_catalog(
        tmp_path
    )
    second_path = bars_path.parent / "INE-TWO.parquet"
    second_path.write_bytes(bars_path.read_bytes())
    membership_path = tmp_path / "membership.csv"
    membership_path.write_text(
        membership_path.read_text()
        + "NIFTY_TEST,INE-TWO,TWO,2019-01-01,\n"
    )
    manifest["membership"].update(
        {
            "sha256": _sha256(membership_path),
            "bytes": membership_path.stat().st_size,
            "rows": 2,
        }
    )
    manifest["instruments"].append(
        {
            "instrument_id": "INE-TWO",
            "exchange": "NSE",
            "display_symbol": "TWO",
            "adjustment_policy": "split_and_dividend_adjusted",
            "bars": {
                "path": "bars/INE-TWO.parquet",
                "sha256": _sha256(second_path),
                "bytes": second_path.stat().st_size,
                "rows": 8,
            },
        }
    )
    manifest_path.write_text(json.dumps(manifest))
    catalog = _trusted_catalog(manifest_path)

    with pytest.raises(SnapshotIntegrityError, match="mixed adjustment"):
        catalog.snapshot(
            SnapshotRequest(
                universe="NIFTY_TEST",
                history_start=index[0].date(),
                as_of=index[-1].date(),
            )
        )


def test_manifest_catalog_rejects_an_unreferenced_instrument_record(tmp_path):
    manifest_path, _, manifest, index = _write_single_instrument_catalog(tmp_path)
    manifest["instruments"].append(
        {
            "instrument_id": "INE-ORPHAN",
            "exchange": "NSE",
            "display_symbol": "ORPHAN",
            "adjustment_policy": "split_adjusted",
            "bars": {
                "path": "bars/INE-ORPHAN.parquet",
                "sha256": "sha256:" + "0" * 64,
                "bytes": 1,
                "rows": 1,
            },
        }
    )
    manifest_path.write_text(json.dumps(manifest))
    catalog = _trusted_catalog(manifest_path)

    with pytest.raises(SnapshotIntegrityError, match="unreferenced instrument"):
        catalog.snapshot(
            SnapshotRequest(
                universe="NIFTY_TEST",
                history_start=index[0].date(),
                as_of=index[-1].date(),
            )
        )


def test_manifest_catalog_rejects_membership_interval_without_matching_bars(
    tmp_path,
):
    manifest_path, _, manifest, index = _write_single_instrument_catalog(tmp_path)
    membership_path = tmp_path / "membership.csv"
    membership_path.write_text(
        "universe,instrument_id,symbol,effective_from,effective_to\n"
        "NIFTY_TEST,INE-ONE,ONE,2019-01-01,2019-02-01\n"
        "NIFTY_TEST,INE-ONE,ONE,2020-01-01,\n"
    )
    manifest["membership"].update(
        {
            "sha256": _sha256(membership_path),
            "bytes": membership_path.stat().st_size,
            "rows": 2,
        }
    )
    manifest_path.write_text(json.dumps(manifest))
    catalog = _trusted_catalog(manifest_path)

    with pytest.raises(SnapshotIntegrityError, match="no matching bars"):
        catalog.snapshot(
            SnapshotRequest(
                universe="NIFTY_TEST",
                history_start=date(2019, 1, 1),
                as_of=index[-1].date(),
            )
        )


def test_manifest_catalog_bounds_membership_to_bar_matching_work(
    tmp_path, monkeypatch
):
    manifest_path, bars_path, manifest, _ = _write_single_instrument_catalog(
        tmp_path
    )
    index = pd.date_range("2020-01-01", periods=128, freq="2D")
    _bars(index, 90).to_parquet(bars_path)
    membership_path = tmp_path / "membership.csv"
    rows = [
        "universe,instrument_id,symbol,effective_from,effective_to"
    ]
    rows.extend(
        "NIFTY_TEST,INE-ONE,ONE,"
        f"{session.date().isoformat()},"
        f"{(session.date() + timedelta(days=1)).isoformat()}"
        for session in index
    )
    membership_path.write_text("\n".join(rows) + "\n")
    manifest["membership"].update(
        {
            "sha256": _sha256(membership_path),
            "bytes": membership_path.stat().st_size,
            "rows": len(index),
        }
    )
    manifest["instruments"][0]["bars"].update(
        {
            "sha256": _sha256(bars_path),
            "bytes": bars_path.stat().st_size,
            "rows": len(index),
        }
    )
    manifest["source"]["retrieved_at"] = index[-1].date().isoformat()
    manifest_path.write_text(json.dumps(manifest))
    original_contains = MembershipInterval.contains
    contains_calls = 0

    def counted_contains(interval, session):
        nonlocal contains_calls
        contains_calls += 1
        return original_contains(interval, session)

    monkeypatch.setattr(MembershipInterval, "contains", counted_contains)

    snapshot = _trusted_catalog(manifest_path).snapshot(
        SnapshotRequest(
            universe="NIFTY_TEST",
            history_start=index[0].date(),
            as_of=index[-1].date(),
        )
    )

    assert snapshot.instrument_ids == ("INE-ONE",)
    assert contains_calls <= 2 * len(index)


def test_manifest_cannot_attest_to_dates_after_it_was_retrieved(tmp_path):
    manifest_path, _, _, index = _write_single_instrument_catalog(tmp_path)

    with pytest.raises(SnapshotIntegrityError, match="retrieval|coverage"):
        _trusted_catalog(manifest_path).snapshot(
            SnapshotRequest(
                universe="NIFTY_TEST",
                history_start=index[0].date(),
                as_of=date(2020, 1, 16),
            )
        )


def test_manifest_catalog_rejects_artifact_over_safety_limit(tmp_path):
    manifest_path, _, manifest, index = _write_single_instrument_catalog(tmp_path)
    manifest["instruments"][0]["bars"]["bytes"] = 1_000_000_000
    manifest_path.write_text(json.dumps(manifest))
    catalog = _trusted_catalog(manifest_path)

    with pytest.raises(SnapshotIntegrityError, match="safety limit"):
        catalog.snapshot(
            SnapshotRequest(
                universe="NIFTY_TEST",
                history_start=index[0].date(),
                as_of=index[-1].date(),
            )
        )


def test_manifest_catalog_rejects_variable_width_bar_columns(
    tmp_path, monkeypatch
):
    manifest_path, bars_path, manifest, index = _write_single_instrument_catalog(
        tmp_path
    )
    frame = _bars(index, 90)
    frame["unbounded_payload"] = "variable-width"
    frame.to_parquet(bars_path)
    manifest["instruments"][0]["bars"].update(
        {
            "sha256": _sha256(bars_path),
            "bytes": bars_path.stat().st_size,
            "rows": len(frame),
        }
    )
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(
        "sensei.research.local_artifacts._read_bar_table",
        lambda *args, **kwargs: pytest.fail(
            "variable-width bars must fail before page decode"
        ),
    )

    with pytest.raises(SnapshotIntegrityError, match="fixed-width"):
        _trusted_catalog(manifest_path).snapshot(
            SnapshotRequest(
                universe="NIFTY_TEST",
                history_start=index[0].date(),
                as_of=index[-1].date(),
            )
        )


def test_manifest_catalog_preserves_fixed_width_extra_bar_columns(tmp_path):
    manifest_path, bars_path, manifest, index = _write_single_instrument_catalog(
        tmp_path
    )
    frame = _bars(index, 90)
    frame["turnover"] = np.arange(len(frame), dtype=float) + 1_000_000
    frame.to_parquet(bars_path)
    manifest["instruments"][0]["bars"].update(
        {
            "sha256": _sha256(bars_path),
            "bytes": bars_path.stat().st_size,
            "rows": len(frame),
        }
    )
    manifest_path.write_text(json.dumps(manifest))

    snapshot = _trusted_catalog(manifest_path).snapshot(
        SnapshotRequest(
            universe="NIFTY_TEST",
            history_start=index[0].date(),
            as_of=index[-1].date(),
        )
    )

    assert "turnover" in snapshot.frame("INE-ONE").columns


def test_parquet_row_shape_is_budgeted_before_page_decode(tmp_path, monkeypatch):
    rows = 100_000
    index = pd.date_range("1900-01-01", periods=rows, freq="D")
    frame = pd.DataFrame(
        {
            "open": np.full(rows, 100.0),
            "high": np.full(rows, 101.0),
            "low": np.full(rows, 99.0),
            "close": np.full(rows, 100.0),
            "volume": np.full(rows, 1_000_000),
        },
        index=index,
    )
    path = tmp_path / "compressed-constant-bars.parquet"
    frame.to_parquet(path)
    content = path.read_bytes()
    assert len(content) < 5_000_000
    monkeypatch.setattr(
        "sensei.research.local_artifacts._read_bar_table",
        lambda *args, **kwargs: pytest.fail(
            "resource preflight must reject before page decode"
        ),
    )

    with pytest.raises(SnapshotIntegrityError, match="working-memory"):
        materialize_daily_bars(
            content,
            label="constant bars",
            expected_rows=rows,
            history_start=index[0].date(),
            as_of=index[-1].date(),
            available_working_bytes=5_000_000,
            max_columns=64,
        )


def test_manifest_catalog_checks_peak_memory_before_bar_decode(
    tmp_path, monkeypatch
):
    manifest_path, _, _, index = _write_single_instrument_catalog(tmp_path)
    monkeypatch.setattr(
        "sensei.research.catalog._MAX_TOTAL_DECODED_BYTES", 100_000
    )

    with pytest.raises(SnapshotIntegrityError, match="working-memory"):
        _trusted_catalog(manifest_path).snapshot(
            SnapshotRequest(
                universe="NIFTY_TEST",
                history_start=index[0].date(),
                as_of=index[-1].date(),
            )
        )


def test_manifest_catalog_rejects_duplicate_json_keys(tmp_path):
    manifest_path, _, _, index = _write_single_instrument_catalog(tmp_path)
    manifest_path.write_text(
        '{"issuer":"forged-prefix",' + manifest_path.read_text()[1:]
    )
    collapsed = json.loads(manifest_path.read_text())
    catalog = ManifestMarketDataCatalog(
        manifest_path=manifest_path,
        trusted_issuers={"trusted-test-vendor"},
        trusted_manifest_ids={_manifest_id(collapsed)},
    )

    with pytest.raises(SnapshotIntegrityError, match="duplicate manifest key"):
        catalog.snapshot(
            SnapshotRequest(
                universe="NIFTY_TEST",
                history_start=index[0].date(),
                as_of=index[-1].date(),
            )
        )


def test_manifest_catalog_enforces_cumulative_decode_budget(tmp_path, monkeypatch):
    manifest_path, _, _, index = _write_single_instrument_catalog(tmp_path)
    monkeypatch.setattr(
        "sensei.research.catalog._MAX_TOTAL_DECODED_BYTES", 1
    )
    catalog = _trusted_catalog(manifest_path)

    with pytest.raises(SnapshotIntegrityError, match="total decoded bytes"):
        catalog.snapshot(
            SnapshotRequest(
                universe="NIFTY_TEST",
                history_start=index[0].date(),
                as_of=index[-1].date(),
            )
        )
