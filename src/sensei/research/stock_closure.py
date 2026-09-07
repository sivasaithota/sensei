"""Integrated raw-price NSE research replay; assumptions never grant live authority."""

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from fractions import Fraction
from importlib.metadata import version
import json
import inspect
import math
from pathlib import Path
import re
import sys
import zlib

import pandas as pd

from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig, run_portfolio_campaign
from sensei.backtest.raw_accounting import RawAccounting, RawAction
from sensei.backtest.strategies import SEED_STRATEGIES
from sensei.data.bhavcopy import QuarantinedRawBhavcopy
from sensei.research import security_master_batch as batch
from sensei.research.security_master_daily import expected_header
from sensei.research.security_master_sample import read_master
from sensei.research.preceding_metadata import prepare_entry_masks, stable_history_lengths
from sensei.research.raw_portfolio import load_actions, action_treatment, tick_reference, tick_from_reference
from sensei.research.stock_evaluation import EvaluationProtocol, audit_stock_data, evaluate_stock_portfolio
from sensei.research.split_reproduction import ROOT, pinned, sha


MASTER_FIELDS = ("TckrSymb", "SctySrs", "ISIN", "FinInstrmId", "SctyTpFlg", "CallAuctnInd",
    "SctyStsNrmlMkt", "ElgbltyNrmlMkt", "PrtdToTrad", "DelFlg", "NewBrdLotQty", "BidIntrvl")


def classify_action(row):
    """Exact bounded text grammar; unknown components remain unsupported."""
    subject = row["subject"].strip()
    if subject in {"Buy Back", "Annual General Meeting", "Extra Ordinary General Meeting"}:
        return "no_accounting", 0.0, None
    kind, amount = action_treatment({**row, "series": "EQ"})
    if kind == "dividend":
        return kind, amount, None
    split = re.fullmatch(r"Face Value Split \(Sub-Division\) - From R(?:s|e) (\d+)/- Per Share To R(?:s|e) (\d+)/- Per Share", subject)
    bonus = re.fullmatch(r"Bonus (\d+):(\d+)", subject)
    ratio = None
    if split and int(split[2]) > 0:
        kind, ratio = "split", Fraction(int(split[1]), int(split[2]))
    elif bonus and int(bonus[2]) > 0:
        kind, ratio = "bonus", Fraction(int(bonus[1]) + int(bonus[2]), int(bonus[2]))
    if ratio is not None and ratio > 1:
        return kind, 0.0, ratio
    return "unsupported", 0.0, None


def build_raw_frames(parent, cache):
    panel_path, receipt_path = cache / "raw-panel.parquet", cache / "raw-panel.json"
    builder_sha = sha(inspect.getsource(build_raw_frames).encode())
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if (receipt["parent_sha256"] != sha(batch.payload(parent)) or receipt["builder_sha256"] != builder_sha
                or sha(panel_path.read_bytes()) != receipt["parquet_sha256"]):
            raise ValueError("raw panel cache changed")
        panel = pd.read_parquet(panel_path)
    else:
        parts, rejected = [], Counter()
        store = QuarantinedRawBhavcopy()
        for i, (session, expected) in enumerate(sorted(parent.items())):
            verified = store.verified_session(pd.Timestamp(session).date())
            if json.loads(json.dumps(asdict(verified.reference), default=str)) != expected:
                raise ValueError("frozen raw receipt changed")
            raw = verified.frame
            subset = raw.loc[raw["series"].isin(["EQ", "BE"]) & raw["ok"] & raw["isin"].notna() & raw["symbol"].notna()].copy()
            duplicated = subset["symbol"].duplicated(keep=False)
            rejected["ambiguous_symbol_rows"] += int(duplicated.sum())
            subset = subset.loc[~duplicated]
            tokens = pd.DataFrame(batch.raw_observations(session, expected))
            tokens = tokens.rename(columns={"TckrSymb": "symbol", "SctySrs": "series", "ISIN": "isin", "FinInstrmId": "token"})
            subset = subset.merge(tokens[["symbol", "series", "isin", "token"]], on=["symbol", "series", "isin"], how="left", validate="one_to_one")
            if subset["token"].isna().any():
                raise ValueError("raw token join incomplete")
            subset["date"] = pd.Timestamp(session)
            parts.append(subset[["date", "symbol", "series", "isin", "token", "open", "high", "low", "close", "volume", "turnover", "prev_close"]])
            if i % 100 == 0:
                print(f"Raw universe {i + 1}/{len(parent)} sessions", flush=True)
        panel = pd.concat(parts, ignore_index=True)
        cache.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(panel_path, index=False)
        receipt = {"parent_sha256": sha(batch.payload(parent)), "builder_sha256": builder_sha, "parquet_sha256": sha(panel_path.read_bytes()),
            "rows": len(panel), "rejected": dict(rejected)}
        batch.immutable(receipt_path, batch.payload(receipt))
    frames = {str(symbol): group.set_index("date").sort_index().assign(identity_verified=True)
        for symbol, group in panel.groupby("symbol", sort=True)}
    return frames, receipt


