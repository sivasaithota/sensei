import json
from datetime import date

import pytest

from sensei.data.nifty_benchmark import parse_nifty500_tri


def row(day="02 Jan 2024", name="Nifty 500", value="100"):
    return {"Index Name": name, "Date": day, "TotalReturnsIndex": value, "NTR_Value": "99"}


def parse(rows):
    return parse_nifty500_tri(json.dumps(rows).encode(), start=date(2024, 1, 1), end=date(2024, 1, 5))


def test_parse_gross_tri_retains_missing_sessions_and_orders_dates():
    result = parse([row("05 Jan 2024", value="105"), row()])
    assert result.close.tolist() == [100, 105]
    assert len(result) == 2


@pytest.mark.parametrize("rows", [[], [row(name="Nifty 50")], [row(), row()],
    [row(value="NaN")], [row(value="0")], [row("10 Jan 2024")]])
def test_invalid_benchmark_data_is_rejected(rows):
    with pytest.raises(ValueError):
        parse(rows)
