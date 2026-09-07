"""Deterministic cash-equity momentum replay, isolated from the live playbook.

Public inputs separate formation rankings from execution permissions. Missing
formation evidence and unsupported held actions fail closed; reports never
authorize trading. Daily OHLC fills remain scenarios, not broker fill evidence.
"""

from collections import defaultdict
from dataclasses import asdict, dataclass
from fractions import Fraction
import math

import pandas as pd

from sensei.backtest.costs import delivery_charge
from sensei.backtest.raw_accounting import RawAccounting, tick_round
from sensei.strategy.relative_strength import buffered_roster


@dataclass(frozen=True)
class MomentumPolicy:
    capital: float = 300000.0
    position_fraction: float = 0.095
    risk_fraction: float = 0.0075
    reserve_fraction: float = 0.05
    atr_multiple: float = 3.0
    participation: float = 0.001
    slippage_bps: float = 10.0
    subscription_inr: float = 500.0
    dp_charge_inr: float = 15.34
    trailing_exit: bool = True
    execution_delay: int = 0
    exit_delay: int = 0
    buy_valid_sessions: int = 5
    maximum_drawdown_pct: float = 100.0

    def __post_init__(self):
        for name in ('capital', 'position_fraction', 'risk_fraction', 'reserve_fraction',
                     'atr_multiple', 'participation', 'maximum_drawdown_pct'):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'positive finite {name} required')
        if (self.position_fraction > 0.095 or self.risk_fraction > 1
                or self.reserve_fraction >= 1 or self.participation > 1
                or self.maximum_drawdown_pct > 100):
            raise ValueError('invalid portfolio limits')
        for name in ('slippage_bps', 'subscription_inr', 'dp_charge_inr'):
            if isinstance(getattr(self, name), bool) or not math.isfinite(getattr(self, name)) or getattr(self, name) < 0:
                raise ValueError(f'nonnegative finite {name} required')
        if self.slippage_bps >= 10000 or type(self.trailing_exit) is not bool:
            raise ValueError('invalid execution policy')
        if any(type(x) is not int or x < 0 for x in (self.execution_delay, self.exit_delay)):
            raise ValueError('execution delays must be nonnegative integers')
        if type(self.buy_valid_sessions) is not int or self.buy_valid_sessions < 1:
            raise ValueError('buy validity must be positive')


@dataclass(frozen=True)
class MomentumInputs:
    raw: RawAccounting
    calendar: pd.DatetimeIndex
    formations: dict[pd.Timestamp, pd.DataFrame | str]
    tradable: dict[pd.Timestamp, set[str]]
    turnover60: dict[str, pd.Series]  # aligned to execution; strictly prior sessions


@dataclass
class Position:
    quantity: int
    atr: float
    high_water: float
    stop: float
    basis: float
    entry_session: pd.Timestamp
    pending_shares: int = 0
    available_from: pd.Timestamp | None = None


@dataclass
class PendingOrder:
    symbol: str
    side: str
    remaining: int
    ready: int
    expires: int | None
    atr: float
    reason: str
    formation: pd.Timestamp

    def to_dict(self):
        return {**asdict(self), 'formation': str(self.formation.date())}


def affordable_quantity(quantity, price, cash, *, dp_charge_inr=15.34):
    """Integer quantity whose purchase and charges fit spendable cash."""
    low, high = 0, max(0, int(quantity))
    while low < high:
        middle = (low + high + 1) // 2
        if middle * price + delivery_charge(middle * price, 'BUY', dp_charge_inr=dp_charge_inr) <= cash:
            low = middle
        else:
            high = middle - 1
    return low