def load_snapshots(sessions, calendar, sample, cache):
    snapshots, evidence = {}, {}
    calendar = list(calendar)
    for i, session in enumerate(sessions):
        folder = cache / session
        if not (folder / "capture.json").exists():
            evidence[session] = {"status": "missing"}
            continue
        receipt, body = batch.read_capture(folder, session)
        try:
            batch.validate_url(receipt["final_url"], session)
            filename = pd.Timestamp(session).strftime("NSE_CM_security_%d%m%Y.csv.gz")
            if receipt.get("error") or receipt["status"] != 200 or receipt["content_disposition"] != f'attachment; filename="{filename}"':
                raise ValueError("source response unavailable")
            target = calendar[calendar.index(session) + 1]
            # At the single activation boundary, a next-session master may
            # already have the documented next-session schema.
            headers = [expected_header(sample["header"], session)]
            next_header = expected_header(sample["header"], target)
            if next_header != headers[0]:
                headers.append(next_header)
            failure = None
            for header in headers:
                try:
                    decoded, rows = read_master(body, header)
                    break
                except ValueError as exc:
                    failure = exc
            else:
                raise failure
        except (ValueError, zlib.error) as exc:
            evidence[session] = {"status": "blocked", "reason": str(exc), "capture": receipt}
            continue
        selected, ambiguous, seen = {}, set(), set()
        for row in rows:
            if row["SctySrs"] != "EQ":
                continue
            symbol = row["TckrSymb"]
            if symbol in seen:
                ambiguous.add(symbol)
            seen.add(symbol)
            # Keep only the explicit proxy; absent candidates cannot enter.
            if batch.normalize(row, session)["screen_status"] == "provisional_candidate" and row.get("ElgbltyClsgAuctnSsn", "0") in {"0", "1"}:
                selected[symbol] = {k: row[k] for k in MASTER_FIELDS}
        for symbol in ambiguous:
            selected.pop(symbol, None)
        snapshots[pd.Timestamp(session)] = selected
        evidence[session] = {"status": "validated", "capture": receipt, "csv_sha256": sha(decoded),
            "master_rows": len(rows), "proxy_rows": len(selected), "ambiguous_symbols": sorted(ambiguous)}
        if i % 50 == 0:
            print(f"Metadata {i + 1}/{len(sessions)} sessions", flush=True)
    return snapshots, evidence


