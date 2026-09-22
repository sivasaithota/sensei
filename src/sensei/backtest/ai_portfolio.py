"""AI selection on the established raw-price research accounting engine.

Private-engine reuse is intentional: keep the pinned momentum implementation
unchanged. Contract tests guard this coupling. No broker or kernel authority.
"""
import json
import math
from pathlib import Path
from functools import partial

import pandas as pd

from sensei.backtest.relative_strength import _Portfolio, PendingOrder
from sensei.investment.cycle import run_desk_cycle


class AIPortfolio(_Portfolio):
    def __init__(self, inputs, policy, start, end, *, universe, output, decide, price_evidence_sha256=None):
        if policy.trailing_exit:
            raise ValueError('AI run must disable mechanical trailing exits')
        super().__init__(inputs, policy, start, end)
        self.universe = tuple(universe)
        if not self.universe or len(set(self.universe)) != len(self.universe) or len(self.universe) > 30:
            raise ValueError('a fixed unique universe of 1–30 stocks is required')
        if not set(self.universe) <= set(inputs.raw.frames):
            raise ValueError('unknown universe symbol')
        self.output, self.decide = Path(output), decide
        self.price_evidence_sha256 = price_evidence_sha256 or inputs.raw.evidence_sha256

    def total_target(self, equity, price, atr):
        # Target order quantities come from AI weights, not ATR position sizing.
        return max(0, math.floor(self.policy.position_fraction * equity / price))

    def packet(self, session):
        if self.entitlements.holdings:
            raise ValueError('AI account packet cannot yet represent resulting-security holdings')
        stamp = pd.Timestamp(session).tz_localize('Asia/Kolkata') + pd.Timedelta(hours=16)
        instruments, evidence = [], []
        for symbol in self.universe:
            bar = self.inputs.raw.bar(symbol, session)
            held = self.positions.get(symbol)
            instruments.append({'symbol': symbol, 'price_paise': round(float(bar.close)*100),
                'marked_at': stamp.isoformat(), 'held_quantity': held.quantity if held else 0,
                'available_quantity': held.quantity-held.pending_shares if held else 0})
            frame = self.inputs.raw.frames[symbol]
            history = frame.loc[frame.index <= session].tail(21)
            rows = [{'date': str(d.date()), 'close': float(row.close), 'volume': float(row.volume)}
                    for d, row in history.iterrows()]
            evidence.append({'id': symbol, 'symbol': symbol,
                'source': 'local-raw-panel:' + self.price_evidence_sha256,
                'published_at': stamp.isoformat(), 'available_at': stamp.isoformat(),
                'text': json.dumps({'raw_unadjusted_history': rows,
                    'limitations': 'Price/volume only. Corporate-action price jumps may occur. No news, fundamentals or sentiment supplied. Archive availability is assumed, not contemporaneously captured.'})})
        return {'label': 'Historical price-only AI research replay', 'synthetic': False,
            'cutoff': stamp.isoformat(), 'cash_paise': round(self.cash*100),
            'receivables_paise': round((sum(self.unsettled.values())+self.dividends)*100),
            'high_water_paise': max(round(self.peak*100), round(self.equity(session, 'close')*100)),
            'instruments': instruments, 'evidence': evidence,
            'limits': {'max_position_bps': round(self.policy.position_fraction*10000),
                'min_cash_bps': round(self.policy.reserve_fraction*10000), 'max_positions': 10,
                'max_mark_age_hours': 96, 'max_drawdown_bps': round(self.policy.maximum_drawdown_pct*100)}}

    def form(self, session, i):
        packet = self.packet(session)
        result = self.decide(packet, self.output / str(session.date()))
        if result['status'] not in ('READY', 'AI_CHOSE_CASH'):
            raise ValueError(f'AI decision failed at {session.date()}: {result}')
        # Preview includes all holdings explicitly and has checked limits/cash.
        self.orders.clear()
        self.roster = [a['symbol'] for a in result['decision']['allocations'] if a['weight_bps']]
        for order in result['preview']['orders']:
            side = order['side']
            ready = i + 1 + self.policy.execution_delay + (self.policy.exit_delay if side == 'SELL' else 0)
            self.orders[order['symbol']] = PendingOrder(order['symbol'], side, order['quantity'],
                ready, ready+self.policy.buy_valid_sessions-1 if side == 'BUY' else None,
                0.0, 'ai_allocation', session)
        self.decisions.append({'session': str(session.date()), 'decision': result['decision'],
            'artifact': str(self.output / str(session.date()) / 'artifact.json'),
            'equity': self.equity(session, 'close'),
            'orders': [o.to_dict() for o in self.orders.values()]})


def run_ai_portfolio(inputs, policy, *, formation_start, end, universe, output, decide=partial(run_desk_cycle, target_only=True), price_evidence_sha256=None):
    """Stop on any invalid model response; never score missing decisions as cash."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    account = None
    try:
        account = AIPortfolio(inputs, policy, formation_start, end,
                              universe=universe, output=output, decide=decide, price_evidence_sha256=price_evidence_sha256)
        account.form(formation_start, account.start_index)
        for i in range(account.start_index+1, account.end_index+1):
            session = account.calendar[i]
            account.cash += account.unsettled.pop(i, 0)
            while session >= account.inception + pd.DateOffset(months=account.cycle):
                account.cash -= policy.subscription_inr
                account.overhead += policy.subscription_inr
                account.cycle += 1
            account.apply_actions(session)
            account.execute_entitlements(session, i)
            account.execute(session, i)
            account.close(session, i)
            if session in inputs.formations and session < end:
                account.form(session, i)
        result = account.report(end)
        result.update({'selection': 'AI_TARGET_ALLOCATIONS', 'universe': list(universe),
                       'price_evidence_sha256': account.price_evidence_sha256,
                       'accounting_evidence_sha256': inputs.raw.evidence_sha256,
                       'model_cost_inr': None, 'model_cost_included': False,
                       'historical_model_hindsight_possible': True,
                       'evidence_scope': 'raw price and volume only; retrospective availability assumption'})
        (output/'report.json').write_text(json.dumps(result, indent=2, allow_nan=False))
        return result
    except Exception as exc:
        (output/'failure.json').write_text(json.dumps({'status': 'FAILED', 'error': str(exc),
            'completed_decisions': len(account.decisions) if account is not None else 0, 'headline_return_published': False}, indent=2))
        raise


def saved_decisions(directory):
    """Build a no-model decision source; reject changed history or account state."""
    from sensei.investment.cycle import canonical, replay
    import shutil
    directory = Path(directory)

    def decide(packet, destination):
        source = directory / packet['cutoff'][:10]
        artifact = json.loads((source/'artifact.json').read_text())
        result = replay(source)
        if canonical(artifact['packet']) != canonical(packet):
            raise ValueError('saved AI decision packet differs from replay account or evidence')
        Path(destination).mkdir(parents=True, exist_ok=False)
        shutil.copyfile(source/'artifact.json', Path(destination)/'artifact.json')
        return result
    return decide
