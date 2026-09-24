"""The alignment figures, rendered for real with Plotly present.

Everything before this ran with Plotly missing, which only ever exercised the
degradation path. A figure that has never been drawn is a figure that will
fail in front of the user.
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


class Rec:
    def __init__(self, i, mod, t0, t1, text='', desc=''):
        self.id, self.modality = i, mod
        self.start_seconds, self.end_seconds = t0, t1
        self.raw_text, self.description = text, desc


RECS = [Rec('ev_1', 'speech', 0.5, 3.0, 'Blow drying ruined my hair.'),
        Rec('ev_2', 'speech', 11.0, 14.0, 'I take these every day.'),
        Rec('ev_3', 'ocr', 28.0, 30.0, 'LINK IN BIO'),
        Rec('ev_4', 'visual', 6.0, 9.0, desc='She holds the white jar.')]


def V(rid, status, alignment, priority='medium', label='', ev=None, flags=None):
    return {'requirement_id': rid, 'status': status, 'priority': priority,
            'weight': 1.0, 'flags': flags or [], 'requirement_label': label or rid,
            'evidence_ids': ev or ['ev_1'], 'reason': 'a reason', 'layer': 'L3',
            'alignment': alignment, 'alignment_reason': 'because of the wording',
            'examined_ids': []}


VERDICTS = [
    V('r1', 'PASS', 'exact', label='Open with a relatable hook', ev=['ev_1']),
    V('r2', 'FAIL', 'none', 'critical', label='Name Ceramosides Oil', ev=['ev_2']),
    V('r3', 'PARTIAL', 'partial', label='Show the product clearly', ev=['ev_4']),
    V('r4', 'PASS', 'strong', label='Deliver a call to action', ev=['ev_3']),
    V('r5', 'UNCERTAIN', 'tangential', label='Mention the discount', ev=['ev_3']),
    # no alignment at all -- nobody judged it
    V('r6', 'PASS', None, 'high', label='No medical claims', ev=[],
      flags=['PASS_FROM_ABSENCE']),
    # judged, but its only citation is an id no record carries a time for
    V('r7', 'PASS', 'strong', label='Keep it under 60 seconds',
      ev=['ev_no_such_record']),
    V('r8', 'NOT_APPLICABLE', None, label='Hook option B'),
]
REQS = [{'id': 'r1', 'type': 'hook', 'priority': 'medium', 'polarity': 'required'},
        {'id': 'r2', 'type': 'speech', 'priority': 'critical', 'polarity': 'required'},
        {'id': 'r3', 'type': 'visual', 'priority': 'medium', 'polarity': 'required'},
        {'id': 'r4', 'type': 'cta', 'priority': 'medium', 'polarity': 'required'},
        {'id': 'r5', 'type': 'cta', 'priority': 'medium', 'polarity': 'required'},
        {'id': 'r6', 'type': 'policy', 'priority': 'high', 'polarity': 'forbidden'},
        {'id': 'r7', 'type': 'timing', 'priority': 'medium', 'polarity': 'required'},
        {'id': 'r8', 'type': 'hook', 'priority': 'medium', 'polarity': 'required'}]
RESULT = {'video_hash': 'vh1', 'video_id': 'vid1', 'cache_key': 'vk1',
          'brief_hash': 'bh1', 'duration_seconds': 30.8, 'verdicts': VERDICTS,
          'sources': {}, 'standing': {'standing': 'on_brief', 'weight': 0.85},
          'hook': {}, 'claims': {'enabled': False}}
COMPILED = {'cache_key': 'bk1', 'brief_hash': 'bh1', 'requirements': REQS,
            'approved': True}

ns = make_ns(Path(tempfile.mkdtemp()))
ns.update({'re': re, 'subprocess': subprocess, 'base64': base64, 'Path': Path,
           'replace': lambda o, **k: o,
           'P4': type('x', (), {'brief': type('y', (), {'temperature': 0.0,
                                                        'max_new_tokens': 1600})()})(),
           'P6': type('x', (), {'l3': type('y', (), {'enabled': True})()})(),
           'parse_model_json': lambda t: (json.loads(t), None, 'direct'),
           'make_brief_backend': lambda *a, **k: None})
ns = load(ns, 's75_config.py', 's76_score.py', 's78_recommend.py',
          's79_report.py', 's79b_figures.py')

print('=' * 78)
print('PLOTLY IS PRESENT -- the figures actually draw')
print('=' * 78)
# plotly is deliberately NOT in Backend/requirements.txt: the report embeds a
# ~4.8 MB bundle when it is present, and "a missing chart library cannot block
# the score" is a design rule (§6). Every check below this line is about what
# plotly DRAWS, so without it there is nothing to assert -- and asserting
# anyway crashed on an empty figure list, which reads as a regression when it
# is really an absent optional dependency. Skip, loudly.
if not ns['PLOTLY_OK']:
    print(f'  SKIPPED -- plotly is not installed here ({ns["PLOTLY_ERR"]}).')
    print('  This suite only tests what plotly draws. The report itself is')
    print('  covered without it by test_p7_report.py, which branches on')
    print('  figs["plotly_available"]. Install plotly to run these checks.')
    raise SystemExit(0)

check('plotly imported by the cell', ns['PLOTLY_OK'] is True, ns['PLOTLY_ERR'])

score = ns['score_audit'](RESULT, COMPILED, verbose=False)
figs = ns['build_figures'](score, RESULT, RECS, [score], ns['P7'])
ids = [f['id'] for f in figs['figures']]
print(f'  drawn: {ids}')
print(f'  notes: {figs["notes"]}')

check('the alignment landscape drew', 'fig-alignment-landscape' in ids)
check('the alignment shape drew', 'fig-alignment-shape' in ids)
check('it leads the report', ids[0] == 'fig-alignment-landscape', ids[:1])
check('the existing figures still draw',
      'fig-dimension-time' in ids and 'fig-ask-delivery' in ids)

land = next(f for f in figs['figures'] if f['id'] == 'fig-alignment-landscape')
h = land['html']
print()
print('=' * 78)
print('WHAT THE LANDSCAPE ACTUALLY CONTAINS')
print('=' * 78)
check('every judged alignment level appears as its own trace',
      all(f'"name":"{lvl}' in h.replace(' ', '') or f"'{lvl} (" in h
          for lvl in ('exact', 'strong', 'partial', 'tangential', 'none')),
      [lvl for lvl in ('exact', 'strong', 'partial', 'tangential', 'none')
       if lvl not in h])
check('the unjudged unit is drawn apart, not as a zero', 'not judged' in h)
check('a judged unit with no timestamp is kept and named', 'no timestamp' in h)
check('NOT_APPLICABLE is not plotted', 'Hook option B' not in h)
check('requirement labels reach the axis', 'Name Ceramosides Oil' in h)
check('hover carries the evidence ids', 'customdata' in h and 'cites' in h)
check('hover carries the alignment reason', 'because of the wording' in h)
check('the z axis is labelled in words, not numbers',
      'tangential' in h and 'exact' in h and 'not judged' in h)
check('the div id is explicit (determinism)', 'fig-alignment-landscape' in h)
check('plotly.js is embedded in the first figure only',
      h.count('Plotly.newPlot') >= 1 and len(h) > 500_000,
      f'{len(h) / 1e6:.2f} MB')
shape = next(f for f in figs['figures'] if f['id'] == 'fig-alignment-shape')
check('the second figure does NOT re-embed plotly.js',
      len(shape['html']) < 200_000, f'{len(shape["html"]) / 1024:.0f} KB')

print()
print('=' * 78)
print('DETERMINISM -- the §81 criterion')
print('=' * 78)
f2 = ns['build_figures'](score, RESULT, RECS, [score], ns['P7'])
check('the same artifact draws byte-identical figures',
      [f['html'] for f in figs['figures']] == [f['html'] for f in f2['figures']])
html1 = ns['build_report_html']({'video_hash': 'vh1', 'path': ''}, RESULT,
                                COMPILED, score, RECS, None, figs, None, ns['P7'])
html2 = ns['build_report_html']({'video_hash': 'vh1', 'path': ''}, RESULT,
                                COMPILED, score, RECS, None, f2, None, ns['P7'])
check('the whole page is byte-identical with figures embedded', html1 == html2,
      f'{len(html1) / 1e6:.2f} MB')
# Grep the TAGS. "cdn.plot" is a topojsonURL default string inside the
# embedded bundle, for map types this report never draws -- searching for the
# substring would fail exactly when the feature is working.
_ext = re.findall(r'<(?:script|link|img|iframe)[^>]*\s(?:src|href)="'
                  r'(?:https?:)?//[^"]{0,60}', html1)
check('the report fetches nothing from the network', not _ext, str(_ext[:2]))
check('plotly.js is inline, not linked',
      'Plotly.newPlot' in html1 and 'plotly-latest' not in html1)

print()
print('=' * 78)
print('THE embed_plotly FLAG DOES SOMETHING')
print('=' * 78)
_cfg_off = ns['Phase7Config'](report=ns['ReportConfig'](embed_plotly=False))
f_off = ns['build_figures'](score, RESULT, RECS, [score], _cfg_off)
check('embed_plotly=False draws no figures', f_off['figures'] == [])
check('and says why, naming the size it saves',
      any('embed_plotly' in n and 'MB' in n for n in f_off['notes']),
      f_off['notes'][:1])
check('it does NOT fall back to a CDN',
      not any('cdn' in n.lower() and 'use' in n.lower() for n in f_off['notes']))
_h_off = ns['build_report_html']({'video_hash': 'vh1', 'path': ''}, RESULT,
                                 COMPILED, score, RECS, None, f_off, None,
                                 _cfg_off)
check('the report without figures is small', len(_h_off) < 100_000,
      f'{len(_h_off) / 1024:.0f} KB vs {len(html1) / 1e6:.1f} MB with them')

print()
print('=' * 78)
print('DEGENERATE INPUT')
print('=' * 78)
noalign = dict(RESULT)
noalign['cache_key'] = 'vk_noalign'
noalign['verdicts'] = [V('r1', 'PASS', None, label='x', ev=['ev_1'])]
s2 = ns['score_audit'](noalign, COMPILED, verbose=False)
f3 = ns['build_figures'](s2, noalign, RECS, [], ns['P7'])
check('no alignment anywhere -> skipped with a reason, not a crash',
      'fig-alignment-landscape' not in [f['id'] for f in f3['figures']]
      and any('alignment' in n for n in f3['notes']), f3['notes'][:1])
onedim = dict(RESULT)
onedim['cache_key'] = 'vk_onedim'
onedim['verdicts'] = [V('r1', 'PASS', 'exact', label='a', ev=['ev_1']),
                      V('r8', 'PASS', 'strong', label='b', ev=['ev_1'])]
s3 = ns['score_audit'](onedim, {'cache_key': 'bk1', 'requirements': [
    {'id': 'r1', 'type': 'hook', 'priority': 'medium'},
    {'id': 'r8', 'type': 'hook', 'priority': 'medium'}]}, verbose=False)
f4 = ns['build_figures'](s3, onedim, RECS, [], ns['P7'])
check('one dimension -> the surface is skipped, the landscape still draws',
      'fig-alignment-landscape' in [f['id'] for f in f4['figures']]
      and 'fig-alignment-shape' not in [f['id'] for f in f4['figures']])
check('and it says why', any('at least two' in n for n in f4['notes']),
      [n for n in f4['notes'] if 'least two' in n][:1])

gated = dict(RESULT)
gated['cache_key'] = 'vk_gated'
gated['standing'] = {'standing': 'off_brief', 'weight': 0.0, 'verdict': 'Other.'}
s5 = ns['score_audit'](gated, COMPILED, verbose=False)
f5 = ns['build_figures'](s5, gated, RECS, [], ns['P7'])
check('an off-brief audit STILL draws the alignment figures',
      'fig-alignment-landscape' in [f['id'] for f in f5['figures']],
      'they are the evidence FOR the gate')

print()
bad = [l for l, g in R if not g]
print(f'{len(R) - len(bad)}/{len(R)} checks pass')
print('ALL PASS' if not bad else 'FAILED:\n   ' + '\n   '.join(bad))
