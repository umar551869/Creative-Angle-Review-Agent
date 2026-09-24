"""API-layer tests: validation, error shapes, secret hygiene, wiring.

These need no API key, no network and no model. The pipeline parity test is
tests/test_parity.py and is marked `integration`.
"""
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ.setdefault('AUDITOR_DATA_ROOT', str(HERE / 'data' / 'test'))
os.environ['AUDITOR_PROBE_ON_STARTUP'] = 'false'

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

GDOC = 'https://docs.google.com/document/d/1uWKQMZbOZW_LcEMC5cnFPMfDUTrA/edit'
VID = 'https://www.tiktok.com/@autumndrews/video/7674625522189618445'


@pytest.fixture(scope='module')
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------
def test_health_is_liveness_only(client):
    """/health must be cheap and must not depend on a model or a key.

    A liveness probe that fails because an API key is missing gets the
    container restarted forever instead of reporting a configuration problem.
    """
    r = client.get('/health')
    assert r.status_code == 200
    body = r.json()
    assert body['status'] == 'ok'
    assert 'uptime_s' in body


def test_ready_reports_the_pipeline_and_the_missing_key(client):
    """/ready is readiness: 503 until this instance can actually serve."""
    r = client.get('/ready')
    body = r.json()
    assert body['namespace'] == 'ready', 'the auditor namespace did not load'
    if not os.environ.get('GEMINI_API_KEY'):
        assert r.status_code == 503
        assert body['ready'] is False
        assert any('GEMINI_API_KEY' in p for p in body['problems'])


def test_ready_states_whether_auth_is_on(client):
    """An unprotected deployment must be visible, not assumed."""
    body = client.get('/ready').json()
    assert 'auth' in body
    if not os.environ.get('AUDITOR_API_KEYS'):
        assert 'OPEN' in body['auth']


def test_metrics_are_prometheus_text(client):
    r = client.get('/metrics')
    assert r.status_code == 200
    assert 'audit_up' in r.text
    assert '# TYPE audit_jobs_total gauge' in r.text


def test_request_id_is_returned_and_echoed(client):
    r = client.get('/health')
    assert r.headers.get('x-request-id')
    mine = 'my-trace-0001'
    r2 = client.get('/health', headers={'x-request-id': mine})
    assert r2.headers['x-request-id'] == mine, (
        'a caller-supplied correlation id must survive, or their logs and '
        'ours cannot be joined')


def test_oversized_body_is_413_not_500(client):
    r = client.post('/analyze',
                    headers={'content-length': str(50 * 1024 * 1024),
                             'content-type': 'application/json'},
                    content=b'{}')
    assert r.status_code == 413
    assert 'PayloadTooLarge' in r.text


# ---------------------------------------------------------------------------
# secret hygiene -- the test that matters most
# ---------------------------------------------------------------------------
def test_config_never_returns_a_key_value(client):
    raw = client.get('/config').text
    assert 'AIza' not in raw
    assert 'sk-' not in raw
    body = client.get('/config').json()
    assert body['gemini_api_key'] in ('NOT SET',) or \
        body['gemini_api_key'].startswith('set (')


def test_hf_token_is_optional_and_never_shown(client):
    """It is optional -- but if it IS set, /config must not echo it."""
    body = client.get('/config').json()
    assert 'hf_token' in body
    assert body['hf_token'].startswith(('set (', 'not set'))
    assert 'hf_' not in client.get('/config').text.replace('hf_token', '') \
        or 'hf_home' in client.get('/config').text


def test_hf_token_is_exported_under_both_names(monkeypatch):
    """huggingface_hub reads HF_TOKEN; older versions read the long name.

    Nothing in the pipeline takes a token argument -- WhisperModel and
    SentenceTransformer both resolve credentials through the environment -- so
    exporting it IS the whole integration.
    """
    import importlib

    from app import config as cfg_mod

    monkeypatch.setenv('HF_TOKEN', 'hf_' + 'a' * 34)
    monkeypatch.delenv('HUGGING_FACE_HUB_TOKEN', raising=False)
    importlib.reload(cfg_mod)
    s = cfg_mod.Settings()
    applied = s.apply_to_environment()
    assert 'HF_TOKEN' in applied
    assert os.environ['HF_TOKEN'] == 'hf_' + 'a' * 34
    assert os.environ['HUGGING_FACE_HUB_TOKEN'] == 'hf_' + 'a' * 34
    assert s.redacted()['hf_token'] == 'set (37 chars)'


def test_hf_token_accepts_the_older_variable_name(monkeypatch):
    monkeypatch.delenv('HF_TOKEN', raising=False)
    monkeypatch.setenv('HUGGING_FACE_HUB_TOKEN', 'hf_' + 'b' * 34)
    from app import config as cfg_mod
    s = cfg_mod.Settings()
    assert s.hf_token == 'hf_' + 'b' * 34


def test_no_hf_token_is_not_a_startup_problem(monkeypatch):
    """OPTIONAL means optional: a missing HF token must not degrade health."""
    monkeypatch.delenv('HF_TOKEN', raising=False)
    monkeypatch.delenv('HUGGING_FACE_HUB_TOKEN', raising=False)
    monkeypatch.setenv('GEMINI_API_KEY', 'x' * 20)
    from app import config as cfg_mod
    s = cfg_mod.Settings()
    assert s.hf_token == ''
    assert s.missing_requirements() == []


