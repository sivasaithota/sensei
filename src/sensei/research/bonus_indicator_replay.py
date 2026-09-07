"""Bounded real bonus and full-warmup indicator diagnostic, never a portfolio."""

import argparse
from dataclasses import asdict, replace
from fractions import Fraction
import json
from pathlib import Path
import re
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from sensei.backtest.strategies import momentum_breakout_55
from sensei.data.bhavcopy import QuarantinedRawBhavcopy
from sensei.research.action_history import ShareAction, signal_history
from sensei.research.raw_portfolio import action_treatment, load_actions
from sensei.research.split_reproduction import FIELDS, ROOT, identity_row, pinned, sha
from sensei.strategy.selection import SignalRankingPolicy, average_turnover, return_correlation


def classify_actions(observed, declared):
    """Require an explicit treatment for every observed row, including dividends."""
    by_id = {r["source_id"]: r for r in observed}
    if (len(by_id) != len(observed) or len({d["source_id"] for d in declared}) != len(declared)
            or set(by_id) != {d["source_id"] for d in declared}):
        raise ValueError("observed and declared action coverage differs")
    result = {}
    for declaration in declared:
        row = by_id[declaration["source_id"]]
        if (row["symbol"] != declaration["symbol"] or row["subject"] != declaration["subject"]
                or row["date"] != pd.Timestamp(declaration["ex_session"])):
            raise ValueError("action declaration does not match evidence")
        kind = declaration["kind"]
        if kind == "price_only_dividend":
            if action_treatment(row)[0] != "dividend":
                raise ValueError("only an explicit dividend may retain the raw price move")
            continue
        if row["series"] != "EQ" or row["isin"] != declaration["old_isin"]:
            raise ValueError("share action identity mismatch")
        if any(type(declaration[k]) is not int or declaration[k] <= 0 for k in ("new_shares", "old_shares")):
            raise ValueError("share ratio must use positive integers")
        if kind == "bonus":
            additional, existing = declaration["additional_shares"], declaration["existing_shares"]
            if (type(additional) is not int or type(existing) is not int or min(additional, existing) <= 0
                    or row["subject"] != f"Bonus {additional}:{existing}"
                    or Fraction(declaration["new_shares"], declaration["old_shares"]) != Fraction(additional + existing, existing)):
                raise ValueError("bonus total-share ratio does not match entitlement")
        elif kind == "split":
            values = re.fullmatch(r"Face Value Split \(Sub-Division\) - From Rs ([\d.]+)/- Per Share To Rs ([\d.]+)/- Per Share", row["subject"])
            if values is None or Fraction(declaration["new_shares"], declaration["old_shares"]) != Fraction(values[1]) / Fraction(values[2]):
                raise ValueError("split ratio does not match documented face values")
        else:
            raise ValueError("unsupported action treatment")
        action = ShareAction(row["source_id"], row["date"], pd.Timestamp(declaration["known_session"]),
            kind, declaration["new_shares"], declaration["old_shares"])
        result.setdefault(row["symbol"], []).append(action)
    return result


def oracle_history(frame, actions, cutoff):
    result = frame.loc[:cutoff].copy(deep=True)
    for stamp in result.index:
        factor = Fraction(1)
        for action in actions:
            if action.ex_session <= cutoff:
                if action.known_session > cutoff:
                    raise ValueError("oracle action was not known")
                if stamp < action.ex_session:
                    factor *= Fraction(action.new_shares, action.old_shares)
        for name in FIELDS:
            value = Fraction(str(frame.loc[stamp, name]))
            result.loc[stamp, name] = float(value * factor if name == "volume" else value / factor)
    return result


def features(histories, cutoff, stop_pct, target_pct):
    policy = SignalRankingPolicy()
    scores, signals = {}, {}
    for symbol, history in sorted(histories.items()):
        signals[symbol] = bool(momentum_breakout_55(history).iloc[-1])
        scores[symbol] = asdict(policy.score(frame=history, average_turnover_inr=average_turnover(history),
            stop_pct=stop_pct, target_pct=target_pct, as_of=cutoff.date()))
    left, right = sorted(histories)
    order = sorted(scores, key=lambda s: (-scores[s]["total"], s))
    return {"scores": scores, "signals": signals, "score_order": order,
        "signalling_order": [s for s in order if signals[s]],
        "pairwise_correlation": return_correlation(histories[left], histories[right],
            lookback=policy.correlation_lookback_sessions)}


