import json
from copy import deepcopy

import pytest

from sensei.investment.cycle import run_cycle, replay


def packet():
    return {
        'label': 'synthetic-test', 'synthetic': True,
        'cutoff': '2026-09-21T16:00:00+05:30',
        'cash_paise': 30_000_000, 'high_water_paise': 30_000_000,
        'instruments': [
            {'symbol': s, 'price_paise': 10_000, 'marked_at': '2026-09-21T15:30:00+05:30',
             'held_quantity': 0, 'available_quantity': 0}
            for s in ('AAA', 'BBB')],
        'evidence': [
            {'id': s, 'symbol': s, 'source': 'synthetic://fixture',
             'published_at': '2026-09-21T14:00:00+05:30',
             'available_at': '2026-09-21T14:01:00+05:30',
             'text': 'Invented test company, no real investment evidence.'}
            for s in ('AAA', 'BBB')],
        'limits': {'max_position_bps': 2000, 'min_cash_bps': 500,
                   'max_positions': 10, 'max_mark_age_hours': 96,
                   'max_drawdown_bps': 1500},
    }


def responses(symbol='BBB', weight=1500):
    note = {'symbol': symbol, 'reason': 'Fixture argument', 'evidence_ids': [symbol]}
    return [
        {'summary': 'Propose investment', 'assessments': [note]},
        {'summary': 'Challenge assumptions', 'assessments': [note]},
        {'allocations': [{**note, 'weight_bps': weight, 'invalidation': 'Fixture fails',
                          'review_after_sessions': 5}],
         'cash_bps': 10000-weight, 'cash_reason': 'Retain liquidity',
         'critic_response': 'Size conservatively given uncertainty'},
    ]


def caller(outputs):
    items = iter(outputs)
    return lambda **kwargs: next(items)


def test_ai_selects_stock_and_replay_does_not_call_model(tmp_path):
    report = run_cycle(packet(), tmp_path/'run', call=caller(responses()))
    assert report['status'] == 'READY'
    assert report['preview']['orders'][0]['symbol'] == 'BBB'
    assert report['preview']['orders'][0]['quantity'] == 450
    assert report['preview']['cash_after_buys_paise'] < 25_500_000
    assert replay(tmp_path/'run') == report
    with pytest.raises(FileExistsError):
        run_cycle(packet(), tmp_path/'run', call=caller(responses()))


def test_intentional_cash_is_not_failure(tmp_path):
    outputs = responses()
    outputs[-1]['allocations'] = []
    outputs[-1]['cash_bps'] = 10000
    result = run_cycle(packet(), tmp_path/'run', call=caller(outputs))
    assert result['status'] == 'AI_CHOSE_CASH'
    assert result['preview']['orders'] == []


@pytest.mark.parametrize('change', ['future', 'stale', 'duplicate', 'boolean_cash'])
def test_invalid_packet_calls_no_model(tmp_path, change):
    p = packet()
    if change == 'future':
        p['evidence'][0]['available_at'] = '2026-09-22T00:00:00+05:30'
    if change == 'stale':
        p['instruments'][0]['marked_at'] = '2026-09-01T00:00:00+05:30'
    if change == 'duplicate':
        p['evidence'].append(deepcopy(p['evidence'][0]))
    if change == 'boolean_cash':
        p['cash_paise'] = True
    def forbidden(**kwargs):
        pytest.fail('invalid packet must not reach model')
    assert run_cycle(p, tmp_path/'run', call=forbidden)['status'] == 'INPUT_BLOCKED'


@pytest.mark.parametrize('change', ['citation', 'overweight', 'missing_holding', 'boolean_weight'])
def test_bad_decision_is_failure_not_cash(tmp_path, change):
    p, outputs = packet(), responses()
    if change == 'citation':
        outputs[-1]['allocations'][0]['evidence_ids'] = ['AAA']
    if change == 'overweight':
        outputs[-1]['allocations'][0]['weight_bps'] = 3000
        outputs[-1]['cash_bps'] = 7000
    if change == 'missing_holding':
        p['instruments'][0].update(held_quantity=10, available_quantity=10)
        p['cash_paise'] -= 100_000
    if change == 'boolean_weight':
        outputs[-1]['allocations'][0]['weight_bps'] = True
    result = run_cycle(p, tmp_path/'run', call=caller(outputs))
    assert result['status'] in ('MODEL_FAILED', 'RISK_REJECTED')
    assert 'preview' not in result


