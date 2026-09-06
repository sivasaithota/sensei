import json
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd
import pytest

from sensei.backtest.portfolio_campaign import PortfolioCampaignConfig
from sensei.operations import OperationalJournal
from sensei.research.stock_evaluation import EvaluationProtocol
from sensei.research.stock_run import load_run_settings, run_stock_development, scope_price_frames


def configured_run(tmp_path):
    dates = pd.bdate_range("2022-01-03", periods=270)
    frame = pd.DataFrame({"open": 100., "close": 100., "high": 101., "low": 99., "volume": 1e6}, index=dates)
    prices = tmp_path / "prices"
    prices.mkdir()
    frame.to_parquet(prices / "A.parquet")
    frame[["close"]].to_parquet(tmp_path / "benchmark.parquet")
    payload = {"name": "baseline", "start": str(dates[252].date()), "end": str(dates[-1].date()),
        "warmup_sessions": 252, "strategy_name": "momentum_breakout_55",
        "strategy_parameters": {"stop_pct": 5, "target_pct": 12, "max_hold_days": 30},
        "portfolio": asdict(PortfolioCampaignConfig(liquidate_at_end=True)),
        "evaluation": asdict(EvaluationProtocol(maximum_drawdown_pct=100, bootstrap_samples=20)),
        "prices_path": "prices", "benchmark_path": "benchmark.parquet", "benchmark_name": "fixture",
        "output_directory": "reports"}
    path = tmp_path / "run.json"
    path.write_text(json.dumps(payload))
    return path, frame


def test_config_drawdown_override_is_local_and_changes_run_identity(tmp_path):
    path, _ = configured_run(tmp_path)
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    original = load_run_settings(path)
    override = load_run_settings(path, maximum_drawdown_pct=20)
    assert original.evaluation.maximum_drawdown_pct == 100
    assert override.evaluation.maximum_drawdown_pct == 20
    assert json.loads(path.read_text())["evaluation"]["maximum_drawdown_pct"] == 100
    first = run_stock_development(original, journal=journal)
    second = run_stock_development(override, journal=journal)
    assert first != second
    assert run_stock_development(original, journal=journal) == first
    report = json.loads(first.read_text())
    assert report["decision"] == "DATA_BLOCKED"
    assert report["simulation_blockers"] == []
    assert report["benchmark"] is not None
    assert first.with_name("manifest.json").exists()


def test_scope_preserves_short_lived_stocks_and_evaluation_gaps():
    dates = pd.bdate_range("2020-01-01", periods=300)
    long = pd.DataFrame({"close": range(300)}, index=dates)
    short = long.iloc[260:270].drop(dates[265])
    scoped = scope_price_frames({"long": long, "short": short}, start=dates[260].date(),
        end=dates[280].date(), warmup_sessions=252)
    assert set(scoped) == {"long", "short"}
    assert len(scoped["long"]) == 252 + 21
    assert scoped["short"].equals(short)


def test_run_blocks_missing_portfolio_session_without_shortening_window(tmp_path):
    path, frame = configured_run(tmp_path)
    frame.drop(frame.index[-2]).to_parquet(tmp_path / "prices/A.parquet")
    report_path = run_stock_development(load_run_settings(path), journal=OperationalJournal(tmp_path / "journal.sqlite3"))
    report = json.loads(report_path.read_text())
    assert report["simulation_blockers"] == ["portfolio_calendar_does_not_match_benchmark"]
    assert report["data"]["calendar"]["missing_from_all_stocks"] == [str(frame.index[-2].date())]
    assert "campaign" not in report


def test_unknown_configuration_setting_is_rejected(tmp_path):
    path, _ = configured_run(tmp_path)
    payload = json.loads(path.read_text())
    payload["max_drawdown"] = 20
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="documented settings"):
        load_run_settings(path)


def test_changed_report_is_not_reused_as_original_evidence(tmp_path):
    path, _ = configured_run(tmp_path)
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    settings = load_run_settings(path)
    report = run_stock_development(settings, journal=journal)
    report.write_text('{"can_trade": true}')
    with pytest.raises(ValueError, match="integrity"):
        run_stock_development(settings, journal=journal)


def test_benchmark_capture_hash_is_checked(tmp_path):
    path, _ = configured_run(tmp_path)
    (tmp_path / "benchmark.manifest.json").write_text(json.dumps({"parquet_sha256": "wrong"}))
    with pytest.raises(ValueError, match="benchmark does not match"):
        run_stock_development(load_run_settings(path), journal=OperationalJournal(tmp_path / "journal.sqlite3"))


