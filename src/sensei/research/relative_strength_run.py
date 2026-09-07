"""Run the registered relative-strength development batch using local evidence.

No downloads, credentials, orders or live configuration access. The closure v4
plan is retained and verified rather than rewritten to accommodate a new strategy.
"""

import argparse
from collections import Counter
from dataclasses import asdict, replace
from importlib.metadata import version
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from sensei.backtest.raw_accounting import RawAccounting
from sensei.backtest.relative_strength import MomentumInputs, MomentumPolicy, run_momentum_portfolio
from sensei.research import security_master_batch as batch
from sensei.research.raw_portfolio import load_actions, tick_reference, tick_from_reference
from sensei.research.split_reproduction import ROOT, pinned, sha
from sensei.research.stock_closure import build_raw_frames, load_snapshots, map_actions
from sensei.research.relative_strength_evidence import recover_metadata, join_documented_renames, repair_share_actions
from sensei.strategy.relative_strength import month_ends, rank_formation


def prepare_inputs(source_plan, *, first_formation, end, repairs=None):
    """Validate frozen source bytes, then construct separate decision/fill inputs."""
    content = pinned(source_plan)
    plan = json.loads(content)
    for spec in [plan['contract'], *plan['implementations'], *plan['evidence']]:
        pinned(spec)
    for bridge in plan.get('split_identity_bridges', ()):
        pinned(bridge['source'])
    scope = json.loads(pinned(plan['acquisition_scope']))
    parent = json.loads(pinned(scope['parent_manifest']))['identity']['raw_evidence']['raw_receipts']
    sample = json.loads(pinned(plan['sample_plan']))
    calendar = pd.DatetimeIndex(sorted(parent))
    frames, receipt = build_raw_frames(parent, ROOT / 'data/research/stock-closure/20260907')
    repairs = repairs or {}
    frames = join_documented_renames(frames, calendar, repairs.get('renames', []))
    snapshots, evidence = load_snapshots(scope['sessions'], sorted(parent), sample,
                                       ROOT / 'data/research/nse-master-batch/v1')
    snapshots, evidence = recover_metadata(snapshots, evidence, repairs.get('metadata', []), sorted(parent), sample)
    pinned(plan['action_manifest'])
    records, action_evidence = load_actions(ROOT / plan['action_manifest']['path'])
    print(f'Mapping {len(records)} corporate-action records', flush=True)
    actions, resets, details = map_actions(frames, records, calendar, sha(content), plan.get('split_identity_bridges', ()))
    actions = repair_share_actions(frames, calendar, actions, repairs.get('share_actions', []))
    references = {d: tick_reference(d, calendar) for d in calendar}
    previous = {d: calendar[i-1] for i, d in enumerate(calendar) if i}
    ticks, turnover, tradable = {}, {}, {d: set() for d in calendar}
    for symbol, frame in frames.items():
        closes = frame.close.to_dict()
        ticks[symbol] = pd.Series([tick_from_reference(d, closes.get(references[d]))
                                  for d in frame.index], index=frame.index, dtype='Int64')
        # Reindex BEFORE rolling: a missing exchange session cannot be silently
        # replaced by an older observation in the sixty-session capacity window.
        turnover[symbol] = frame.turnover.reindex(calendar).rolling(60, min_periods=60).median().shift(1)
        for d, observed_symbol, isin, token, series in frame[['symbol', 'isin', 'token', 'series']].itertuples():
            metadata = snapshots.get(previous.get(d), {}).get(observed_symbol)
            if metadata is not None and (isin, token, series) == (
                    metadata['ISIN'], metadata['FinInstrmId'], metadata['SctySrs']):
                tradable[d].add(symbol)
    formations = {}
    # The last source month may be incomplete (September 3 is NOT month-end).
    dates = [d for period, d in month_ends(calendar).items()
             if first_formation <= d < end and period < calendar[-1].to_period('M')]
    for d in dates:
        snapshot = snapshots.get(d)
        eligible = None
        if snapshot is not None:
            eligible = set()
            for symbol, frame in frames.items():
                if d not in frame.index:
                    continue
                row = frame.loc[d]
                metadata = snapshot.get(row['symbol'])
                if metadata is not None and row['isin'] == metadata['ISIN']:
                    eligible.add(symbol)
        try:
            ranking = rank_formation(frames, calendar, d, eligible, reset_dates=resets)
        except ValueError as exc:
            formations[d] = str(exc)
            print(f'Formation {d.date()}: BLOCKED {exc}', flush=True)
        else:
            formations[d] = ranking
            print(f'Formation {d.date()}: {len(ranking)} stocks', flush=True)
    identity = {'raw_panel': receipt, 'source_plan': source_plan, 'metadata': evidence, 'repairs': repairs,
        'actions': action_evidence, 'action_details': details,
        'effective_actions': json.loads(json.dumps([asdict(a) for a in actions], default=str)),
        'formations': {str(d.date()): (f if isinstance(f, str) else {
            'sha256': sha(batch.payload(f.reset_index().to_dict('records'))), 'coverage': f.attrs})
            for d, f in formations.items()},
        'tradable_sha256': sha(batch.payload({str(d.date()): sorted(v) for d, v in tradable.items()})),
        'ticks_sha256': sha(batch.payload({s: sha(pd.util.hash_pandas_object(v, index=True).values.tobytes()) for s, v in ticks.items()})),
        'turnover_sha256': sha(batch.payload({s: sha(pd.util.hash_pandas_object(v, index=True).values.tobytes()) for s, v in turnover.items()}))}
    raw = RawAccounting(frames, ticks, actions, sha(batch.payload(identity)), calendar[0], calendar[-1],
        signal_basis='six/twelve calendar-month raw price returns; complete same-identity history without non-dividend action crossings')
    benchmark_bytes = pinned(plan['benchmark'])
    benchmark = pd.read_parquet(ROOT / plan['benchmark']['path'])['close']
    identity['benchmark_sha256'] = sha(benchmark_bytes)
    return MomentumInputs(raw, calendar, formations, tradable, turnover), benchmark, identity


