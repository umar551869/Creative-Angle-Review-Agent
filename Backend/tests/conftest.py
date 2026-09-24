"""Make the test environment deterministic, whatever is in Backend/.env.

WHY THIS EXISTS. app.config reads .env into the process at import. A developer
who puts a real AUDITOR_API_KEYS there for a live run then finds twelve tests
failing with `assert 401 == 404` -- the suite was not testing 404 handling, it
was testing whether the machine happened to have auth switched on.

A test suite whose result depends on an untracked local file is not a test
suite. These variables are pinned BEFORE app.config is imported; python-dotenv
is called with override=False, so a name already present in os.environ -- even
as an empty string -- wins over the file.

Tests that need a value (test_security, test_ephemeral) set it themselves via
monkeypatch and clear the settings cache, which is the explicit path.
"""
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

# Pinned to '' rather than deleted: an empty value still counts as "present"
# for python-dotenv's override=False, which is what blocks the file.
_PINNED = {
    'AUDITOR_API_KEYS': '',        # the suite tests the UNAUTHENTICATED shape
    'GEMINI_API_KEY': '',          # ...and the missing-key shape
    'OPENAI_API_KEY': '',
    'HF_TOKEN': '',
    'HUGGING_FACE_HUB_TOKEN': '',
    'HF_WRITE_TOKEN': '',
    'AUDITOR_CORS_ORIGINS': '',
    'AUDITOR_EPHEMERAL': 'false',
    'AUDITOR_PROBE_ON_STARTUP': 'false',   # no live API calls from a test
    'AUDITOR_DATA_ROOT': str(HERE / 'data' / 'test'),
}
for _k, _v in _PINNED.items():
    os.environ[_k] = _v


@pytest.fixture(scope='session', autouse=True)
def _clean_job_workspace():
    """Start every session with an empty jobs/ under the TEST data root.

    Several tests create real job directories, and `GET /jobs` returns the
    newest 100 by created_at. Left to accumulate across runs, new jobs pushed
    an older fixture job out of that window and
    test_listing_includes_jobs_that_survived_a_restart began failing -- in a
    different file, for a reason invisible from inside it, and only after the
    suite had been run enough times.

    A suite whose result depends on how often it has been run before is the
    same problem this file already exists to solve for .env, so it is fixed in
    the same place. Only jobs/ under data/test is touched; the real data root
    is never in scope here.
    """
    import shutil

    jobs = Path(_PINNED['AUDITOR_DATA_ROOT']) / 'jobs'
    if jobs.is_dir():
        shutil.rmtree(jobs, ignore_errors=True)
    yield


@pytest.fixture(autouse=True)
def _isolated_settings():
    """Reset the cached Settings between tests that mutate the environment."""
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