def test_repaired_inputs_are_verified_and_recorded_without_certification(tmp_path):
    from sensei.data.stock_repair import build_calendar_clean_snapshot, verify_repair_snapshot

    path, _ = configured_run(tmp_path)
    snapshot = build_calendar_clean_snapshot(prices_path=tmp_path / "prices", output_directory=tmp_path / "repairs")
    settings = replace(load_run_settings(path), prices_path=snapshot)
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    report_path = run_stock_development(settings, journal=journal)
    report = json.loads(report_path.read_text())
    manifest = json.loads(report_path.with_name("manifest.json").read_text())
    assert manifest["identity"]["repair_manifest"] == verify_repair_snapshot(snapshot)
    assert report["data"]["repair"]["snapshot_id"] == snapshot.name
    assert report["data"]["repair"]["admissible"] is False
    assert report["decision"] == "DATA_BLOCKED"
    assert report["can_trade"] is False
    (snapshot / "A.parquet").write_bytes(b"changed")
    with pytest.raises(ValueError, match="content mismatch"):
        run_stock_development(settings, journal=journal)


def test_cached_report_requires_original_manifest(tmp_path):
    path, _ = configured_run(tmp_path)
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    settings = load_run_settings(path)
    report = run_stock_development(settings, journal=journal)
    report.with_name("manifest.json").unlink()
    with pytest.raises(ValueError, match="no frozen manifest"):
        run_stock_development(settings, journal=journal)


def test_kite_snapshot_is_verified_and_bound_to_frozen_run(tmp_path):
    from sensei.data.kite_history import KiteRawStore, KiteDataError, build_plan, encoded, private_write
    from sensei.data.kite_validation import build_priority_snapshot

    path, frame = configured_run(tmp_path)
    master = b'instrument_token,tradingsymbol,exchange,segment,instrument_type\n1,A,NSE,NSE,EQ\n'
    master_request = {'kind': 'master', 'as_of': '2026-09-06'}
    class Client:
        def fetch(self, req):
            if req['kind'] == 'master': return master
            return encoded({'status': 'success', 'data': {'candles': [
                [str(stamp.date())+'T00:00:00+0530', 100,101,99,100,1000000]
                for stamp in frame.index]}})
    store, client = KiteRawStore(tmp_path/'raw-store'), Client()
    store.capture(master_request, client)
    plan = build_plan(master, master_request=master_request,
                      start=frame.index[0].date(), end=frame.index[-1].date())
    plan_path = tmp_path/'plan.json'; private_write(plan_path, encoded(plan))
    for req in plan['identity']['requests']: store.capture(req, client)
    universe = tmp_path/'universe.csv'; universe.write_text('symbol\nA\nRETIRED\n')
    snapshot = build_priority_snapshot(plan_path, store, universe,
        start=frame.index[0].date(), end=frame.index[-1].date(), output=tmp_path/'snapshots')
    settings = replace(load_run_settings(path), prices_path=snapshot, snapshot_type='kite_development')
    journal = OperationalJournal(tmp_path/'journal.sqlite3')
    report_path = run_stock_development(settings, journal=journal)
    report = json.loads(report_path.read_text())
    assert report['data']['kite_snapshot']['unmapped_symbols'] == ['RETIRED']
    assert report['data']['kite_snapshot']['admissible'] is False
    assert report['can_trade'] is False
    manifest = json.loads(report_path.with_name('manifest.json').read_text())
    assert manifest['identity']['kite_manifest']['snapshot_id'] == snapshot.name
    snapshot_manifest = snapshot/'kite_snapshot_manifest.json'
    original_manifest = snapshot_manifest.read_bytes()
    snapshot_manifest.unlink()
    with pytest.raises(ValueError, match='required Kite snapshot manifest'):
        run_stock_development(settings, journal=journal)
    snapshot_manifest.write_bytes(original_manifest)
    (snapshot/'A.parquet').write_bytes(b'changed')
    with pytest.raises(KiteDataError, match='content'):
        run_stock_development(settings, journal=journal)


def test_changed_compiled_rules_cannot_reuse_results(tmp_path, monkeypatch):
    from sensei.backtest import playbook
    from sensei.backtest.rulespec import RuleSpec, compile_spec

    path, _ = configured_run(tmp_path)
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    settings = load_run_settings(path)
    def configure_rule(threshold):
        rule = RuleSpec(name="momentum_breakout_55", source="fixture", principle="fixture",
            conditions=[{"left": "close", "op": ">", "right": threshold}],
            stop_pct=5, target_pct=12, max_hold_days=30)
        monkeypatch.setattr(playbook, "all_strategies", lambda: {
            settings.strategy_name: {"fn": compile_spec(rule), **settings.strategy_parameters}})
    configure_rule(200)
    first = run_stock_development(settings, journal=journal)
    configure_rule(50)
    second = run_stock_development(settings, journal=journal)
    assert first != second
    assert json.loads(first.read_text())["campaign"]["trades"] == []
    assert json.loads(second.read_text())["campaign"]["trades"]


