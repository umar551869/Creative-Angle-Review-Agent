"""§78 + §79 + §79b: recommendations, figures, and the page itself."""
import base64
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from p7_harness import load, make_ns                              # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
TMP = Path(tempfile.mkdtemp())
R = []


def check(label, cond, detail=''):
    R.append((label, bool(cond)))
    print(f'  {"PASS" if cond else "FAIL"}  {label}' + (f'   [{detail}]' if detail else ''))


class Rec:
    def __init__(self, i, mod, t0, t1, text='', desc=''):
        self.id, self.modality = i, mod
        self.start_seconds, self.end_seconds = t0, t1
        self.raw_text, self.description = text, desc


class FakeBackend:
    name = 'fake'

    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    def complete(self, system, user, cfg):
        self.calls += 1
        self.last_user = user
        return {'text': json.dumps(self.payload), 'backend': 'fake'}


def parse_model_json(text):
    try:
        return json.loads(text), None, 'direct'
    except Exception as e:
        return None, str(e), 'failed'


class _Cfg:
    temperature = 0.0
    max_new_tokens = 1600


class _P4:
    brief = _Cfg()


class _L3:
    enabled = True


class _P6:
    l3 = _L3()


ns = make_ns(TMP)
ns.update({'re': re, 'subprocess': subprocess, 'base64': base64, 'Path': Path,
           'replace': lambda o, **kw: o, 'P4': _P4(), 'P6': _P6(),
           'parse_model_json': parse_model_json,
           'make_brief_backend': lambda *a, **kw: FakeBackend({})})
ns = load(ns, 's75_config.py', 's76_score.py', 's78_recommend.py',
          's79b_figures.py', 's79_report.py')

RECS = [Rec('ev_1', 'speech', 0.5, 3.0, 'Blow drying ruined my hair.'),
        Rec('ev_2', 'speech', 11.0, 14.0, 'I take these every day.'),
        Rec('ev_3', 'ocr', 28.0, 30.0, 'LINK IN BIO'),
        Rec('ev_4', 'visual', 6.0, 9.0, desc='She holds the white jar.')]


def V(rid, status, priority='medium', flags=None, label='', ev=None, **kw):
    d = {'requirement_id': rid, 'status': status, 'priority': priority,
         'weight': ns['PRIORITY_WEIGHT'][priority], 'flags': flags or [],
         'requirement_label': label or rid, 'evidence_ids': ev or ['ev_1'],
         'reason': 'a reason', 'layer': 'L3', 'alignment': 'strong',
         'examined_ids': []}
    d.update(kw)
    return d


VERDICTS = [V('r1', 'PASS', label='Open with a relatable hook', ev=['ev_1']),
            V('r2', 'FAIL', 'critical', label='Name Ceramosides Oil', ev=['ev_2']),
            V('r3', 'PARTIAL', label='Show the product clearly', ev=['ev_4']),
            V('r4', 'UNCERTAIN', label='Mention the discount', ev=['ev_3']),
            V('r5', 'NOT_APPLICABLE', label='Hook option B'),
            V('r6', 'PASS', flags=['PASS_FROM_ABSENCE'], label='No medical claims',
              ev=[])]
REQS = [{'id': 'r1', 'type': 'hook', 'priority': 'medium', 'polarity': 'required'},
        {'id': 'r2', 'type': 'speech', 'priority': 'critical', 'polarity': 'required'},
        {'id': 'r3', 'type': 'visual', 'priority': 'medium', 'polarity': 'required'},
        {'id': 'r4', 'type': 'cta', 'priority': 'medium', 'polarity': 'required'},
        {'id': 'r5', 'type': 'hook', 'priority': 'medium', 'polarity': 'required'},
        {'id': 'r6', 'type': 'policy', 'priority': 'high', 'polarity': 'forbidden'}]
RESULT = {'video_hash': 'vh1', 'video_id': 'vid1', 'cache_key': 'vk1',
          'brief_hash': 'bh1', 'duration_seconds': 30.8, 'verdicts': VERDICTS,
          'sources': {'evidence': 'ek1'},
          'standing': {'standing': 'partial', 'weight': 0.55,
                       'verdict': 'Mostly on brief.', 'covered': ['hair health'],
                       'missing': ['Name Ceramosides Oil'], 'evidence_ids': ['ev_1'],
                       'disclaimer': 'Second opinion.'},
          'hook': {'hook_present': True, 'hook_type': 'problem_statement',
                   'strength': 'strong', 'start': 0.5, 'end': 3.0,
                   'transcript': 'Blow drying ruined my hair.',
                   'reason': 'Names a problem the viewer has.',
                   'within_required_window': True},
          'creative_angle': {'angle': 'problem_solution', 'summary': 'Problem then fix.',
                             'nearest_brief_concept': None, 'anticipated_by_brief': False},
          'claims': {'enabled': False, 'note': 'Switched off.'}}
COMPILED = {'cache_key': 'bk1', 'brief_hash': 'bh1', 'requirements': REQS,
            'approved': True, 'brief_text': 'Talk about hair.'}