def bonus_negative_controls(frame, bonus, *, rtol, atol, transform=signal_history):
    original = frame.copy(deep=True)
    expected = oracle_history(frame, [bonus], bonus.ex_session)
    omitted = transform(frame, [], bonus.ex_session)
    if np.allclose(omitted[FIELDS], expected[FIELDS], rtol=rtol, atol=atol):
        raise ValueError("omitted bonus negative control unexpectedly matched")
    pd.testing.assert_frame_equal(frame, original)
    late = replace(bonus, known_session=bonus.ex_session + pd.Timedelta(days=1))
    try:
        transform(frame, [late], bonus.ex_session)
    except ValueError as exc:
        if "not known" not in str(exc):
            raise
    else:
        raise ValueError("later knowledge negative control did not block")
    pd.testing.assert_frame_equal(frame, original)


def replay(frames, actions, cutoffs, *, minimum_history=252, rtol=1e-12, atol=1e-10,
           stop_pct=5, target_pct=12, transform=signal_history):
    if (len(frames) != 2 or minimum_history < 252 or not 0 <= rtol <= 1e-12
            or not 0 <= atol <= 1e-10 or not len(cutoffs)):
        raise ValueError("invalid replay scope or tolerance")
    originals = {s: f.copy(deep=True) for s, f in frames.items()}
    decisions, cells, signal_cells = [], 0, 0
    for cutoff in cutoffs:
        actual, oracle, raw = {}, {}, {}
        for symbol, frame in frames.items():
            if cutoff not in frame.index or len(frame.loc[:cutoff]) < minimum_history:
                raise ValueError("insufficient decision history")
            raw[symbol] = frame.loc[:cutoff].copy(deep=True)
            actual[symbol] = transform(frame, actions.get(symbol, []), cutoff)
            prefix = transform(raw[symbol], actions.get(symbol, []), cutoff)
            pd.testing.assert_frame_equal(actual[symbol], prefix)
            oracle[symbol] = oracle_history(frame, actions.get(symbol, []), cutoff)
            if not actual[symbol].index.equals(oracle[symbol].index) or not actual[symbol].columns.equals(oracle[symbol].columns):
                raise ValueError("transform changed history shape")
            if not np.allclose(actual[symbol][FIELDS], oracle[symbol][FIELDS], rtol=rtol, atol=atol):
                raise ValueError("dated history failed rational oracle")
            pd.testing.assert_series_equal(actual[symbol]["turnover"], raw[symbol]["turnover"])
            if not momentum_breakout_55(actual[symbol]).equals(momentum_breakout_55(oracle[symbol])):
                raise ValueError("signal history differs from oracle")
            pd.testing.assert_frame_equal(frame, originals[symbol])
            cells += len(actual[symbol]) * len(FIELDS)
            signal_cells += len(actual[symbol])
        current = features(actual, cutoff, stop_pct, target_pct)
        reference = features(oracle, cutoff, stop_pct, target_pct)
        if any(current[k] != reference[k] for k in ("signals", "score_order", "signalling_order")):
            raise ValueError("signal/ranking order differs from oracle")
        for symbol in frames:
            if not np.allclose(list(current["scores"][symbol].values()), list(reference["scores"][symbol].values()), rtol=rtol, atol=1e-12):
                raise ValueError("ranking components differ from oracle")
        if not np.isclose(current["pairwise_correlation"], reference["pairwise_correlation"], rtol=rtol, atol=1e-12):
            raise ValueError("correlation differs from oracle")
        decisions.append({"session": str(cutoff.date()), "dated": current,
            "raw_unnormalized": features(raw, cutoff, stop_pct, target_pct)})
    return {"decisions": decisions, "ohlcv_oracle_cells": cells, "signal_oracle_cells": signal_cells,
        "all_components_match_oracle": True, "append_invariance": True, "raw_input_unchanged": True}


