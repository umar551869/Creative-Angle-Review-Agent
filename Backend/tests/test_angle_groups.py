"""The public answer: which video falls under which creative angle.

Through the tunnel, GET /jobs/{id} returns only the angle groups; scores,
verdicts and reports stay on the host. On the host, everything is returned.
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

from app.jobs import Job, get_store  # noqa: E402
from app.main import app  # noqa: E402
from app.security import configured_keys  # noqa: E402
from app.services.pipeline import NO_ANGLE, angle_groups  # noqa: E402

ANGLES = ['Knocked Out', 'Stopped Melatonin', 'Back to School']


def _row(url, dominant, status='ok'):
    return {'video_id': url[-2:], 'video_hash': url[-2:],
            'source': url[-2:] + '.mp4', 'url': url,
            'status': status, 'error': None if status == 'ok' else 'boom',
            'creative_angle': {'named_angles': ANGLES,
                               'dominant_angle': dominant}}


ROWS = [_row('https://t/v1', 'Knocked Out'),
        _row('https://t/v2', 'Knocked Out'),
        _row('https://t/v3', 'Back to School'),
        _row('https://t/v4', 'none of the listed angles'),
        _row('https://t/v5', None, status='module_failed')]


def test_groups_videos_under_their_dominant_angle():
    groups, unplaced = angle_groups(ROWS)
    by = {g['angle']: g['videos'] for g in groups}
    assert by['Knocked Out'] == ['https://t/v1', 'https://t/v2']
    assert by['Back to School'] == ['https://t/v3']
    # Every named angle is listed, even with nobody on it.
    assert by['Stopped Melatonin'] == []
    assert by[NO_ANGLE] == ['https://t/v4']
    assert unplaced == [{'video': 'https://t/v5', 'reason': 'boom'}]
    # The brief's own order, then the catch-all.
    assert [g['angle'] for g in groups] == ANGLES + [NO_ANGLE]


def test_every_submitted_link_is_accounted_for():
    """A link that never became a result row (download failed) must still
    appear -- in `unplaced` -- or the answer silently loses a video."""
    submitted = [r['url'] for r in ROWS] + ['https://t/v6', 'https://t/v7',
                                            'https://t/v6']
    groups, unplaced = angle_groups(ROWS, submitted=submitted,
                                    failed=['https://t/v6'])
    placed = [u for g in groups for u in g['videos']]
    assert sorted(placed + [u['video'] for u in unplaced]) == \
        sorted(dict.fromkeys(submitted))
    reasons = {u['video']: u['reason'] for u in unplaced}
    assert reasons['https://t/v6'] == 'could not download this link'
    assert 'dropped' in reasons['https://t/v7']


def test_a_failed_job_gives_its_error_as_the_reason():
    groups, unplaced = angle_groups([], submitted=['https://t/a', 'https://t/b'],
                                    job_error='no video could be downloaded')
    assert groups == []
    assert [u['reason'] for u in unplaced] == ['no video could be downloaded'] * 2


def test_short_link_maps_back_to_the_link_that_was_sent():
    from app.services.ingest import url_for_source
    short = 'https://vm.tiktok.com/ZMabcDEF/'
    full = 'https://www.tiktok.com/@x/video/7677937368036347167'
    assert url_for_source('7677937368036347167.mp4', [short],
                          {short: full}) == short
    assert url_for_source('7677937368036347167.mp4', [short]) is None


@pytest.fixture(scope='module')
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def job_id():
    job = Job('angletest0001', {'video_urls': [r['url'] for r in ROWS]})
    job.status, job.phase, job.results = 'succeeded', 'done', ROWS
    store = get_store()
    store._jobs[job.id] = job
    yield job.id
    store._jobs.pop(job.id, None)


def _h(extra=None):
    keys = configured_keys()
    return {**({'x-api-key': sorted(keys)[0]} if keys else {}), **(extra or {})}


def test_host_request_gets_the_full_result(client, job_id):
    body = client.get(f'/jobs/{job_id}', headers=_h()).json()
    assert body['view'] == 'full'
    assert len(body['results']) == len(ROWS)
    assert body['angle_groups'][0]['videos'] == ['https://t/v1', 'https://t/v2']


@pytest.mark.parametrize('proxy', [{'x-forwarded-for': '1.2.3.4'},
                                   {'cf-connecting-ip': '1.2.3.4'}])
def test_tunnel_request_gets_only_the_angle_groups(client, job_id, proxy):
    body = client.get(f'/jobs/{job_id}', headers=_h(proxy)).json()
    assert body['view'] == 'angles'
    assert body['results'] == [] and body['brief'] is None
    # The shape the frontend reads: angle -> links, brief order preserved.
    assert body['angles'] == {
        'Knocked Out': ['https://t/v1', 'https://t/v2'],
        'Stopped Melatonin': [],
        'Back to School': ['https://t/v3'],
        NO_ANGLE: ['https://t/v4']}
    assert list(body['angles']) == ANGLES + [NO_ANGLE]
    assert body['angle_groups'][0] == {'angle': 'Knocked Out',
                                       'videos': ['https://t/v1',
                                                  'https://t/v2']}
    assert body['unplaced'][0]['video'] == 'https://t/v5'


def test_reports_are_not_served_through_the_tunnel(client, job_id):
    h = _h({'x-forwarded-for': '1.2.3.4'})
    assert client.get(f'/jobs/{job_id}/report/abc.html',
                      headers=h).status_code == 403
    assert client.get(f'/jobs/{job_id}/reports.zip',
                      headers=h).status_code == 403

# ---------------------------------------------------------------------------
# Several briefs: a brand with two focus products
# ---------------------------------------------------------------------------
LUNG = ['Toxins for Years', 'Pharmacist Said']
COLON = ['Japanese Gut Secret', 'Bloated to Flat']


def _audit(vid, label, named, dominant, score, pct=100.0):
    return {'video_id': vid, 'video_hash': vid, 'source': vid + '.mp4',
            'url': 'https://t/' + vid, 'status': 'ok', 'brief_label': label,
            'score': {'headline': score},
            'creative_angle': {
                'named_angles': named, 'dominant_angle': dominant,
                'concept_fit': [{'angle': dominant, 'percent': pct}]}}


def test_each_video_keeps_the_brief_it_followed():
    from app.services.pipeline import pick_followed_brief, placements
    none = 'none of the listed angles'
    lung = [_audit('a', 'Lung Health', LUNG, 'Pharmacist Said', 55),
            _audit('b', 'Lung Health', LUNG, none, 90),
            _audit('c', 'Lung Health', LUNG, none, 40)]
    colon = [_audit('a', 'Colon Cleanse', COLON, none, 95),
             _audit('b', 'Colon Cleanse', COLON, 'Bloated to Flat', 30),
             _audit('c', 'Colon Cleanse', COLON, none, 80)]
    rows = pick_followed_brief([lung, colon])
    got = {p['video']: (p['angle'], p['brief']) for p in placements(rows)}
    # Matching a named angle beats a higher score on the brief it missed.
    assert got['https://t/a'] == ('Pharmacist Said', 'Lung Health')
    assert got['https://t/b'] == ('Bloated to Flat', 'Colon Cleanse')
    # Fits neither: Matched None, and it is reported once, not twice.
    assert got['https://t/c'][0] == NO_ANGLE == 'Matched None'
    assert len(rows) == 3

    # Angles of BOTH briefs are listed, even the ones nobody used.
    groups, _ = angle_groups(rows, named_angles=LUNG + COLON)
    assert [g['angle'] for g in groups] == LUNG + COLON + [NO_ANGLE]
    by = {g['angle']: g['videos'] for g in groups}
    assert by['Toxins for Years'] == [] and by['Japanese Gut Secret'] == []


def test_a_tie_goes_to_the_first_brief():
    from app.services.pipeline import pick_followed_brief
    one = [_audit('a', 'First', LUNG, 'Pharmacist Said', 70)]
    two = [_audit('a', 'Second', COLON, 'Bloated to Flat', 70)]
    assert pick_followed_brief([one, two])[0]['brief_label'] == 'First'


def test_a_brief_link_can_name_one_tab():
    from app.services.ingest import doc_tab
    base = 'https://docs.google.com/document/d/1lEKrZzZ51fEHmUgwg5ksBw6eYsvYNmI9/edit'
    assert doc_tab(base + '?tab=t.iyd0i3cnge8e') == 't.iyd0i3cnge8e'
    assert doc_tab(base + '?usp=sharing&tab=t.0') == 't.0'
    assert doc_tab(base + '?usp=sharing') == ''


def test_briefs_cannot_be_mixed_with_a_single_brief(client):
    r = client.post('/analyze', headers=_h(), json={
        'video_urls': ['https://www.tiktok.com/@a/video/7674625522189618445'],
        'brief_text': 'Show the product.',
        'briefs': [{'url': 'https://docs.google.com/document/d/1lEKrZzZ51fEHmUgwg5ksBw6eYsvYNmI9/edit',
                    'label': 'Lung Health'}]})
    assert r.status_code == 422
    r = client.post('/analyze', headers=_h(), json={
        'video_urls': ['https://www.tiktok.com/@a/video/7674625522189618445'],
        'briefs': [{'url': 'https://example.com/brief', 'label': 'x'}]})
    assert r.status_code == 422


def test_downloaded_videos_are_deleted_when_the_job_is_over(tmp_path, monkeypatch):
    """The inbox goes; the job record and everything else stay."""
    from app import jobs as jobs_mod

    class S:
        jobs = tmp_path
    monkeypatch.setattr(jobs_mod, 'get_settings', lambda: S)
    inbox = tmp_path / 'job1' / 'inbox'
    inbox.mkdir(parents=True)
    (inbox / '7677937368036347167.mp4').write_bytes(b'x' * 2048)
    (tmp_path / 'job1' / 'job.json').write_text('{}')
    jobs_mod._drop_videos('job1')
    assert not inbox.exists()
    assert (tmp_path / 'job1' / 'job.json').is_file()
    jobs_mod._drop_videos('job1')            # nothing left: must not raise

# ---------------------------------------------------------------------------
# Angle names given by the caller
# ---------------------------------------------------------------------------
BRIEF = """UGC Brief - Format Library, Hooks and Talking Points
Purpose
Some purpose text.
Creative Concepts
These formats have shown great results.
*   	   1. 3 Signs Your Lungs May Need Extra Support
   * The creator opens with a strong hook.
   * Format Example: Here
	   2. “Tired Day Fix!”
   * She shows the product on a rough morning.
