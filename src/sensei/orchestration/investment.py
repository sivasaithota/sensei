"""Journal the AI research desk alongside, never inside, order admission."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from sensei.investment.cycle import canonical, replay, run_desk_cycle
from sensei.operations import EventAppend


def run_investment_research(journal, packet, output_dir, *, command_id, call=None):
    if not isinstance(command_id, str) or not command_id.strip():
        raise ValueError('command_id is required')
    if not journal.verify().ok:
        raise RuntimeError('desk journal integrity failed')
    path = Path(output_dir).resolve()
    identity = sha256(canonical({'packet': packet, 'output_dir': str(path)}).encode()).hexdigest()
    stream = 'ai-desk:' + sha256(command_id.encode()).hexdigest()
    events = journal.read_stream(stream)
    if events:
        if events[0].payload['request_id'] != identity:
            raise ValueError('command_id reused with different research inputs')
        last = events[-1]
        if last.event_type != 'AIInvestmentResearchCompleted':
            raise RuntimeError('research attempt incomplete or failed; inspect saved evidence before a new command')
        artifact = json.loads((path / 'artifact.json').read_text())
        result = replay(path)
        if artifact['digest'] != last.payload['artifact_digest'] or sha256(canonical(result).encode()).hexdigest() != last.payload['result_digest']:
            raise ValueError('research artifact differs from journal record')
        return result

    def append(kind, payload):
        journal.append(EventAppend(
            stream_id=stream, event_type=kind, payload=payload,
            idempotency_key=f'{stream}:{kind}',
            expected_version=len(journal.read_stream(stream)),
            occurred_at=datetime.now(timezone.utc), correlation_id=stream,
        ))

    # Compare-and-append prevents two callers from owning the same model attempt.
    journal.append(EventAppend(
        stream_id=stream, event_type='AIInvestmentResearchStarted',
        payload={'request_id': identity, 'output_dir': str(path), 'authority': 'RESEARCH_ONLY'},
        idempotency_key=f'{stream}:start:{uuid4()}', expected_version=0,
        occurred_at=datetime.now(timezone.utc), correlation_id=stream,
    ))
    try:
        result = run_desk_cycle(packet, path, call=call)
        artifact = json.loads((path / 'artifact.json').read_text())
        append('AIInvestmentResearchCompleted', {
            'result': result, 'artifact_digest': artifact['digest'],
            'result_digest': sha256(canonical(result).encode()).hexdigest(), 'authority': 'RESEARCH_ONLY',
        })
        return result
    except Exception as exc:
        append('AIInvestmentResearchFailed', {'error': f'{type(exc).__name__}: {exc}',
                                              'authority': 'RESEARCH_ONLY'})
        raise