def configure_event_run(tmp_path, monkeypatch, *, announcement_offset):
    from sensei.backtest import playbook
    from sensei.backtest.rulespec import RuleSpec, compile_spec

    path, frame = configured_run(tmp_path)
    dates = frame.index
    policy = {"version": 1, "post_event_observations": 252, "events": [{
        "id": "a-demerger", "symbol": "A",
        "announced_on": str(dates[252 + announcement_offset].date()),
        "available_from": str(dates[253 + announcement_offset].date()),
        "ex_date": str(dates[260].date()), "sources": ["https://example.com/notice.pdf"]}]}
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy))
    config = json.loads(path.read_text())
    config["event_risk_path"] = "policy.json"
    path.write_text(json.dumps(config))
    rule = RuleSpec(name="momentum_breakout_55", source="fixture", principle="fixture",
        conditions=[{"left": "close", "op": ">", "right": 50}],
        stop_pct=5, target_pct=12, max_hold_days=30)
    monkeypatch.setattr(playbook, "all_strategies", lambda: {
        rule.name: {"fn": compile_spec(rule), **config["strategy_parameters"]}})
    return load_run_settings(path), policy_path


def test_event_policy_blocks_entries_and_policy_content_changes_run_identity(tmp_path, monkeypatch):
    settings, policy_path = configure_event_run(tmp_path, monkeypatch, announcement_offset=-1)
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    first = run_stock_development(settings, journal=journal)
    report = json.loads(first.read_text())
    assert report["campaign"]["trades"] == []
    assert report["data"]["event_risk"]["blocked_entry_sessions"] == {"A": 18}
    assert report["data"]["event_risk"]["held_event_exposure"] == []
    assert report["can_trade"] is False
    policy = json.loads(policy_path.read_text())
    policy["post_event_observations"] = 253
    policy_path.write_text(json.dumps(policy))
    assert run_stock_development(settings, journal=journal) != first
    policy_path.unlink()
    with pytest.raises(FileNotFoundError):
        run_stock_development(settings, journal=journal)


def test_existing_holding_crossing_event_withholds_economic_verdict(tmp_path, monkeypatch):
    settings, _ = configure_event_run(tmp_path, monkeypatch, announcement_offset=2)
    report_path = run_stock_development(settings, journal=OperationalJournal(tmp_path / "journal.sqlite3"))
    report = json.loads(report_path.read_text())
    assert report["simulation_blockers"] == ["unmodeled_demerger_entitlements_in_held_positions"]
    exposure = report["data"]["event_risk"]["held_event_exposure"]
    assert len(exposure) == 1 and exposure[0]["symbol"] == "A"
    assert report["economics"]["verdict"] == "INCONCLUSIVE"
    assert "campaign" not in report
    assert report["decision"] == "DATA_BLOCKED" and report["can_trade"] is False


def test_event_policy_requires_closed_position_audit(tmp_path, monkeypatch):
    settings, _ = configure_event_run(tmp_path, monkeypatch, announcement_offset=-1)
    settings = replace(settings, portfolio=replace(settings.portfolio, liquidate_at_end=False))
    with pytest.raises(ValueError, match="end liquidation"):
        run_stock_development(settings, journal=OperationalJournal(tmp_path / "journal.sqlite3"))


@pytest.mark.parametrize("state", ["at_or_below_sma200", "unknown"])
def test_market_gate_changes_run_identity_and_denies_below_or_unknown_entries(tmp_path, monkeypatch, state):
    settings, _ = configure_event_run(tmp_path, monkeypatch, announcement_offset=-1)
    settings = replace(settings, event_risk_path=None)
    if state == "unknown":
        benchmark = pd.read_parquet(settings.benchmark_path)
        benchmark.iloc[250:].to_parquet(settings.benchmark_path)
    journal = OperationalJournal(tmp_path / "journal.sqlite3")
    control = run_stock_development(settings, journal=journal)
    gated = run_stock_development(replace(settings, market_entry_gate="benchmark_above_sma200"), journal=journal)
    assert control != gated
    assert json.loads(control.read_text())["campaign"]["trades"]
    result = json.loads(gated.read_text())
    assert result["campaign"]["trades"] == []
    assert result["data"]["market_entry_gate"]["session_states"] == {state: 18}
    assert result["can_trade"] is False


def test_market_gate_does_not_liquidate_existing_holdings_on_state_change(tmp_path, monkeypatch):
    settings, _ = configure_event_run(tmp_path, monkeypatch, announcement_offset=-1)
    settings = replace(settings, event_risk_path=None, market_entry_gate="benchmark_above_sma200")
    benchmark = pd.read_parquet(settings.benchmark_path)
    benchmark["close"] = list(range(100, 100 + len(benchmark)))
    benchmark.iloc[253:, 0] = 1
    benchmark.to_parquet(settings.benchmark_path)
    report = run_stock_development(settings, journal=OperationalJournal(tmp_path / "journal.sqlite3"))
    result = json.loads(report.read_text())
    trades = result["campaign"]["trades"]
    assert len(trades) == 1
    assert trades[0]["entry_date"] == str(settings.start)
    assert trades[0]["exit_date"] == str(settings.end)
    assert trades[0]["exit_reason"] == "final_session"
    assert result["data"]["market_entry_gate"]["session_states"]["at_or_below_sma200"] == 16


def test_unknown_market_gate_setting_is_not_silently_ignored(tmp_path):
    path, _ = configured_run(tmp_path)
    payload = json.loads(path.read_text()); payload["market_entry_gate"] = "sma_50"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="market_entry_gate"):
        load_run_settings(path)