def compare_benchmark(result, benchmark, maximum_drawdown_pct):
    """Align marked wealth with gross TRI; no normality/significance claim."""
    curve = result['equity_curve']
    dates = pd.DatetimeIndex([r['session'] for r in curve])
    prior = pd.Timestamp(result['formation_start'])
    window = benchmark.loc[(benchmark.index >= prior) & (benchmark.index <= dates[-1])]
    required = pd.DatetimeIndex([prior, *dates])
    if (not window.index.equals(required) or not np.isfinite(window.to_numpy()).all()
            or (window <= 0).any()):
        raise ValueError('benchmark calendar mismatch or invalid TRI')
    benchmark_return = (float(window.iloc[-1])/float(window.iloc[0])-1)*100
    excess = result['return_pct']-benchmark_return
    equity = pd.Series([result['policy']['capital'], *[r['equity'] for r in curve]], index=required)
    monthly = equity.groupby(equity.index.to_period('M')).last()
    monthly = monthly.pct_change().dropna()*100
    verdict = ('OUTSIDE_RESEARCH_DRAWDOWN_LIMIT' if result['max_drawdown_pct'] > maximum_drawdown_pct
        else 'NO_DEMONSTRATED_NET_EDGE' if result['return_pct'] <= 0 or excess <= 0
        else 'POSITIVE_DEVELOPMENT_SCENARIO_ONLY')
    return {'name': 'Nifty 500 gross TRI', 'return_pct': benchmark_return,
        'excess_total_return_percentage_points': excess, 'development_verdict': verdict,
        'worst_months': {str(k): float(v) for k, v in monthly.sort_values().head(5).items()},
        'maximum_stock_weight_pct': max((max(p['weights'].values(), default=0)*100 for p in curve), default=0),
        'mean_gross_exposure_pct': float(np.mean([p['gross_exposure_pct'] for p in curve])),
        'extra_cost_budget_before_benchmark_parity_inr': max(0, excess/100*result['policy']['capital']),
        'extra_cost_budget_interpretation': 'Static ending-wealth difference, not a resimulated break-even slippage estimate.',
        'passive_product_comparison': 'UNAVAILABLE: no pinned investable-product history; gross TRI is not a funded comparator.'}


