"""Authentication, and the paths that must stay open.

An API that spends model quota on anyone who can reach the port is the single
most consequential gap in a deployed version of this, so these are asserted
rather than assumed.
"""
import importlib
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ.setdefault('AUDITOR_DATA_ROOT', str(HERE / 'data' / 'test'))
os.environ['AUDITOR_PROBE_ON_STARTUP'] = 'false'

KEY = 'test-key-aaaaaaaaaaaaaaaaaaaa'
OTHER = 'test-key-bbbbbbbbbbbbbbbbbbbb'


@pytest.fixture()
def secured(monkeypatch):
    """An app instance with auth switched on."""
    monkeypatch.setenv('AUDITOR_API_KEYS', f'{KEY}, {OTHER}')
    monkeypatch.setenv('GEMINI_API_KEY', 'x' * 30)
    import app.config
    import app.main
    import app.security
    app.config.get_settings.cache_clear()
    importlib.reload(app.security)
    importlib.reload(app.main)
    from fastapi.testclient import TestClient
    with TestClient(app.main.app, raise_server_exceptions=False) as c:
        yield c
    app.config.get_settings.cache_clear()


# ---------------------------------------------------------------------------
def test_protected_endpoint_refuses_without_a_key(secured):
    r = secured.post('/analyze', json={'video_urls': ['https://x/1'],
                                       'brief_text': 'Show it.'})
    assert r.status_code == 401
    assert 'x-api-key' in r.text


def test_wrong_key_is_401(secured):
    r = secured.get('/jobs', headers={'x-api-key': 'nope'})
    assert r.status_code == 401


def test_correct_key_passes(secured):
    r = secured.get('/jobs', headers={'x-api-key': KEY})
    assert r.status_code == 200


def test_any_configured_key_works(secured):
    assert secured.get('/jobs',
                       headers={'x-api-key': OTHER}).status_code == 200


def test_bearer_token_is_accepted_too(secured):
    r = secured.get('/jobs', headers={'authorization': f'Bearer {KEY}'})
    assert r.status_code == 200


@pytest.mark.parametrize('path', ['/health', '/ready', '/metrics'])
def test_probe_paths_stay_open(secured, path):
    """A load balancer cannot present a key, and a health check that 401s
    reads as a dead container."""
    assert secured.get(path).status_code in (200, 503)


def test_config_is_protected_when_auth_is_on(secured):
    """/config lists settings. It stays behind the key even though the values
    are redacted -- it still describes the deployment."""
    assert secured.get('/config').status_code == 401
    assert secured.get('/config',
                       headers={'x-api-key': KEY}).status_code == 200


def test_key_comparison_is_constant_time():
    """== short-circuits on the first differing byte, which leaks the prefix
    to anyone willing to time the responses."""
    src = (HERE / 'app' / 'security.py').read_text(encoding='utf-8')
    assert 'compare_digest' in src
    assert 'presented == k' not in src


def test_a_rejected_key_is_not_logged_in_full(caplog):
    import logging

    import app.security as sec
    os.environ['AUDITOR_API_KEYS'] = KEY

    class _Req:
        url = type('U', (), {'path': '/analyze'})()
        headers = {'x-api-key': 'wrongkeywrongkeywrongkey'}

    with caplog.at_level(logging.WARNING):
        with pytest.raises(Exception):
            sec.require_key(_Req())
    text = ' '.join(r.getMessage() for r in caplog.records)
    assert 'wrongkeywrongkeywrongkey' not in text, (
        'a rejected credential was written to the log in full')
    os.environ.pop('AUDITOR_API_KEYS', None)


def test_open_by_default_but_says_so():
    import app.security as sec
    os.environ.pop('AUDITOR_API_KEYS', None)
    importlib.reload(sec)
    assert sec.configured_keys() == []
    assert 'OPEN' in sec.auth_mode()