def test_provider_failure_saved(tmp_path):
    def fail(**kwargs):
        raise RuntimeError('provider down')
    result = run_cycle(packet(), tmp_path/'run', call=fail)
    assert result['status'] == 'MODEL_FAILED'
    assert json.loads((tmp_path/'run'/'artifact.json').read_text())['result'] == result


def test_sales_cannot_fund_buys(tmp_path):
    p = packet()
    p['cash_paise'] = 0
    p['instruments'][0].update(held_quantity=3000, available_quantity=3000)
    outputs = responses()
    outputs[-1]['allocations'].append({**outputs[-1]['allocations'][0],
                                      'symbol': 'AAA', 'weight_bps': 0, 'evidence_ids': ['AAA']})
    assert run_cycle(p, tmp_path/'run', call=caller(outputs))['status'] == 'RISK_REJECTED'


def test_drawdown_blocks_increase_but_allows_exit(tmp_path):
    p = packet()
    p['high_water_paise'] = 40_000_000
    assert run_cycle(p, tmp_path/'buy', call=caller(responses()))['status'] == 'RISK_REJECTED'
    p['instruments'][1].update(held_quantity=10, available_quantity=10)
    assert run_cycle(p, tmp_path/'sell', call=caller(responses(weight=0)))['status'] == 'AI_CHOSE_CASH'


def test_unavailable_holding_cannot_be_sold(tmp_path):
    p = packet()
    p['instruments'][1]['held_quantity'] = 10
    p['cash_paise'] -= 100_000
    assert run_cycle(p, tmp_path/'run', call=caller(responses(weight=0)))['status'] == 'RISK_REJECTED'


def test_replay_detects_edit(tmp_path):
    run_cycle(packet(), tmp_path/'run', call=caller(responses()))
    path = tmp_path/'run'/'artifact.json'
    artifact = json.loads(path.read_text())
    artifact['packet']['cash_paise'] += 1
    path.write_text(json.dumps(artifact))
    with pytest.raises(ValueError, match='digest'):
        replay(tmp_path/'run')


def test_isolated_provider_has_no_tools(monkeypatch):
    from types import SimpleNamespace
    from sensei import llm
    monkeypatch.setenv('SENSEI_LLM_BACKEND', 'claude-code')
    monkeypatch.setattr(llm.shutil, 'which', lambda name: '/bin/claude')
    captured = []
    def execute(command, **kwargs):
        captured.append(command)
        return SimpleNamespace(returncode=0, stdout='{"result":"{\\"ok\\":true}"}')
    monkeypatch.setattr(llm.subprocess, 'run', execute)
    assert llm.structured_call(system='test', user='test', schema={}, name='test', isolated=True) == {'ok': True}
    command = captured[0]
    assert command[command.index('--tools')+1] == ''
    assert '--safe-mode' in command
    assert '--strict-mcp-config' in command
    assert command[command.index('--mcp-config')+1] == '{"mcpServers":{}}'


def test_model_is_free_to_choose_different_stock(tmp_path):
    first = run_cycle(packet(), tmp_path/'first', call=caller(responses('AAA')))
    second = run_cycle(packet(), tmp_path/'second', call=caller(responses('BBB')))
    assert first['preview']['orders'][0]['symbol'] == 'AAA'
    assert second['preview']['orders'][0]['symbol'] == 'BBB'


def test_nonfinite_input_has_durable_failure(tmp_path):
    p = packet()
    p['cash_paise'] = float('inf')
    assert run_cycle(p, tmp_path/'run', call=caller([]))['status'] == 'INPUT_BLOCKED'
    assert replay(tmp_path/'run')['status'] == 'INPUT_BLOCKED'


