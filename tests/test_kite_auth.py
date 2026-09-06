import hashlib
from types import SimpleNamespace

import httpx
import pytest

from sensei.data import kite_auth


def test_callback_requires_state_success_and_exactly_one_token():
    assert kite_auth.callback_token('/?status=success&state=known&request_token=abcdefgh', 'known') == 'abcdefgh'
    for path in ['/?status=success&state=wrong&request_token=abcdefgh',
                 '/?status=success&request_token=abcdefgh',
                 '/?status=success&state=known&request_token=abcdefgh&request_token=ijklmnop',
                 '/other?status=success&state=known&request_token=abcdefgh']:
        assert kite_auth.callback_token(path, 'known') is None


def test_keychain_secret_uses_stdin_not_process_arguments(monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout='supersecret\n' if 'find-generic-password' in args else '')
    monkeypatch.setattr(kite_auth.subprocess, 'run', run)
    kite_auth.write_secret('api-secret', 'supersecret')
    assert all('supersecret' not in str(args) for args, _ in calls)
    assert 'supersecret' in calls[0][1]['input']
    with pytest.raises(kite_auth.KiteAuthError):
        kite_auth.write_secret('api-secret', 'secret\nmalicious-command')


def test_exchange_posts_checksum_without_secret_and_matches_app():
    def handler(request):
        assert request.url == 'https://api.kite.trade/session/token'
        body = request.content.decode()
        assert 'supersecret' not in body
        assert hashlib.sha256(b'apikey123request123supersecret').hexdigest() in body
        return httpx.Response(200, json={'status': 'success', 'data': {
            'api_key': 'apikey123', 'access_token': 'access123'}})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert kite_auth.exchange_token('apikey123', 'supersecret', 'request123', http=client) == 'access123'
