""""Frozen" must mean frozen -- the FIRST compile, not the latest one.

WHAT WENT WRONG
---------------
The compiler is not deterministic. One brief produced 20, 27 and 28
requirements across runs at temperature 0, and the requirement set is the
contract a score means something against. So the first compile of a brief is
frozen and every later video is measured against it.

_frozen_compile() selected the NEWEST approved compile on disk. That made the
guarantee false in the one way nobody would check: any later compile silently
became the contract. It was reached by accident here -- timing a cold compile
replaced a 28-requirement contract with a 27-requirement one, and the next
ordinary run would have used it. Two finished reports scored against 28 would
have stopped being comparable with everything after, and nothing in any
output would have said so.

Selection is now an explicit pointer (FROZEN.json), falling back to the
OLDEST approved compile. recompile=True is the only thing that moves it.
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from app.services import ingest  # noqa: E402


class _NS(dict):
    def __init__(self):
        super().__init__()
        self['read_json'] = lambda p: (
            json.loads(Path(p).read_text(encoding='utf-8'))
            if Path(p).is_file() else None)

        def _write(p, d):
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            Path(p).write_text(json.dumps(d), encoding='utf-8')
        self['write_json'] = _write


def _compile(bdir: Path, key: str, n: int, mtime: float) -> dict:
    """An approved compile with n requirements, stamped at mtime."""
    import os
    d = {'cache_key': key, 'status': 'OK', 'approved': True,
         'approved_digest': f'dig_{key}',
         'requirements': [{'id': f'r{i}'} for i in range(n)]}
    p = bdir / f'requirements__{key}.json'
    bdir.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d), encoding='utf-8')
    os.utime(p, (mtime, mtime))
    return d


def test_the_first_compile_wins_not_the_newest(tmp_path):
    ns = _NS()
    bdir = tmp_path / 'brief'
    _compile(bdir, 'first', 28, 1000.0)
    _compile(bdir, 'later', 27, 2000.0)          # newer, and WRONG to pick

    got = ingest._frozen_compile(ns, bdir)
    assert got['cache_key'] == 'first', (
        f"picked {got['cache_key']} -- a later compile became the contract, "
        f"which is the bug: scores before and after stop being comparable "
        f"with nothing saying so")
    assert len(got['requirements']) == 28


def test_selecting_writes_the_pointer_so_the_choice_is_explicit(tmp_path):
    ns = _NS()
    bdir = tmp_path / 'brief'
    _compile(bdir, 'first', 28, 1000.0)
    ingest._frozen_compile(ns, bdir)
    ptr = json.loads((bdir / ingest.FROZEN_POINTER).read_text(encoding='utf-8'))
    assert ptr['cache_key'] == 'first'
    assert ptr['requirements'] == 28


def test_the_pointer_is_obeyed_over_age(tmp_path):
    """recompile=True moves the pointer deliberately; that must stick."""
    ns = _NS()
    bdir = tmp_path / 'brief'
    _compile(bdir, 'first', 28, 1000.0)
    newer = _compile(bdir, 'later', 27, 2000.0)
    ingest.freeze_pointer(ns, bdir, newer)       # the deliberate act

    got = ingest._frozen_compile(ns, bdir)
    assert got['cache_key'] == 'later', (
        'a deliberate recompile must be able to replace the contract')


def test_a_dangling_pointer_falls_back_to_the_first(tmp_path):
    """A pointer at a deleted compile must not leave the brief with none."""
    ns = _NS()
    bdir = tmp_path / 'brief'
    _compile(bdir, 'first', 28, 1000.0)
    ns['write_json'](bdir / ingest.FROZEN_POINTER, {'cache_key': 'deleted'})
    got = ingest._frozen_compile(ns, bdir)
    assert got['cache_key'] == 'first'


def test_unapproved_compiles_are_never_the_contract(tmp_path):
    ns = _NS()
    bdir = tmp_path / 'brief'
    bdir.mkdir(parents=True)
    (bdir / 'requirements__raw.json').write_text(json.dumps(
        {'cache_key': 'raw', 'status': 'OK', 'approved': False,
         'requirements': [{'id': 'r0'}]}), encoding='utf-8')
    assert ingest._frozen_compile(ns, bdir) is None


def test_no_compiles_at_all_is_None_not_a_crash(tmp_path):
    d = tmp_path / 'empty'
    d.mkdir()
    assert ingest._frozen_compile(_NS(), d) is None


def test_recompile_moves_the_pointer_in_the_source():
    """The write alone must not be what changes the contract."""
    src = (HERE / 'app' / 'services' / 'ingest.py').read_text(encoding='utf-8')
    body = src.split('def compile_brief', 1)[1].split('\ndef ', 1)[0]
    assert 'freeze_pointer(' in body, (
        'compile_brief writes a new compile but never moves the pointer, so '
        'recompile=True would have no effect on later runs')


@pytest.mark.parametrize('n_extra', [1, 3])
def test_many_later_compiles_still_lose(tmp_path, n_extra):
    ns = _NS()
    bdir = tmp_path / 'brief'
    _compile(bdir, 'first', 28, 1000.0)
    for i in range(n_extra):
        _compile(bdir, f'late{i}', 20 + i, 2000.0 + i)
    assert ingest._frozen_compile(ns, bdir)['cache_key'] == 'first'
