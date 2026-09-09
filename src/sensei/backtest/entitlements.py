"""Separate, nonspendable demerger assets for the marked research scenario.

Discovery-based marks are valuation assumptions, never executable prices. Parent
and resulting securities retain distinct identities and an aggregate cost basis.
"""
from dataclasses import dataclass
from fractions import Fraction
import math
import re

import pandas as pd


@dataclass(frozen=True)
class ResultingSecurity:
    symbol: str
    isin: str
    new_shares: int
    old_shares: int
    listed_from: pd.Timestamp
    listing_known_from: pd.Timestamp
    available_from: pd.Timestamp


@dataclass(frozen=True)
class Demerger:
    symbol: str
    ex_date: pd.Timestamp
    known_from: pd.Timestamp
    replaces_source_id: str
    parent_isin: str
    children: tuple[ResultingSecurity, ...]
    evidence_sha256: str

    def validate(self, raw, calendar):
        dates = pd.DatetimeIndex(calendar)
        stamps = [self.ex_date,self.known_from]
        for child in self.children:
            stamps.extend([child.listed_from,child.listing_known_from,child.available_from])
        if any(not isinstance(d,pd.Timestamp) or pd.isna(d) or d.tz is not None or d!=d.normalize() for d in stamps):
            raise ValueError('demerger requires valid daily dates')
        if (self.symbol not in raw.frames or self.ex_date not in dates
                or self.ex_date == dates[0] or self.known_from >= self.ex_date
                or not self.children or re.fullmatch('[0-9a-f]{64}', self.evidence_sha256) is None):
            raise ValueError('invalid documented demerger')
        actions = [a for a in raw.actions if a.symbol == self.symbol and a.ex_date == self.ex_date]
        if len(actions)!=1 or actions[0].kind!='unsupported' or actions[0].source_id!=self.replaces_source_id:
            raise ValueError('demerger does not match exact rejected action')
        for d in (dates[dates.get_loc(self.ex_date)-1], self.ex_date):
            if raw.bar(self.symbol, d)['isin'] != self.parent_isin:
                raise ValueError('demerger parent identity mismatch')
        seen, isins = {self.symbol}, {self.parent_isin}
        for child in self.children:
            if (child.symbol in seen or child.symbol not in raw.frames
                    or child.isin in isins
                    or any(type(v) is not int or v<=0 for v in (child.new_shares,child.old_shares))
                    or child.listed_from not in dates or child.listed_from < self.ex_date
                    or child.available_from < child.listed_from
                    or child.available_from not in dates
                    or pd.isna(child.listing_known_from)):
                raise ValueError('invalid resulting security')
            seen.add(child.symbol)
            isins.add(child.isin)
            f = raw.frames[child.symbol]
            if f.index[0]!=child.listed_from or set(f['isin'])!={child.isin}:
                raise ValueError('resulting security listing/identity mismatch')


@dataclass
class Entitlement:
    parent: str
    ex_date: pd.Timestamp
    security: ResultingSecurity
    quantity: int
    initial_mark: float
    basis: float


class EntitlementBook:
    def __init__(self):
        self.holdings: dict[str, Entitlement] = {}
        self.closed: dict[str, tuple[Entitlement, pd.Timestamp]] = {}

    def distribute(self, rule, quantity, basis, previous_close, discovered_parent_price):
        """Return transferred basis and distribution value per old parent share."""
        if type(quantity) is not int or quantity<=0 or not math.isfinite(basis) or basis<0:
            raise ValueError('invalid eligible parent quantity or basis')
        if not all(math.isfinite(p) and p>0 for p in (previous_close,discovered_parent_price)):
            raise ValueError('invalid demerger price discovery')
        distribution = max(0., previous_close-discovered_parent_price)
        child_total = quantity*distribution
        transferred = basis*distribution/(discovered_parent_price+distribution)
        additions = {}
        for child in rule.children:
            if child.symbol in self.holdings:
                raise ValueError('overlapping resulting-security ownership')
            count = quantity*Fraction(child.new_shares,child.old_shares)
            if count.denominator!=1:
                raise ValueError('fractional demerger entitlement requires reconciliation')
            additions[child.symbol] = Entitlement(rule.symbol,rule.ex_date,child,int(count),
                child_total/len(rule.children)/int(count),transferred/len(rule.children))
        self.holdings.update(additions)
        return transferred, distribution

    def mark(self, symbol, session, column, raw):
        p = self.holdings[symbol]
        if session < p.security.listed_from:
            return p.initial_mark
        bar = raw.bar(symbol,session)
        if bar['isin'] != p.security.isin:
            raise ValueError(f'changed resulting-security identity: {symbol}:{session.date()}')
        return float(bar[column])

    def value(self, session, column, raw, *, unlisted_only=False):
        return sum(p.quantity*self.mark(s,session,column,raw) for s,p in self.holdings.items()
            if not unlisted_only or session < p.security.listed_from)
