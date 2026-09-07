import pandas as pd
import pytest

from sensei.research.relative_strength_run import compare_benchmark


def report():
    return {'formation_start': '2025-06-30', 'return_pct': 1., 'max_drawdown_pct': 0.,
        'policy': {'capital': 300000.}, 'equity_curve': [
            {'session': '2025-07-01', 'equity': 301000., 'weights': {}, 'gross_exposure_pct': 0.},
            {'session': '2025-07-02', 'equity': 303000., 'weights': {}, 'gross_exposure_pct': 0.}]}


def test_comparison_includes_preceding_close_and_does_not_use_wrong_window():
    benchmark = pd.Series([100., 101., 102.], index=pd.to_datetime(['2025-06-30', '2025-07-01', '2025-07-02']))
    comparison = compare_benchmark(report(), benchmark, 100)
    assert comparison['return_pct'] == pytest.approx(2.)
    assert comparison['excess_total_return_percentage_points'] == pytest.approx(-1.)
    assert comparison['development_verdict'] == 'NO_DEMONSTRATED_NET_EDGE'
    with pytest.raises(ValueError, match='benchmark calendar'):
        compare_benchmark(report(), benchmark.iloc[1:], 100)
