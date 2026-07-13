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


def evaluate_strategy(name: str, spec: dict, symbols: list[str],
                      load_fn=load_prices, cost_pct: float | None = None,
                      min_history: int = 500) -> dict:
    """Aggregate in-sample / out-of-sample stats across a universe.
    `load_fn` and `cost_pct` let other asset classes (crypto) reuse the
    same examiner with their own data and friction model."""
    ins, oos = [], []
    for sym in symbols:
        try:
            df = load_fn(sym)
        except FileNotFoundError:
            continue
        if len(df) < min_history:
            continue
        train, test = walk_forward_split(df)
        kwargs = dict(strategy=name, symbol=sym, stop_pct=spec["stop_pct"],
                      target_pct=spec["target_pct"], max_hold_days=spec["max_hold_days"])
        if cost_pct is not None:
            kwargs["cost_pct"] = cost_pct
        ins.append(run_backtest(train, spec["fn"], **kwargs))
        oos.append(run_backtest(test, spec["fn"], **kwargs))

    def agg(results):
        trades = [t for r in results for t in r.trades]
        if not trades:
            return {"trades": 0, "hit_rate": 0.0, "expectancy_pct": 0.0}
        rets = np.array([t.ret_pct for t in trades])
        wins, losses = rets[rets > 0], rets[rets <= 0]
        reasons = [t.exit_reason for t in trades]
        return {
            "trades": len(trades),
            "hit_rate": round(float(np.mean(rets > 0)), 3),
            "expectancy_pct": round(float(rets.mean()), 3),
            # loss-distribution context the Devil's Advocate needs:
            "avg_win_pct": round(float(wins.mean()), 2) if len(wins) else 0.0,
            "avg_loss_pct": round(float(losses.mean()), 2) if len(losses) else 0.0,
            "worst_trade_pct": round(float(rets.min()), 2),
            "pct_exit_target": round(reasons.count("target") / len(trades), 3),
            "pct_exit_stop": round(reasons.count("stop") / len(trades), 3),
            "pct_exit_time": round(reasons.count("time") / len(trades), 3),
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


def studied_strategies() -> dict:
    """Rule specs extracted by the Scholar (data/studied_rules.json),
    compiled into the same {fn, stop_pct, ...} shape as seed strategies."""
    from sensei.backtest.rulespec import RuleSpec, compile_spec
    f = PLAYBOOK_DIR.parent / "studied_rules.json"
    if not f.exists():
        return {}
    out = {}
    for raw in json.loads(f.read_text()):
        spec = RuleSpec.model_validate(raw)
        out[spec.name] = dict(fn=compile_spec(spec), stop_pct=spec.stop_pct,
                              target_pct=spec.target_pct,
                              max_hold_days=spec.max_hold_days,
                              source=spec.source, principle=spec.principle)
    return out


def all_strategies() -> dict:
    return {**SEED_STRATEGIES, **studied_strategies()}


def build_playbook(symbols: list[str] | None = None) -> dict:
    """Evaluate all strategies (seed + studied) and write a versioned Playbook."""
    symbols = symbols or available_symbols()
    entries = []
    for name, spec in all_strategies().items():
        e = evaluate_strategy(name, spec, symbols)
        if "source" in spec:
            e["source"] = spec["source"]
            e["principle"] = spec["principle"]
        entries.append(e)
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


CRYPTO_COST_PCT = 0.50  # exchange taker fees both sides + slippage; the
                        # 30% flat tax and 1% TDS are NOT modelled here —
                        # they are owner-level tax, reported separately.


def build_crypto_playbook() -> dict:
    """Run every strategy (seed + studied) against crypto daily candles.
    Same adoption thresholds; separate playbook file — crypto rules must
    earn adoption on crypto evidence."""
    from sensei.data.crypto import available_crypto, load_crypto
    symbols = available_crypto()
    entries = []
    for name, spec in all_strategies().items():
        e = evaluate_strategy(name, spec, symbols, load_fn=load_crypto,
                              cost_pct=CRYPTO_COST_PCT)
        if "source" in spec:
            e["source"] = spec["source"]
        entries.append(e)
    playbook = {
        "version": date.today().isoformat(),
        "asset_class": "crypto",
        "universe_size": len(symbols),
        "cost_pct": CRYPTO_COST_PCT,
        "thresholds": {"min_trades_oos": MIN_TRADES_OOS,
                       "min_expectancy_pct": MIN_EXPECTANCY_PCT,
                       "min_hit_rate": MIN_HIT_RATE},
        "strategies": entries,
    }
    PLAYBOOK_DIR.mkdir(parents=True, exist_ok=True)
    (PLAYBOOK_DIR / f"crypto-{playbook['version']}.json").write_text(
        json.dumps(playbook, indent=2))
    (PLAYBOOK_DIR / "crypto-current.json").write_text(json.dumps(playbook, indent=2))
    return playbook


def load_current_playbook() -> dict:
    return json.loads((PLAYBOOK_DIR / "current.json").read_text())


def adopted_strategies() -> list[dict]:
    """Legacy backtest passage is evidence, never trading authorization.

    Governed plans will be supplied by StrategyLifecycle. Until that module
    authorizes an exact plan version, the scanner must fail closed.
    """

    return []
