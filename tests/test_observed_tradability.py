"""Behavioral tests for the quarantined observed-tradability research seam."""

from datetime import date

import pandas as pd
import pytest

from sensei.data import bhavcopy
from sensei.data.bhavcopy import (
    BhavcopySessionReference,
    QuarantinedRawBhavcopy,
    VerifiedBhavcopySession,
)
from sensei.research.observed_tradability import (
    ObservedTradabilityError,
    build_observed_tradability,
)


class _Source(QuarantinedRawBhavcopy):

    def __init__(self, frames: dict[date, pd.DataFrame]) -> None:
        self._frames = frames

    def sessions(self) -> list[date]:
        return sorted(self._frames)

    def verified_session(self, day: date) -> VerifiedBhavcopySession:
        return bhavcopy._issue_verified_session(
            self._frames[day].copy(),
            BhavcopySessionReference(
                trade_date=day,
                parser_version="test-parser/1",
                manifest_sha256="a" * 64,
                zip_sha256="b" * 64,
                csv_sha256="c" * 64,
                parquet_sha256="d" * 64,
                source_uri=f"test://{day}",
            ),
        )


def _frame(day: date, *rows: dict) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame.index = pd.DatetimeIndex([pd.Timestamp(day)] * len(frame), name="date")
    return frame


def _row(
    symbol: str,
    isin: str,
    *,
    series: str = "EQ",
    open_price: float = 100.0,
    close: float = 101.0,
    ok: bool = True,
) -> dict:
    return {
        "symbol": symbol,
        "series": series,
        "isin": isin,
        "open": open_price,
        "high": max(open_price, close) + 1,
        "low": min(open_price, close) - 1,
        "close": close,
        "volume": 1000,
        "turnover": 100_000,
        "instrument_class": "equity",
        "ok": ok,
        "issue": "" if ok else "bad_row",
    }


def test_observation_never_claims_listing_delisting_membership_or_adjustment():
    day = date(2026, 8, 3)
    report = build_observed_tradability(
        _Source({day: _frame(day, _row("ACME", "INE000A01001"))})
    )

    assert report.ADMISSIBLE is False
    assert len(report.observations) == 1
    observation = report.observations[0]
    assert observation.observed_traded is True
    assert observation.listing_status == "unknown"
    assert observation.delisting_status == "unknown"
    assert observation.index_membership_status == "unknown"
    assert observation.price_adjustment_status == "raw_unadjusted"
    assert report.source_references[0].trade_date == day


def test_absence_between_sessions_does_not_close_or_delist_identity():
    first, missing, last = date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)
    report = build_observed_tradability(
        _Source(
            {
                first: _frame(first, _row("ACME", "INE000A01001", close=100)),
                missing: _frame(missing, _row("OTHER", "INE999A01001")),
                last: _frame(last, _row("ACME", "INE000A01001", open_price=101)),
            }
        )
    )

    episode = next(item for item in report.identity_episodes if item.symbol == "ACME")
    assert episode.first_observed == first
    assert episode.last_observed == last
    assert episode.observed_sessions == 2
    assert episode.listing_status == "unknown"
    assert episode.delisting_status == "unknown"


def test_symbol_change_for_same_isin_creates_observed_alias_episodes_only():
    first, last = date(2026, 8, 3), date(2026, 8, 4)
    report = build_observed_tradability(
        _Source(
            {
                first: _frame(first, _row("OLDNAME", "INE000A01001")),
                last: _frame(last, _row("NEWNAME", "INE000A01001")),
            }
        )
    )

    assert {item.symbol for item in report.identity_episodes} == {"OLDNAME", "NEWNAME"}
    assert {item.observed_key for item in report.identity_episodes} == {
        "isin:INE000A01001"
    }
    assert all(item.authority == "observed_only" for item in report.identity_episodes)


def test_return_to_prior_alias_starts_a_new_observed_episode():
    first, second, third = (
        date(2026, 8, 3),
        date(2026, 8, 4),
        date(2026, 8, 5),
    )
    report = build_observed_tradability(
        _Source(
            {
                first: _frame(first, _row("OLDNAME", "INE000A01001")),
                second: _frame(second, _row("NEWNAME", "INE000A01001")),
                third: _frame(third, _row("OLDNAME", "INE000A01001")),
            }
        )
    )

    old_episodes = [
        item for item in report.identity_episodes if item.symbol == "OLDNAME"
    ]
    assert len(old_episodes) == 2
    assert {item.first_observed for item in old_episodes} == {first, third}


def test_large_overnight_gap_is_quarantined_as_unverified_action_candidate():
    first, last = date(2026, 8, 3), date(2026, 8, 4)
    report = build_observed_tradability(
        _Source(
            {
                first: _frame(first, _row("ACME", "INE000A01001", close=100)),
                last: _frame(last, _row("ACME", "INE000A01001", open_price=52, close=54)),
            }
        ),
        discontinuity_threshold_pct=30,
    )

    assert len(report.anomalies) == 1
    anomaly = report.anomalies[0]
    assert anomaly.session_date == last
    assert anomaly.return_pct == pytest.approx(-48.0)
    assert anomaly.reason == "observed_interval_gap_exceeds_threshold"
    assert anomaly.corporate_action_status == "unverified"
    assert anomaly.quarantined is True


def test_bad_or_non_equity_rows_never_become_observed_tradability():
    day = date(2026, 8, 3)
    report = build_observed_tradability(
        _Source(
            {
                day: _frame(
                    day,
                    _row("BAD", "INE000A01001", ok=False),
                    _row("BOND", "IN0000000002", series="GS")
                    | {"instrument_class": "non_equity"},
                )
            }
        )
    )
    assert report.observations == ()
    assert report.excluded_rows == 2


def test_string_false_integrity_flag_is_not_treated_as_true():
    day = date(2026, 8, 3)
    row = _row("BAD", "INE000A01001") | {"ok": "False"}
    report = build_observed_tradability(_Source({day: _frame(day, row)}))
    assert report.observations == ()
    assert report.excluded_rows == 1


def test_zero_activity_row_does_not_become_an_observed_trade():
    day = date(2026, 8, 3)
    row = _row("IDLE", "INE000A01001") | {"volume": 0, "turnover": 0}
    report = build_observed_tradability(_Source({day: _frame(day, row)}))
    assert report.observations == ()
    assert report.excluded_rows == 1


def test_duplicate_observed_identity_in_one_session_fails_closed():
    day = date(2026, 8, 3)
    with pytest.raises(ObservedTradabilityError, match="duplicate observed identity"):
        build_observed_tradability(
            _Source(
                {
                    day: _frame(
                        day,
                        _row("ACME", "INE000A01001"),
                        _row("ACME", "INE000A01001"),
                    )
                }
            )
        )


def test_invalid_discontinuity_threshold_is_rejected():
    with pytest.raises(ValueError, match="threshold"):
        build_observed_tradability(_Source({}), discontinuity_threshold_pct=0)


def test_unverified_frame_cannot_create_observed_facts():
    day = date(2026, 8, 3)
    source = _Source({day: _frame(day, _row("ACME", "INE000A01001"))})
    source.verified_session = lambda _: source._frames[day]  # type: ignore[method-assign]
    with pytest.raises(ObservedTradabilityError, match="verified bhavcopy capability"):
        build_observed_tradability(source)