score = ns['score_audit'](RESULT, COMPILED, verbose=False)

print('=' * 76)
print('§78  RECOMMENDATIONS -- the rules bite')
print('=' * 76)
good = {'recommendations': [
    {'requirement_id': 'r2', 'edit': 'Name Ceramosides Oil right after the jar shot.',
     'at_seconds': 12.0, 'evidence_ids': ['ev_2'], 'effort': 'trivial'}],
    'keep': ['The opening problem statement lands fast.']}
ns['make_brief_backend'] = lambda *a, **kw: FakeBackend(good)
rec = ns['evaluate_recommendations'](RESULT, COMPILED, score, RECS,
                                     backend=FakeBackend(good), verbose=False)
check('a clean recommendation survives', len(rec['recommendations']) == 1, rec['recommendations'])
check('anchor kept when it matches a cited record',
      rec['recommendations'][0]['at_seconds'] == 12.0)
check('keep list survives', rec['keep'] == ['The opening problem statement lands fast.'])
check('only FAIL/PARTIAL considered', rec['considered_units'] == 2, rec['considered_units'])

bad = {'recommendations': [
    {'requirement_id': 'r2', 'edit': 'You scored 60 percent, fix the messaging.',
     'at_seconds': 12.0, 'evidence_ids': ['ev_2'], 'effort': 'small'},
    {'requirement_id': 'r2', 'edit': 'Name the oil at the jar shot.',
     'at_seconds': 12.0, 'evidence_ids': ['ev_999'], 'effort': 'small'},
    {'requirement_id': 'r3', 'edit': 'Hold the jar closer to the lens.',
     'at_seconds': 99.0, 'evidence_ids': ['ev_4'], 'effort': 'small'}]}
rec2 = ns['evaluate_recommendations'](RESULT, COMPILED, score, RECS,
                                      backend=FakeBackend(bad), verbose=False)
codes = [v['code'] for v in rec2['violations']]
check('a recommendation writing a number is DROPPED',
      not any('scored' in r['edit'] for r in rec2['recommendations']), codes)
check('forbidden wording is reported', 'FORBIDDEN_WORDING' in codes, codes)
check('a fabricated evidence id is reported', 'FABRICATED_EVIDENCE_ID' in codes)
check('an invented anchor is reported', 'ANCHOR_NOT_IN_CITED_EVIDENCE' in codes)
check('the edit survives but the invented time does not',
      any(r['requirement_id'] == 'r3' and r['at_seconds'] is None
          for r in rec2['recommendations']), rec2['recommendations'])
check('a fabricated id is stripped from what remains',
      all('ev_999' not in (r['evidence_ids'] or []) for r in rec2['recommendations']))

clean = {'video_hash': 'vh1', 'cache_key': 'vk2', 'verdicts':
         [V('r1', 'PASS'), V('r2', 'PASS')], 'duration_seconds': 30.0}
rec3 = ns['evaluate_recommendations'](clean, COMPILED, score, RECS,
                                      backend=FakeBackend(good), verbose=False)
check('abstains when nothing failed', rec3['recommendations'] == [] and 'Nothing to fix' in rec3['note'])
check('no model call when there is nothing to fix', rec3.get('backend') is None)

print()
print('=' * 76)
print('§79b  FIGURES -- degradation is a feature')
print('=' * 76)
figs = ns['build_figures'](score, RESULT, RECS, sibling_scores=[score], cfg=ns['P7'])
# This must hold whether or not plotly happens to be installed here -- the
# point is that the report survives EITHER way, so the test cannot assume one.
if figs['plotly_available']:
    check('figures drawn when plotly is present', bool(figs['figures']),
          [f['id'] for f in figs['figures']])
    check('each figure records whether its markers are traceable',
          all('provenance' in f for f in figs['figures']))
else:
    check('plotly absent leaves a note saying so',
          figs['figures'] == [] and len(figs['notes']) >= 1, figs['notes'][:1])
check('every figure that could not be drawn explains why',
      all(':' in n for n in figs['notes']), figs['notes'][:1])
check('a missing chart library cannot block the score', score['score']['headline'] is not None)

print()
print('=' * 76)
print('§79  THE PAGE')
print('=' * 76)
html = ns['build_report_html']({'video_hash': 'vh1', 'path': ''}, RESULT, COMPILED,
                               score, RECS, rec, figs, None, ns['P7'])
check('is a complete html document',
      html.startswith('<!doctype html>') and html.rstrip().endswith('</html>'))
# This audit has no contradictions (standing 'partial', score 30 -- nothing
# disagrees), so the section must be ABSENT. A section that always renders
# would train the reader to ignore it.
check('no contradictions -> no alert section', 'Read this first' not in html,
      [c['code'] for c in score['contradictions']])
_cres = dict(RESULT)
# A DIFFERENT verdict cache key, because the score artifact is keyed on it.
# In the pipeline that key is content-derived, so two different verdict sets
# can never share one; only a test can arrange that, and it must not.
_cres['cache_key'] = 'vk_contra'
_cres['verdicts'] = [V('r1', 'PASS', label='Name Ceramosides Oil')]
_cres['standing'] = {'standing': 'off_brief', 'weight': 0.0,
                     'verdict': 'A different product entirely.',
                     'missing': ['Name Ceramosides Oil'], 'evidence_ids': ['ev_9']}
