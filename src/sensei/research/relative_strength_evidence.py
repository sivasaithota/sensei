"""Narrow, source-pinned repairs; no inferred ratios or guessed issuer lineage."""

from dataclasses import replace
from fractions import Fraction
import math
from pathlib import Path

import pandas as pd

from sensei.backtest.raw_accounting import RawAction
from sensei.research import security_master_batch as batch
from sensei.research.split_reproduction import ROOT, pinned, sha
from sensei.research.stock_closure import load_snapshots


def recover_metadata(snapshots, evidence, overrides, calendar, sample):
    snapshots, evidence = dict(snapshots), dict(evidence)
    seen = set()
    for rule in overrides:
        session = rule['session']
        if session in seen or evidence.get(session, {}).get('status') == 'validated':
            raise ValueError('metadata repair must replace a unique missing/blocked date')
        seen.add(session)
        pinned(rule['receipt'])
        cache = (ROOT / rule['receipt']['path']).parent.parent
        if (cache / session / 'capture.json').resolve() != (ROOT / rule['receipt']['path']).resolve():
            raise ValueError('metadata repair directory/date mismatch')
        fresh, receipts = load_snapshots([session], list(calendar), sample, cache)
        if receipts[session]['status'] != 'validated':
            raise ValueError(f'replacement metadata not validated: {session}')
        snapshots.update(fresh)
        evidence[session] = {**receipts[session], 'supersedes': evidence.get(session), 'repair': rule}
    return snapshots, evidence


def join_documented_renames(frames, calendar, rules):
    """Retain raw observed symbols while giving a holding a continuous key."""
    frames = dict(frames)
    calendar = pd.DatetimeIndex(calendar)
    for rule in rules:
        pinned(rule['source'])
        old, new = rule['old_symbol'], rule['new_symbol']
        effective, known = pd.Timestamp(rule['effective_from']), pd.Timestamp(rule['known_from'])
        if old == new or old not in frames or new not in frames or known >= effective or effective not in calendar:
            raise ValueError('invalid documented rename')
        before, after = frames[old], frames[new]
        index = calendar.get_loc(effective)
        if (index == 0 or before.index[-1] != calendar[index-1] or after.index[0] != effective
                or before['isin'].iloc[-1] != rule['isin'] or after['isin'].iloc[0] != rule['isin']
                or set(before['symbol']) != {old} or set(after['symbol']) != {new}):
            raise ValueError('rename does not match consecutive raw identities')
        frames[old] = pd.concat([before, after]).sort_index()
        del frames[new]
    return frames


def repair_share_actions(frames, calendar, actions, rules):
    """Replace only the named rejected event after independent source review.

    Dates, identities and ratios are claims in the frozen reviewed plan, backed
    by pinned primary documents. Compatible prices are a cross-check, never the
    evidence from which a ratio is chosen.
    """
    calendar = pd.DatetimeIndex(calendar)
    result = list(actions)
    seen = set()
    for rule in rules:
        for source in rule['sources']:
            pinned(source)
        if not rule['sources']:
            raise ValueError('share repair requires primary documents')
        symbol, ex = rule['symbol'], pd.Timestamp(rule['ex_date'])
        known = pd.Timestamp(rule['known_from'])
        key = symbol, ex
        if key in seen or known >= ex or ex not in calendar or rule['kind'] not in {'split', 'bonus'}:
            raise ValueError('invalid or duplicate share repair')
        seen.add(key)
        matches = [a for a in result if (a.symbol, a.ex_date) == key]
        if len(matches) != 1 or matches[0].kind != 'unsupported' or matches[0].source_id != rule['replaces_source_id']:
            raise ValueError('share repair no longer matches the rejected event')
        n, d = rule['new_shares'], rule['old_shares']
        if type(n) is not int or type(d) is not int or not n > d > 0:
            raise ValueError('invalid documented total-share ratio')
        ratio = Fraction(n, d)
        i = calendar.get_loc(ex)
        f = frames[symbol]
        if not i or calendar[i-1] not in f.index or ex not in f.index:
            raise ValueError('share repair lacks consecutive raw endpoints')
        before, after = f.loc[calendar[i-1]], f.loc[ex]
        if (before['isin'], after['isin']) != (rule['before_isin'], rule['after_isin']):
            raise ValueError('share repair raw identity mismatch')
        if before['series'] != 'EQ' or after['series'] != 'EQ':
            raise ValueError('share repair series mismatch')
        if rule['kind'] == 'bonus' and rule['before_isin'] != rule['after_isin']:
            raise ValueError('bonus cannot explain a changed traded ISIN')
        if not any(math.isclose(float(after.prev_close), value, rel_tol=0.005, abs_tol=0.01)
                   for value in (float(before.close), float(before.close)/float(ratio))):
            raise ValueError('documented action does not reconcile raw previous close')
        available = pd.Timestamp(rule['available_from'])
        availability_known = pd.Timestamp(rule['availability_known_from'])
        if available not in calendar or available < ex or availability_known > available:
            raise ValueError('invalid share availability repair')
        source_id = sha(batch.payload(rule))
        result.remove(matches[0])
        result.append(RawAction(symbol, ex, rule['kind'], 0., source_id,
            rule['subject'], n, d, known, available, availability_known,
            source_id, rule['availability_basis']))
    return tuple(result)


