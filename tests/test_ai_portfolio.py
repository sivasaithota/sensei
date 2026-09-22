from dataclasses import replace
import json
import pytest

from sensei.backtest.ai_portfolio import run_ai_portfolio
from sensei.backtest.relative_strength import MomentumPolicy
from sensei.investment.cycle import run_cycle
from tests.test_relative_strength_portfolio import market


def decision(symbol, weight):
    note = {'symbol': symbol, 'reason': 'test', 'evidence_ids': [symbol]}
    return [{'summary': 'test', 'assessments': [note]}]*2 + [
        {'allocations': [{**note, 'weight_bps': weight, 'invalidation': 'test', 'review_after_sessions': 5}],
         'cash_bps': 10000-weight, 'cash_reason': 'reserve', 'critic_response': 'test'}]


def test_ai_buy_then_exit_has_next_session_fills_and_account_continuity(tmp_path):
    inputs = market()
    dates = inputs.calendar
    inputs = replace(inputs, formations={dates[0]: None, dates[5]: None})
    packets = []
    def decide(packet, path):
        packets.append(packet)
        replies = iter(decision('A', 900 if len(packets) == 1 else 0))
        return run_cycle(packet, path, call=lambda **kw: next(replies))
    result = run_ai_portfolio(inputs, MomentumPolicy(trailing_exit=False),
        formation_start=dates[0], end=dates[-1], universe=['A'], output=tmp_path/'run', decide=decide)
    assert [f['side'] for f in result['fills']] == ['BUY', 'SELL']
    assert result['fills'][0]['session'] == str(dates[1].date())
    assert result['fills'][1]['session'] == str(dates[6].date())
    assert packets[1]['instruments'][0]['held_quantity'] > 0
    for packet in packets:
        cutoff = packet['cutoff'][:10]
        rows = json.loads(packet['evidence'][0]['text'])['raw_unadjusted_history']
        assert all(row['date'] <= cutoff for row in rows)
    assert result['attribution_residual_inr'] == pytest.approx(0, abs=0.001)
    assert result['model_cost_included'] is False


def test_failed_model_publishes_no_return(tmp_path):
    inputs = market()
    with pytest.raises(ValueError, match='AI decision failed'):
        run_ai_portfolio(inputs, MomentumPolicy(trailing_exit=False),
            formation_start=inputs.calendar[0], end=inputs.calendar[-1], universe=['A'],
            output=tmp_path/'run', decide=lambda *args: {'status': 'MODEL_FAILED'})
    assert not (tmp_path/'run'/'report.json').exists()
    assert (tmp_path/'run'/'failure.json').exists()


def test_saved_ai_decisions_reproduce_portfolio_without_models(tmp_path):
    from sensei.backtest.ai_portfolio import saved_decisions
    inputs = market()
    def decide(packet, path):
        replies = iter(decision('A', 900))
        return run_cycle(packet, path, call=lambda **kw: next(replies))
    args = dict(formation_start=inputs.calendar[0], end=inputs.calendar[-1], universe=['A'])
    policy = MomentumPolicy(trailing_exit=False)
    original = run_ai_portfolio(inputs, policy, **args, output=tmp_path/'original', decide=decide)
    reproduced = run_ai_portfolio(inputs, policy, **args, output=tmp_path/'replay', decide=saved_decisions(tmp_path/'original'))
    assert original['fills'] == reproduced['fills']
    assert original['equity_curve'] == reproduced['equity_curve']
    with pytest.raises(ValueError, match='packet differs'):
        run_ai_portfolio(inputs, replace(policy, capital=400000), **args,
                         output=tmp_path/'changed', decide=saved_decisions(tmp_path/'original'))


def test_dividend_receivables_reach_next_ai_packet_without_becoming_cash(tmp_path):
    from sensei.backtest.raw_accounting import RawAction
    inputs = market()
    dates = inputs.calendar
    action = RawAction('A', dates[3], 'dividend', 1., 'dividend', 'Dividend')
    inputs = replace(inputs, raw=replace(inputs.raw, actions=(action,)),
                     formations={dates[0]: None, dates[5]: None})
    packets = []
    def decide(packet, path):
        packets.append(packet)
        replies = iter(decision('A', 900))
        return run_cycle(packet, path, call=lambda **kw: next(replies))
    result = run_ai_portfolio(inputs, MomentumPolicy(trailing_exit=False),
        formation_start=dates[0], end=dates[-1], universe=['A'], output=tmp_path/'run', decide=decide)
    assert packets[1]['receivables_paise'] > 0
    assert result['equity_curve'][-1]['dividend_receivables'] > 0
    assert result['attribution_residual_inr'] == pytest.approx(0, abs=0.001)