def map_actions(frames, records, calendar, scenario_sha, identity_bridges=()):
    bridges = {}
    for bridge in identity_bridges:
        dates = [pd.Timestamp(bridge[name]) for name in ("ex_date", "announced_on")]
        if any(pd.isna(d) or d.tz is not None or d != d.normalize() for d in dates):
            raise ValueError("split identity bridge requires explicit daily dates")
        key = bridge["symbol"], dates[0]
        if (key in bridges or bridge["old_isin"] == bridge["new_isin"] or bridge["series"] != "EQ"
                or dates[1] >= key[1]
                or type(bridge["new_shares"]) is not int or type(bridge["old_shares"]) is not int
                or not bridge["new_shares"] > bridge["old_shares"] > 0
                or not re.fullmatch(r"[0-9a-f]{64}", bridge["source"]["sha256"])):
            raise ValueError("invalid or duplicate documented split identity bridge")
        bridges[key] = bridge
    used_bridges = {}
    by_identity = defaultdict(set)
    for symbol, frame in frames.items():
        for stamp, isin in frame["isin"].items():
            by_identity[(stamp, isin)].add(symbol)
    groups = defaultdict(list)
    for row in records:
        if row["date"] < calendar[0] or row["date"] > calendar[-1]:
            continue
        if row["date"] not in calendar:
            row = {**row, "date": calendar[calendar.searchsorted(row["date"])],
                "subject": "Unresolved non-session action: " + str(row["date"].date()) + ": " + row["subject"]}
        matches = by_identity.get((row["date"], row["isin"]), set())
        exact_symbol = (row["symbol"] in frames and row["date"] in frames[row["symbol"]].index
            and frames[row["symbol"]].loc[row["date"], "isin"] == row["isin"])
        if exact_symbol:
            symbol = row["symbol"]
        elif len(matches) == 1:
            symbol = next(iter(matches))
        elif row["symbol"] in frames and row["date"] in frames[row["symbol"]].index:
            symbol = row["symbol"]
            bridge = bridges.get((symbol, row["date"]))
            frame = frames[symbol]
            prior = calendar[calendar.get_loc(row["date"]) - 1] if row["date"] != calendar[0] else None
            kind, _, ratio = classify_action(row)
            if (bridge is not None and kind == "split"
                    and ratio == Fraction(bridge["new_shares"], bridge["old_shares"])
                    and row["isin"] == bridge["old_isin"] and prior in frame.index
                    and row.get("series") == bridge["series"]
                    and frame.loc[prior, "series"] == bridge["series"] == frame.loc[row["date"], "series"]
                    and frame.loc[prior, "isin"] == bridge["old_isin"]
                    and frame.loc[row["date"], "isin"] == bridge["new_isin"]):
                used_bridges[(symbol, row["date"])] = bridge
            else:
                row = {**row, "subject": "Unresolved action ISIN linkage: " + row["isin"] + ": " + row["subject"]}
        else:
            continue
        groups[(symbol, row["date"])].append(row)
    actions, resets, details = [], defaultdict(set), []
    for (symbol, stamp), source_rows in sorted(groups.items()):
        unique = {row["subject"].strip(): row for row in source_rows}
        parsed = [(row, classify_action(row)) for row in unique.values()]
        active = [(row, terms) for row, terms in parsed if terms[0] != "no_accounting"]
        if not active:
            continue
        bridge = used_bridges.get((symbol, stamp))
        source_id = sha(batch.payload({"source_ids": sorted(r["source_id"] for r in source_rows), "identity_bridge": bridge}))
        subject = " | ".join(sorted(unique))
        if all(terms[0] == "dividend" for _, terms in active):
            action = RawAction(symbol, stamp, "dividend", sum(terms[1] for _, terms in active), source_id, subject)
        elif len(active) == 1 and active[0][1][0] in {"split", "bonus"}:
            kind, _, ratio = active[0][1]
            index = calendar.get_loc(stamp)
            available = calendar[index + 2] if index + 2 < len(calendar) else None
            kwargs = {} if available is None else {"available_from": available, "availability_known_from": stamp,
                "availability_source_sha256": scenario_sha, "availability_basis": "scenario"}
            action = RawAction(symbol, stamp, kind, 0.0, source_id, subject,
                ratio.numerator, ratio.denominator, stamp, **kwargs)
        else:
            action = RawAction(symbol, stamp, "unsupported", 0.0, source_id, subject)
        actions.append(action)
        if action.kind != "dividend":
            resets[symbol].add(stamp)
        details.append({"action": json.loads(json.dumps(asdict(action), default=str)), "source_ids": sorted(r["source_id"] for r in source_rows),
            "identity_bridge": bridge})
    by_date = {(a.symbol, a.ex_date): a for a in actions}
    for symbol, frame in frames.items():
        for i in range(1, len(frame)):
            stamp = frame.index[i]
            identity_changed = frame["isin"].iloc[i] != frame["isin"].iloc[i - 1]
            old_close, previous_close = float(frame["close"].iloc[i - 1]), float(frame["prev_close"].iloc[i])
            restated = not math.isfinite(previous_close) or abs(previous_close / old_close - 1) > 0.005
            existing = by_date.get((symbol, stamp))
            if existing is not None and existing.kind == "unsupported":
                continue
            explained = False
            if existing is not None and existing.kind in {"split", "bonus"}:
                expected = old_close * existing.old_shares / existing.new_shares
                compatible = math.isclose(previous_close, expected, rel_tol=0.005, abs_tol=0.01)
                # NSE may retain yesterday's unadjusted close on the split row.
                # Only a documented exact identity transition can use that form.
                if (symbol, stamp) in used_bridges:
                    compatible |= math.isclose(previous_close, old_close, rel_tol=0.005, abs_tol=0.01)
                explained = compatible and (existing.kind == "split" or not identity_changed)
            elif existing is not None and existing.kind == "dividend" and not identity_changed:
                explained = math.isclose(previous_close, old_close - existing.amount, rel_tol=0.005, abs_tol=0.01)
            if (identity_changed or restated) and not explained:
                observation = {"symbol": symbol, "date": str(stamp), "before": str(frame["isin"].iloc[i - 1]),
                    "after": str(frame["isin"].iloc[i]), "old_close": old_close,
                    "previous_close": previous_close if math.isfinite(previous_close) else None,
                    "existing_source_id": existing.source_id if existing else None}
                source = sha(batch.payload(observation))
                if existing is not None:
                    actions.remove(existing)
                guard = RawAction(symbol, stamp, "unsupported", 0.0, source, "Unresolved raw identity or previous-close restatement")
                actions.append(guard)
                details.append({"action": json.loads(json.dumps(asdict(guard), default=str)), "raw_guard": observation})
                resets[symbol].add(stamp)
    return tuple(actions), resets, details