def repair_cash_actions(frames, actions, rules):
    """Admit exact, independently documented cash events rejected by the grammar."""
    result = list(actions)
    seen = set()
    for rule in rules:
        for source in rule['sources']:
            pinned(source)
        date = pd.Timestamp(rule['ex_date'])
        key = rule['symbol'],date
        matches = [a for a in result if (a.symbol,a.ex_date)==key]
        amount = rule['amount']
        if (not rule['sources'] or key in seen or len(matches)!=1
                or matches[0].kind!='unsupported' or matches[0].source_id!=rule['replaces_source_id']
                or pd.Timestamp(rule['known_from'])>=date
                or not math.isfinite(amount) or amount<=0
                or frames[key[0]].loc[date,'isin']!=rule['isin']):
            raise ValueError('invalid exact-source cash action repair')
        seen.add(key)
        result.remove(matches[0])
        result.append(RawAction(key[0],date,'dividend',amount,sha(batch.payload(rule)),rule['subject']))
    return tuple(result)


def documented_demergers(source, rules):
    """Reviewed source claims become explicit research rules, not raw actions."""
    import json
    from sensei.backtest.entitlements import Demerger, ResultingSecurity
    if source is None:
        if rules:
            raise ValueError('demergers require a source manifest')
        return ()
    content = pinned(source)
    manifest = json.loads(content)
    pinned(manifest['raw_panel'])
    for document in manifest['documents'].values():
        for key in ('source','receipt','archive'):
            if key in document:
                pinned(document[key])
    if manifest['valuation_contract']['basis']!='NSE_SPOS_RULE_PLUS_RAW_OPEN':
        raise ValueError('unsupported demerger valuation convention')
    events = {(r['symbol'],r['ex_date']):r for r in manifest['events']}
    children = {r['symbol']:r for r in manifest['children']}
    result = []
    seen = set()
    for rule in rules:
        key = rule['symbol'],rule['ex_date']
        if key in seen or key not in events:
            raise ValueError('unknown or duplicate documented demerger')
        seen.add(key)
        event = events[key]
        terms = []
        for symbol in event['children']:
            child = children[symbol]
            terms.append(ResultingSecurity(symbol,child['isin'],child['ratio_numerator'],
                child['ratio_denominator'],pd.Timestamp(child['listing_date']),
                pd.Timestamp(child['listing_announcement_date']),pd.Timestamp(child['listing_date'])))
        result.append(Demerger(key[0],pd.Timestamp(key[1]),pd.Timestamp(event['entitlement_known_from']),
            rule['replaces_source_id'],event['parent_isin'],tuple(terms),sha(content)))
    return tuple(result)