def test_invalid_universe_keeps_failure_record(tmp_path):
    inputs = market()
    with pytest.raises(ValueError, match='unknown universe'):
        run_ai_portfolio(inputs, MomentumPolicy(trailing_exit=False),
            formation_start=inputs.calendar[0], end=inputs.calendar[-1], universe=['UNKNOWN'], output=tmp_path/'run')
    failure = json.loads((tmp_path/'run'/'failure.json').read_text())
    assert failure['completed_decisions'] == 0
    assert failure['headline_return_published'] is False


def test_ai_holding_receives_split_shares(tmp_path):
    from sensei.backtest.raw_accounting import RawAction
    inputs = market()
    dates = inputs.calendar
    inputs.raw.frames['A'].loc[dates[3]:, ['open', 'high', 'low', 'close']] = [50., 51., 49., 50.]
    action = RawAction('A', dates[3], 'split', 0., 'split', 'Split', 2, 1,
                       dates[2], dates[4], dates[2], 'b'*64, 'scenario')
    inputs = replace(inputs, raw=replace(inputs.raw, actions=(action,)))
    def decide(packet, path):
        replies = iter(decision('A', 900))
        return run_cycle(packet, path, call=lambda **kw: next(replies))
    result = run_ai_portfolio(inputs, MomentumPolicy(trailing_exit=False),
        formation_start=dates[0], end=dates[-1], universe=['A'], output=tmp_path/'run', decide=decide)
    assert result['terminal_positions'][0]['quantity'] == 538
    assert result['terminal_positions'][0]['pending_shares'] == 0
    assert not [fill for fill in result['fills'] if fill['side'] == 'SELL']
    assert result['attribution_residual_inr'] == pytest.approx(0, abs=0.001)


def test_accounting_overlay_preserves_prices_and_first_decision_but_changes_receivables(tmp_path):
    from hashlib import sha256
    from sensei.backtest.ai_portfolio import AIPortfolio
    from sensei.backtest.raw_accounting import RawAction
    from sensei.research.ai_backtest import accounting_overlay
    inputs = market()
    dates = inputs.calendar
    inputs.raw.frames['A']['prev_close'] = 100.
    inputs = replace(inputs, raw=replace(inputs.raw, actions=(
        RawAction('A', dates[3], 'unsupported', 0., 'old-action', 'Stale ISIN'),)))
    notice = tmp_path/'notice.txt'
    notice.write_text('Synthetic fixture primary notice')
    manifest = {'share_actions': [], 'cash_actions': [{
        'symbol': 'A', 'isin': 'A', 'ex_date': str(dates[3].date()),
        'known_from': str(dates[1].date()), 'amount': 1., 'subject': 'Dividend',
        'replaces_source_id': 'old-action',
        'sources': [{'path': str(notice), 'sha256': sha256(notice.read_bytes()).hexdigest()}]}]}
    repaired, identity = accounting_overlay(inputs, manifest)
    assert repaired.raw.frames is inputs.raw.frames
    assert repaired.formations is inputs.formations
    assert repaired.raw.evidence_sha256 != inputs.raw.evidence_sha256
    assert inputs.raw.actions[0].kind == 'unsupported'
    policy = MomentumPolicy(trailing_exit=False)
    args = dict(universe=['A'], output=tmp_path/'unused', decide=None)
    before = AIPortfolio(inputs, policy, dates[0], dates[-1], **args).packet(dates[0])
    after = AIPortfolio(repaired, policy, dates[0], dates[-1],
                        price_evidence_sha256=inputs.raw.evidence_sha256, **args).packet(dates[0])
    assert before == after  # Raw prices and supplied facts did not change.
    def decide(packet, path):
        replies = iter(decision('A', 900))
        return run_cycle(packet, path, call=lambda **kw: next(replies))
    result = run_ai_portfolio(repaired, policy, formation_start=dates[0], end=dates[-1],
        universe=['A'], output=tmp_path/'run', decide=decide, price_evidence_sha256=inputs.raw.evidence_sha256)
    assert result['equity_curve'][-1]['dividend_receivables'] > 0
    assert result['price_evidence_sha256'] != result['accounting_evidence_sha256']
    assert result['attribution_residual_inr'] == pytest.approx(0, abs=.001)
    notice.write_text('Changed notice')
    with pytest.raises(ValueError):
        accounting_overlay(inputs, manifest)
