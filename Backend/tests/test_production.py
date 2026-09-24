"""Backpressure, shutdown, retention -- the operational contracts.

Each of these is a promise the deployment docs make. A promise nothing checks
is a promise that quietly stops being true.
"""
import os
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ.setdefault('AUDITOR_DATA_ROOT', str(HERE / 'data' / 'test'))
os.environ['AUDITOR_PROBE_ON_STARTUP'] = 'false'


# ---------------------------------------------------------------------------
# backpressure
# ---------------------------------------------------------------------------
def test_queue_depth_counts_only_unfinished_work():
    from app.jobs import JobStore

    store = JobStore()
    a = store.create({'video_urls': ['u'], 'label': 'a'})
    b = store.create({'video_urls': ['u'], 'label': 'b'})
    assert store.queue_depth() == 2
    a.status = 'succeeded'
    assert store.queue_depth() == 1
    b.status = 'failed'
    assert store.queue_depth() == 0


def test_analyze_returns_429_when_the_queue_is_full(monkeypatch):
    """An unbounded queue turns 'too much work' into 'nothing finishes'.

    max_queued_jobs=0 makes the check fire on the first request without
    patching queue_depth -- patching it on the CLASS also made the shutdown
    drain believe work was outstanding and wait the full grace period.
    """
    from fastapi.testclient import TestClient

    import app.main

    monkeypatch.setattr(app.main.settings, 'max_queued_jobs', 0)
    monkeypatch.setattr(app.main.settings, 'gemini_api_key', 'x' * 30)

    with TestClient(app.main.app, raise_server_exceptions=False) as c:
        r = c.post('/analyze', json={
            'video_urls': ['https://www.tiktok.com/@a/video/12345678'],
            'brief_text': 'Show the product.'})
    assert r.status_code == 429, r.text
    assert 'queued' in r.text


def test_state_resets_on_restart_so_a_reused_app_still_accepts_work():
    """_STATE is module-level and shutdown sets accepting=False. Without a
    reset, starting the app twice in one process leaves it permanently
    answering 503 -- which reads as a dependency failure, not a lifecycle bug.
    """
    from fastapi.testclient import TestClient

    import app.main

    with TestClient(app.main.app, raise_server_exceptions=False):
        pass                                    # start then shut down
    assert app.main._STATE['accepting'] is False
    with TestClient(app.main.app, raise_server_exceptions=False) as c:
        assert app.main._STATE['accepting'] is True
        assert c.get('/ready').json()['accepting_work'] is True


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------
def test_shutdown_marks_unfinished_jobs_failed_not_running():
    """A record that still says 'running' after the process died is a lie,
    and a caller polling it waits forever."""
    from app.jobs import JobStore

    store = JobStore()
    job = store.create({'video_urls': ['u'], 'label': 'stuck'})
    job.status = 'running'
    store.shutdown(grace_s=0)
    assert job.status == 'failed'
    assert 'shut down' in (job.error or '')
    assert job.finished_at is not None


def test_shutdown_returns_promptly_when_nothing_is_running():
    from app.jobs import JobStore

    store = JobStore()
    t0 = time.time()
    store.shutdown(grace_s=10)
    assert time.time() - t0 < 2, 'waited for a drain with nothing to drain'


# ---------------------------------------------------------------------------
# artifact retention -- the cache, which is NOT the same as job files
# ---------------------------------------------------------------------------
def test_artifact_sweep_removes_whole_sets_only_when_stale():
    from app.config import get_settings
    from app.jobs import _sweep_artifacts

    s = get_settings()
    old = s.artifacts / 'staleset'
    old.mkdir(parents=True, exist_ok=True)
    for name in ('visual__a.json', 'transcript__b.json'):
        (old / name).write_text('{}', encoding='utf-8')
    stamp = time.time() - (s.keep_artifacts_days + 5) * 86400
    for f in old.iterdir():
        os.utime(f, (stamp, stamp))

    fresh = s.artifacts / 'freshset'
    fresh.mkdir(parents=True, exist_ok=True)
    (fresh / 'visual__c.json').write_text('{}', encoding='utf-8')

    _sweep_artifacts(s)
    assert not old.exists(), 'a stale artifact set was kept'
    assert (fresh / 'visual__c.json').is_file(), 'a fresh set was destroyed'


def test_artifact_sweep_is_all_or_nothing_per_video():
    """Removing one stage while keeping another leaves a video that LOOKS
    processed and is not -- worse than removing the lot."""
    src = (HERE / 'app' / 'jobs.py').read_text(encoding='utf-8')
    assert 'shutil.rmtree(d' in src, (
        'the sweep must remove the directory, not individual artifacts')


def test_artifact_retention_can_be_disabled():
    from app.config import get_settings
    from app.jobs import _sweep_artifacts

    s = get_settings()
    keep = s.artifacts / 'keepforever'
    keep.mkdir(parents=True, exist_ok=True)
    (keep / 'visual__z.json').write_text('{}', encoding='utf-8')
    stamp = time.time() - 9999 * 86400
    os.utime(keep / 'visual__z.json', (stamp, stamp))

    original = s.keep_artifacts_days
    try:
        s.keep_artifacts_days = 0
        _sweep_artifacts(s)
        assert keep.exists(), '0 must mean never sweep'
    finally:
        s.keep_artifacts_days = original


# ---------------------------------------------------------------------------
# configuration coherence
# ---------------------------------------------------------------------------
def test_config_and_ready_report_the_same_auth_state(monkeypatch):
    """Two sources that can disagree is how an operator ends up believing
    auth is on when it is not."""
    from app.config import get_settings
    from app.security import auth_mode

    monkeypatch.delenv('AUDITOR_API_KEYS', raising=False)
    get_settings.cache_clear()
    assert get_settings().redacted()['auth'] == auth_mode()

    monkeypatch.setenv('AUDITOR_API_KEYS', 'k1,k2')
    assert get_settings().redacted()['auth'] == auth_mode()
    assert '2 key' in auth_mode()
    get_settings.cache_clear()


def test_redacted_settings_never_contain_a_secret_value(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv('GEMINI_API_KEY', 'AIzaSyREALKEYVALUE1234567890abcdefgh')
    monkeypatch.setenv('HF_TOKEN', 'hf_' + 'r' * 34)
    get_settings.cache_clear()
    blob = repr(get_settings().redacted())
    assert 'AIzaSyREALKEY' not in blob
    assert 'hf_rrrr' not in blob
    get_settings.cache_clear()
