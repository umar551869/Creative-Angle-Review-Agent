"""§75b: the label-free discrimination experiment.

The claim under test is that a video scored against its OWN brief separates
from the same video scored against a FOREIGN one -- with no human saying which
is which.
"""
import base64
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from p7_harness import load, make_ns                              # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
R = []


def check(label, cond, detail=''):
    R.append((label, bool(cond)))
    print(f'  {"PASS" if cond else "FAIL"}  {label}' + (f'   [{detail}]' if detail else ''))


def V(rid, status, priority='medium', flags=None, alignment=None):
    return {'requirement_id': rid, 'status': status, 'priority': priority,
            'weight': 1.0, 'flags': flags or [], 'requirement_label': rid,
            'evidence_ids': ['ev_1'], 'reason': 'r', 'layer': 'L3',
            'alignment': alignment, 'examined_ids': []}


def artifact(vh, vid, bh, verdicts, standing):
    return {'video_hash': vh, 'video_id': vid, 'brief_hash': bh,
            'cache_key': f'{vh}_{bh}', 'duration_seconds': 30.0,
            'verdicts': verdicts, 'standing': {'standing': standing},
            'sources': {}, 'hook': {}, 'claims': {}}


def setup(tmp, with_controls=True):
    art = tmp / 'artifacts'
    # Two videos, each shot for its own brief.
    good = [V('r1', 'PASS', alignment='exact'), V('r2', 'PASS', alignment='strong'),
            V('r3', 'PARTIAL', alignment='partial')]
    bad = [V('r1', 'FAIL', alignment='none'), V('r2', 'FAIL', alignment='none'),
           V('r3', 'FAIL', alignment='tangential'),
           V('r4', 'PASS', flags=['PASS_FROM_ABSENCE'])]
    pairs = [('vhA', 'hair_vid', 'bhHAIR', good, 'on_brief', False),
             ('vhB', 'pill_vid', 'bhPILL', good, 'on_brief', False)]
    if with_controls:
        pairs += [('vhA', 'hair_vid', 'bhPILL', bad, 'off_brief', True),
                  ('vhB', 'pill_vid', 'bhHAIR', bad, 'off_brief', True)]
    controls = []
    for vh, vid, bh, vs, st, is_ctl in pairs:
        d = art / vh
        d.mkdir(parents=True, exist_ok=True)
        (d / f'verdicts__{vh}_{bh}.json').write_text(
            json.dumps(artifact(vh, vid, bh, vs, st)), encoding='utf-8')
        if is_ctl:
            controls.append([vh, bh])
    if controls:
        (art / '_discrimination').mkdir(parents=True, exist_ok=True)
        (art / '_discrimination' / 'controls.json').write_text(
            json.dumps({'pairs': controls}), encoding='utf-8')


def run(with_controls=True):
    tmp = Path(tempfile.mkdtemp())
    setup(tmp, with_controls)
    ns = make_ns(tmp)
    ns.update({'re': re, 'subprocess': subprocess, 'base64': base64,
               'Path': Path, 'replace': lambda o, **k: o,
               'P6': type('x', (), {'l3': type('y', (), {'enabled': True})()})()})
    load(ns, 's75_config.py', 's75b_discriminate.py')
    return ns['_discrimination'], ns


print('=' * 78)
print('WITH CONTROLS -- each video against its own brief and a foreign one')
print('=' * 78)
d, ns = run(True)
print()
check('no human label was required', 'ONBRIEF_VIDEOS' not in ns,
      'the variable no longer exists')
check('native and control pairings both found',
      d['native'] == 2 and d['control'] == 2, f"{d['native']}/{d['control']}")
check('a winner was chosen', bool(d['winner']), d['verdict'])
check('B separates own from foreign',
      d['candidates']['B_status_achievement']['discriminates'] is True,
      str(d['candidates']['B_status_achievement']))
check('the vacuous pass did not rescue the foreign pairing',
      d['candidates']['B_status_achievement']['foreign'][1]
      < d['candidates']['A_status_all']['foreign'][1],
      f"B foreign {d['candidates']['B_status_achievement']['foreign']} vs "
      f"A foreign {d['candidates']['A_status_all']['foreign']}")
check('the margin is recorded, not just a boolean',
      isinstance(d['candidates']['B_status_achievement']['margin'], float))
check('standing also separates',
      d['candidates']['D_standing']['discriminates'] is True)

print()
print('=' * 78)
print('WITHOUT CONTROLS -- it must say what is missing, not guess')
print('=' * 78)
d2, ns2 = run(False)
print()
# THE first-run case, and the one that shipped broken: controls.json does not
# exist yet. read_json RAISES on a missing file rather than returning None, so
# `read_json(p) or {}` was a crash with a fallback attached. This test only has
# teeth because the harness's read_json is now copied verbatim from the
# notebook -- the forgiving stub it replaced passed this happily.
check('a first run with no controls.json does not crash',
      isinstance(d2, dict) and 'verdict' in d2)
check('refuses to name a winner from one population', d2['winner'] is None)
check('says exactly what is missing', d2['verdict'] == 'no controls yet',
      d2['verdict'])
check('control audits are OFF by default', ns2['RUN_CONTROL_AUDITS'] is False)
check('spending is capped', isinstance(ns2['MAX_CONTROL_AUDITS'], int)
      and ns2['MAX_CONTROL_AUDITS'] <= 20)

print()
bad_ = [l for l, g in R if not g]
print(f'{len(R) - len(bad_)}/{len(R)} checks pass')
print('ALL PASS' if not bad_ else 'FAILED:\n   ' + '\n   '.join(bad_))