def run(plan_path, output):
    content = plan_path.read_bytes()
    plan = json.loads(content)
    if plan["authority"] != "RESEARCH_ONLY" or plan["can_trade"] is not False:
        raise ValueError("research authority required")
    for spec in [plan["contract"], *plan["implementations"], *plan["evidence"]]:
        pinned(spec)
    for bridge in plan.get("split_identity_bridges", ()):
        pinned(bridge["source"])
    scope = json.loads(pinned(plan["acquisition_scope"]))
    parent = json.loads(pinned(scope["parent_manifest"]))["identity"]["raw_evidence"]["raw_receipts"]
    sample = json.loads(pinned(plan["sample_plan"]))
    calendar = pd.DatetimeIndex(sorted(parent))
    start, end = pd.Timestamp(plan["start"]), pd.Timestamp(plan["end"])
    prior_sessions = [str(calendar[i - 1].date()) for i, s in enumerate(calendar) if start <= s <= end and i]
    if prior_sessions != scope["sessions"]:
        raise ValueError("acquisition scope does not cover all preceding sessions")
    frames, raw_receipt = build_raw_frames(parent, ROOT / "data/research/stock-closure/20260907")
    snapshots, metadata_evidence = load_snapshots(scope["sessions"], sorted(parent), sample, ROOT / "data/research/nse-master-batch/v1")
    records, action_evidence = load_actions(ROOT / plan["action_manifest"]["path"])
    pinned(plan["action_manifest"])
    print(f"Mapping {len(records)} corporate-action source records", flush=True)
    actions, resets, action_details = map_actions(frames, records, calendar, sha(content), plan.get("split_identity_bridges", ()))
    for symbol, frame in frames.items():
        lengths = stable_history_lengths(frame, calendar, resets.get(symbol, ()))
        frame["research_history_epoch"] = lengths.eq(1).cumsum().astype("int64")
    # Dated announcement exclusions are retained; no pre-announcement future-event mask.
    from sensei.research.event_risk import load_event_risk, entry_masks, EventRiskPolicy
    risk = load_event_risk(ROOT / plan["event_risk"]["path"])
    pinned(plan["event_risk"])
    risk = EventRiskPolicy(risk.post_event_observations, tuple(e for e in risk.events if e.symbol in frames), risk.source_sha256)
    event_masks = entry_masks(frames, risk)
    print("Building preceding-session entry masks", flush=True)
    masks, _, gate_counts = prepare_entry_masks(frames, calendar, snapshots, reset_dates=resets, event_masks=event_masks)
    # Executability is a separate entry-session identity check. No current OHLC,
    # volume, return or ranking feature is used to grant a pre-open decision.
    execution_blocks = 0
    previous = {s: calendar[i - 1] for i, s in enumerate(calendar) if i}
    for symbol, frame in frames.items():
        for stamp in masks[symbol].index[masks[symbol]]:
            metadata = snapshots[previous[stamp]][symbol]
            row = frame.loc[stamp]
            if (row["series"], row["isin"], row["token"]) != (metadata["SctySrs"], metadata["ISIN"], metadata["FinInstrmId"]):
                masks[symbol].loc[stamp] = False
                execution_blocks += 1
    print("Building execution tick references", flush=True)
    references = {stamp: tick_reference(stamp, calendar) for stamp in calendar}
    ticks = {}
    for symbol, frame in frames.items():
        values = []
        for stamp in frame.index:
            reference = references[stamp]
            close = frame.loc[reference, "close"] if reference in frame.index else None
            values.append(tick_from_reference(stamp, close))
        ticks[symbol] = pd.Series(values, index=frame.index, dtype="Int64")
    benchmark_content = pinned(plan["benchmark"])
    benchmark = pd.read_parquet(ROOT / plan["benchmark"]["path"])["close"]
    accounting_evidence = {"raw_panel": raw_receipt, "metadata": metadata_evidence, "actions": action_evidence,
        "action_details": action_details, "scenario": "split and bonus sellability at ex-session plus two exchange sessions; assumed, not account credit",
        "restatement_policy": "unexplained previous-close restatement over 0.5% or ISIN change is an unsupported held event"}
    evidence_sha = sha(batch.payload(accounting_evidence))
    identity = {"plan": plan, "plan_sha256": sha(content), "accounting_evidence": accounting_evidence,
        "runtime": {"python": sys.version, **{name: version(name) for name in ("numpy", "pandas", "pyarrow")}},
        "frames": {s: sha(pd.util.hash_pandas_object(f, index=True).values.tobytes()) for s, f in sorted(frames.items())},
        "masks": {s: sha(pd.util.hash_pandas_object(m, index=True).values.tobytes()) for s, m in sorted(masks.items())},
        "benchmark_sha256": sha(benchmark_content)}
    run_id = sha(batch.payload(identity))
    root = output / run_id
    batch.immutable(root / "manifest.json", batch.payload(identity))
    from sensei.research.exposure import record_development_frames
    record_development_frames(frames, campaign_id="stock-closure-" + run_id)
    results = []
    data_audit = audit_stock_data(frames)
    active = {s for s, mask in masks.items() if mask.loc[(mask.index >= start) & (mask.index <= end)].any()}
    simulation_frames = {s: f for s, f in frames.items() if s in active}
    if not simulation_frames:
        raise ValueError("no instruments satisfy the explicit research entry policy")
    if sorted({d for f in simulation_frames.values() for d in f.index}) != list(calendar):
        raise ValueError("simulation optimization must preserve the complete exchange calendar")
    raw = RawAccounting(simulation_frames, {s: ticks[s] for s in active}, tuple(a for a in actions if a.symbol in active), evidence_sha, calendar[0], calendar[-1],
        signal_basis="raw OHLCV within explicit stable-identity epochs; 252 preceding observations required; no retroactive share-unit adjustments")
    for experiment in plan["experiments"]:
        print(f"Evaluating {experiment['name']} across {len(active)} eligible instruments", flush=True)
        spec = {**SEED_STRATEGIES[experiment["strategy"]], **experiment["parameters"]}
        signals = {}
        for symbol, frame in simulation_frames.items():
            signal = pd.Series(False, index=frame.index)
            for _, group in frame.groupby("research_history_epoch", sort=False):
                signal.loc[group.index] = spec["fn"](group).fillna(False).astype(bool)
            signals[(experiment["strategy"], symbol)] = signal
        try:
            campaign = run_portfolio_campaign(frames=simulation_frames, strategies={experiment["strategy"]: spec},
                config=PortfolioCampaignConfig(**plan["portfolio"]), evaluation_start=start, evaluation_end=end,
                prepared_signals=signals, entry_eligibility=masks, raw_accounting=raw)
        except ValueError as exc:
            result = {"name": experiment["name"], "status": "SIMULATION_BLOCKED", "blocker": str(exc)}
        else:
            result = {"name": experiment["name"], "status": "INCOMPLETE_ACCOUNTING_SCENARIO" if campaign.open_positions else "COMPLETED_RESEARCH_SCENARIO",
                **evaluate_stock_portfolio(campaign=campaign, protocol=EvaluationProtocol(**plan["evaluation"]),
                    data_audit=data_audit, benchmark=benchmark, benchmark_name="Nifty 500 gross TRI")}
        results.append(result)
        print(experiment["name"], result["status"], result.get("blocker", result.get("campaign", {}).get("final_equity")), flush=True)
    report = {"authority": "RESEARCH_ONLY", "can_trade": False, "admissible": False, "run_id": run_id,
        "universe": "Historical observed EQ/BE superset, selected by prior-session broad-equity EQ metadata proxy",
        "instruments": len(frames), "master_coverage": dict(Counter(r["status"] for r in metadata_evidence.values())),
        "missing_master_dates": [s for s, r in metadata_evidence.items() if r["status"] != "validated"],
        "entry_gate_counts": gate_counts, "entry_execution_identity_blocks": execution_blocks, "experiments": results,
        "remaining_live_blockers": ["Historical publication timing and exhaustive ordinary-share subtype not certified",
            "Share availability is a research scenario; cash dividends remain receivables",
            "Ticks use the existing dated reconstruction policy, not certified master tick units",
            "All inspected dates are development data; no independent forward validation",
            "Any stopped or unliquidated simulation is not a valid performance result"]}
    path = root / "report.json"
    batch.immutable(path, batch.payload(report))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True, help="Frozen research plan, including source and code hashes")
    parser.add_argument("--output", type=Path, default=ROOT / "data/reports/stock-closure")
    args = parser.parse_args()
    print(run(args.plan, args.output))


if __name__ == "__main__":
    main()
