"""Conservative potential-ownership audit across the complete registered batch.

This is an input audit, not a simulation or a filter that drops problem trades.
It reports every gap in the declared scope before publishing any account return.
"""
import pandas as pd

from sensei.strategy.relative_strength import buffered_roster


def experiment_formations(inputs, experiment):
    formations = inputs.formations
    if experiment.get('cadence') == 'semiannual':
        formations = {d:f for d,f in formations.items() if d.month in (6,12)}
    if experiment.get('selection') == 'liquidity':
        formations = {d:(f if isinstance(f,str) else f.reset_index().sort_values(
            ['turnover60','isin','symbol'],ascending=[False,True,True]).set_index('symbol'))
            for d,f in formations.items()}
    return formations


def audit_inputs(inputs, plan):
    starts, formation_errors = {}, {}
    end = pd.Timestamp(plan['end'])
    for experiment in plan['experiments']:
        start = pd.Timestamp(plan['extended_formation'] if experiment.get('extended') else plan['common_formation'])
        roster = []
        for date,ranking in sorted(experiment_formations(inputs,experiment).items()):
            if not start <= date < end:
                continue
            if isinstance(ranking,str):
                formation_errors[str(date.date())] = ranking
                continue
            roster = buffered_roster(list(ranking.index),roster)
            for symbol in roster:
                starts[symbol] = min(starts.get(symbol,date),date)
    errors, covered, children = [], set(), {}
    for rule in inputs.demergers:
        try:
            rule.validate(inputs.raw,inputs.calendar)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if rule.replaces_source_id in covered:
            errors.append('duplicate demerger rule')
        covered.add(rule.replaces_source_id)
        if rule.symbol in starts and starts[rule.symbol] < rule.ex_date <= end:
            for child in rule.children:
                children[child.symbol] = rule.ex_date
                starts[child.symbol] = child.listed_from
    unsupported, child_actions = [], []
    for action in inputs.raw.actions:
        since = children.get(action.symbol,starts.get(action.symbol))
        if since is None or action.ex_date>end or (action.ex_date<since if action.symbol in children else action.ex_date<=since):
            continue
        entry = {'symbol':action.symbol,'ex_date':str(action.ex_date.date()),
            'kind':action.kind,'subject':action.subject,'source_id':action.source_id}
        if action.symbol in children:
            child_actions.append(entry)
            if (action.kind not in {'dividend','no_accounting'}
                    or (action.kind!='no_accounting' and action.ex_date<starts[action.symbol])):
                unsupported.append(entry)
        elif action.kind=='unsupported' and action.source_id not in covered:
            unsupported.append(entry)
    missing, invalid = {}, []
    for symbol,start in starts.items():
        if symbol not in inputs.raw.frames:
            errors.append(f'missing raw security: {symbol}')
            continue
        dates=inputs.calendar[(inputs.calendar>=start)&(inputs.calendar<=end)]
        absent=dates.difference(inputs.raw.frames[symbol].index)
        if len(absent):
            missing[symbol]=[str(d.date()) for d in absent]
        for date in dates.difference(absent):
            try:
                inputs.raw.bar(symbol,date)
            except ValueError as exc:
                invalid.append(str(exc))
    blocked=bool(formation_errors or errors or unsupported or missing or invalid)
    return {'status':'BLOCKED' if blocked else 'CLEAR',
        'scope':'union of scheduled rosters, earliest selection through end, plus resulting securities',
        'potential_holdings':sorted(starts),'formation_errors':formation_errors,
        'rule_errors':errors,'unsupported_actions':unsupported,
        'missing_raw_bars':missing,'invalid_raw_bars':invalid,'child_actions':child_actions,
        'declared_demergers':len(covered),
        'execution_gaps':'Dated permission, tick, capacity and availability gaps defer fills; they are never forward-filled.'}
