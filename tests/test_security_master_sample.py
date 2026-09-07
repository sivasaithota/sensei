import gzip

import pytest

from sensei.research.security_master_sample import read_master, reconcile


HEADER = ["TckrSymb", "SctySrs", "ISIN", "FinInstrmId", "SctyTpFlg"]
BODY = ",".join(HEADER) + "\nSBIN,EQ,INE062A01020,3045,0\nBANKBEES,EQ,INF204KB15I9,11439,4\n"


def test_bounded_parser_preserves_raw_flags_without_inferring_eligibility():
    body, rows = read_master(gzip.compress(BODY.encode()), HEADER)
    assert body.decode() == BODY
    assert [r["SctyTpFlg"] for r in rows] == ["0", "4"]
    assert "eligible" not in rows[0]


@pytest.mark.parametrize("body", ["<html>error</html>", BODY.replace("ISIN", "Unknown"),
    BODY + "SBIN,EQ,INE062A01020,999,0\n", BODY.replace("11439", "3045"),
    BODY + "SHORT,ROW\n", ",".join(HEADER) + "\n"])
def test_malformed_or_ambiguous_master_rejects(body):
    with pytest.raises(ValueError):
        read_master(gzip.compress(body.encode()), HEADER)


def test_gzip_truncation_and_decompression_bomb_reject():
    with pytest.raises(ValueError):
        read_master(gzip.compress(BODY.encode())[:-4], HEADER)
    with pytest.raises(ValueError, match="decompression"):
        read_master(gzip.compress(b"x" * (32 * 1024 * 1024 + 1)), HEADER)


def test_missing_isin_and_wrong_token_are_reported_not_silently_dropped():
    _, rows = read_master(gzip.compress(BODY.encode()), HEADER)
    observations = [{**rows[0], "FinInstrmId": "999"}, {**rows[1], "ISIN": "OLD"}]
    result = reconcile(rows, observations)
    assert result["observed_count"] == 2
    assert result["matched_count"] == 0
    assert len(result["missing"]) == len(result["token_mismatches"]) == 1
    assert result["master_only_count"] == 1
    assert result["missing"][0]["raw_token"] == "11439"
    assert result["observed_count"] == result["matched_count"] + result["missing_count"] + result["token_mismatch_count"]


def test_exact_identity_and_token_match_retains_nonordinary_example():
    _, rows = read_master(gzip.compress(BODY.encode()), HEADER)
    result = reconcile(rows, rows)
    assert result["matched_count"] == 2
    assert result["matched_raw_type_flags"] == {"0": 1, "4": 1}
    assert result["matched_rows"] == rows
    assert result["missing_count"] == result["token_mismatch_count"] == 0


def test_duplicate_raw_identity_rejects():
    _, rows = read_master(gzip.compress(BODY.encode()), HEADER)
    with pytest.raises(ValueError, match="ambiguous"):
        reconcile(rows, [rows[0], rows[0]])