Hooks
"Listen! If your lungs feel heavy every morning."
Key talking points + Product features for the Bottle
* Natural herbs
"""


def test_given_angles_are_used_exactly_and_keep_their_detail():
    """The notebook's reader drops a concept typed as a bullet and one ending
    in '!'. Given names are returned as given, each with what the brief says
    under it -- that detail is what the angle judge reads."""
    from auditor import runtime
    from app.services import ingest
    ns = runtime.load()
    names = ['3 Signs Your Lungs May Need Extra Support', 'Tired Day Fix!']
    c = ingest.use_given_angles({'brief_text': BRIEF, 'cache_key': 'abc'}, names)
    blocks = ns['brief_angle_blocks'](c)
    assert [b['name'] for b in blocks] == names
    assert blocks[0]['detail'][0].startswith('The creator opens')
    assert blocks[1]['detail'] == ['She shows the product on a rough morning.']
    # the pipeline's own entry point sees them too
    assert ns['named_brief_angles'](c) == names


def test_a_different_angle_list_is_a_different_cache_key():
    from app.services import ingest
    a = ingest.use_given_angles({'brief_text': BRIEF, 'cache_key': 'abc'}, ['One'])
    b = ingest.use_given_angles({'brief_text': BRIEF, 'cache_key': 'abc'}, ['Two'])
    assert a['cache_key'] != b['cache_key'] and a['cache_key'].startswith('abc+angles:')
    # applying it twice does not stack suffixes
    again = ingest.use_given_angles(a, ['One'])
    assert again['cache_key'].count('+angles:') == 1


def test_no_given_angles_leaves_the_notebook_reader_alone():
    from auditor import runtime
    from app.services import ingest
    ns = runtime.load()
    c = ingest.use_given_angles({'brief_text': BRIEF, 'cache_key': 'abc'}, None)
    assert 'given_angles' not in c and c['cache_key'] == 'abc'
    # the document path still answers, with whatever it finds
    assert isinstance(ns['brief_angle_blocks']({'brief_text': BRIEF}), list)

# ---------------------------------------------------------------------------
# Reading the concepts out of the document itself
# The four shapes below are real briefs the notebook's reader got wrong.
# ---------------------------------------------------------------------------
def test_a_concept_typed_as_a_bullet_is_still_a_concept():
    from app.services.ingest import document_angles
    assert document_angles(BRIEF) == [
        '3 Signs Your Lungs May Need Extra Support', 'Tired Day Fix!']


def test_a_later_heading_is_not_a_concept():
    """`Key talking points + Product features for <product>` was reported as a
    fourth angle of a three-angle brief."""
    from app.services.ingest import document_angles
    text = """Bentgo Hydration - Creator Brief