@pytest.mark.parametrize('label,sample', [
    ('google AIza', 'AIzaSyA1234567890abcdefghijklmnopqrstuv'),
    # The newer Google format. It leaked past a redactor that knew only AIza
    # -- a scrubber covering one vendor shape gives false confidence.
    ('google AQ.', 'AQ.Ab8RN6abcdefghij1234567890ABCDEFGHIJKLMN'),
    ('google ya29', 'ya29.a0AfB_byC1234567890abcdefghijklmnop'),
    ('openai', 'sk-proj-abcdefghij1234567890XYZlmnopqrst'),
    # SYNTHETIC. An earlier version of this line carried a real token copied
    # out of .env.example -- writing the leak test is exactly when it is
    # easiest to create a leak, because a realistic fixture is one
    # copy-paste away. Every sample here contains an obvious sequence
    # (abcdef / 123456) so the repo scanner can tell it from a live key.
    ('hugging face', 'hf_abcdefghij1234567890ABCDEFGHIJKLMN'),
])
def test_every_key_shape_is_redacted(label, sample):
    import logging

    from app.logging_setup import RedactingFilter

    rec = logging.LogRecord('t', logging.INFO, __file__, 1, 'key=%s',
                            (sample,), None)
    RedactingFilter().filter(rec)
    assert sample not in rec.getMessage(), f'{label} leaked into the log'


@pytest.mark.parametrize('msg', [
    'processing video 7674625522189618445.mp4',
    'gemini-3.5-flash-lite answered in 25.5s',
    'brief hash 4a9c1f2e written to disk',
])
def test_redaction_does_not_eat_ordinary_logs(msg):
    """A scrubber that mangles normal lines gets switched off."""
    import logging

    from app.logging_setup import RedactingFilter

    rec = logging.LogRecord('t', logging.INFO, __file__, 1, msg, (), None)
    RedactingFilter().filter(rec)
    assert rec.getMessage() == msg


def test_env_example_carries_no_real_credential():
    """.env.example is COMMITTED; .gitignore covers .env and not the template.

    A value left in it is a value that ships.
    """
    import re as _re

    text = (HERE / '.env.example').read_text(encoding='utf-8')
    filled = [(m.group(2), m.group(3).strip())
              for m in _re.finditer(r'^(#\s*)?([A-Z][A-Z0-9_]*)=(.+)$', text,
                                    _re.M)
              if any(s in m.group(2) for s in
                     ('API_KEY', 'TOKEN', 'SECRET', 'PASSWORD'))
              and m.group(3).strip()]
    assert not filled, (
        f'the committed template carries {len(filled)} credential(s): '
        f'{[n for n, _ in filled]}')


def test_dotenv_is_actually_loaded():
    """`cp .env.example .env` must do something outside Docker."""
    from app.config import DOTENV_STATUS

    assert 'NOT read' not in DOTENV_STATUS, DOTENV_STATUS


def test_log_filter_redacts_credentials():
    import logging

    from app.logging_setup import RedactingFilter

    f = RedactingFilter()
    rec = logging.LogRecord('t', logging.INFO, __file__, 1,
                            'key=AIzaSyA1234567890abcdefghijklmnopqrstuv',
                            (), None)
    f.filter(rec)
    assert 'AIzaSyA1234567890' not in rec.getMessage()

    rec2 = logging.LogRecord('t', logging.INFO, __file__, 1,
                             'token: sk-proj-abcdefghij1234567890XYZ',
                             (), None)
    f.filter(rec2)
    assert 'abcdefghij1234567890XYZ' not in rec2.getMessage()


# ---------------------------------------------------------------------------
# input validation -- specific errors, never a generic "failed"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('payload,fragment', [
    ({'video_urls': [VID]}, 'brief_url'),
    ({'video_urls': [VID], 'brief_url': GDOC, 'brief_text': 'x'},
     'mutually exclusive'),
    ({'video_urls': [], 'brief_text': 'x'}, 'too_short'),
    ({'video_urls': ['tiktok.com/@a/video/1'], 'brief_text': 'x'}, 'not a URL'),
])
def test_bad_requests_are_422_and_say_why(client, payload, fragment):
    r = client.post('/analyze', json=payload)
    assert r.status_code == 422
    assert fragment in r.text, r.text[:300]


def test_video_ceiling_is_enforced_and_names_the_knob(client):
    r = client.post('/analyze', json={
        'video_urls': [f'https://www.tiktok.com/@a/video/{i}'
                       for i in range(100)],
        'brief_text': 'Show the product.'})
    assert r.status_code == 422
    assert 'AUDITOR_MAX_VIDEOS' in r.text


def test_analyze_refuses_without_a_key(client):
    """503, not a job that fails twelve minutes later."""
    if os.environ.get('GEMINI_API_KEY'):
        pytest.skip('a key is configured')
    r = client.post('/analyze',
                    json={'video_urls': [VID], 'brief_text': 'Show it.'})
    assert r.status_code == 503
    assert 'GEMINI_API_KEY' in r.text


def test_unknown_job_is_404(client):
    assert client.get('/jobs/0123456789abcdef').status_code == 404


def test_report_for_unknown_job_is_404(client):
    r = client.get('/jobs/0123456789abcdef/report/abc.html')
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# brief ingestion rules carried over from the notebook
# ---------------------------------------------------------------------------
def test_non_google_brief_url_is_refused_with_the_reason(client):
    r = client.post('/briefs/compile',
                    json={'brief_url': 'https://example.com/brief.txt'})
    assert r.status_code == 422
    assert 'Google Doc' in r.text


def test_brief_requires_one_of_the_two_inputs(client):
    r = client.post('/briefs/compile', json={})
    assert r.status_code == 422
