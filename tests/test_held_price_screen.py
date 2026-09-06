import pandas as pd

from sensei.research.held_price_screen import match_endpoint


def fixture():
    row = dict(symbol="A", isin="old", series="EQ", instrument_class="equity", ok=True,
               open=100., high=110., low=90., close=105., volume=1000.)
    return pd.DataFrame([row]), pd.Series(dict(open=50., high=55., low=45., close=52.5, volume=2000.)), dict(symbol="A", isin="new", series="EQ")


def test_different_isin_is_retained_as_unverified_and_ratios_are_observations():
    raw, kite, reference = fixture()
    result = match_endpoint(raw, kite, reference)
    assert result["identity_status"] == "different_isin_unverified"
    assert result["kite_over_raw_price"]["close"] == .5
    assert result["kite_over_raw_volume"] == 2
    assert result["raw_identity"]["isin"] == "old"


def test_ambiguous_rows_are_not_resolved_by_volume_and_missing_stays_missing():
    raw, kite, reference = fixture()
    other = raw.copy(); other["volume"] = 999999; other["series"] = "BE"
    assert match_endpoint(pd.concat([raw, other]), kite, reference)["status"] == "ambiguous_candidates"
    assert match_endpoint(raw.iloc[:0], kite, reference)["status"] == "missing_candidate"


def test_zero_volume_is_unknown_and_invalid_raw_is_not_used():
    raw, kite, reference = fixture()
    raw["volume"] = 0
    assert match_endpoint(raw, kite, reference)["kite_over_raw_volume"] is None
    raw["ok"] = False
    result = match_endpoint(raw, kite, reference)
    assert result["status"] == "invalid_raw_row" and "kite_over_raw_price" not in result


def test_exact_isin_candidate_survives_symbol_rename_without_certifying_lineage():
    raw, kite, reference = fixture()
    reference.update(symbol="RENAMED", isin="old")
    result = match_endpoint(raw, kite, reference)
    assert result["status"] == "matched"
    assert result["identity_status"] == "same_current_reference_isin"
    assert result["raw_identity"]["symbol"] == "A"


def test_canonical_exchange_symbol_matches_alias_with_historical_isin():
    raw, kite, reference = fixture()
    reference.update(symbol="A-BE", exchange_symbol="A")
    result = match_endpoint(raw, kite, reference)
    assert result["status"] == "matched"
    assert result["identity_status"] == "different_isin_unverified"
    assert result["raw_identity"]["symbol"] == "A"
