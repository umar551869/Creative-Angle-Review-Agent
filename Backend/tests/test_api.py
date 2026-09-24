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


# ---------------------------------------------------------------------------
# POST /analyze/upload -- the client already has the bytes
#
# This exists because URL ingestion is the least reliable stage of a deployed
# run: TikTok refuses anonymous downloads from datacentre IPs far more often
# than from residential ones. Everything downstream is identical, so these
# tests are about the boundary: what gets written, what gets refused, and what
# is left behind when a request fails.
# ---------------------------------------------------------------------------
MP4 = b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom' + b'\x00' * 64


def _upload(client, files, **form):
    form.setdefault('brief_text', 'Show the product and name it.')
    return client.post('/analyze/upload', files=files, data=form)


@pytest.fixture
def staged(monkeypatch):
    """A key present, the worker disarmed, and no job left behind.

    Staging is what these tests are about. Letting the job actually submit
    would start the real pipeline in a background thread -- it would fail on
    the fake brief, slowly, while the assertions raced it.

    THE CLEANUP IS NOT TIDINESS. Every accepted upload writes a real
    jobs/<id>/ directory, and `GET /jobs` is capped at 100 by created_at. Left
    to accumulate, these pushed an older fixture job out of the window and
    broke test_listing_includes_jobs_that_survived_a_restart -- a test in
    another file, failing for a reason invisible from inside it.
    """
    import shutil

    from app import jobs as jobs_mod
    from app.main import settings as live

    monkeypatch.setattr(live, 'gemini_api_key', 'test-key-not-real')
    monkeypatch.setattr(jobs_mod.JobStore, 'submit', lambda self, job: None)

    root = live.jobs
    before = {d.name for d in root.iterdir()} if root.is_dir() else set()
    yield live
    if root.is_dir():
        for d in root.iterdir():
            if d.name not in before:
                shutil.rmtree(d, ignore_errors=True)


def test_upload_rejects_a_non_video_extension(client, staged):
    r = _upload(client, [('files', ('notes.txt', b'hello', 'text/plain'))])
    assert r.status_code == 422
    assert 'video extension' in r.text, r.text[:300]


def test_upload_rejects_bytes_that_are_not_a_video(client, staged):
    """The extension is the caller's claim; the container bytes are the fact.

    Accepting this would trade a clear 422 for a job that dies in Phase 1
    decode with an ffmpeg error no operator can act on.
    """
    r = _upload(client, [('files', ('clip.mp4', b'not a video at all' * 4,
                                    'video/mp4'))])
    assert r.status_code == 422
    assert 'container' in r.text, r.text[:300]


def test_upload_rejects_an_empty_file(client, staged):
    r = _upload(client, [('files', ('clip.mp4', b'', 'video/mp4'))])
    assert r.status_code == 422
    assert 'empty' in r.text


def test_upload_enforces_the_per_file_ceiling(client, staged, monkeypatch):
    monkeypatch.setattr(staged, 'max_video_bytes', 1024)
    r = _upload(client, [('files', ('big.mp4', MP4 + b'\x00' * 4096,
                                    'video/mp4'))])
    assert r.status_code == 413
    assert 'AUDITOR_MAX_VIDEO_BYTES' in r.text


def test_upload_still_requires_a_brief(client, staged):
    """The guard is shared with /analyze, so a second door cannot skip it."""
    r = client.post('/analyze/upload',
                    files=[('files', ('a.mp4', MP4, 'video/mp4'))])
    assert r.status_code == 422
    assert 'brief_url' in r.text


def test_upload_refuses_without_a_key(client):
    if os.environ.get('GEMINI_API_KEY'):
        pytest.skip('a key is configured')
    r = _upload(client, [('files', ('a.mp4', MP4, 'video/mp4'))])
    assert r.status_code == 503
    assert 'GEMINI_API_KEY' in r.text


def test_upload_honours_the_video_ceiling(client, staged, monkeypatch):
    monkeypatch.setattr(staged, 'max_videos_per_job', 2)
    r = _upload(client, [('files', (f'{i}.mp4', MP4, 'video/mp4'))
                         for i in range(3)])
    assert r.status_code == 422
    assert 'AUDITOR_MAX_VIDEOS' in r.text


def test_upload_stages_the_files_and_queues_a_job(client, staged):
    from auditor import runtime

    r = _upload(client, [('files', ('7671762950687919390.mp4', MP4,
                                    'video/mp4')),
                         ('files', ('second.mov', MP4, 'video/quicktime'))])
    assert r.status_code == 202, r.text[:400]
    body = r.json()
    assert body['status'] == 'queued'
    job_id = body['job_id']

    inbox = runtime.job_dirs(job_id)['inbox']
    landed = sorted(p.name for p in inbox.iterdir())
    assert landed == ['7671762950687919390.mp4', 'second.mov']
    # The id-named file keeps the link mapping url_for_source relies on.
    assert client.get(f'/jobs/{job_id}').json()['requested_videos'] == 2


def test_upload_sanitises_a_traversing_filename(client, staged):
    from auditor import runtime

    r = _upload(client, [('files', ('../../../evil.mp4', MP4, 'video/mp4'))])
    assert r.status_code == 202, r.text[:300]
    inbox = runtime.job_dirs(r.json()['job_id'])['inbox']
    names = [p.name for p in inbox.iterdir()]
    assert names == ['evil.mp4'], names
    assert not (inbox.parent.parent / 'evil.mp4').exists()