Purpose
Why we are doing this.
Creative concepts
1. Steady & Warm
Format example:
2. Partner Approved
3. POV: Hydration for Busy Days
Hook Concepts
1. "Listen, this bottle changed my mornings"
Key talking points + Product features for Bentgo Flip 2-in-1 Bottle
1. Keeps drinks warm
Call to action (CTA) Ideas
"""
    assert document_angles(text) == [
        'Steady & Warm', 'Partner Approved', 'POV: Hydration for Busy Days']


def test_concepts_with_no_creative_concepts_heading():
    """One brief goes straight from Purpose to its numbered concepts; the
    notebook's reader found no angles in it at all."""
    from app.services.ingest import document_angles
    text = """UGC Brief - Format Library, Hooks and Talking Points
Purpose
What this is for.
1. “Visual hook”(Top performing angle)
Format example:
https://www.tiktok.com/@cheershealth/video/7649863482753518878
2. “What I wish I could tell my younger self”
Hook Concepts
"""
    assert document_angles(text) == [
        'Visual hook (Top performing angle)',
        'What I wish I could tell my younger self']


def test_a_brief_with_no_numbered_concepts_reads_as_none():
    from app.services.ingest import document_angles, settle_angles
    text = 'Show the product in the first five seconds. Mention the price.'
    assert document_angles(text) == []
    c = {'brief_text': text, 'cache_key': 'k'}
    assert settle_angles(c, text) == 'notebook' and 'given_angles' not in c


def test_settle_prefers_given_then_document():
    from app.services.ingest import settle_angles
    c = {'cache_key': 'k'}
    assert settle_angles(c, BRIEF, ['Mine']) == 'given'
    assert c['given_angles'] == ['Mine']
    c = {'cache_key': 'k'}
    assert settle_angles(c, BRIEF) == 'document'
    assert c['given_angles'] == ['3 Signs Your Lungs May Need Extra Support',
                                 'Tired Day Fix!']


def test_angles_can_be_previewed_without_a_model(client):
    r = client.post('/briefs/angles', headers=_h(), json={'brief_text': BRIEF})
    assert r.status_code == 200
    assert r.json()['angles'] == ['3 Signs Your Lungs May Need Extra Support',
                                  'Tired Day Fix!']
