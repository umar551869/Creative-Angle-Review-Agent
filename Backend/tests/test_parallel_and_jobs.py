"""Parallelism, job lifecycle, retention -- the parts that fail silently.

Every test here is for a failure mode that produces plausible-looking output
rather than an exception, which is why they are worth writing down.
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ.setdefault('AUDITOR_DATA_ROOT', str(HERE / 'data' / 'test'))
os.environ['AUDITOR_PROBE_ON_STARTUP'] = 'false'

from app.parallel import run_parallel  # noqa: E402
from auditor import runtime  # noqa: E402


# ---------------------------------------------------------------------------
# run_parallel
# ---------------------------------------------------------------------------
def test_results_come_back_in_input_order():
    """Completion order is not input order, and every caller builds a table."""
    def slow(x):
        time.sleep(0.05 if x % 2 == 0 else 0.0)   # evens finish last
        return x * 10

    assert run_parallel(list(range(8)), slow, workers=4) == [
        0, 10, 20, 30, 40, 50, 60, 70]


def test_workers_one_runs_inline_no_threads():
    """AUDITOR_*_WORKERS=1 must be sequential, not 'parallel with 1 worker'."""
    seen = []

    def where(x):
        seen.append(threading.current_thread().name)
        return x

    run_parallel([1, 2, 3], where, workers=1)
    assert set(seen) == {threading.current_thread().name}


def test_concurrency_is_actually_bounded():
    live, peak, lock = 0, 0, threading.Lock()

    def track(x):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.05)
        with lock:
            live -= 1
        return x

    run_parallel(list(range(12)), track, workers=3)
    assert peak <= 3, f'peak concurrency {peak} exceeded the cap'
    assert peak > 1, 'nothing actually ran in parallel'


def test_one_failure_does_not_cost_the_others():
    def maybe(x):
        if x == 2:
            raise ValueError('boom')
        return x

    out = run_parallel([1, 2, 3], maybe, workers=2,
                       on_error=lambda item, exc: f'failed:{item}')
    assert out == [1, 'failed:2', 3]


def test_without_on_error_the_failure_is_raised_and_names_the_item():
    """A batch failure must say WHICH item, not just that one failed."""
    def maybe(x):
        if x == 'bad':
            raise ValueError('boom')
        return x

    with pytest.raises(RuntimeError) as e:
        run_parallel(['ok', 'bad'], maybe, workers=2, label='things')
    msg = str(e.value)
    assert 'things' in msg and 'bad' in msg and 'boom' in msg, msg
    assert '1 of 2 failed' in msg, msg


# ---------------------------------------------------------------------------
# THE TRAP: ContextVar propagation
# ---------------------------------------------------------------------------
def test_workers_inherit_the_job_context():
    """ThreadPoolExecutor does NOT copy context into its workers.

    Without copy_context(), a worker sees DIRS unset, falls back to the SHARED
    inbox, and two concurrent jobs read each other's videos. Nothing raises:
    the paths exist, the files are real, and the wrong video gets audited.
    This is the single most important test in the Backend.
    """
    with runtime.use_job_dirs('ctxjob'):
        expected = runtime.DIRS['inbox']
        seen = run_parallel(list(range(6)),
                            lambda _: str(runtime.DIRS['inbox']),
                            workers=3, label='ctx')
    assert set(seen) == {str(expected)}, (
        'a worker did not see the job context -- copy_context() is missing')
    assert 'ctxjob' in str(expected)


def test_job_dirs_are_per_job_and_share_the_cache():
    with runtime.use_job_dirs('jobA'):
        a_inbox, a_art = runtime.DIRS['inbox'], runtime.DIRS['artifacts']
    with runtime.use_job_dirs('jobB'):
        b_inbox, b_art = runtime.DIRS['inbox'], runtime.DIRS['artifacts']
    assert a_inbox != b_inbox, 'two jobs would read each other\'s videos'
    assert a_art == b_art, (
        'artifacts must be SHARED -- a private cache re-pays every vision '
        'pass, which is the entire performance story')


def test_dirs_falls_back_outside_a_job():
    assert runtime.DIRS['inbox'].is_dir()


# ---------------------------------------------------------------------------
# Job record: restore, retention
# ---------------------------------------------------------------------------
def test_restoring_a_finished_job_does_not_crash_on_elapsed_s():
    """elapsed_s is a read-only property. hasattr() says True; assignment
    raises. The previous restore loop setattr'd every key it found, so any
    finished job returned 500 after a restart."""
    from app.config import get_settings
    from app.jobs import _restore

    s = get_settings()
    d = s.jobs / 'restoreme'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'job.json').write_text(json.dumps({
        'job_id': 'restoreme', 'status': 'succeeded', 'phase': 'done',
        'label': 'x', 'created_at': '2026-09-23T10:00:00+00:00',
        'elapsed_s': 412.8, 'requested_videos': 2, 'completed_videos': 2,
        'results': [], 'timings': [], 'warnings': [], 'error': None,
    }), encoding='utf-8')

    job = _restore('restoreme')
    assert job is not None
    assert job.status == 'succeeded'
    assert job.elapsed_s == pytest.approx(412.8)


def test_a_job_running_at_restart_is_reported_failed_not_running():
    """A record saying 'running' after a restart is a lie -- nothing is."""
    from app.config import get_settings
    from app.jobs import _restore

    d = get_settings().jobs / 'wasrunning'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'job.json').write_text(json.dumps({
        'job_id': 'wasrunning', 'status': 'running', 'phase': 'phase3',
        'created_at': '2026-09-23T10:00:00+00:00', 'results': [],
        'timings': [], 'warnings': [],
    }), encoding='utf-8')

    job = _restore('wasrunning')
    assert job.status == 'failed'
    assert 'restart' in (job.error or '')


def test_listing_includes_jobs_that_survived_a_restart():
    from app.jobs import get_store

    ids = {j.id for j in get_store().list(limit=100)}
    assert 'restoreme' in ids, (
        'GET /jobs returned [] while job.json files sat on disk')


def test_cleanup_removes_workspaces_but_keeps_the_record_and_the_cache():
    from app.config import get_settings
    from app.jobs import _sweep_old_jobs
    import app.jobs as jobs_mod

    s = get_settings()
    d = s.jobs / 'oldjob'
    (d / 'inbox').mkdir(parents=True, exist_ok=True)
    (d / 'reports').mkdir(parents=True, exist_ok=True)
    (d / 'inbox' / 'v.mp4').write_bytes(b'x' * 1000)
    (d / 'reports' / 'r.html').write_text('<h1>r</h1>', encoding='utf-8')
    rec = d / 'job.json'
    rec.write_text('{"job_id": "oldjob", "status": "succeeded"}',
                   encoding='utf-8')
    old = time.time() - (s.keep_job_files_hours + 5) * 3600
    os.utime(rec, (old, old))

    art = s.artifacts / 'keepme'
    art.mkdir(parents=True, exist_ok=True)
    (art / 'visual__abc.json').write_text('{}', encoding='utf-8')

    jobs_mod._LAST_SWEEP = 0.0
    _sweep_old_jobs(s)

    assert not (d / 'inbox').exists(), 'stale video workspace was not removed'
    assert not (d / 'reports').exists()
    assert rec.is_file(), 'the job RECORD must outlive its bytes'
    assert (art / 'visual__abc.json').is_file(), (
        'artifacts/ is shared and content-addressed -- cleanup must never '
        'touch it')


def test_a_recent_job_is_not_swept():
    from app.config import get_settings
    from app.jobs import _sweep_old_jobs
    import app.jobs as jobs_mod

    s = get_settings()
    d = s.jobs / 'freshjob'
    (d / 'inbox').mkdir(parents=True, exist_ok=True)
    (d / 'inbox' / 'v.mp4').write_bytes(b'x')
    (d / 'job.json').write_text('{}', encoding='utf-8')

    jobs_mod._LAST_SWEEP = 0.0
    _sweep_old_jobs(s)
    assert (d / 'inbox' / 'v.mp4').is_file()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def test_network_stages_default_to_sequential():
    """Vision and audit look like the biggest parallelism win and are not.

    A live free-tier key returned 503 on seven of eight models and 429 on the
    eighth. Issuing those N-at-once turns a slow job into a failed one.
    """
    from app.config import Settings

    s = Settings()
    assert s.vision_workers == 1
    assert s.audit_workers == 1
    assert s.download_workers > 1, 'downloads are pure network wait'
    assert s.decode_workers >= 1