_cs = ns['score_audit'](_cres, {'cache_key': 'bk1', 'requirements': [
    {'id': 'r1', 'type': 'speech', 'priority': 'medium', 'polarity': 'required'}]},
    verbose=False)
_ch = ns['build_report_html']({'video_hash': 'vh1', 'path': ''}, _cres, COMPILED,
                              _cs, RECS, None, figs, None, ns['P7'])
check('contradictions section leads when they exist', 'Read this first' in _ch)
check('it names both sides', 'STANDING_CONTRADICTS_SCORE' in _ch
      and 'different product' in _ch.lower())
check('it appears above the dimensions table',
      _ch.index('Read this first') < _ch.index('By dimension'))
# Raw requirement ids are deliberately no longer printed in the reader's view
# (§11a), so pinning 'r1'..'r4' tested the old page, not the requirement. What
# must hold is that no requirement goes MISSING -- check the labels.
check('every requirement is listed',
      all(lbl in html for lbl in
          ('Open with a relatable hook', 'Name Ceramosides Oil',
           'Show the product clearly', 'Mention the discount',
           'Hook option B', 'No medical claims')),
      [lbl for lbl in ('Open with a relatable hook', 'Name Ceramosides Oil',
                       'Show the product clearly', 'Mention the discount',
                       'Hook option B', 'No medical claims')
       if lbl not in html])
check('timestamps are seek links', 'class="ts" href="#player" data-t=' in html)
check('the seek handler is present', 'currentTime' in html)
check('NOT_APPLICABLE is disclosed, not hidden', 'not selected' in html)
check('compliance-by-absence is labelled',
      'compliance, not achievement' in html)
check('uncovered dimensions are named on the page',
      'says nothing about it' in html)
check('thin dimensions are marked', 'thin' in html)
# The disclosure moved into Technical details and was reworded for a lay
# reader. The REQUIREMENT is that it still exists somewhere on the page --
# not that it uses my old phrasing.
_low = html.lower()
check('placeholder thresholds are disclosed',
      ('placeholder' in _low or 'provisional' in _low) and 'threshold' in _low)
check('the verdict artifact is named', 'vk1' in html)
check('claims disclaimer or off-note present', 'Switched off' in html)
check('standing appears as a separate whole-video judgement',
      'The whole brief against the whole video' in html)
# 'Appendix' was renamed 'Technical details'. Splitting on the old name left
# the technical block IN the slice, where escaped dicts are legitimate -- so
# this check was reading the one part of the page it was meant to exclude.
check('no raw dict leaked into the page',
      '{&#39;' not in html.split('Technical details')[0])

evil = dict(RESULT)
evil['verdicts'] = [V('rX', 'FAIL', label='<script>alert(1)</script>',
                      reason='<img src=x onerror=alert(2)>')]
s2 = ns['score_audit'](evil, {'cache_key': 'bk1', 'requirements':
                              [{'id': 'rX', 'type': 'speech', 'priority': 'medium'}]},
                       verbose=False)
h2 = ns['build_report_html']({'video_hash': 'vh1', 'path': ''}, evil, COMPILED, s2,
                             RECS, None, figs, None, ns['P7'])
check('markup in a label cannot inject script', '<script>alert(1)</script>' not in h2)
check('the escaped form is what appears', '&lt;script&gt;' in h2)
# The escaped text still CONTAINS the characters "onerror=alert" -- as inert
# text content. What must not survive is a TAG, so that is what to assert.
check('no img tag is formed', '<img' not in h2)
check('no attribute can break out of a quoted value', ' onerror="' not in h2)

a = ns['build_report_html']({'video_hash': 'vh1', 'path': ''}, RESULT, COMPILED,
                            score, RECS, rec, figs, None, ns['P7'])
b = ns['build_report_html']({'video_hash': 'vh1', 'path': ''}, RESULT, COMPILED,
                            score, RECS, rec, figs, None, ns['P7'])
check('the same artifact renders byte-identically', a == b, f'{len(a)} vs {len(b)}')

print()
print('=' * 76)
print('NO MODEL OUTPUT REACHES A NUMERIC FIELD')
print('=' * 76)
numeric = []
for k, v in (score.get('score') or {}).items():
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        numeric.append(k)
check('every numeric score field is arithmetic',
      score['provenance']['model_free'] is True, numeric)
check('recommendations carry no numeric score field',
      not any(isinstance(x, (int, float)) and not isinstance(x, bool)
              for r in rec['recommendations'] for k, x in r.items()
              if k not in ('at_seconds',)))

print()
bad_ = [l for l, g in R if not g]
print(f'{len(R) - len(bad_)}/{len(R)} checks pass')
print('ALL PASS' if not bad_ else 'FAILED:\n   ' + '\n   '.join(bad_))