class _Portfolio:
    def __init__(self, inputs, policy, formation_start, end):
        self.inputs, self.policy = inputs, policy
        self.calendar = pd.DatetimeIndex(inputs.calendar)
        if (self.calendar.has_duplicates or not self.calendar.is_monotonic_increasing
                or formation_start not in self.calendar or end not in self.calendar
                or formation_start >= end or formation_start not in inputs.formations):
            raise ValueError('invalid evaluation calendar or inception formation')
        self.start_index = self.calendar.get_loc(formation_start)
        self.end_index = self.calendar.get_loc(end)
        inputs.raw.validate(set(inputs.raw.frames), list(self.calendar))
        if set(inputs.turnover60) != set(inputs.raw.frames):
            raise ValueError('capacity inputs must cover every stock')
        self.cash = policy.capital - policy.subscription_inr
        self.overhead = policy.subscription_inr
        if self.cash <= 0:
            raise ValueError('subscription exceeds starting capital')
        self.inception = self.calendar[self.start_index + 1]
        self.cycle = 1
        self.positions = {}
        self.orders = {}
        self.roster = []
        self.unsettled = defaultdict(float)
        self.dividends = 0.0
        self.fees = 0.0
        self.fills, self.curve, self.decisions, self.events = [], [], [], []
        self.contributions = defaultdict(float)
        self.peak = policy.capital
        self.longest_underwater = self.underwater = 0
        self.actions = defaultdict(list)
        for action in inputs.raw.actions:
            self.actions[action.ex_date].append(action)

    def equity(self, session, column):
        return (self.cash + sum(self.unsettled.values()) + self.dividends
                + sum(p.quantity * float(self.inputs.raw.bar(s, session)[column])
                      for s, p in self.positions.items()))

    def fill_price(self, symbol, session, price, side):
        slipped = price * (1 + (1 if side == 'BUY' else -1) * self.policy.slippage_bps / 10000)
        return tick_round(slipped, self.inputs.raw.tick(symbol, session), buy=side == 'BUY')

    def capacity(self, symbol, session, price):
        turnover = self.inputs.turnover60[symbol].get(session)
        if turnover is None or not math.isfinite(turnover) or turnover <= 0:
            return 0
        return max(0, math.floor(self.policy.participation * turnover / price))

    def total_target(self, equity, price, atr):
        return max(0, math.floor(min(self.policy.position_fraction * equity / price,
                                    self.policy.risk_fraction * equity / (self.policy.atr_multiple * atr))))

    def schedule_exit(self, symbol, i, reason, formation):
        existing = self.orders.get(symbol)
        if existing and existing.side == 'SELL' and existing.reason != 'trim':
            return
        p = self.positions[symbol]
        self.orders[symbol] = PendingOrder(symbol, 'SELL', p.quantity,
            i + 1 + self.policy.execution_delay + self.policy.exit_delay,
            None, p.atr, reason, formation)

    def form(self, session, i):
        ranking = self.inputs.formations[session]
        if isinstance(ranking, str):
            raise ValueError(ranking)
        if ranking.index.has_duplicates or ranking.empty:
            raise ValueError('invalid ranked formation')
        equity = self.equity(session, 'close')
        self.roster = buffered_roster(list(ranking.index), self.roster)
        # Only full exits survive the next review. The scheduled roster never
        # reads actual positions, preserving the exit-control selection path.
        self.orders = {s: o for s, o in self.orders.items()
                       if o.side == 'SELL' and o.reason != 'trim'}
        targets = {}
        for symbol in self.roster:
            p = self.positions.get(symbol)
            row = ranking.loc[symbol]
            atr = p.atr if p else float(row.atr20)
            price = self.fill_price(symbol, session, float(row.close), 'BUY')
            if (not math.isfinite(atr) or atr <= 0
                    or (p is None and price <= self.policy.atr_multiple * atr)):
                targets[symbol] = (0, atr, price)
                continue
            target = self.total_target(equity, price, atr)
            # Capacity limits delta orders, not an existing stock position.
            delta_cap = math.floor(self.policy.participation * float(row.turnover60) / price)
            target = min(target, (p.quantity if p else 0) + delta_cap)
            targets[symbol] = (target, atr, price)
        for symbol, p in self.positions.items():
            if symbol not in self.roster:
                self.schedule_exit(symbol, i, 'roster', session)
            elif symbol not in self.orders:
                target = targets[symbol][0]
                if target < p.quantity:
                    self.orders[symbol] = PendingOrder(symbol, 'SELL', p.quantity-target,
                        i+1+self.policy.execution_delay+self.policy.exit_delay, None,
                        p.atr, 'trim', session)
        projected = self.cash + sum(self.unsettled.values()) - self.policy.reserve_fraction * equity
        for symbol, order in self.orders.items():
            price = self.fill_price(symbol, session, float(self.inputs.raw.bar(symbol, session).close), 'SELL')
            projected += order.remaining * price - delivery_charge(order.remaining * price, 'SELL', dp_charge_inr=self.policy.dp_charge_inr)
        for symbol in self.roster:
            if symbol in self.orders:
                continue
            target, atr, price = targets[symbol]
            held = self.positions[symbol].quantity if symbol in self.positions else 0
            q = affordable_quantity(max(0, target-held), price, projected, dp_charge_inr=self.policy.dp_charge_inr)
            if q:
                ready = i + 1 + self.policy.execution_delay
                self.orders[symbol] = PendingOrder(symbol, 'BUY', q, ready,
                    ready+self.policy.buy_valid_sessions-1, atr, 'rebalance', session)
                projected -= q*price + delivery_charge(q*price, 'BUY', dp_charge_inr=self.policy.dp_charge_inr)
        trace_ranking = ranking.rename(columns={'rank': 'momentum_rank'}).copy()
        trace_ranking['rank'] = range(1, len(trace_ranking)+1)
        self.decisions.append({'session': str(session.date()), 'roster': list(self.roster),
            'equity': equity, 'orders': [o.to_dict() for o in self.orders.values()],
            'coverage': ranking.attrs, 'ranking': trace_ranking.reset_index().to_dict('records')})

    def apply_actions(self, session):
        for action in self.actions[session]:
            p = self.positions.get(action.symbol)
            if action.kind != 'dividend' and action.symbol in self.orders and self.orders[action.symbol].side == 'BUY':
                del self.orders[action.symbol]
            if p is None:
                continue
            if action.kind == 'unsupported':
                raise ValueError(f'unsupported held action: {action.symbol}:{session.date()}:{action.subject}')
            if action.kind == 'dividend':
                amount = p.quantity * action.amount
                self.dividends += amount
                self.contributions[action.symbol] += amount
                p.stop -= action.amount
                p.high_water -= action.amount
            elif action.kind in {'split', 'bonus'}:
                if p.pending_shares:
                    raise ValueError('overlapping share availability requires reconciliation')
                ratio = Fraction(action.new_shares, action.old_shares)
                quantity = p.quantity * ratio
                if quantity.denominator != 1:
                    raise ValueError(f'fractional share entitlement: {action.symbol}:{session.date()}')
                before = p.quantity
                p.quantity = int(quantity)
                p.pending_shares = p.quantity if action.kind == 'split' else p.quantity-before
                p.available_from = (max(action.available_from, action.availability_known_from)
                    if action.available_from is not None and action.availability_known_from is not None else None)
                p.atr /= float(ratio)
                p.stop /= float(ratio)
                p.high_water /= float(ratio)
                order = self.orders.get(action.symbol)
                if order:
                    adjusted = order.remaining * ratio
                    if adjusted.denominator != 1:
                        raise ValueError('fractional pending exit requires reconciliation')
                    order.remaining, order.atr = int(adjusted), p.atr
            self.events.append({'session': str(session.date()), 'symbol': action.symbol,
                'kind': action.kind, 'source_id': action.source_id})
        for p in self.positions.values():
            if p.available_from is not None and session >= p.available_from:
                p.pending_shares = 0

    def execute(self, session, i):
        ranks = {s: n for n, s in enumerate(self.roster)}
        ordered = sorted(list(self.orders), key=lambda s: (
            self.orders[s].side == 'BUY', ranks.get(s, 999), s))
        for symbol in ordered:
            order = self.orders.get(symbol)
            if order is None:
                continue
            if order.expires is not None and i > order.expires:
                self.events.append({'session': str(session.date()), 'symbol': symbol,
                    'kind': 'buy_expired', 'quantity': order.remaining})
                del self.orders[symbol]
                continue
            if i < order.ready:
                continue
            if symbol not in self.inputs.tradable.get(session, set()):
                self.events.append({'session': str(session.date()), 'symbol': symbol,
                    'kind': 'no_fill', 'reason': 'missing_or_nonqualifying_dated_permission'})
                continue
            bar = self.inputs.raw.bar(symbol, session)
            # Ex-post conservative non-fill proxy, not an intraday circuit feed.
            if bar.volume <= 0 or bar.high == bar.low:
                self.events.append({'session': str(session.date()), 'symbol': symbol,
                    'kind': 'no_fill', 'reason': 'zero_activity_or_one_price_bar'})
                continue
            price = self.fill_price(symbol, session, float(bar.open), order.side)
            if price <= 0:
                raise ValueError('nonpositive executable price')
            q = min(order.remaining, self.capacity(symbol, session, price))
            equity = self.equity(session, 'open')
            p = self.positions.get(symbol)
            if order.side == 'BUY':
                held = p.quantity if p else 0
                if ((p is None and price <= self.policy.atr_multiple * order.atr)
                        or self.inputs.turnover60[symbol].get(session, 0) < 50_000_000):
                    continue
                q = min(q, max(0, self.total_target(equity, price, order.atr)-held))
                # Avoid funding gross exposure >95% via receivables or rounding.
                held_value = sum(pos.quantity * float(self.inputs.raw.bar(s, session).open)
                                 for s, pos in self.positions.items())
                gross_room = max(0, (1-self.policy.reserve_fraction)*equity-held_value)
                q = min(q, math.floor(gross_room/price))
                q = affordable_quantity(q, price, self.cash-self.policy.reserve_fraction*equity,
                                        dp_charge_inr=self.policy.dp_charge_inr)
            else:
                if p is None:
                    raise ValueError('exit without holding')
                q = min(q, p.quantity-p.pending_shares)
            if q <= 0:
                self.events.append({'session': str(session.date()), 'symbol': symbol,
                    'kind': 'no_fill', 'reason': 'capacity_cash_risk_or_share_availability'})
                continue
            fee = delivery_charge(q*price, order.side, dp_charge_inr=self.policy.dp_charge_inr)
            net_pnl = None
            if order.side == 'BUY':
                self.cash -= q*price + fee
                if p:
                    p.quantity += q
                    p.basis += q*price + fee
                else:
                    self.positions[symbol] = Position(q, order.atr, price,
                        price-self.policy.atr_multiple*order.atr, q*price+fee, session)
            else:
                basis = p.basis*q/p.quantity
                net_pnl = q*price-fee-basis
                self.contributions[symbol] += net_pnl
                p.basis -= basis
                p.quantity -= q
                self.unsettled[i+1] += q*price-fee
                if p.quantity == 0:
                    del self.positions[symbol]
            self.fees += fee
            self.fills.append({'session': str(session.date()), 'symbol': symbol, 'side': order.side,
                'quantity': q, 'price': price, 'notional': q*price, 'fees': fee,
                'net_realized_pnl': net_pnl, 'reason': order.reason,
                'formation': str(order.formation.date()), 'equity_before': equity,
                'participation': q*price/float(self.inputs.turnover60[symbol].loc[session]),
                'slippage_inr': q*(price-float(bar.open))*(1 if order.side == 'BUY' else -1)})
            order.remaining -= q
            if order.remaining == 0:
                del self.orders[symbol]

    def close(self, session, i):
        for symbol, p in self.positions.items():
            price = float(self.inputs.raw.bar(symbol, session).close)
            if self.policy.trailing_exit and price <= p.stop:
                self.schedule_exit(symbol, i, 'trailing_close', session)
            else:
                p.high_water = max(p.high_water, price)
                p.stop = max(p.stop, p.high_water-self.policy.atr_multiple*p.atr)
        equity = self.equity(session, 'close')
        if equity <= 0 or self.cash < -0.01:
            raise ValueError('account insolvent or cash overdrawn')
        self.peak = max(self.peak, equity)
        self.underwater = self.underwater+1 if equity < self.peak else 0
        self.longest_underwater = max(self.longest_underwater, self.underwater)
        weights = {s: p.quantity*float(self.inputs.raw.bar(s, session).close)/equity
                   for s, p in self.positions.items()}
        self.curve.append({'session': str(session.date()), 'equity': equity, 'cash': self.cash,
            'unsettled_sales': sum(self.unsettled.values()), 'dividend_receivables': self.dividends,
            'drawdown_pct': (1-equity/self.peak)*100, 'weights': weights,
            'gross_exposure_pct': 100*sum(weights.values()),
            'pending_share_quantity': sum(p.pending_shares for p in self.positions.values())})

    def report(self, session):
        equity = self.equity(session, 'close')
        contribution = dict(self.contributions)
        terminal = []
        for symbol, p in self.positions.items():
            price = float(self.inputs.raw.bar(symbol, session).close)
            contribution[symbol] = contribution.get(symbol, 0) + p.quantity*price-p.basis
            terminal.append({'symbol': symbol, **asdict(p), 'marked_value': p.quantity*price,
                'entry_session': str(p.entry_session.date()),
                'available_from': str(p.available_from.date()) if p.available_from is not None else None})
        error = equity-self.policy.capital-(sum(contribution.values())-self.overhead)
        if not math.isclose(error, 0, abs_tol=0.001):
            raise ValueError('stock attribution does not reconcile to account equity')
        return {'authority': 'RESEARCH_ONLY', 'can_trade': False, 'holdout_is_untouched': False,
            'policy': asdict(self.policy), 'formation_start': str(self.calendar[self.start_index].date()),
            'inception': str(self.inception.date()), 'end': str(session.date()),
            'final_equity': equity, 'return_pct': (equity/self.policy.capital-1)*100,
            'max_drawdown_pct': max(p['drawdown_pct'] for p in self.curve),
            'longest_underwater_sessions': self.longest_underwater,
            'fills': self.fills, 'equity_curve': self.curve, 'formations': self.decisions,
            'events': self.events, 'terminal_positions': terminal,
            'pending_orders': [o.to_dict() for o in self.orders.values()],
            'fees_inr': self.fees, 'overhead_inr': self.overhead,
            'stock_contributions': contribution, 'attribution_residual_inr': error,
            'turnover_one_way_multiple': sum(f['notional'] for f in self.fills)/self.policy.capital/2,
            'liquidation': {'status': 'NOT_EXECUTED',
                'reason': 'Requires later session prices, capacity, permissions and share availability; terminal close is not a fill.'}}


def run_momentum_portfolio(inputs: MomentumInputs, policy: MomentumPolicy, *,
                           formation_start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """Replay a frozen schedule; raise instead of publishing a partial return."""
    account = _Portfolio(inputs, policy, formation_start, end)
    account.form(formation_start, account.start_index)
    for i in range(account.start_index+1, account.end_index+1):
        session = account.calendar[i]
        account.cash += account.unsettled.pop(i, 0)
        while session >= account.inception + pd.DateOffset(months=account.cycle):
            account.cash -= policy.subscription_inr
            account.overhead += policy.subscription_inr
            account.cycle += 1
        account.apply_actions(session)
        account.execute(session, i)
        account.close(session, i)
        if session in inputs.formations:
            account.form(session, i)
    return account.report(end)
