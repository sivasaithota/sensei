"""Signal Playbook (PRD §4.2) — the versioned library of vetted rules.

A strategy earns a Playbook entry only by passing thresholds on both
in-sample and out-of-sample data across the universe. The live system
may only cite strategies present in the current Playbook version.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np

from sensei.backtest.engine import run_backtest, walk_forward_split
from sensei.backtest.strategies import SEED_STRATEGIES
from sensei.data.store import available_symbols, load_prices

PLAYBOOK_DIR = Path(__file__).resolve().parents[3] / "data" / "playbook"

# Adoption thresholds — a hypothesis must clear ALL of these out-of-sample.
MIN_TRADES_OOS = 30
MIN_EXPECTANCY_PCT = 0.30   # per-trade edge after costs
MIN_HIT_RATE = 0.40


def evaluate_strategy(name: str, spec: dict, symbols: list[str]) -> dict:
    """Aggregate in-sample / out-of-sample stats across the universe."""
    ins, oos = [], []
    for sym in symbols:
        try:
            df = load_prices(sym)
        except FileNotFoundError:
            continue
        if len(df) < 500:
            continue
        train, test = walk_forward_split(df)
        kwargs = dict(strategy=name, symbol=sym, stop_pct=spec["stop_pct"],
                      target_pct=spec["target_pct"], max_hold_days=spec["max_hold_days"])
        ins.append(run_backtest(train, spec["fn"], **kwargs))
        oos.append(run_backtest(test, spec["fn"], **kwargs))

    def agg(results):
        trades = [t for r in results for t in r.trades]
        if not trades:
            return {"trades": 0, "hit_rate": 0.0, "expectancy_pct": 0.0}
        rets = [t.ret_pct for t in trades]
        return {
            "trades": len(trades),
            "hit_rate": round(float(np.mean([r > 0 for r in rets])), 3),
            "expectancy_pct": round(float(np.mean(rets)), 3),
        }

    is_stats, oos_stats = agg(ins), agg(oos)
    passed = (
        oos_stats["trades"] >= MIN_TRADES_OOS
        and oos_stats["expectancy_pct"] >= MIN_EXPECTANCY_PCT
        and oos_stats["hit_rate"] >= MIN_HIT_RATE
    )
    return {
        "name": name,
        "params": {k: spec[k] for k in ("stop_pct", "target_pct", "max_hold_days")},
        "in_sample": is_stats,
        "out_of_sample": oos_stats,
        "adopted": passed,
    }


def build_playbook(symbols: list[str] | None = None) -> dict:
    """Evaluate all seed strategies and write a versioned Playbook file."""
    symbols = symbols or available_symbols()
    entries = [evaluate_strategy(name, spec, symbols)
               for name, spec in SEED_STRATEGIES.items()]
    playbook = {
        "version": date.today().isoformat(),
        "universe_size": len(symbols),
        "thresholds": {"min_trades_oos": MIN_TRADES_OOS,
                       "min_expectancy_pct": MIN_EXPECTANCY_PCT,
                       "min_hit_rate": MIN_HIT_RATE},
        "strategies": entries,
    }
    PLAYBOOK_DIR.mkdir(parents=True, exist_ok=True)
    path = PLAYBOOK_DIR / f"playbook-{playbook['version']}.json"
    path.write_text(json.dumps(playbook, indent=2))
    (PLAYBOOK_DIR / "current.json").write_text(json.dumps(playbook, indent=2))
    return playbook


def load_current_playbook() -> dict:
    return json.loads((PLAYBOOK_DIR / "current.json").read_text())


def adopted_strategies() -> list[dict]:
    return [s for s in load_current_playbook()["strategies"] if s["adopted"]]
