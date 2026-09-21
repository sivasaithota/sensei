"""Frozen, price-only historical AI pilot; local evidence, no market downloads."""
from dataclasses import asdict, replace
from hashlib import sha256
import argparse
import json
from pathlib import Path

import pandas as pd

from sensei.backtest.ai_portfolio import run_ai_portfolio
from sensei.backtest.relative_strength import MomentumPolicy, run_momentum_portfolio
from sensei.research.relative_strength_run import prepare_inputs, compare_benchmark
from sensei.research.split_reproduction import pinned


def run(output):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    source = Path('config/liquid-relative-strength-v8.json')
    plan = json.loads(source.read_text())
    start, end = pd.Timestamp('2025-06-30'), pd.Timestamp('2025-08-29')
    policy = MomentumPolicy(**plan['policy'])
    # Register dates, selection rule and accounting before any model outputs exist.
    registration = {'status': 'REGISTERED', 'start': str(start.date()), 'end': str(end.date()),
        'capital': policy.capital, 'universe_rule': 'Top 20 prior-60-session median turnover among dated tradable stocks at inception; freeze thereafter',
        'decision_schedule': 'source calendar month ends strictly before end',
        'maximum_model_calls': 14, 'source_plan_sha256': sha256(source.read_bytes()).hexdigest(),
        'ai_policy': asdict(replace(policy, trailing_exit=False)),
        'evidence_scope': 'Price/volume only, archive availability assumed; no historical news or fundamentals',
        'out_of_sample_claim': False, 'model_cost_included': False}
    files = ['src/sensei/backtest/ai_portfolio.py', 'src/sensei/backtest/relative_strength.py',
             'src/sensei/investment/cycle.py', 'src/sensei/investment/models.py', 'src/sensei/llm.py', __file__]
    registration['implementations'] = {str(p): sha256(Path(p).read_bytes()).hexdigest() for p in files}
    (root/'registration.json').write_text(json.dumps(registration, indent=2))
    try:
        for spec in [plan['contract'], *plan['implementations']]:
            pinned(spec)
        (root/'v8-verification.json').write_text(json.dumps({'verified': [plan['contract'], *plan['implementations']]}, indent=2))
        inputs, tri, evidence = prepare_inputs(plan['source_plan'], first_formation=start,
                                              end=end, repairs=plan.get('repairs'))
        candidates = []
        for symbol in sorted(inputs.tradable[start]):
            value = inputs.turnover60[symbol].get(start)
            history = inputs.raw.frames[symbol].loc[:start].tail(21)
            if pd.notna(value) and value >= 50_000_000 and len(history) == 21 and start in history.index:
                candidates.append((float(value), symbol))
        universe = [symbol for _, symbol in sorted(candidates, key=lambda item: (-item[0], item[1]))[:20]]
        if len(universe) != 20:
            raise ValueError('insufficient inception liquidity coverage')
        formations = {d: f for d, f in inputs.formations.items() if start <= d < end}
        if len(formations) != 2:
            raise ValueError('unexpected decision schedule; refusing unregistered call count')
        (root/'inputs.json').write_text(json.dumps({'universe': universe, 'evidence': evidence}, indent=2, default=str))
        filtered = {}
        for day, ranking in formations.items():
            if isinstance(ranking, str):
                raise ValueError(f'momentum control unavailable: {ranking}')
            filtered[day] = ranking.loc[ranking.index.isin(universe)].copy()
        # Same accounting, window and candidate universe; frozen momentum mechanics.
        control = run_momentum_portfolio(replace(inputs, formations=filtered), policy,
                                         formation_start=start, end=end)
        control['tri_comparison'] = compare_benchmark(control, tri, policy.maximum_drawdown_pct)
        (root/'momentum.json').write_text(json.dumps(control, indent=2))
        ai = run_ai_portfolio(replace(inputs, formations=formations), replace(policy, trailing_exit=False),
                              formation_start=start, end=end, universe=universe, output=root/'ai')
        comparison = {'status': 'COMPLETE', 'authority': 'RESEARCH_ONLY', 'can_trade': False,
            'ai_return_pct': ai['return_pct'], 'ai_max_drawdown_pct': ai['max_drawdown_pct'],
            'ai_fills': len(ai['fills']), 'momentum_return_pct': control['return_pct'],
            'momentum_max_drawdown_pct': control['max_drawdown_pct'],
            'ai_tri_comparison': compare_benchmark(ai, tri, policy.maximum_drawdown_pct),
            'limitations': ['Retrospective price-only evidence; model historical hindsight possible',
                'Inception universe drawn from existing research panel, not survivorship-free full exchange',
                'Model costs unknown and excluded; returns include execution fees and configured subscription overhead',
                'Same-universe momentum control uses frozen mechanics; not a rerun of the full-universe headline',
                'AI ATR sizing/trailing exits disabled; price gaps and execution risk caps may reduce fills',
                'Review horizons recorded but this pilot acts only on registered monthly dates']}
        (root/'comparison.json').write_text(json.dumps(comparison, indent=2))
        return comparison
    except Exception as exc:
        (root/'failure.json').write_text(json.dumps({'status': 'FAILED', 'error': str(exc)}, indent=2))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output')
    print(json.dumps(run(parser.parse_args().output), indent=2))
