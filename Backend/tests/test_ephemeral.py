"""Ephemeral mode and the client-held contract.

The whole point is running with no persistent volume without giving up the
one guarantee that storage was buying: that a brief always means the same
requirement set. So the tests are about that guarantee, not about disk.
"""
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ.setdefault('AUDITOR_DATA_ROOT', str(HERE / 'data' / 'test'))
os.environ['AUDITOR_PROBE_ON_STARTUP'] = 'false'

from auditor import runtime  # noqa: E402


# ---------------------------------------------------------------------------
# where things live
# ---------------------------------------------------------------------------
def test_ephemeral_makes_artifacts_per_job():
    a = runtime.job_dirs('e1', ephemeral=True)
    b = runtime.job_dirs('e2', ephemeral=True)
    assert a['artifacts'] != b['artifacts'], (
        'ephemeral artifacts must be per-job so the whole workspace can go')
    assert 'e1' in str(a['artifacts'])


def test_briefs_stay_shared_even_when_ephemeral():
    """The asymmetry IS the design.

    Artifacts are 5-20 MB per video and pure optimisation. The frozen compile
    is ~30 KB and is the only stored thing whose loss changes what a score
    MEANS, because the compiler is non-deterministic.
    """
    a = runtime.job_dirs('e1', ephemeral=True)
    b = runtime.job_dirs('e2', ephemeral=True)
    assert a['briefs'] == b['briefs']


def test_default_still_shares_the_cache():
    """Ephemeral is opt-in; nothing already deployed changes."""
    a = runtime.job_dirs('d1')
    b = runtime.job_dirs('d2')
    assert a['artifacts'] == b['artifacts']
    assert a['inbox'] != b['inbox']


def test_use_job_dirs_honours_ephemeral():
    with runtime.use_job_dirs('ctx-e', ephemeral=True):
        art = runtime.DIRS['artifacts']
    assert 'ctx-e' in str(art)


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------
def test_drop_bulk_removes_inputs_but_keeps_the_report():
    from app.config import get_settings
    from app.jobs import _drop_bulk

    s = get_settings()
    j = s.jobs / 'bulkjob'
    for sub in ('inbox', 'artifacts', 'reports'):
        (j / sub).mkdir(parents=True, exist_ok=True)
    (j / 'inbox' / 'v.mp4').write_bytes(b'x' * 5000)
    (j / 'artifacts' / 'frames.json').write_text('{}', encoding='utf-8')
    (j / 'reports' / 'r.html').write_text('<h1>r</h1>', encoding='utf-8')
    (j / 'job.json').write_text('{}', encoding='utf-8')

    _drop_bulk('bulkjob')

    assert not (j / 'inbox').exists(), 'videos should be gone'
    assert not (j / 'artifacts').exists(), 'frames/audio should be gone'
    assert (j / 'reports' / 'r.html').is_file(), (
        'deleting reports breaks GET /jobs/{id}/report before the caller has '
        'fetched them')
    assert (j / 'job.json').is_file(), 'the job record must survive'


def test_drop_bulk_is_safe_on_a_job_that_wrote_nothing():
    from app.jobs import _drop_bulk
    _drop_bulk('never-existed')          # must not raise


# ---------------------------------------------------------------------------
# the client-held contract
# ---------------------------------------------------------------------------
@pytest.fixture(scope='module')
def ns():
    return runtime.load()


def _contract(ns, reqs=None):
    reqs = reqs if reqs is not None else [
        {'id': 'r1', 'requirement': 'Show the product in the first 5 seconds',
         'type': 'visual', 'evidence_mode': 'visual_only',
         'polarity': 'required', 'priority': 'high'},
        {'id': 'r2', 'requirement': 'End with a clear CTA', 'type': 'speech',
         'evidence_mode': 'speech_or_text', 'polarity': 'required',
         'priority': 'medium'},
    ]
    c = {'status': 'OK', 'brief_hash': 'a' * 64, 'requirements': reqs,
         'stats': {'requirements': len(reqs)}, 'approved': True,
         'approved_by': 'api:freeze-on-first-compile'}
    c['approved_digest'] = ns['requirements_digest'](reqs)
    return c


def test_a_returned_contract_is_accepted(ns):
    from app.services.ingest import use_precompiled

    out = use_precompiled(_contract(ns))
    assert out['status'] == 'OK'
    assert len(out['requirements']) == 2


def test_an_edited_contract_is_REFUSED(ns):
    """Not trusted -- verified. Editing the requirements invalidates the
    approval digest, which is exactly the check that makes accepting a
    client-supplied contract safe."""
    from app.services.ingest import IngestError, use_precompiled

    c = _contract(ns)
    c['requirements'][0]['requirement'] = 'Show the product in 30 seconds'
    with pytest.raises(IngestError) as e:
        use_precompiled(c)
    assert 'not usable' in str(e.value)
    assert 'changed since approval' in str(e.value)


def test_adding_a_requirement_is_refused(ns):
    from app.services.ingest import IngestError, use_precompiled

    c = _contract(ns)
    c['requirements'].append({'id': 'r3', 'requirement': 'Say it is free'})
    with pytest.raises(IngestError):
        use_precompiled(c)


def test_a_contract_for_a_different_brief_is_refused(ns):
    """Both a document and a contract given, and they disagree. Without this
    the report claims to have audited brief X against a contract compiled
    from brief Y, and nothing contradicts it."""
    from app.services.ingest import IngestError, use_precompiled

    with pytest.raises(IngestError) as e:
        use_precompiled(_contract(ns), expect_text='a completely other brief')
    assert 'different documents' in str(e.value)


def test_a_matching_brief_text_passes(ns):
    from app.services.ingest import use_precompiled

    text = 'Show the product. End with a CTA.'
    c = _contract(ns)
    c['brief_hash'] = ns['sha256_text'](text)
    assert use_precompiled(c, expect_text=text)['status'] == 'OK'


@pytest.mark.parametrize('bad,frag', [
    ('not a dict', 'JSON object'),
    ({'status': 'NO_REQUIREMENTS', 'requirements': []}, 'not "OK"'),
    ({'status': 'OK', 'requirements': []}, 'no requirements'),
])
def test_malformed_contracts_are_refused_with_a_reason(bad, frag):
    from app.services.ingest import IngestError, use_precompiled

    with pytest.raises(IngestError) as e:
        use_precompiled(bad)
    assert frag in str(e.value)


def test_an_unapproved_contract_is_refused(ns):
    from app.services.ingest import IngestError, use_precompiled

    c = _contract(ns)
    c['approved'] = False
    with pytest.raises(IngestError) as e:
        use_precompiled(c)
    assert 'never approved' in str(e.value)


# ---------------------------------------------------------------------------
# request shape
# ---------------------------------------------------------------------------
def test_analyze_accepts_compiled_brief_with_no_document():
    from app.schemas import AnalyzeRequest

    r = AnalyzeRequest(video_urls=['https://www.tiktok.com/@a/video/123456'],
                       compiled_brief={'status': 'OK'})
    assert r.compiled_brief == {'status': 'OK'}
    assert r.brief_url is None


def test_compile_brief_now_records_an_approval_digest():
    """Without it approval_state falls back to 'legacy', which passes but
    proves nothing about WHICH requirement set was approved."""
    src = (HERE / 'app' / 'services' / 'ingest.py').read_text(encoding='utf-8')
    assert "compiled['approved_digest']" in src
