"""Shared bracket ordering for fill-relative daily research simulations.

Opening prices precede unknown intraday paths. Stop gaps fill at the open;
target gaps conservatively fill at the target without price improvement.
These are research assumptions, not evidence of actual broker fills.
"""

from typing import Literal, NamedTuple

DAILY_EXECUTION_POLICY = "daily-fill-relative-open-first-target-capped-v1"


class BracketExit(NamedTuple):
    price: float
    reason: Literal["stop_gap", "stop", "target"]


def opening_exit(open_price: float, stop: float, target: float) -> BracketExit | None:
    """Resolve only information known at the opening phase."""
    if open_price <= stop:
        return BracketExit(open_price, "stop_gap")
    if open_price >= target:
        return BracketExit(target, "target")
    return None


def intraday_exit(low: float, high: float, stop: float, target: float) -> BracketExit | None:
    """Resolve a remaining position conservatively after the opening phase."""
    if low <= stop:
        return BracketExit(stop, "stop")
    if high >= target:
        return BracketExit(target, "target")
    return None