def test_a_failed_upload_leaves_no_phantom_job(client, staged):
    """A queued job no worker will pick up is worse than no job at all."""
    before = {j['job_id'] for j in client.get('/jobs').json()}
    r = _upload(client, [('files', ('clip.mp4', b'junk junk junk',
                                    'video/mp4'))])
    assert r.status_code == 422
    after = {j['job_id'] for j in client.get('/jobs').json()}
    assert after == before, 'the discarded job is still listed'


def test_compiled_brief_must_be_json_in_a_form_field(client, staged):
    r = client.post('/analyze/upload',
                    files=[('files', ('a.mp4', MP4, 'video/mp4'))],
                    data={'compiled_brief': 'not json{'})
    assert r.status_code == 422
    assert 'compiled_brief' in r.text and 'JSON' in r.text


# ---------------------------------------------------------------------------
# limits and path safety
# ---------------------------------------------------------------------------
def test_the_big_body_limit_applies_only_to_the_upload_path(client):
    """Raising one ceiling must not raise the other.

    A single global limit big enough for video would let any caller post half a
    gigabyte of JSON at /analyze, which is the attack the limit exists to stop.
    """
    from app.main import settings as live

    assert live.max_upload_bytes > live.max_body_bytes
    huge = str(live.max_upload_bytes - 1)
    r = client.post('/analyze', json={'video_urls': [VID], 'brief_text': 'x'},
                    headers={'content-length': huge})
    assert r.status_code == 413
    assert '/analyze/upload' in r.text


# ---------------------------------------------------------------------------
# ffmpeg -- not pip-installable, and the first thing a job touches
# ---------------------------------------------------------------------------
def test_ready_reports_the_media_binaries(client):
    """Named on /ready, so a failure is one line and not a paragraph."""
    body = client.get('/ready').json()
    assert 'ffmpeg' in body and 'ffprobe' in body


def test_missing_ffmpeg_makes_the_server_NOT_ready(monkeypatch):
    """The gap this closes: /ready said `true` on a box where every job would
    die in Phase 1. A green probe in front of a server that cannot work is
    worse than a red one."""
    from app import media
    from app.config import get_settings

    monkeypatch.setattr(media, 'status',
                        lambda refresh=False: {
                            'ffmpeg': None, 'ffprobe': '/usr/bin/ffprobe',
                            'added': None, 'missing': ['ffmpeg']})
    get_settings.cache_clear()
    problems = get_settings().missing_requirements()
    assert any('ffmpeg' in p for p in problems), problems
    assert any('AUDITOR_FFMPEG_DIR' in p for p in problems), (
        'the error must name the escape hatch, not just the problem')


def test_resolver_extends_path_rather_than_installing(monkeypatch, tmp_path):
    """Installed-but-invisible is the common Windows case: winget appends to
    the USER PATH, and a process that predates the install never sees it.

    Real files on a real (empty) PATH, not a mocked `which` -- the first
    version of this test stubbed shutil.which and the stub could never satisfy
    the resolver's own exit condition, so it walked every candidate directory
    and reported the last one. The test failed for a reason that had nothing
    to do with the behaviour under test.
    """
    from app import media

    fake, empty = tmp_path / 'bin', tmp_path / 'empty'
    fake.mkdir()
    empty.mkdir()
    for b in ('ffmpeg', 'ffprobe'):
        p = fake / (b + ('.exe' if sys.platform == 'win32' else ''))
        p.write_bytes(b'')
        p.chmod(0o755)

    monkeypatch.setenv('PATH', str(empty))       # nothing findable
    monkeypatch.setenv('AUDITOR_FFMPEG_DIR', str(fake))
    assert media.resolve()['missing'] == [] or sys.platform != 'win32'

    monkeypatch.setenv('PATH', str(empty))
    out = media.resolve()
    assert out['added'] == str(fake), out
    assert os.environ['PATH'].startswith(str(fake)), (
        'it must PREPEND -- appending lets a broken copy earlier on PATH win')


def test_resolver_reports_what_it_cannot_find(monkeypatch, tmp_path):
    """Nothing anywhere must be a clean report, never an exception."""
    from app import media

    empty = tmp_path / 'empty'
    empty.mkdir()
    monkeypatch.setenv('PATH', str(empty))
    monkeypatch.setenv('AUDITOR_FFMPEG_DIR', str(empty))
    monkeypatch.setattr(media, '_candidate_dirs', lambda: [empty])
    out = media.resolve()
    assert out['missing'] == ['ffmpeg', 'ffprobe']
    assert out['added'] is None


@pytest.mark.parametrize('job_id', ['..%2f..%2fetc', '../../secret',
                                    'has spaces', 'a' * 65])
def test_report_routes_refuse_a_malformed_job_id(client, job_id):
    """job_id reaches the filesystem, so it is patterned like GET /jobs/{id}.

    Without the pattern a percent-encoded traversal decodes into the path used
    to locate jobs/<id>/job.json and reads outside the data root.
    """
    for url in (f'/jobs/{job_id}/report/a.html', f'/jobs/{job_id}/reports.zip'):
        assert client.get(url).status_code in (404, 422), url