def load_inputs(plan):
    for spec in plan["implementations"] + [plan[k] for k in ("contract", "bonus_note", "split_note", "action_manifest")]:
        pinned(spec)
    parent = json.loads(pinned(plan["parent_manifest"]))["identity"]["raw_evidence"]
    captures = []
    for name in ("bonus_manifest", "split_manifest"):
        captures.extend(json.loads(pinned(plan[name]))["captures"])
    by_url = {c["url"]: c for c in captures}
    if len(by_url) != len(captures):
        raise ValueError("duplicate primary capture")
    allowed = {"nsearchives.nseindia.com", "www.msei.in", "www.mazagondock.in"}
    for c in captures:
        if c["http_status"] != 200 or any(urlparse(c[k]).scheme != "https" or urlparse(c[k]).hostname not in allowed for k in ("url", "final_url")):
            raise ValueError("unexpected primary source")
        pdf = pinned({"path": c["path"], "sha256": c["sha256"]})
        if not pdf.startswith(b"%PDF-") or len(pdf) != c["bytes"]:
            raise ValueError("invalid pinned PDF")
    calendar = pd.DatetimeIndex(sorted(parent["raw_receipts"]))
    start, first, end = (pd.Timestamp(plan[k]) for k in ("history_start", "decision_start", "decision_end"))
    sessions = calendar[(calendar >= start) & (calendar <= end)]
    cutoffs = calendar[(calendar >= first) & (calendar <= end)]
    if (len(sessions) != plan["expected_raw_sessions"] or len(cutoffs) != plan["expected_decisions"]
            or any(d not in calendar for d in (start, first, end)) or len(sessions[sessions <= first]) < plan["minimum_history"]):
        raise ValueError("calendar/warmup differs from plan")
    all_rows, _ = load_actions(ROOT / plan["action_manifest"]["path"])
    observed = [a for a in all_rows if a["symbol"] in plan["instruments"] and start <= a["date"] <= end]
    actions = classify_actions(observed, plan["actions"])
    for a in plan["actions"]:
        if a["kind"] == "price_only_dividend":
            continue
        published = max(pd.Timestamp(by_url[u]["publication_date"]) for u in a["support_urls"])
        if calendar[calendar > published][0] != pd.Timestamp(a["known_session"]) or published >= pd.Timestamp(a["ex_session"]):
            raise ValueError("required evidence was not available before ex-session")
    store, receipts = QuarantinedRawBhavcopy(), {}
    rows = {s: [] for s in plan["instruments"]}
    for stamp in sessions:
        verified = store.verified_session(stamp.date())
        receipt = json.loads(json.dumps(asdict(verified.reference), default=str))
        if receipt != parent["raw_receipts"][str(stamp.date())]:
            raise ValueError("raw input differs from frozen receipt")
        receipts[str(stamp.date())] = receipt
        for symbol, spec in plan["instruments"].items():
            isin = spec["initial_isin"]
            for a in sorted(plan["actions"], key=lambda a: a["ex_session"]):
                if a["symbol"] == symbol and a["kind"] != "price_only_dividend" and pd.Timestamp(a["ex_session"]) <= stamp:
                    if isin != a["old_isin"]:
                        raise ValueError("broken identity chain")
                    isin = a["new_isin"]
            row = identity_row(verified.frame, symbol, isin)
            rows[symbol].append({"session": stamp, **{k: float(row[k]) for k in FIELDS + ["turnover"]}})
    return {s: pd.DataFrame(r).set_index("session") for s, r in rows.items()}, actions, cutoffs, receipts, observed


def run(plan_path, output):
    content = plan_path.read_bytes()
    plan = json.loads(content)
    if (plan["authority"] != "RESEARCH_ONLY" or plan["can_trade"] is not False
            or plan["price_policy"] != "share-unit-price-only-v1" or set(plan["instruments"]) != {"BSE", "HEG"}):
        raise ValueError("unsupported diagnostic authority or policy")
    frames, actions, cutoffs, receipts, observed = load_inputs(plan)
    result = replay(frames, actions, cutoffs, **{k: plan[k] for k in ("minimum_history", "rtol", "atol", "stop_pct", "target_pct")})
    bonus = next(a for a in actions["BSE"] if a.kind == "bonus")
    # Real negative controls prove that omitted or unavailable bonus evidence fails.
    bonus_negative_controls(frames["BSE"], bonus, rtol=plan["rtol"], atol=plan["atol"])
    ex_history = signal_history(frames["BSE"], [bonus], bonus.ex_session)
    prior = frames["BSE"].index[frames["BSE"].index < bonus.ex_session][-1]
    result.update({"plan": plan, "plan_sha256": sha(content), "implementation_sha256": sha(Path(__file__).read_bytes()),
        "raw_receipts": receipts, "observed_actions": observed, "negative_controls_pass": True,
        "bonus_prices": {"prior_raw_close": float(frames["BSE"].loc[prior, "close"]),
            "prior_in_ex_units": float(ex_history.loc[prior, "close"]), "ex_close": float(ex_history.loc[bonus.ex_session, "close"])},
        "authority": "RESEARCH_ONLY", "decision": "DATA_BLOCKED", "can_trade": False,
        "limitations": ["Observed action coverage and currently captured dated files do not certify historical completeness/vintages",
            "Two diagnostic instruments, not a historical index universe or portfolio", "Price-only dividend convention; no receivables, cash or physical share crediting",
            "May 26 allotment corroboration is not used for pre-ex knowledge", "Score ordering tie-breaks by symbol in this diagnostic; no portfolio admission is simulated"]})
    payload = (json.dumps(result, sort_keys=True, indent=2, default=str) + "\n").encode()
    path = output / sha(payload) / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != payload:
        raise ValueError("existing report changed")
    path.write_bytes(payload)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=ROOT / "config/bonus-indicator-replay-v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/reports/bonus-indicator-replay")
    args = parser.parse_args()
    print(run(args.plan, args.output))


if __name__ == "__main__":
    main()
