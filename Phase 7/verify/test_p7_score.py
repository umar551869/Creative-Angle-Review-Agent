"""§75 + §76 against hand-computed arithmetic.

Every expected number here was worked out on paper first. That is the point of
the headline exit criterion: if I cannot do the sum by hand, neither can a
creator manager, and the score is not defensible.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from p7_harness import load, make_ns                         # noqa: E402

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
TMP = Path(tempfile.mkdtemp())
ns = load(make_ns(TMP), 's75_config.py', 's76_score.py')
score_audit = ns['score_audit']
R = []


def check(label, cond, detail=''):
    R.append((label, bool(cond)))
    print(f'  {"PASS" if cond else "FAIL"}  {label}' + (f'   [{detail}]' if detail else ''))


def V(rid, status, priority='medium', flags=None, rtype='speech', label='', **kw):
    d = {'requirement_id': rid, 'status': status, 'priority': priority,
         'weight': ns['PRIORITY_WEIGHT'][priority], 'flags': flags or [],
         'requirement_label': label or rid, 'evidence_ids': ['ev_1'],
         'reason': 'because', 'layer': 'L1', 'alignment': None}
    d.update(kw)
    return d


def audit(verdicts, standing=None, vh='vh1', ck=None):
    return {'video_hash': vh, 'cache_key': ck or ('k_' + str(abs(hash(str(verdicts))) % 10 ** 8)),
            'brief_hash': 'bh1', 'duration_seconds': 30.0, 'verdicts': verdicts,
            'sources': {'evidence': 'ev_key'}, 'standing': standing or {},
            'hook': {}, 'claims': {'enabled': False}, 'stats': {}}


def brief(reqs):
    return {'cache_key': 'bk1', 'brief_hash': 'bh1', 'requirements': reqs}


def Rq(rid, rtype='speech', priority='medium', polarity='required'):
    return {'id': rid, 'type': rtype, 'priority': priority, 'polarity': polarity,
            'label': rid, 'weight': ns['PRIORITY_WEIGHT'][priority]}


print('=' * 76)
print('CONFIG INVARIANTS')
print('=' * 76)
check('every REQUIREMENT_TYPE maps to a dimension',
      not set(ns['REQUIREMENT_TYPES']) - set(ns['TYPE_TO_DIMENSION']))
check('dimension weights sum to 1.0', abs(sum(ns['DIMENSION_WEIGHT'].values()) - 1.0) < 1e-9)
check('UNCERTAIN has no score entry', 'UNCERTAIN' not in ns['STATUS_SCORE'])
check('NOT_APPLICABLE has no score entry', 'NOT_APPLICABLE' not in ns['STATUS_SCORE'])
check('PRIORITY_WEIGHT reused, not redefined',
      ns['PRIORITY_WEIGHT'] == {'critical': 3.0, 'high': 2.0, 'medium': 1.0, 'low': 0.5})

print()
print('=' * 76)
print('THE SUM, BY HAND')
print('=' * 76)
# 3 units: PASS(w1) + PARTIAL(w2) + FAIL(w3)
#   weights 1.0, 2.0, 3.0  -> total 6.0
#   earned  1.0*1.0 + 2.0*0.5 + 3.0*0.0 = 2.0
#   score   2.0/6.0 = 0.3333 -> 33
vs = [V('r1', 'PASS', 'medium'), V('r2', 'PARTIAL', 'high'),
      V('r3', 'FAIL', 'critical')]
s = score_audit(audit(vs), brief([Rq('r1'), Rq('r2'), Rq('r3', priority='critical')]),
                verbose=False)
check('weighted score = 2.0/6.0 = 33', s['score']['headline'] == 33, s['score']['headline'])
check('coverage 1.0 when nothing is UNCERTAIN', s['score']['coverage'] == 1.0)
check('pessimistic == optimistic at full coverage',
      s['score']['band_low'] == s['score']['band_high'])
check('a critical FAIL cannot be APPROVED',
      s['score']['status_band'] != 'APPROVED', s['score']['status_band'])

print()
print('=' * 76)
print('NOT_APPLICABLE LEAVES THE DENOMINATOR')
print('=' * 76)
# one_of group: 1 winner PASS + 11 losers NOT_APPLICABLE -> ONE unit, score 100
vs = [V('w', 'PASS')] + [V(f'l{i}', 'NOT_APPLICABLE') for i in range(11)]
s = score_audit(audit(vs), brief([Rq('w')] + [Rq(f'l{i}') for i in range(11)]),
                verbose=False)
check('a one_of group contributes exactly one unit', s['score']['scoring_units'] == 1,
      s['score']['scoring_units'])
check('11 losers do not drag the score to 8', s['score']['headline'] == 100,
      s['score']['headline'])
check('not_applicable counted separately', s['counts']['not_applicable'] == 11)

print()
print('=' * 76)
print('UNCERTAIN IS AN ABSTENTION, NOT A ZERO')
print('=' * 76)
# PASS(w1) + UNCERTAIN(w1):  pess = 1/2 = 50, opt = 1/1 = 100, coverage = 0.5
vs = [V('r1', 'PASS'), V('r2', 'UNCERTAIN')]
s = score_audit(audit(vs), brief([Rq('r1'), Rq('r2')]), verbose=False)
check('pessimistic 50 (UNCERTAIN as 0)', s['score']['band_low'] == 50, s['score']['band_low'])
check('optimistic 100 (UNCERTAIN excluded)', s['score']['band_high'] == 100,
      s['score']['band_high'])
check('coverage 0.5', s['score']['coverage'] == 0.5)
check('pessimistic <= optimistic', s['score']['band_low'] <= s['score']['band_high'])
check('leads with the band, not one number', s['score']['lead_with_band'] is True)

print()
print('=' * 76)
print('COMPLIANCE BY ABSENCE IS NOT ACHIEVEMENT')
print('=' * 76)
# the Phase 6 measurement: 2 vacuous passes + 1 real FAIL
vs = [V('f1', 'PASS', flags=['PASS_FROM_ABSENCE']),
      V('f2', 'PASS', flags=['PASS_FROM_ABSENCE']),
      V('r1', 'FAIL')]
s = score_audit(audit(vs), brief([Rq('f1', 'policy'), Rq('f2', 'policy'), Rq('r1')]),
                verbose=False)
check('vacuous passes excluded from achievement',
      s['score']['scoring_units'] == 1, s['score']['scoring_units'])
check('score is 0, not 67', s['score']['headline'] == 0, s['score']['headline'])
check('safety reported separately: 2 checks', s['safety']['checks'] == 2)
check('safety passes counted', s['safety']['passed_by_absence'] == 2)

print()
print('=' * 76)
print('DIMENSIONS NORMALISE OVER WHAT THE BRIEF COVERS')
print('=' * 76)
# brief covers hook + cta only: raw 0.20 + 0.10 = 0.30 -> normalised 0.667/0.333
vs = [V('h', 'PASS'), V('c', 'FAIL')]
s = score_audit(audit(vs), brief([Rq('h', 'hook'), Rq('c', 'cta')]), verbose=False)
d = s['dimensions']
check('2 dimensions covered', s['dimensions_covered'] == ['hook', 'cta'],
      s['dimensions_covered'])
check('5 dimensions absent and named', len(s['dimensions_absent']) == 5)
check('hook normalises to 0.667', abs(d['hook']['weight_normalised'] - 0.6667) < 0.001,
      d['hook']['weight_normalised'])
check('cta normalises to 0.333', abs(d['cta']['weight_normalised'] - 0.3333) < 0.001)
check('normalised weights of covered dims sum to 1',
      abs(sum(d[k]['weight_normalised'] for k in s['dimensions_covered']) - 1.0) < 0.001)
check('an absent dimension scores None, not 0',
      d['audience']['score'] is None and d['audience']['covered'] is False)
check('a one-unit dimension is marked thin', d['hook']['thin'] is True)

print()
print('=' * 76)
print('EMPTY AND DEGENERATE INPUT')
print('=' * 76)
s = score_audit(audit([]), brief([]), verbose=False)
check('no verdicts does not divide by zero', s['score']['headline'] is None)
check('no verdicts gives coverage 0, not score 0', s['score']['coverage'] == 0.0)
s = score_audit(audit([V('x', 'NOT_APPLICABLE')]), brief([Rq('x')]), verbose=False)
check('all NOT_APPLICABLE yields no score', s['score']['headline'] is None)

print()
print('=' * 76)
print('BAND BOUNDARIES, BOTH SIDES')
print('=' * 76)
for val, want in ((85.0, 'APPROVED'), (84.9, 'NEEDS_MINOR_REVISION'),
                  (70.0, 'NEEDS_MINOR_REVISION'), (69.9, 'NEEDS_MAJOR_REVISION'),
                  (50.0, 'NEEDS_MAJOR_REVISION'), (49.9, 'REJECTED'),
                  (0.0, 'REJECTED'), (100.0, 'APPROVED')):
    check(f'{val} -> {want}', ns['band_for'](val) == want, ns['band_for'](val))

print()
print('=' * 76)
print('CONTRADICTIONS (the qualitative gate)')
print('=' * 76)
vs = [V('r1', 'PASS', label='Mention the 27% hair loss statistic')]
st = {'standing': 'off_brief', 'weight': 0.0, 'verdict': 'Different product entirely.',
      'missing': ['Mention the 27% hair loss statistic'], 'evidence_ids': ['ev_9']}
s = score_audit(audit(vs, standing=st), brief([Rq('r1')]), verbose=False)
codes = [c['code'] for c in s['contradictions']]
check('standing off_brief vs a 100 score fires', 'STANDING_CONTRADICTS_SCORE' in codes, codes)
check('PASS vs standing-missing fires', 'PASS_BUT_STANDING_CALLS_IT_MISSING' in codes)
vs = [V('p1', 'FAIL', flags=['PASS_FROM_ABSENCE'])]
s = score_audit(audit(vs), brief([Rq('p1', 'policy', polarity='forbidden')]), verbose=False)
check('a failed safety check fires',
      'SAFETY_CHECK_FAILED' in [c['code'] for c in s['contradictions']])
st = {'standing': 'on_brief', 'weight': 0.85, 'verdict': 'Good.', 'missing': []}
s = score_audit(audit([V('r1', 'PASS')], standing=st), brief([Rq('r1')]), verbose=False)
check('a healthy audit fires nothing', s['contradictions'] == [], s['contradictions'])

print()
print('=' * 76)
print('DETERMINISM AND PURITY')
print('=' * 76)
a = audit([V('r1', 'PASS'), V('r2', 'FAIL')], ck='fixed_key')
b = brief([Rq('r1'), Rq('r2')])
s1 = score_audit(a, b, verbose=False)
s2 = score_audit(a, b, force=True, verbose=False)
for k in ('provenance',):
    s1.pop(k, None)
    s2.pop(k, None)
check('same artifact scored twice is identical',
      ns['canonical_json'](s1) == ns['canonical_json'](s2))
check('score artifact names the verdict it scored',
      s1['scored_from']['verdicts_cache_key'] == 'fixed_key')
check('provenance records model_free',
      score_audit(a, b, force=True, verbose=False)['provenance']['model_free'] is True)
check('the constants travel with the artifact',
      score_audit(a, b, force=True, verbose=False)['provenance']['status_score']
      == {'PASS': 1.0, 'PARTIAL': 0.5, 'FAIL': 0.0})
check('thresholds flagged as placeholders',
      s1['score']['thresholds_are_placeholders'] is True)

print()
bad = [l for l, g in R if not g]
print(f'{len(R) - len(bad)}/{len(R)} checks pass')
print('ALL PASS' if not bad else 'FAILED:\n   ' + '\n   '.join(bad))
