"""A job must only work on -- and report on -- the videos it was given.

WHY THIS IS NOT OBVIOUS
-----------------------
`discover_videos()` reads MANIFESTS out of the artifact store, and that store
is shared across jobs on purpose: it is the cache that makes a re-run nearly
free. In the notebook, where one run owns the machine, "every manifest" and
"my videos" are the same set, so the notebook code is correct as written.

Behind an API they are different sets, and nothing in the notebook's code says
so. The consequences differ by phase:

  phases 2/3  wasted work. Measured: auditing one 65 s clip with force=true
              also re-transcribed a previous job's video; phase 2 took 344 s
              instead of ~170 s. On a server holding 500 audited videos,
              "re-run this one" means 500 transcriptions.

  audit_all   WRONG OUTPUT. Another job's creator appears in this caller's
              results, capped only by max_videos_per_job.

The second one lined up correctly on every run measured during development,
because the store happened to hold one video. That is luck, not a guarantee,
which is exactly what a test is for.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from app.services import pipeline  # noqa: E402

SRC = (HERE / 'app' / 'services' / 'pipeline.py').read_text(encoding='utf-8')


class _NS(dict):
    """The notebook namespace, with discover_videos() returning the WHOLE
    store -- which is what it really does."""

    def __init__(self, inbox: Path, all_sources: list):
        super().__init__()
        self['DIRS'] = {'inbox': inbox}
        self['VIDEO_SUFFIXES'] = {'.mp4', '.mov', '.webm'}
        self['discover_videos'] = lambda: [
            {'source': s, 'video_hash': f'h_{s}'} for s in all_sources]


def _inbox(tmp_path: Path, names: list) -> Path:
    d = tmp_path / 'inbox'
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).write_bytes(b'\x00\x00\x00\x18ftypmp42')
    return d


def test_only_this_jobs_videos_are_returned(tmp_path):
    ns = _NS(_inbox(tmp_path, ['mine.mp4']),
             ['mine.mp4', 'someone_elses.mp4', 'a_third.mp4'])
    got = [v['source'] for v in pipeline._this_jobs_videos(ns)]
    assert got == ['mine.mp4'], (
        f'a job would have processed {got} -- the store holds three videos '
        f'and this job submitted one')


def test_a_multi_video_job_keeps_all_of_its_own(tmp_path):
    ns = _NS(_inbox(tmp_path, ['a.mp4', 'b.mp4']),
             ['a.mp4', 'b.mp4', 'other.mp4'])
    got = sorted(v['source'] for v in pipeline._this_jobs_videos(ns))
    assert got == ['a.mp4', 'b.mp4']


def test_an_empty_inbox_falls_back_rather_than_finding_nothing(tmp_path):
    """Ephemeral mode deletes the inbox when a job ends. A stage re-entered
    after that must not silently conclude it has no work."""
    ns = _NS(_inbox(tmp_path, []), ['a.mp4'])
    assert [v['source'] for v in pipeline._this_jobs_videos(ns)] == ['a.mp4']


def test_a_missing_inbox_directory_is_survivable(tmp_path):
    ns = _NS(tmp_path / 'not_created', ['a.mp4'])
    assert [v['source'] for v in pipeline._this_jobs_videos(ns)] == ['a.mp4']


def test_non_video_files_in_the_inbox_do_not_widen_the_scope(tmp_path):
    d = _inbox(tmp_path, ['mine.mp4'])
    (d / 'notes.txt').write_text('x', encoding='utf-8')
    ns = _NS(d, ['mine.mp4', 'notes.txt', 'other.mp4'])
    got = [v['source'] for v in pipeline._this_jobs_videos(ns)]
    assert got == ['mine.mp4']


def test_every_stage_that_discovers_videos_is_scoped():
    """The guard that matters: a stage added later must not reintroduce this.

    audit_all is the one where an unscoped call produces WRONG OUTPUT rather
    than slow output, so it is named explicitly.
    """
    body = SRC.split('def _this_jobs_videos', 1)[1]
    raw = body.count("ns['discover_videos']()")
    assert raw <= 2, (
        f'{raw} unscoped discover_videos() calls after the helper -- one is '
        f'the helper itself, one is the phase-1 reconciliation which compares '
        f'against the inbox deliberately. Any other stage must use '
        f'_this_jobs_videos().')

    audit = SRC.split('def audit_all', 1)[1].split('\ndef ', 1)[0]
    assert '_this_jobs_videos(ns)' in audit, (
        'audit_all must be scoped: unscoped it returns results for videos the '
        'caller never submitted')
    assert "ns['discover_videos']()" not in audit