def run(plan_path, output):
    content = plan_path.read_bytes()
    plan = json.loads(content)
    if plan.get('authority') != 'RESEARCH_ONLY' or plan.get('can_trade') is not False:
        raise ValueError('research-only plan required')
    for spec in [plan['contract'], *plan['implementations']]:
        pinned(spec)
    policy = MomentumPolicy(**plan['policy'])
    end = pd.Timestamp(plan['end'])
    inputs, benchmark, evidence = prepare_inputs(plan['source_plan'],
        first_formation=pd.Timestamp(plan['extended_formation']), end=end, repairs=plan.get('repairs'))
    identity = {'plan': plan, 'plan_sha256': sha(content), 'inputs': evidence,
        'runtime': {'python': sys.version, **{n: version(n) for n in ('numpy', 'pandas', 'pyarrow')}}}
    run_id = sha(batch.payload(identity))
    root = output / run_id
    batch.immutable(root / 'manifest.json', batch.payload(identity))
    from sensei.research.exposure import record_development_frames
    record_development_frames(inputs.raw.frames, campaign_id='liquid-relative-strength-'+run_id)
    results = []
    for experiment in plan['experiments']:
        name = experiment['name']
        run_policy = replace(policy, **experiment.get('overrides', {}))
        formations = inputs.formations
        if experiment.get('cadence') == 'semiannual':
            formations = {d: f for d, f in formations.items() if d.month in (6, 12)}
        if experiment.get('selection') == 'liquidity':
            formations = {d: (f if isinstance(f, str) else f.reset_index().sort_values(
                ['turnover60', 'isin', 'symbol'], ascending=[False, True, True]).set_index('symbol'))
                for d, f in formations.items()}
        formation = pd.Timestamp(plan['extended_formation'] if experiment.get('extended') else plan['common_formation'])
        print(f'Running {name} from {formation.date()}', flush=True)
        # Every attempt is durably recorded BEFORE invoking the simulation.
        batch.immutable(root / f'{name}.registration.json', batch.payload({
            'run_id': run_id, 'experiment': experiment, 'formation_start': str(formation.date()),
            'policy': asdict(run_policy), 'status': 'REGISTERED_DEVELOPMENT_ATTEMPT'}))
        try:
            result = run_momentum_portfolio(replace(inputs, formations=formations), run_policy,
                formation_start=formation, end=end)
            comparison = compare_benchmark(result, benchmark, run_policy.maximum_drawdown_pct)
        except ValueError as exc:
            result = {'name': name, 'status': 'SIMULATION_BLOCKED', 'blocker': str(exc),
                'authority': 'RESEARCH_ONLY', 'can_trade': False}
        else:
            result = {'name': name, 'status': 'COMPLETED_MARKED_RESEARCH_SCENARIO',
                'comparison': comparison, **result}
        batch.immutable(root / f'{name}.json', batch.payload(result))
        results.append({'name': name, 'status': result['status'], 'path': str(root / f'{name}.json'),
            **{k: result[k] for k in ('blocker', 'final_equity', 'return_pct', 'max_drawdown_pct',
                                    'fees_inr', 'overhead_inr', 'comparison') if k in result}})
        print(name, result['status'], result.get('blocker', result.get('final_equity')), flush=True)
    complete = {r['name']: r for r in results if r['status'] != 'SIMULATION_BLOCKED'}
    baseline, doubled = complete.get('candidate'), complete.get('slippage20')
    batch_verdict = 'INCOMPLETE_EVIDENCE'
    if baseline and doubled:
        batch_verdict = ('NO_DEMONSTRATED_NET_EDGE' if any(r['return_pct'] <= 0 or
            r['comparison']['excess_total_return_percentage_points'] <= 0 for r in (baseline, doubled))
            else 'POSITIVE_DEVELOPMENT_SCENARIO_ONLY')
    report = {'run_id': run_id, 'authority': 'RESEARCH_ONLY', 'can_trade': False,
        'admissible': False, 'holdout_is_untouched': False, 'batch_verdict': batch_verdict,
        'experiments': results, 'master_coverage': dict(Counter(v['status'] for v in evidence['metadata'].values())),
        'blocked_formations': {str(d.date()): f for d, f in inputs.formations.items() if isinstance(f, str)},
        'limitations': plan['assumptions']}
    path = root / 'report.json'
    batch.immutable(path, batch.payload(report))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/reports/liquid-relative-strength')
    args = parser.parse_args()
    print(run(args.plan, args.output))


if __name__ == '__main__':
    main()
