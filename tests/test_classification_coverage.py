from dataclasses import replace

import pandas as pd
import pytest

from sensei.research.classification_coverage import DatedClassification, classification_coverage


DAY = pd.Timestamp("2024-01-02")
OBSERVED = pd.DataFrame([
    {"symbol": "SBIN", "series": "EQ", "isin": "INE062A01020", "instrument_class": "equity"},
    {"symbol": "BANKBEES", "series": "EQ", "isin": "INF204KB15I9", "instrument_class": "equity"},
])


def fact(symbol="SBIN", kind="ordinary_equity", board="main"):
    row = OBSERVED[OBSERVED.symbol == symbol].iloc[0]
    return DatedClassification(symbol, row.series, row["isin"], DAY, DAY, DAY - pd.Timedelta(days=1), kind, board, "a" * 64)


def check(evidence=(), observed=OBSERVED, **kwargs):
    return classification_coverage(observed, evidence, session=DAY, as_of=kwargs.get("as_of", DAY))


def test_parser_equity_label_does_not_make_stocks_or_etfs_eligible():
    report = check()
    assert report["observed_count"] == report["unresolved_count"] == 2
    assert report["can_trade"] is report["admissible"] is False


def test_missing_observed_series_stays_visible_as_identity_gap():
    observed = OBSERVED.copy()
    observed.loc[0, "series"] = ""
    report = check([fact()], observed=observed)
    assert report["observed_count"] == report["unresolved_count"] == 2
    assert report["counts"]["unresolved_observed_identity"] == 1


def test_positive_and_negative_classification_keep_both_rows():
    report = check([fact(), fact("BANKBEES", "etf", None)])
    assert report["counts"] == {"confirmed_main_board_ordinary": 1, "confirmed_nonordinary": 1}
    assert report["observed_count"] == 2
    assert report["unresolved_count"] == 0
    assert report["admissible"] is False


def test_future_knowledge_cannot_backfill_a_missing_classification():
    assert check([replace(fact(), known_from=DAY + pd.Timedelta(days=1))]) == check()
    assert check([fact()], as_of=DAY - pd.Timedelta(days=2)) == check(as_of=DAY - pd.Timedelta(days=2))


def test_classification_is_not_forward_filled_beyond_its_interval():
    expired = replace(fact(), effective_from=DAY - pd.Timedelta(days=3), effective_through=DAY - pd.Timedelta(days=1))
    assert check([expired]) == check()


@pytest.mark.parametrize("kind,board,status", [
    (None, "main", "unresolved_security_type"), ("ordinary_equity", None, "unresolved_board"),
    ("ordinary_equity", "sme", "confirmed_sme"),
])
def test_unknown_fields_are_distinct_from_documented_exclusions(kind, board, status):
    assert check([fact(kind=kind, board=board)])["counts"][status] == 1


def test_mismatched_isin_is_not_resolved_by_matching_symbol():
    assert check([replace(fact(), isin="OLDISIN")]) == check()


def test_duplicate_or_overlapping_evidence_rejects():
    with pytest.raises(ValueError, match="overlapping"):
        check([fact(), fact()])
    with pytest.raises(ValueError, match="unique"):
        check(observed=pd.concat([OBSERVED, OBSERVED]))


def test_future_conflicting_classification_does_not_change_prior_coverage():
    future = replace(fact(kind="etf"), known_from=DAY + pd.Timedelta(days=1))
    assert check([fact(), future]) == check([fact()])


@pytest.mark.parametrize("changes", [{"source_sha256": "unknown"}, {"security_type": "STK"},
    {"effective_through": DAY - pd.Timedelta(days=1)}, {"known_from": pd.NaT}])
def test_bad_classification_evidence_rejects(changes):
    with pytest.raises(ValueError):
        check([replace(fact(), **changes)])
