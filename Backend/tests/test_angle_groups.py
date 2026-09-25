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
