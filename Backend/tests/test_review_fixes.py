"""Defects found by review of the multi-brief / angle-name work, each pinned.

Every test here is a failure that was real: a video filed under the wrong
brief, a category invented from the wrong line of a brief, a good link
reported as undownloadable, a wrong tab audited without a word.
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
from app.services import ingest, pipeline  # noqa: E402
from app.services.pipeline import NO_ANGLE  # noqa: E402

LUNG = ['Toxins for Years', 'Pharmacist Said']
COLON = ['Japanese Gut Secret', 'Bloated to Flat']
NONE = 'none of the listed angles'
DOC = 'https://docs.google.com/document/d/1lEKrZzZ51fEHmUgwg5ksBw6eYsvYNmI9/edit'


def _audit(vid, label, named, dominant, score=50, status='ok', **extra):
    fit = [{'angle': dominant, 'percent': 100.0}] if dominant else []
    return {'video_id': vid, 'video_hash': vid, 'source': vid + '.mp4',
            'url': 'https://www.tiktok.com/@c/video/' + vid, 'status': status,
            'error': None if status == 'ok' else 'RateLimited: 429',
            'brief_label': label, 'score': {'headline': score},
            'creative_angle': {'named_angles': named,
                               'dominant_angle': dominant,
                               'concept_fit': fit}, **extra}


@pytest.fixture(scope='module')
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _h(extra=None):
    keys = configured_keys()
    return {**({'x-api-key': sorted(keys)[0]} if keys else {}), **(extra or {})}


# ---------------------------------------------------------------------------
# A video is only placed if it was judged against EVERY brief
# ---------------------------------------------------------------------------
def test_a_failed_audit_on_one_brief_means_not_placed():
    """Brief 2's angle call failed once. Before: the video was placed from
    brief 1 alone, under Matched None, in a job that said `succeeded`."""
    lung = [_audit('7000000000000000001', 'Lung', LUNG, NONE, 80)]
    colon = [_audit('7000000000000000001', 'Colon', COLON, 'Bloated to Flat',
                    status='module_failed')]
    rows = pipeline.pick_followed_brief([lung, colon])
    assert rows[0]['status'] == 'BRIEF_AUDIT_INCOMPLETE'
    assert 'Colon' in rows[0]['error'] and 'RateLimited' in rows[0]['error']
    assert pipeline.placements(rows) == []
    groups, unplaced = pipeline.angle_groups(rows, named_angles=LUNG + COLON)
    assert all(g['videos'] == [] for g in groups)
    assert unplaced[0]['video'].endswith('7000000000000000001')
    assert 'not judged against every brief' in unplaced[0]['reason']


def test_a_brief_that_never_ran_means_not_placed():
    """The deadline arrived between briefs: every video is SKIPPED on brief 2.
    None of them may be reported as if brief 1 were the whole answer."""
    lung = [_audit('7000000000000000002', 'Lung', LUNG, 'Pharmacist Said')]
    colon = [_audit('7000000000000000002', 'Colon', COLON, None,
                    status='SKIPPED_DEADLINE')]
    rows = pipeline.pick_followed_brief([lung, colon])
    assert rows[0]['status'] == 'BRIEF_AUDIT_INCOMPLETE'
    # ... and one missing from a brief's results entirely
    rows = pipeline.pick_followed_brief(
        [[_audit('7000000000000000003', 'Lung', LUNG, 'Pharmacist Said')], []])
    assert rows[0]['status'] == 'BRIEF_AUDIT_INCOMPLETE'


def test_matched_none_carries_no_brief_and_keeps_the_first_audit():
    """It followed neither brief. Naming the higher-scoring one says it did."""
    lung = [_audit('7000000000000000004', 'Lung', LUNG, NONE, 40)]
    colon = [_audit('7000000000000000004', 'Colon', COLON, NONE, 95)]
    rows = pipeline.pick_followed_brief([lung, colon])
    assert rows[0]['score']['headline'] == 40          # the FIRST audit
    p = pipeline.placements(rows)[0]
    assert p['angle'] == NO_ANGLE and p['brief'] is None


def test_a_match_beats_a_higher_score_on_the_brief_it_missed():
    lung = [_audit('7000000000000000005', 'Lung', LUNG, 'Pharmacist Said', 30)]
    colon = [_audit('7000000000000000005', 'Colon', COLON, NONE, 99)]
    p = pipeline.placements(pipeline.pick_followed_brief([lung, colon]))[0]
    assert (p['angle'], p['brief']) == ('Pharmacist Said', 'Lung')
    assert p['needs_review'] is False


def test_matched_none_says_when_it_could_not_really_tell():
    """A video that was never SEEN looks exactly like one that fits nothing."""
    blind = _audit('7000000000000000006', None, LUNG, NONE, visual_missing=True)
    empty = _audit('7000000000000000007', None, LUNG, None)
    real = _audit('7000000000000000008', None, LUNG, NONE)
    a, b, c = pipeline.placements([blind, empty, real])
    assert a['needs_review'] and 'no visual evidence' in a['note']
    assert b['needs_review'] and 'returned nothing' in b['note']
    assert c['angle'] == NO_ANGLE and c['needs_review'] is False


# ---------------------------------------------------------------------------
# Reading concepts out of a brief
# ---------------------------------------------------------------------------
def test_a_detail_line_starting_like_a_heading_does_not_end_the_list():
    """`Does the creator show it?` matched the old `do.?s` stop rule, and the
    concepts after it were lost."""
    text = """Brief
