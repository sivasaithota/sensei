"""Frozen, price-only historical AI pilot; local evidence, no market downloads."""
from dataclasses import asdict, replace
from hashlib import sha256
import argparse
import json
from pathlib import Path

import pandas as pd

from sensei.backtest.ai_portfolio import run_ai_portfolio, saved_decisions
from sensei.investment.cycle import run_desk_cycle
from sensei.backtest.relative_strength import MomentumPolicy, run_momentum_portfolio
from sensei.research.relative_strength_run import prepare_inputs, compare_benchmark
from sensei.research.split_reproduction import pinned
from sensei.research.relative_strength_evidence import repair_cash_actions, repair_share_actions


def accounting_overlay(inputs, manifest):
    """Repair accounting only; preserve registered prices and momentum signals."""
    if set(manifest) != {'cash_actions', 'share_actions'}:
        raise ValueError('accounting overlay must contain only cash_actions and share_actions')
    raw = inputs.raw
    actions = repair_share_actions(raw.frames, inputs.calendar, raw.actions, manifest['share_actions'])
    actions, _ = repair_cash_actions(raw.frames, inputs.calendar, actions, {}, manifest['cash_actions'])
    identity = {'base_evidence_sha256': raw.evidence_sha256, 'overlay': manifest,
                'effective_actions': [asdict(a) for a in actions]}
    digest = sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
    return replace(inputs, raw=replace(raw, actions=actions, evidence_sha256=digest)), identity


def run(output, *, replay_from=None, resume_from=None, action_repairs=None):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    source = Path('config/liquid-relative-strength-v8.json')
    plan = json.loads(source.read_text())
    start, end = pd.Timestamp('2025-06-30'), pd.Timestamp('2025-08-29')
    policy = MomentumPolicy(**plan['policy'])
    # Register dates, selection rule and accounting before any model outputs exist.
    registration = {'status': 'REGISTERED', 'start': str(start.date()), 'end': str(end.date()),
        'action_repairs': ({'path': str(action_repairs), 'sha256': sha256(Path(action_repairs).read_bytes()).hexdigest()} if action_repairs else None),
        'resume_from': str(resume_from) if resume_from is not None else None,
        'capital': policy.capital, 'universe_rule': 'Top 20 prior-60-session median turnover among dated tradable stocks at inception; freeze thereafter',
        'decision_schedule': 'source calendar month ends strictly before end',
        'maximum_model_calls': 0 if replay_from is not None else 14, 'replay_from': str(replay_from) if replay_from is not None else None, 'source_plan_sha256': sha256(source.read_bytes()).hexdigest(),
        'ai_policy': asdict(replace(policy, trailing_exit=False)),
        'evidence_scope': 'Price/volume only, archive availability assumed; no historical news or fundamentals',
        'manager_contract': 'preserved_from_source_artifacts' if replay_from is not None else 'target_weights_with_derived_cash', 'out_of_sample_claim': False, 'model_cost_included': False}
    files = ['src/sensei/backtest/ai_portfolio.py', 'src/sensei/backtest/relative_strength.py',
             'src/sensei/investment/cycle.py', 'src/sensei/investment/models.py', 'src/sensei/llm.py', __file__]
    registration['implementations'] = {str(p): sha256(Path(p).read_bytes()).hexdigest() for p in files}
    (root/'registration.json').write_text(json.dumps(registration, indent=2))
    try:
        for spec in [plan['contract'], plan['accounting_contract'], *plan['implementations']]:
            pinned(spec)
        (root/'v8-verification.json').write_text(json.dumps({'verified': [plan['contract'], plan['accounting_contract'], *plan['implementations']]}, indent=2))
        inputs, tri, evidence = prepare_inputs(plan['source_plan'], first_formation=start,
                                              end=end, repairs=plan.get('repairs'))
        price_evidence_sha256 = inputs.raw.evidence_sha256
        if action_repairs:
            manifest = json.loads(pinned(registration['action_repairs']))
            inputs, overlay = accounting_overlay(inputs, manifest)
            evidence['accounting_overlay'] = overlay
        candidates = []
        for symbol in sorted(inputs.tradable[start]):
            value = inputs.turnover60[symbol].get(start)
            history = inputs.raw.frames[symbol].loc[:start].tail(21)
            if pd.notna(value) and value >= 50_000_000 and len(history) == 21 and start in history.index:
                candidates.append((float(value), symbol))
        universe = [symbol for _, symbol in sorted(candidates, key=lambda item: (-item[0], item[1]))[:20]]
        if len(universe) != 20:
            raise ValueError('insufficient inception liquidity coverage')
        blocked = [f'{a.symbol}:{a.ex_date.date()}' for a in inputs.raw.actions
                   if a.symbol in universe and start < a.ex_date <= end and a.kind == 'unsupported']
        if blocked:
            raise ValueError('unresolved universe actions before model calls: ' + ', '.join(blocked))
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
        decision_source = {'decide': saved_decisions(Path(replay_from)/'ai')} if replay_from is not None else {}
        if resume_from is not None:
            if replay_from is not None:
                raise ValueError('choose replay or resume, not both')
            def resume_decision(packet, path):
                previous = Path(resume_from)/'ai'/packet['cutoff'][:10]
                return run_desk_cycle(packet, path, target_only=True, resume_from=previous if previous.exists() else None)
            decision_source = {'decide': resume_decision}
        ai = run_ai_portfolio(replace(inputs, formations=formations), replace(policy, trailing_exit=False),
                              formation_start=start, end=end, universe=universe, output=root/'ai',
                              price_evidence_sha256=price_evidence_sha256, **decision_source)
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
        if action_repairs:
            comparison['limitations'].append('Documented action overlay changes accounting for both portfolios; momentum signal rankings remain frozen from the original inputs')
        (root/'comparison.json').write_text(json.dumps(comparison, indent=2))
        return comparison
    except Exception as exc:
        (root/'failure.json').write_text(json.dumps({'status': 'FAILED', 'error': str(exc)}, indent=2))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output')
    parser.add_argument('--replay-from', help='Prior pilot directory; reuse exact saved decisions without model calls')
    parser.add_argument('--resume-from', help='Reuse exact validated role responses from a failed pilot; preserve original attempt')
    parser.add_argument('--action-repairs', help='Pinned primary-source accounting overlay; leaves prices and momentum signals unchanged')
    args = parser.parse_args()
    print(json.dumps(run(args.output, replay_from=args.replay_from, resume_from=args.resume_from, action_repairs=args.action_repairs), indent=2))
