"""Run §75 through §82 in sequence, as the notebook will.

§80, §81 and §82 are driver cells -- they were never executed by the unit
tests, only their callees were. A driver cell that has never run is a cell
that will fail in front of the user.
"""
import base64
import json
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from p7_harness import load, make_ns                              # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
CELLS = Path(r'C:\Users\Umar Ilyas\creative project\Phase 7\cells')
TMP = Path(tempfile.mkdtemp())


class Rec:
    def __init__(self, i, mod, t0, t1, text='', desc=''):
        self.id, self.modality = i, mod
        self.start_seconds, self.end_seconds = t0, t1
        self.raw_text, self.description = text, desc


RECORDS = [Rec('ev_1', 'speech', 0.5, 3.0, 'Blow drying ruined my hair.'),
           Rec('ev_2', 'speech', 11.0, 14.0, 'I take these every single day.'),
           Rec('ev_3', 'ocr', 28.0, 30.0, 'LINK IN BIO'),
           Rec('ev_4', 'visual', 6.0, 9.0, desc='She holds the white jar.')]


def V(rid, status, priority='medium', flags=None, label='', ev=None, layer='L3',
      alignment=None):
    return {'requirement_id': rid, 'status': status, 'priority': priority,
            'weight': {'critical': 3.0, 'high': 2.0, 'medium': 1.0,
                       'low': 0.5}[priority],
            'flags': flags or [], 'requirement_label': label or rid,
            'evidence_ids': ev or [], 'reason': 'a stated reason', 'layer': layer,
            'alignment': alignment, 'examined_ids': ['ev_1'], 'group': None}


VERDICTS = [
    V('r1', 'PASS', label='Open with a relatable hook', ev=['ev_1'],
      alignment='strong'),
    V('r2', 'FAIL', 'critical', label='Name Ceramosides Oil', ev=['ev_2'],
      alignment='none'),
    V('r3', 'PARTIAL', label='Show the product clearly', ev=['ev_4'],
      alignment='partial'),
    V('r4', 'UNCERTAIN', label='Mention the discount code', ev=['ev_3']),
    V('r5', 'NOT_APPLICABLE', label='Hook option B'),
    V('r6', 'PASS', 'high', flags=['PASS_FROM_ABSENCE'],
      label='No medical claims', ev=[]),
]
REQS = [{'id': 'r1', 'type': 'hook', 'priority': 'medium', 'polarity': 'required'},
        {'id': 'r2', 'type': 'speech', 'priority': 'critical', 'polarity': 'required'},
        {'id': 'r3', 'type': 'visual', 'priority': 'medium', 'polarity': 'required'},
        {'id': 'r4', 'type': 'cta', 'priority': 'medium', 'polarity': 'required'},
        {'id': 'r5', 'type': 'hook', 'priority': 'medium', 'polarity': 'required'},
        {'id': 'r6', 'type': 'policy', 'priority': 'high', 'polarity': 'forbidden'}]


class FakeBackend:
    name = 'fake'

    def complete(self, system, user, cfg):
        return {'text': json.dumps({'recommendations': [
            {'requirement_id': 'r2',
             'edit': 'Name Ceramosides Oil right after the jar shot.',
             'at_seconds': 12.0, 'evidence_ids': ['ev_2'], 'effort': 'trivial'}],
            'keep': ['The opening problem statement lands fast.']}),
            'backend': 'fake'}


ns = make_ns(TMP)
ns.update({
    're': re, 'subprocess': subprocess, 'base64': base64, 'Path': Path,
    'time': time, 'asdict': asdict, 'dataclass': dataclass, 'field': field,
    'replace': lambda o, **kw: o,
    'P4': type('x', (), {'brief': type('y', (), {'temperature': 0.0,
                                                 'max_new_tokens': 1600})()})(),
    'P6': type('x', (), {'l3': type('y', (), {'enabled': True})()})(),
    'parse_model_json': lambda t: (json.loads(t), None, 'direct'),
    'make_brief_backend': lambda *a, **kw: FakeBackend(),
    'load_records': lambda ev: RECORDS,
    'DIMENSION_LABEL': None,     # overwritten by §75
})
ns['TARGET'] = {'video_hash': 'vh_integration', 'video_id': 'vid_int',
                'path': '', 'duration_s': 30.8}