Purpose
Why.
Creative concepts
1. Steady & Warm
Does the creator show it? yes
Hooks that open on the product work best here.
2. Partner Approved
Dogs are welcome in the shot.
3. POV: Busy Days
Hooks
1. "Listen up"
"""
    assert ingest.document_angles(text) == [
        'Steady & Warm', 'Partner Approved', 'POV: Busy Days']


def test_a_numbered_list_in_the_purpose_is_not_the_concepts():
    text = """Brief
Purpose
1. Drive awareness of the bottle
2. Show everyday use
Creative Concepts
1. Steady & Warm
2. Partner Approved
Hooks
"""
    assert ingest.document_angles(text) == ['Steady & Warm', 'Partner Approved']


def test_a_second_numbered_list_is_not_more_concepts():
    """Under a heading this reader does not know by name, the numbering
    restarting at 1 is what says the concepts are over."""
    text = """Brief
Creative Concepts
1. Steady & Warm
2. Partner Approved
Filming notes
1. Film vertical
2. Tag the brand
Hooks
"""
    assert ingest.document_angles(text) == ['Steady & Warm', 'Partner Approved']


def test_known_later_sections_end_the_list():
    for heading in ('Deliverables', "Do’s:", "DON'TS", 'Product Links',
                    'Call to Actions', 'Key Talking Points/Features',
                    'Hook Concepts', 'Posting requirements'):
        text = f'Creative Concepts\n1. One Thing\n{heading}\n2. Not A Concept\n'
        assert ingest.document_angles(text) == ['One Thing'], heading


# ---------------------------------------------------------------------------
# Link handling
# ---------------------------------------------------------------------------
def test_the_video_id_is_not_the_handle():
    """`@jane1234567` has seven digits; the old rule took them for the id and
    a good link was reported as undownloadable."""
    vid = '7671762950687919390'
    for url in (f'https://www.tiktok.com/@jane1234567/video/{vid}',
                f'https://www.tiktok.com/@jane1234567/video/{vid}?is_from=x',
                f'https://www.tiktok.com/@a/video/{vid}#comments',
                f'https://www.tiktok.com/@a/video/{vid}&a=1',
                f'https://m.tiktok.com/v/{vid}'):
        assert ingest._video_id(url) == vid, url
    assert ingest._video_id('https://vm.tiktok.com/ZMabcDEF/') == ''


def test_the_same_video_sent_twice_is_not_reported_as_a_failure():
    row = _audit('7671762950687919390', None, LUNG, 'Pharmacist Said')
    twin = 'https://www.tiktok.com/@c/video/7671762950687919390?lang=en'
    groups, unplaced = pipeline.angle_groups(
        [row], submitted=[row['url'], twin])
    assert [g['videos'] for g in groups if g['angle'] == 'Pharmacist Said'] \
        == [[row['url']]]
    assert len(unplaced) == 1 and unplaced[0]['video'] == twin
    assert 'the same video as' in unplaced[0]['reason']
    assert row['url'] in unplaced[0]['reason']


# ---------------------------------------------------------------------------
# Fetching one tab of a Google Doc
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, text, status=200):
        self.status_code, self.content = status, text.encode('utf-8')


def _fake_google(monkeypatch, tabs, whole='WHOLE DOCUMENT'):
    """`tabs` maps a tab id to its text. An unknown tab answers with t.0,
    which is what Google really does."""
    import requests
    seen = []

    def get(url, timeout=None, allow_redirects=True):
        seen.append(url)
        if '&tab=' not in url:
            return _Resp(whole)
        tab = url.split('&tab=')[1]
        return _Resp(tabs.get(tab, tabs['t.0']))
    monkeypatch.setattr(requests, 'get', get)
    return seen


def test_a_tab_link_fetches_that_tab(monkeypatch):
    seen = _fake_google(monkeypatch, {'t.0': 'COLON BRIEF', 't.abc': 'LUNG BRIEF'})
    got = ingest.load_brief(brief_url=DOC + '?tab=t.abc')
    assert got['text'] == 'LUNG BRIEF'
    assert got['origin'].endswith('#t.abc')
    assert any(u.endswith('&tab=t.abc') for u in seen)
    # no tab: the whole document, as before
    assert ingest.load_brief(brief_url=DOC + '?usp=sharing')['text'] \
        == 'WHOLE DOCUMENT'


def test_a_tab_that_does_not_exist_is_refused(monkeypatch):
    """Google answers an unknown tab id with the FIRST tab and a 200. Left
    alone, one product's videos are audited against the other's brief."""
    _fake_google(monkeypatch, {'t.0': 'COLON BRIEF', 't.abc': 'LUNG BRIEF'})
    with pytest.raises(ingest.IngestError) as exc:
        ingest.load_brief(brief_url=DOC + '?tab=t.typo99')
    assert "no tab 't.typo99'" in str(exc.value)


def test_a_private_doc_is_refused_not_compiled(monkeypatch):
    import requests
    monkeypatch.setattr(
        requests, 'get', lambda *a, **k: _Resp('<!DOCTYPE html><html>Sign in'))
    with pytest.raises(ingest.IngestError) as exc:
        ingest.load_brief(brief_url=DOC + '?tab=t.0')
    assert 'not publicly readable' in str(exc.value)


# ---------------------------------------------------------------------------
# Request validation, and what the public view shows
# ---------------------------------------------------------------------------
VID = 'https://www.tiktok.com/@a/video/7674625522189618445'


def test_angle_names_are_tidied_and_bounded(client):
    from app.schemas import AnalyzeRequest
    req = AnalyzeRequest(video_urls=[VID], briefs=[{
        'url': DOC, 'angles': ['  One  ', 'one', 'Two', '', 'TWO']}])
    assert req.briefs[0].angles == ['One', 'Two']
    r = client.post('/analyze', headers=_h(), json={
        'video_urls': [VID], 'briefs': [{'url': DOC, 'angles': ['x' * 121]}]})
    assert r.status_code == 422 and 'over 120 characters' in r.text


def test_top_level_angles_cannot_ride_along_with_briefs(client):
    """They would be silently ignored, and the caller would believe they
    had been used."""
    r = client.post('/analyze', headers=_h(), json={
        'video_urls': [VID], 'angles': ['One'],
        'briefs': [{'url': DOC, 'label': 'x'}]})
    assert r.status_code == 422 and 'each brief carries its own' in r.text


def test_stale_given_angles_are_dropped_when_nothing_settles_them():
    c = {'given_angles': ['Old'], 'cache_key': 'k+angles:abc',
         'brief_text': 'no numbered concepts here'}
    assert ingest.settle_angles(c, 'no numbered concepts here') == 'notebook'
    assert 'given_angles' not in c and c['cache_key'] == 'k'


def test_the_public_view_gives_placements_and_nothing_else(client):
    rows = [_audit('7000000000000000009', 'Lung', LUNG, 'Pharmacist Said', 88)]
    job = Job('reviewfix00001', {'video_urls': [rows[0]['url']]})
    job.status, job.phase, job.results = 'succeeded', 'done', rows
    job.named_angles, job.brief_labels = LUNG, ['Lung']
    job.angles_from = ['Lung: given']
    store = get_store()
    store._jobs[job.id] = job
    try:
        body = client.get(f'/jobs/{job.id}',
                          headers=_h({'x-forwarded-for': '1.2.3.4'})).json()
    finally:
        store._jobs.pop(job.id, None)
    assert body['view'] == 'angles' and body['results'] == []
    assert body['placements'] == [{
        'video': rows[0]['url'], 'angle': 'Pharmacist Said', 'brief': 'Lung',
        'needs_review': False, 'note': None}]
    assert body['angles_from'] == ['Lung: given']
    # nothing that is the report's business
    assert '88' not in str(body['placements']) and body['brief'] is None

def test_one_download_per_video_however_many_links(tmp_path, monkeypatch):
    """Two links to one video were fetched in parallel into the same file, and
    one was logged "could not download". Each video is fetched once and every
    link to it shares the outcome."""
    from auditor import runtime
    ns = runtime.load()
    calls = []

    def fake_download(urls, verbose=False):
        calls.append(urls[0])
        vid = ingest._video_id(urls[0])
        if vid != '7000000000000000099':          # that one is "deleted"
            (tmp_path / f'{vid}.mp4').write_bytes(b'x' * 64)

    monkeypatch.setitem(ns, 'download_videos', fake_download)
    monkeypatch.setitem(ns, 'DIRS', {**ns['DIRS'], 'inbox': tmp_path})
    a = 'https://www.tiktok.com/@c/video/7000000000000000011'
    twin = a + '?lang=en'
    b = 'https://www.tiktok.com/@c/video/7000000000000000022'
    dead = 'https://www.tiktok.com/@c/video/7000000000000000099'
    out = ingest.download_videos([a, twin, b, dead, dead + '?x=1'], workers=4)
    assert sorted(calls) == sorted([a, b, dead])      # three videos, three fetches
    assert out['failed_urls'] == [dead, dead + '?x=1']
    assert len(out['downloaded']) == 2