def test_malformed_model_text_is_saved(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from sensei import llm
    monkeypatch.setenv('SENSEI_LLM_BACKEND', 'claude-code')
    monkeypatch.setattr(llm.shutil, 'which', lambda name: '/bin/claude')
    raw = '{"result":"not JSON, but useful failure evidence"}'
    monkeypatch.setattr(llm.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0, stdout=raw))
    assert run_cycle(packet(), tmp_path/'run')['status'] == 'MODEL_FAILED'
    artifact = json.loads((tmp_path/'run'/'artifact.json').read_text())
    assert artifact['steps'][0]['raw_provider_response'] == raw


def test_isolated_api_disables_transport_retries(monkeypatch):
    import anthropic
    from types import SimpleNamespace
    from sensei import llm
    monkeypatch.setenv('SENSEI_LLM_BACKEND', 'api')
    seen = {}
    def create_client(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(messages=SimpleNamespace(create=lambda **kw:
            SimpleNamespace(content=[SimpleNamespace(type='tool_use', input={'ok': True})])))
    monkeypatch.setattr(anthropic, 'Anthropic', create_client)
    assert llm.structured_call(system='test', user='test', schema={}, name='test', isolated=True) == {'ok': True}
    assert seen['max_retries'] == 0


def test_full_desk_uses_research_roles_and_coach_cannot_change_decision(tmp_path):
    from sensei.investment.cycle import run_desk_cycle
    outputs = responses()
    research = outputs[0]
    calls = []
    scripted = iter([research, research, research, *outputs, research])
    def model(**kwargs):
        calls.append(kwargs['name'])
        if kwargs['name'] == 'analyst':
            prior = json.loads(kwargs['user'])['previous_roles']
            assert [item['role'] for item in prior] == ['historian', 'reporter', 'crowd_reader']
        return next(scripted)
    result = run_desk_cycle(packet(), tmp_path/'run', call=model)
    assert calls == ['historian', 'reporter', 'crowd_reader', 'analyst', 'critic', 'manager', 'coach']
    assert result['decision']['allocations'][0]['symbol'] == 'BBB'
    assert len(result['desk_roles']) == 9
    assert result['execution_status'] == 'NOT_ADMITTED'
    assert result['desk_roles']['trader']['status'] == 'SKIPPED'
    assert replay(tmp_path/'run') == result


def test_full_desk_research_failure_skips_downstream_roles(tmp_path):
    from sensei.investment.cycle import run_desk_cycle
    result = run_desk_cycle(packet(), tmp_path/'run', call=caller([{}]))
    assert result['status'] == 'MODEL_FAILED'
    assert result['role'] == 'historian'
    assert result['desk_roles']['analyst']['status'] == 'SKIPPED'
    assert result['desk_roles']['trader']['status'] == 'SKIPPED'


def test_existing_desk_journals_ai_research_without_using_order_path(tmp_path):
    from tests.test_desk_runtime import _runtime_fixture
    desk, _, coach, secretary, gateway, journal, _ = _runtime_fixture(tmp_path)
    outputs = responses()
    scripted = [outputs[0]] * 3 + outputs + [outputs[0]]
    result = desk.run_investment_cycle(packet(), tmp_path/'research', command_id='ai-1', call=caller(scripted))
    assert result['execution_status'] == 'NOT_ADMITTED'
    def forbidden(**kwargs):
        pytest.fail('completed command replay must not call the model')
    assert desk.run_investment_cycle(packet(), tmp_path/'research', command_id='ai-1', call=forbidden) == result
    changed = packet()
    changed['label'] = 'different request'
    with pytest.raises(ValueError, match='reused'):
        desk.run_investment_cycle(changed, tmp_path/'research', command_id='ai-1', call=forbidden)
    assert coach.calls == 0  # Process critique does not fabricate reconciled outcomes.
    assert journal.verify().ok


def test_coach_failure_does_not_relabel_valid_committee_risk_result(tmp_path):
    from sensei.investment.cycle import run_desk_cycle
    outputs = responses()
    result = run_desk_cycle(packet(), tmp_path/'run', call=caller([outputs[0]]*3 + outputs + [{}]))
    assert result['status'] == 'MODEL_FAILED'
    assert result['role'] == 'coach'
    assert result['desk_roles']['committee']['risk_preview'] == 'READY'


def test_risk_rejection_skips_coach(tmp_path):
    from sensei.investment.cycle import run_desk_cycle
    outputs = responses(weight=3000)
    result = run_desk_cycle(packet(), tmp_path/'run', call=caller([outputs[0]]*3 + outputs))
    assert result['status'] == 'RISK_REJECTED'
    assert result['desk_roles']['coach']['status'] == 'SKIPPED'


def test_journal_binding_rejects_rehashed_artifact(tmp_path):
    from tests.test_desk_runtime import _runtime_fixture
    from sensei.investment.cycle import save
    desk, _, _, _, _, _, _ = _runtime_fixture(tmp_path)
    outputs = responses()
    directory = tmp_path/'research'
    desk.run_investment_cycle(packet(), directory, command_id='ai-1', call=caller([outputs[0]]*3 + outputs + [outputs[0]]))
    artifact = json.loads((directory/'artifact.json').read_text())
    artifact['packet']['label'] = 'silently edited'
    save(directory, artifact)
    with pytest.raises(ValueError, match='differs from journal'):
        desk.run_investment_cycle(packet(), directory, command_id='ai-1', call=caller([]))


def test_in_progress_desk_command_cannot_be_run_twice(tmp_path):
    from tests.test_desk_runtime import _runtime_fixture
    desk, _, _, _, gateway, _, _ = _runtime_fixture(tmp_path)
    outputs = responses()
    scripted = iter([outputs[0]]*3 + outputs + [outputs[0]])
    def model(**kwargs):
        with pytest.raises(RuntimeError, match='incomplete'):
            desk.run_investment_cycle(packet(), tmp_path/'research', command_id='ai-1', call=caller([]))
        return next(scripted)
    desk.run_investment_cycle(packet(), tmp_path/'research', command_id='ai-1', call=model)
    assert gateway.commands == ()


def test_resume_reuses_only_exact_validated_role_responses(tmp_path):
    from sensei.investment.cycle import run_desk_cycle
    outputs = responses()
    failed = run_desk_cycle(packet(), tmp_path/'failed', call=caller([outputs[0], outputs[0], {}]))
    assert failed['role'] == 'crowd_reader'
    calls = []
    remaining = iter([outputs[0], *outputs, outputs[0]])
    def model(**kwargs):
        calls.append(kwargs['name'])
        return next(remaining)
    recovered = run_desk_cycle(packet(), tmp_path/'recovered', call=model, resume_from=tmp_path/'failed')
    assert recovered['status'] == 'READY'
    assert calls == ['crowd_reader', 'analyst', 'critic', 'manager', 'coach']
    artifact = json.loads((tmp_path/'recovered'/'artifact.json').read_text())
    assert 'source_digest' in artifact['steps'][0]
    assert replay(tmp_path/'failed')['status'] == 'MODEL_FAILED'
    changed = packet()
    changed['label'] = 'changed'
    assert run_desk_cycle(changed, tmp_path/'bad', call=caller([]), resume_from=tmp_path/'failed')['status'] == 'INPUT_BLOCKED'


def test_peer_comparison_allowed_only_with_primary_stock_evidence(tmp_path):
    outputs = responses()
    outputs[1]['assessments'][0]['evidence_ids'] = ['BBB', 'AAA']
    assert run_cycle(packet(), tmp_path/'valid', call=caller(outputs))['status'] == 'READY'
    outputs = responses()
    outputs[1]['assessments'][0]['evidence_ids'] = ['AAA']
    assert run_cycle(packet(), tmp_path/'invalid', call=caller(outputs))['status'] == 'MODEL_FAILED'


def test_resume_revalidates_response_rejected_by_old_peer_rule(tmp_path):
    from sensei.investment.cycle import run_desk_cycle, save
    outputs = responses()
    outputs[1]['assessments'][0]['evidence_ids'] = ['BBB', 'AAA']
    run_desk_cycle(packet(), tmp_path/'old', call=caller([outputs[0]]*3 + outputs + [outputs[0]]))
    artifact = json.loads((tmp_path/'old'/'artifact.json').read_text())
    artifact['steps'] = artifact['steps'][:5]
    artifact['steps'][-1]['validated'] = False
    artifact['result'] = {'status': 'MODEL_FAILED', 'role': 'critic', 'error': 'old peer-citation restriction'}
    save(tmp_path/'old', artifact)
    calls = []
    remaining = iter([outputs[2], outputs[0]])
    def model(**kwargs):
        calls.append(kwargs['name'])
        return next(remaining)
    result = run_desk_cycle(packet(), tmp_path/'new', call=model, resume_from=tmp_path/'old')
    assert result['status'] == 'READY'
    assert calls == ['manager', 'coach']
    saved = json.loads((tmp_path/'new'/'artifact.json').read_text())
    assert saved['steps'][4]['revalidated_after_failure'] is True


def test_target_contract_derives_cash_without_altering_stock_choices(tmp_path):
    from sensei.investment.cycle import run_desk_cycle
    outputs = responses()
    del outputs[-1]['cash_bps']
    result = run_desk_cycle(packet(), tmp_path/'run', target_only=True,
                            call=caller([outputs[0]]*3 + outputs + [outputs[0]]))
    assert result['status'] == 'READY'
    assert result['decision']['cash_bps'] == 8500
    assert result['decision']['allocations'][0]['weight_bps'] == 1500
    assert replay(tmp_path/'run') == result


def test_new_manager_contract_reuses_research_but_requests_new_decision(tmp_path):
    from sensei.investment.cycle import run_desk_cycle
    outputs = responses()
    outputs[-1]['cash_bps'] = 9000
    old = run_desk_cycle(packet(), tmp_path/'old', call=caller([outputs[0]]*3+outputs))
    assert old['status'] == 'RISK_REJECTED'
    del outputs[-1]['cash_bps']
    calls = []
    remaining = iter([outputs[-1], outputs[0]])
    def model(**kwargs):
        calls.append(kwargs['name'])
        return next(remaining)
    result = run_desk_cycle(packet(), tmp_path/'new', target_only=True, resume_from=tmp_path/'old', call=model)
    assert result['status'] == 'READY'
    assert calls == ['manager', 'coach']


def test_coach_process_notes_do_not_need_fictitious_stock(tmp_path):
    from sensei.investment.cycle import run_desk_cycle
    outputs = responses()
    coach = {'summary': 'Research gaps', 'assessments': [],
             'process_notes': ['Obtain dated filings before drawing earnings conclusions.']}
    result = run_desk_cycle(packet(), tmp_path/'run',
                            call=caller([outputs[0]]*3 + outputs + [coach]))
    assert result['status'] == 'READY'
    assert result['decision'] == outputs[-1]
    assert replay(tmp_path/'run') == result
    coach['assessments'] = [{'symbol': 'PORTFOLIO_PROCESS', 'reason': 'Review', 'evidence_ids': ['BBB']}]
    rejected = run_desk_cycle(packet(), tmp_path/'bad',
                              call=caller([outputs[0]]*3 + outputs + [coach]))
    assert rejected['status'] == 'MODEL_FAILED'
    assert 'unknown symbol' in rejected['error']


def test_new_coach_contract_preserves_saved_manager(tmp_path):
    from sensei.investment.cycle import run_desk_cycle, save
    from sensei.investment.models import Analysis
    outputs = responses()
    run_desk_cycle(packet(), tmp_path/'old', call=caller([outputs[0]]*3 + outputs + [{}]))
    artifact = json.loads((tmp_path/'old'/'artifact.json').read_text())
    artifact['steps'][-1]['schema'] = Analysis.model_json_schema()
    artifact['steps'][-1]['output'] = outputs[0]
    save(tmp_path/'old', artifact)
    calls = []
    def model(**kwargs):
        calls.append(kwargs['name'])
        return {'summary': 'Review', 'assessments': [], 'process_notes': ['Missing news.']}
    result = run_desk_cycle(packet(), tmp_path/'new', resume_from=tmp_path/'old', call=model)
    assert result['status'] == 'READY'
    assert result['decision'] == outputs[-1]
    assert calls == ['coach']