ns['evidence'] = {'cache_key': 'ek1', 'duration_seconds': 30.8}
ns['result'] = {
    'video_hash': 'vh_integration', 'video_id': 'vid_int', 'cache_key': 'vk_int',
    'brief_hash': 'bh_int', 'duration_seconds': 30.8, 'verdicts': VERDICTS,
    'sources': {'evidence': 'ek1', 'brief': 'bk_int'}, 'flags': [],
    'stats': {'requirements': len(VERDICTS)},
    'standing': {'standing': 'partial', 'weight': 0.55,
                 'verdict': 'Broadly on brief, but the named ingredient is absent.',
                 'covered': ['hair health'], 'missing': ['Name Ceramosides Oil'],
                 'off_brief_additions': [], 'evidence_ids': ['ev_1'],
                 'confidence': 'high', 'disclaimer': 'A second opinion.'},
    'hook': {'hook_present': True, 'hook_type': 'problem_statement',
             'strength': 'strong', 'start': 0.5, 'end': 3.0,
             'transcript': 'Blow drying ruined my hair.',
             'visual': '', 'within_required_window': True,
             'reason': 'Names a problem the viewer has.',
             'features': {}, 'evidence_ids': ['ev_1'], 'layer': 'L1', 'flags': []},
    'creative_angle': {'angle': 'problem_solution', 'summary': 'Problem then fix.',
                       'nearest_brief_concept': None,
                       'anticipated_by_brief': False, 'evidence_ids': ['ev_1'],
                       'flags': [], 'disclaimer': ''},
    'claims': {'enabled': False, 'note': 'Switched off.', 'claims': [],
               'disclaimer': 'Not legal advice.'},
}
ns['_p6_brief'] = {'cache_key': 'bk_int', 'brief_hash': 'bh_int',
                   'requirements': REQS, 'approved': True,
                   'approved_by': 'the integration test',
                   'brief_text': 'Talk about hair health and name the oil.'}

print('#' * 78)
print('RUNNING §75 -> §82 IN ORDER')
print('#' * 78)
ORDER = ['s75_config.py', 's75b_discriminate.py', 's76_score.py',
         's78_recommend.py', 's79_report.py', 's79b_figures.py',
         's77_tests.py', 's80_run.py', 's81_exit.py', 's82_selfcheck.py']
for name in ORDER:
    print()
    print(f'>>>>>> {name}')
    try:
        exec(compile((CELLS / name).read_text('utf-8'), name, 'exec'), ns)
    except Exception as exc:
        import traceback
        print(f'!!!!!! {name} RAISED {type(exc).__name__}: {exc}')
        traceback.print_exc()
        raise SystemExit(1)

print()
print('#' * 78)
print('INTEGRATION RESULT')
print('#' * 78)
sc = ns['score']
print(f'  score        : {sc["score"]["band_low"]}-{sc["score"]["band_high"]} '
      f'{sc["score"]["status_band"]}')
print(f'  units        : {sc["score"]["scoring_units"]}')
print(f'  tests green  : {ns.get("_p7_tests_ok")}')
print(f'  exit green   : {ns.get("_p7_exit_ok")}')
rp = ns['report']
print(f'  html         : {rp["html_path"].name} ({len(rp["html"]) / 1024:.0f} KB)')
print(f'  json         : {rp["json_path"].name}')
print(f'  html exists  : {rp["html_path"].exists()}')
print(f'  json exists  : {rp["json_path"].exists()}')

# Hand-check the arithmetic one more time, from the outside.
# achievement = r1 PASS w1, r2 FAIL w3, r3 PARTIAL w1, r4 UNCERTAIN w1
#   total w 6, decided w 5, earned 1*1 + 3*0 + 1*0.5 = 1.5
#   pessimistic 100*1.5/6 = 25   optimistic 100*1.5/5 = 30   coverage 5/6 = .833
ok = (sc['score']['band_low'] == 25 and sc['score']['band_high'] == 30
      and abs(sc['score']['coverage'] - 0.8333) < 0.001
      and sc['score']['scoring_units'] == 4)
print()
print(f'  arithmetic checked by hand (25-30, 83% coverage, 4 units): '
      f'{"PASS" if ok else "FAIL"}')
print(f'  critical floor applied: {sc["score"]["critical_floor_applied"]} '
      f'-> {sc["score"]["status_band"]}')
raise SystemExit(0 if ok and ns.get('_p7_tests_ok') else 1)

