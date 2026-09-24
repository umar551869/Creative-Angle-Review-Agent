"""Deep cross-check: the things that break on a fresh Colab kernel.

The shallow checks (JSON, parse, order) already pass. These target the class
of bug that survives all of them:

  * Phase 7 calling a Phase 1-6 function with the wrong arguments
  * Phase 7 redefining a name Phase 1-6 relies on
  * Phase 7 mutating a Phase 1-6 global
  * a driver cell that explodes instead of explaining when its input is absent
  * a cell that only works because an earlier cell left a variable lying around
"""
import ast
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
# The batch notebook is a generated COPY of this one, so it gets exactly the
# same scrutiny: pass a path to check that instead of the default.
NB = (Path(sys.argv[1]) if len(sys.argv) > 1
      else Path(r'C:\Users\Umar Ilyas\creative project\Phase 7'
                r'\phases_1_to_7_gemini_vision.ipynb'))
R = []


def ck(label, ok, detail=''):
    R.append((label, bool(ok), detail))
    print(f'  {"PASS" if ok else "FAIL"}  {label}' + (f'   {detail}' if detail else ''))


cells = json.loads(NB.read_text(encoding='utf-8'))['cells']
code = [(i, ''.join(c['source'])) for i, c in enumerate(cells)
        if c['cell_type'] == 'code']
trees = {}
for i, s in code:
    try:
        trees[i] = ast.parse(s)
    except SyntaxError:
        pass

# Phase 7 begins at the first cell carrying a bridge/Phase-7 section marker.
p7_start = min(i for i, s in code
               if re.search(r'^# §(74a|74b|75|75b|76|77|78|79|79b|80|81|82)\b',
                            s, re.M))
OLD = [(i, s) for i, s in code if i < p7_start]
NEW = [(i, s) for i, s in code if i >= p7_start]
print(f'  Phases 1-6: cells 0..{p7_start - 1} ({len(OLD)} code cells)')
print(f'  Phase 7   : cells {p7_start}..  ({len(NEW)} code cells)')

print()
print('=' * 78)
print('A  CROSS-PHASE CALLS  --  does Phase 7 call Phase 1-6 correctly?')
print('=' * 78)


def signatures(pairs):
    sigs = {}
    for _i, s in pairs:
        t = trees.get(_i)
        if t is None:
            continue
        for n in ast.walk(t):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = n.args
                pos = [x.arg for x in a.posonlyargs + a.args]
                sigs[n.name] = {
                    'pos': pos,
                    'kwonly': [x.arg for x in a.kwonlyargs],
                    'defaults': len(a.defaults),
                    'vararg': a.vararg is not None,
                    'kwarg': a.kwarg is not None,
                    'cell': _i,
                }
    return sigs


old_sigs = signatures(OLD)
new_sigs = signatures(NEW)
problems = []
checked = 0
for i, s in NEW:
    t = trees.get(i)
    if t is None:
        continue
    # Calls written inside a def in the SAME cell can still target an older
    # function, so walk everything.
    for n in ast.walk(t):
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Name):
            continue
        sig = old_sigs.get(n.func.id)
        if sig is None:
            continue
        checked += 1
        npos = len([a for a in n.args if not isinstance(a, ast.Starred)])
        starred = any(isinstance(a, ast.Starred) for a in n.args)
        kws = [k.arg for k in n.keywords if k.arg]
        dstar = any(k.arg is None for k in n.keywords)
        required = len(sig['pos']) - sig['defaults']
        if not starred and not sig['vararg'] and npos > len(sig['pos']):
            problems.append((i, n.func.id, f'{npos} positional args, '
                                           f'signature takes {len(sig["pos"])}'))
        if not dstar and not sig['kwarg']:
            bad_kw = [k for k in kws if k not in sig['pos'] + sig['kwonly']]
            if bad_kw:
                problems.append((i, n.func.id, f'unknown keyword(s) {bad_kw}'))
        if not starred and not dstar:
            supplied = npos + len([k for k in kws if k in sig['pos']])
            if supplied < required:
                problems.append((i, n.func.id,
                                 f'{supplied} arg(s) supplied, {required} required'))
ck(f'every Phase 7 call into Phases 1-6 matches its signature ({checked} calls)',
   not problems, str(problems[:4]))

# And the reverse: Phase 7 calling its own functions correctly.
prob2, checked2 = [], 0
for i, s in NEW:
    t = trees.get(i)
    if t is None:
        continue
    for n in ast.walk(t):
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Name):
            continue
        sig = new_sigs.get(n.func.id)
        if sig is None:
            continue
        checked2 += 1
        npos = len([a for a in n.args if not isinstance(a, ast.Starred)])
        if any(isinstance(a, ast.Starred) for a in n.args) or sig['vararg']:
            continue
        kws = [k.arg for k in n.keywords if k.arg]
        if npos > len(sig['pos']):
            prob2.append((i, n.func.id, f'{npos} > {len(sig["pos"])}'))
        if not sig['kwarg'] and not any(k.arg is None for k in n.keywords):
            bad = [k for k in kws if k not in sig['pos'] + sig['kwonly']]
            if bad:
                prob2.append((i, n.func.id, f'unknown kw {bad}'))
        req = len(sig['pos']) - sig['defaults']
        if npos + len([k for k in kws if k in sig['pos']]) < req \
                and not any(k.arg is None for k in n.keywords):
            prob2.append((i, n.func.id, 'too few args'))
ck(f'every Phase 7 internal call matches its signature ({checked2} calls)',
   not prob2, str(prob2[:4]))

print()
print('=' * 78)
print('B  NAME COLLISIONS  --  does Phase 7 shadow Phases 1-6?')
print('=' * 78)


def toplevel_defs(pairs):
    out = {}
    for _i, s in pairs:
        t = trees.get(_i)
        if t is None:
            continue
        for n in t.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.setdefault(n.name, _i)
            elif isinstance(n, ast.Assign):
                for tgt in n.targets:
                    for nn in ast.walk(tgt):
                        if isinstance(nn, ast.Name):
                            out.setdefault(nn.id, _i)
    return out


old_top, new_top = toplevel_defs(OLD), toplevel_defs(NEW)
# Loop/throwaway names starting with _ are local convention and harmless.
collisions = {k: (old_top[k], new_top[k]) for k in new_top
              if k in old_top and not k.startswith('_')}
ck('Phase 7 redefines no Phase 1-6 name', not collisions,
   str(sorted(collisions.items())[:5]))

print()
print('=' * 78)
print('C  MUTATION  --  does Phase 7 change Phase 1-6 state?')
print('=' * 78)
FROZEN = {'P6', 'P4', 'P5', 'DIRS', 'PIPELINE_VERSION', 'PRIORITY_WEIGHT',
          'REQUIREMENT_TYPES', 'VERDICT_STATUSES', 'ALIGNMENT_WEIGHTS',
          'BRIEF_STANDING_WEIGHTS', 'EVAL_LAYERS', 'ALIGNMENT_LEVELS',
          'JUDGMENT_WORDS', 'TARGET', 'result', 'evidence', 'compiled'}
mutations = []
for i, s in NEW:
    t = trees.get(i)
    if t is None:
        continue
    for n in ast.walk(t):
        tgts = []
        if isinstance(n, ast.Assign):
            tgts = n.targets
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
            tgts = [n.target]
        for tgt in tgts:
            if isinstance(tgt, ast.Name) and tgt.id in FROZEN:
                mutations.append((i, tgt.id, 'rebound'))
            if isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name) \
                    and tgt.value.id in FROZEN:
                # ONE exemption, and it is the opposite of the hazard this
                # rule exists for: §77 redirects DIRS['artifacts'] at a temp
                # directory so its fixtures cannot collide with real artifacts
                # or with a previous run of itself, and restores it in
                # `finally`. A test that sandboxes its own I/O is not leaking
                # state, it is refusing to.
                if '_run_phase7_tests' in s and 'finally:' in s:
                    continue
                mutations.append((i, tgt.value.id, 'item assigned'))
            if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) \
                    and tgt.value.id in FROZEN:
                mutations.append((i, tgt.value.id, 'attribute set'))
ck('Phase 7 never rebinds or mutates a Phase 1-6 global', not mutations,
   str(mutations[:5]))

# .append/.update/.pop on a frozen global
calls = []
for i, s in NEW:
    for m in re.finditer(r'\b(' + '|'.join(sorted(FROZEN)) + r')\.'
                         r'(append|extend|update|pop|clear|setdefault|insert)\(',
                         s):
        calls.append((i, m.group(0)))
ck('Phase 7 never mutates a Phase 1-6 container in place', not calls,
   str(calls[:4]))

print()
print('=' * 78)
print('D  DRIVER CELLS  --  do they explain, or explode?')
print('=' * 78)
drivers = {}
for i, s in NEW:
    m = re.search(r'^# §(\d+\w*)\b', s, re.M)
    if m:
        drivers[m.group(1)] = (i, s)
for sec, needs in (('80', ('result', '_p6_brief')),
                   ('81', ('score',)),
                   ('82', ('score',))):
    if sec not in drivers:
        ck(f'§{sec} present', False)
        continue
    _i, s = drivers[sec]
    guarded = any(f"'{n}' not in globals()" in s or f"'{n}' in globals()" in s
                  or f"globals().get('{n}')" in s for n in needs)
    ck(f'§{sec} guards on its input instead of raising NameError', guarded,
       f'needs {needs}')

# Every Phase 7 cell must be runnable top-to-bottom without a try/except
# swallowing a real error silently.
bare = []
for i, s in NEW:
    for m in re.finditer(r'except\s+Exception[^:]*:\s*\n\s*(pass|continue)\s*$',
                         s, re.M):
        bare.append((i, m.group(0).split('\n')[0]))
ck('no Phase 7 handler swallows an exception silently', not bare, str(bare[:3]))

print()
print('=' * 78)
print('E  ARTIFACT SHAPE vs STAGE VERSION  (they must move together)')
print('=' * 78)
# Defined here rather than in the later section, which used to be the first
# place it appeared -- this section now needs it first.
P7SRC = ''.join(s for _i, s in NEW)
# The score cache key is built from SCORE_STAGE_VERSION, not from the
# artifact's shape. Change the output without bumping the version and §80
# keeps returning a score computed by older code -- silently, while the tests
# pass. That happened twice: `band_basis` and `inferred_units` both landed
# unbumped, and the next run reported APPROVED from a cached artifact.
#
# So the shape is recorded HERE, beside the version it belongs to. Changing
# either without the other fails this check.
SCORE_SHAPE = {
    # 1.5.0: the brief's feature bullets collapse to ONE coverage unit
    # (_collapse_talking_points), and how they collapsed is recorded so the
    # unit that stands for eight can be recomputed by hand.
    '1.6.0': {
        'score': {'headline', 'band_low', 'band_high', 'gated', 'gate_reason',
                  'lead_with_band', 'coverage', 'status_band', 'band_basis',
                  'critical_floor_applied', 'critical_fail_ids',
                  'scoring_units', 'decided_units', 'total_weight',
                  'thresholds_are_placeholders', 'talking_points',
                  'literal_headline', 'literal_band_low',
                  'credited_in_substance', 'credited_requirement_ids',
                  'not_in_brief_excluded', 'not_in_brief_ids'},
        'dimension': {'label', 'covered', 'weight_raw', 'weight_normalised',
                      'units', 'thin', 'inferred_units', 'score',
                      'score_pessimistic', 'coverage', 'requirement_ids'},
    },
    '1.4.0': {
        'score': {'headline', 'band_low', 'band_high', 'gated', 'gate_reason',
                  'lead_with_band', 'coverage', 'status_band', 'band_basis',
                  'critical_floor_applied', 'critical_fail_ids',
                  'scoring_units', 'decided_units', 'total_weight',
                  'thresholds_are_placeholders',
                  # 1.2.0: the strict reading travels with the credited one
                  'literal_headline', 'literal_band_low',
                  'credited_in_substance', 'credited_requirement_ids',
                  # 1.3.0: untraceable requirements leave the denominator
                  'not_in_brief_excluded', 'not_in_brief_ids'},
        'dimension': {'label', 'covered', 'weight_raw', 'weight_normalised',
                      'units', 'thin', 'inferred_units', 'score',
                      'score_pessimistic', 'coverage', 'requirement_ids'},
    },
}
_ver = re.search(r"SCORE_STAGE_VERSION = '([\d.]+)'", P7SRC)
_v = _ver.group(1) if _ver else '?'
ck('SCORE_STAGE_VERSION is one this check knows the shape of',
   _v in SCORE_SHAPE,
   f'{_v} -- if you changed the artifact, add its shape to SCORE_SHAPE')
if _v in SCORE_SHAPE:
    _s76 = next((s for _i, s in NEW if 'def score_audit' in s), '')
    _blk = re.search(r"'score': \{(.*?)\n        \},", _s76, re.S)
    _got = set(re.findall(r"'(\w+)':", _blk.group(1))) if _blk else set()
    _want = SCORE_SHAPE[_v]['score']
    ck(f'the score block matches the shape recorded for {_v}',
       _got == _want,
       f'added {sorted(_got - _want)} missing {sorted(_want - _got)}')
    _dblk = re.search(r"out\[k\] = \{(.*?)\n        \}", _s76, re.S)
    _dgot = set(re.findall(r"'(\w+)':", _dblk.group(1))) if _dblk else set()
    _dwant = SCORE_SHAPE[_v]['dimension']
    ck(f'the dimension block matches the shape recorded for {_v}',
       _dgot == _dwant,
       f'added {sorted(_dgot - _dwant)} missing {sorted(_dwant - _dgot)}')

print()
print('=' * 78)
print('F  COST AND SAFETY DEFAULTS')
print('=' * 78)
P7SRC = ''.join(s for _i, s in NEW)
ck('control audits are OFF by default',
   re.search(r'^RUN_CONTROL_AUDITS = False', P7SRC, re.M) is not None)
ck('control audits are capped',
   re.search(r'^MAX_CONTROL_AUDITS = \d+', P7SRC, re.M) is not None)
ck('rescoring is OFF by default',
   re.search(r'^RESCORE = False', P7SRC, re.M) is not None)
_model_calls = len(re.findall(r'\.complete\(', P7SRC))
ck('Phase 7 makes exactly one kind of model call', _model_calls == 1,
   f'{_model_calls} call site(s)')
ck('the one model call is in §78',
   'RECOMMEND_SYSTEM' in P7SRC and
   P7SRC.index('.complete(') > P7SRC.index('RECOMMEND_SYSTEM'))
ck('the recommender abstains before spending on an off-brief video',
   'RECOMMEND_GATED_OFF_BRIEF' in P7SRC
   and P7SRC.index('RECOMMEND_GATED_OFF_BRIEF') < P7SRC.index('.complete('))

print()
print('=' * 78)
print('F  THE GATE, END TO END')
print('=' * 78)
ck('the gate is defined once', len(re.findall(r'^def relevance_of', P7SRC, re.M)) == 1)
ck('it fails open', 'RELEVANCE_FAIL_OPEN = True' in P7SRC)
ck('gated audits get their own band', "BAND_OFF_BRIEF = 'OFF_BRIEF'" in P7SRC)
ck('the score still records the full arithmetic when gated',
   "'gated': not relevance['scorable']" in P7SRC)
ck('the report suppresses the headline when gated',
   "if s.get('gated'):" in P7SRC)
ck('the report suppresses the dimension bars when gated',
   "if (score.get('score') or {}).get('gated'):" in P7SRC)
ck('alignment figures are NOT suppressed by the gate',
   'evidence FOR the gate' in P7SRC)

print()
print('=' * 78)
print('G  SUBMODULE IMPORTS  --  the AttributeError that waits for a clean kernel')
print('=' * 78)
# `import importlib` does NOT bind importlib.util; `import os` does not bind
# os.path's siblings either. The attribute usually resolves because some other
# library imported the submodule first, so this only fails on a clean kernel --
# which is exactly where a user starts.
SUBMODULE_TRAPS = {
    'importlib': ('util', 'metadata', 'resources', 'machinery'),
    'concurrent': ('futures',),
    'xml': ('etree', 'dom', 'sax'),
    'email': ('mime', 'parser'),
    'logging': ('handlers', 'config'),
    'multiprocessing': ('pool', 'shared_memory'),
    'urllib': ('request', 'parse', 'error'),
}
trap_hits = []
ALL = [(i, s) for i, s in code]
for i, s in ALL:
    t = trees.get(i)
    if t is None:
        continue
    bare, deep = set(), set()
    for n in ast.walk(t):
        if isinstance(n, ast.Import):
            for a in n.names:
                if '.' in a.name:
                    deep.add(a.name)
                else:
                    bare.add(a.name)
        elif isinstance(n, ast.ImportFrom) and n.module:
            deep.add(n.module)
    for pkg, subs in SUBMODULE_TRAPS.items():
        for sub in subs:
            if re.search(rf'(?<!\w){pkg}\.{sub}\b', s):
                if f'{pkg}.{sub}' in deep:
                    continue
                if any(d == f'{pkg}.{sub}' or d.startswith(f'{pkg}.{sub}.')
                       for d in deep):
                    continue
                trap_hits.append((i, f'{pkg}.{sub} used; '
                                     f'"import {pkg}.{sub}" not in this cell'))
ck('no submodule is used without being imported', not trap_hits,
   str(trap_hits[:4]))

print()
print('=' * 78)
print("H  read_json  --  it RAISES on a missing file, it does not return None")
print('=' * 78)
# The notebook's read_json is `with open(path) as fh: return json.load(fh)`.
# A missing file is a FileNotFoundError, not a None -- so `read_json(p) or {}`
# is not a safe default, it is a crash with a fallback attached. Reading a
# path that came out of .glob() is fine (glob only yields what exists);
# anything else needs an .exists() guard or a try.
unguarded = []
for i, s in ALL:
    t = trees.get(i)
    if t is None:
        continue
    for fn in [n for n in ast.walk(t)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))] + [t]:
        src_seg = ast.get_source_segment(s, fn) if fn is not t else s
        src_seg = src_seg or s
        # Names bound by iterating a glob, or taken from one.
        from_glob = set()
        for n in ast.walk(fn):
            if isinstance(n, (ast.For, ast.comprehension)):
                it = ast.dump(n.iter)
                if 'glob' in it or 'iterdir' in it or 'rglob' in it:
                    for nn in ast.walk(n.target):
                        if isinstance(nn, ast.Name):
                            from_glob.add(nn.id)
            if isinstance(n, ast.Assign) and 'glob' in ast.dump(n.value):
                for tg in n.targets:
                    for nn in ast.walk(tg):
                        if isinstance(nn, ast.Name):
                            from_glob.add(nn.id)
        guarded = ('.exists()' in src_seg or 'try:' in src_seg)
        for n in ast.walk(fn):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == 'read_json' and n.args):
                continue
            a = n.args[0]
            # read_json(x) where x came from a glob, or is an index/max of one
            dumped = ast.dump(a)
            if isinstance(a, ast.Name) and a.id in from_glob:
                continue
            if any(g in dumped for g in from_glob) or 'glob' in dumped:
                continue
            if guarded:
                continue
            unguarded.append((i, getattr(fn, 'name', '<module>'),
                              ast.unparse(a)[:40]))
# de-duplicate: the module-level pass re-walks every function
unguarded = sorted(set(unguarded))
p7_bad = [u for u in unguarded if u[0] >= p7_start]
p6_bad = [u for u in unguarded if u[0] < p7_start]
ck('every read_json in Phase 7 is glob-sourced or guarded', not p7_bad,
   str(p7_bad[:4]))
# Phases 1-6 read TARGET['manifest_path'] unguarded in four places. Those are
# safe in the normal flow -- Phase 1 writes that file immediately before -- and
# those cells are byte-identical to the notebook that has been run end to end.
# Reported, not failed: changing validated code to satisfy a static check I
# wrote would be the tail wagging the dog.
print(f'     (Phases 1-6 carry {len(p6_bad)} unguarded read_json call(s), all '
      f'on a path written moments earlier:')
for u in p6_bad[:4]:
    print(f'        cell {u[0]} {u[1]}: {u[2]}')
print('      pre-existing, and out of scope for this change.)')

print()
print('=' * 78)
print('I  WHAT COLAB WILL ACTUALLY SEE')
print('=' * 78)
ck('no absolute Windows path leaked into the notebook',
   not re.search(r'[A-Z]:\\\\Users', ''.join(s for _i, s in code)),
   'a local path would break every artifact read in Colab')
ck('no scratchpad or temp path leaked',
   'AppData\\\\Local\\\\Temp' not in ''.join(s for _i, s in code))
ck('Phase 7 writes only under DIRS',
   not re.search(r"(write_text|write_json|open)\(\s*['\"]/(?!content)", P7SRC))
_first = code[0][1]
ck('cell 0 is still the disarmed environment cell',
   'pip' in _first or 'constraint' in _first.lower(), _first.splitlines()[1][:60])

print()
print('=' * 78)
print('J  THE CACHE KEY  --  does the READER rebuild what the WRITER files?')
print('=' * 78)
# The bug this exists to catch, found 2026-09-22 on a live batch run:
# run_vision_stage puts the RESOLVED model in the visual cache key (added in
# VLM_STAGE_VERSION 1.11.0 so a Gemini artifact can never collide with a Qwen
# one) and _visual_keys, which rebuilds that key to decide which files Phase 5
# may accept, was never told. Every key it computed was missing a component, so
# it matched NOTHING on disk, for every video, on every run -- and the
# newest-file fallback quietly covered for it. Nothing failed. The warning read
# like a stale artifact when the artifact was current and the reader was wrong.
#
# No static check can see that: both sides are syntactically fine and neither
# mentions the other. So this one EXECUTES both key builders on a synthetic
# manifest and compares the hashes they produce.
_WANT = {'canonical_json', 'stage_key', 'resolve_vision_config', 'vision_ladder',
         'plan_vlm_load', 'scene_count_of', '_visual_keys', 'VisionConfig'}
_WANT_ASSIGN = {'PIPELINE_VERSION', 'VLM_STAGE_VERSION', 'PROMPT_VERSION',
                'P3_GPU_GB'}


def _seg(src, node):
    """Source of a node INCLUDING its decorators -- ast.get_source_segment
    drops them, which silently turns a frozen dataclass into a plain class."""
    lines = src.split('\n')
    start = min([node.lineno] + [d.lineno for d in
                                 getattr(node, 'decorator_list', [])])
    return '\n'.join(lines[start - 1:node.end_lineno])


def _key_agreement():
    import dataclasses
    import hashlib
    import math
    import tempfile
    import typing
    chunks = []
    for _i, _s in code:
        t = trees.get(_i)
        if t is None:
            continue
        for node in t.body:
            if (isinstance(node, (ast.FunctionDef, ast.ClassDef))
                    and node.name in _WANT):
                chunks.append(_seg(_s, node))
            elif isinstance(node, ast.Assign) and any(
                    isinstance(x, ast.Name) and x.id in _WANT_ASSIGN
                    for x in node.targets):
                chunks.append(_seg(_s, node))
    ns = {'json': json, 'hashlib': hashlib, 'math': math, 're': re,
          'dataclasses': dataclasses, 'Path': Path,
          'Optional': typing.Optional, 'Tuple': typing.Tuple,
          'List': typing.List, 'dataclass': dataclasses.dataclass,
          'field': dataclasses.field, 'asdict': dataclasses.asdict,
          'replace': dataclasses.replace,
          'read_json': lambda p: json.loads(Path(p).read_text('utf-8'))}
    for ch in chunks:
        try:
            exec(ch, ns)
        except Exception:
            pass                  # a helper we do not need for this check
    missing = [n for n in _WANT if n not in ns]
    if missing:
        return None, f'could not load {missing} out of the notebook'
    if not dataclasses.is_dataclass(ns['VisionConfig']):
        return None, 'VisionConfig lost its @dataclass decorator in extraction'

    d = Path(tempfile.mkdtemp()) / 'm.json'
    d.write_text(json.dumps({'media': {'duration_seconds': 84.0},
                             'scenes': {'cut_times': [1., 5., 9., 14., 22., 40.]}}),
                 encoding='utf-8')
    p3 = type('P3', (), {})()
    p3.vision = ns['VisionConfig']()
    ns['P3'] = p3
    vid = {'video_hash': '0257b2b59769929b', 'plan_hash': 'planhash123',
           'duration_s': 84.0, 'manifest_path': str(d)}

    reader = ns['_visual_keys'](vid, dict(ns), vid['video_hash'], vid['plan_hash'])

    # rebuilt exactly as run_vision_stage does it
    manifest = json.loads(d.read_text('utf-8'))
    vcfg = ns['resolve_vision_config'](p3.vision, 84.0,
                                       ns['scene_count_of'](manifest))
    planned = list((ns['plan_vlm_load'](vcfg) or [(None, None)])[0])
    writer = []
    for n, px in ns['vision_ladder'](vcfg):
        c = (vcfg if (n, px) == (vcfg.max_frames, vcfg.max_pixels)
             else dataclasses.replace(vcfg, max_frames=n, max_pixels=px))
        writer.append(ns['stage_key'](
            'visual', ns['VLM_STAGE_VERSION'],
            [vid['video_hash'], vid['plan_hash']],
            {'vision': dataclasses.asdict(c), 'prompt': ns['PROMPT_VERSION'],
             'vlm': planned}))
    return (writer, reader), f'{len(writer)} rung(s), provider={p3.vision.provider}'


try:
    _res, _detail = _key_agreement()
except Exception as _exc:
    _res, _detail = None, f'{type(_exc).__name__}: {str(_exc)[:90]}'
if _res is None:
    ck('_visual_keys rebuilds the key run_vision_stage writes', False, _detail)
else:
    _w, _r = _res
    ck('_visual_keys rebuilds the key run_vision_stage writes', _w == _r,
       _detail if _w == _r
       else f'{len(set(_w) & set(_r))}/{len(_w)} rungs match -- Phase 5 will '
            f'fall back on every video')
    ck('...and it agrees on EVERY rung, not just the top one',
       _w == _r and len(_w) > 1, f'{len(_w)} rungs compared')

# A notebook TEST CELL that swaps globals must swap everything the code under
# test reads. Fix 22 made _visual_keys call plan_vlm_load; the §60 suite stubs
# P3 with a minimal fake and stubs three collaborators but not that one, so the
# REAL plan_vlm_load ran against the fake and died with
# "'_FakeVision' object has no attribute 'model_id'".
#
# Every local check passed, because this harness EXTRACTS functions and runs
# them -- it never executes the notebook's own test cells. Only Colab found it,
# on a live run. This check closes that specific hole: whatever _STAGE_SPECS
# declares the visual stage needs, the §60 stub must provide.
_specs = next((s for _i, s in code if '_STAGE_SPECS = (' in s), '')
_stub = next((s for _i, s in code if '_FAKE_RUNGS' in s and '_NAMES' in s), '')
_m = re.search(r"\('visual',\s*_visual_keys,\s*\((.*?)\)\)", _specs, re.S)
_needs = set(re.findall(r"'([A-Za-z_][\w]*)'", _m.group(1))) if _m else set()
_mn = re.search(r'_NAMES\s*=\s*\((.*?)\)\n', _stub, re.S)
_named = set(re.findall(r"'([A-Za-z_][\w]*)'", _mn.group(1))) if _mn else set()
# P3 is swapped wholesale and the version constants come with it.
_exempt = {'P3', 'VLM_STAGE_VERSION', 'PROMPT_VERSION'}
_gap = sorted((_needs - _exempt) - _named)
ck('the notebook test stub swaps every global _visual_keys reads',
   bool(_needs) and bool(_named) and not _gap,
   f'{sorted(_needs)} vs stub' if not _needs or not _named
   else (f'NOT STUBBED: {_gap} -- the real one will run against the fake '
         f'config and raise in Colab' if _gap else f'{len(_needs)} need(s) covered'))

print()
print('=' * 78)
print('K  THE L3 PROMPT  --  a menu option must not read as the ask')
print('=' * 78)
# Measured on a1a06e8d: the Hooks group returned `alignment: none` with the
# reason "No speech or text matching the hook phrase", while CITING her actual
# opening -- a bedtime hook, against a brief holding three bedtime hooks. The
# instructions were already right; the FRAME was not. The requirement line led
# with one literal sentence, so the model answered that sentence.
#
# This renders the real prompt and asserts the ask comes FIRST for a grouped
# requirement, and that an ungrouped one is untouched.


def _prompt_frame():
    import types
    chunks = []
    for _i, _s in code:
        t = trees.get(_i)
        if t is None:
            continue
        for node in t.body:
            if (isinstance(node, ast.FunctionDef)
                    and node.name in ('_evidence_line', 'build_l3_prompt')):
                chunks.append(_seg(_s, node))
    if len(chunks) < 2:
        return None, 'could not extract build_l3_prompt'
    ns = {'re': re}
    for ch in chunks:
        exec(ch, ns)
    rec = types.SimpleNamespace(
        id='ev_1', modality='speech', start_seconds=2.0, end_seconds=3.0,
        time_tolerance_seconds=0.15, description='', independence=None,
        type='speech',
        raw_text='this is how you get your children to go to sleep at night.')
    intent = 'Open with a hook naming a parenting pain point and a fix.'
    opt = {'id': 'r1', 'evidence_mode': 'speech_or_text', 'group': 'g',
           'group_label': 'Hooks', 'group_intent': intent,
           'match_hints': ['nuggets'], 'acceptance_criteria': [],
           'requirement': 'Open the video using the hook: "nuggets and fries"'}
    sib = dict(opt, id='r2', requirement='Open the video using: "option two"')
    solo = {'id': 's1', 'evidence_mode': 'speech_or_text', 'match_hints': [],
            'acceptance_criteria': [], 'requirement': 'State the disclaimer.'}
    g = ns['build_l3_prompt']([(opt, [{'record': rec}])], 35.7, {'g': [opt, sib]})
    u = ns['build_l3_prompt']([(solo, [{'record': rec}])], 35.7, {})
    return (g, u), ''


try:
    _res, _why = _prompt_frame()
except Exception as _e:
    _res, _why = None, f'{type(_e).__name__}: {str(_e)[:80]}'
if _res is None:
    ck('the grouped L3 prompt leads with THE ASK', False, _why)
else:
    _g, _u = _res
    _ask = _g.find('THE ASK')
    _opt = _g.find('this option')
    ck('the grouped L3 prompt leads with THE ASK', 0 < _ask < _opt,
       f'ask@{_ask} option@{_opt}')
    ck('...and says which judgement each question answers',
       "status judges THIS option's wording" in _g
       and 'alignment judges THE ASK' in _g)
    ck('...the intent is stated ONCE, not twice',
       _g.count('Open with a hook naming a parenting pain point') == 1,
       f"{_g.count('Open with a hook naming a parenting pain point')}x")
    ck('...match_hints are scoped to the OPTION, not the ask',
       'satisfy THIS OPTION' in _g)
    ck('an UNGROUPED requirement still renders as plain text',
       '  text          : State the disclaimer.' in _u and 'THE ASK' not in _u)

print()
print('=' * 78)
print('L  MUTATING A REQUIREMENT  --  both shapes, or neither')
print('=' * 78)
# A requirement is a DATACLASS on the compile path and a dict after to_dict().
# ungroup_non_alternatives has always handled both. ungroup_compliance_lines
# shipped handling only the dict branch, so on the compile path it matched the
# disclaimer, appended it to `moved`, reported success -- and changed nothing.
# Seven videos, every one still NOT_APPLICABLE.
#
# The shape of the bug is visible in the source: `if isinstance(r, dict):`
# that writes to the requirement and has no `else`.
_shape_bugs = []
for _i, _s in code:
    t = trees.get(_i)
    if t is None:
        continue
    for fn in [n for n in ast.walk(t) if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(fn):
            if not isinstance(node, ast.If) or node.orelse:
                continue
            test = ast.unparse(node.test)
            if not re.fullmatch(r'isinstance\(\s*\w+\s*,\s*dict\s*\)', test):
                continue
            # does the body WRITE to that object?
            writes = any(
                isinstance(x, (ast.Assign, ast.AugAssign))
                and any(isinstance(t2, ast.Subscript) for t2 in
                        (x.targets if isinstance(x, ast.Assign) else [x.target]))
                for x in ast.walk(node))
            if writes:
                _shape_bugs.append((_i, fn.name))
_shape_bugs = sorted(set(_shape_bugs))
ck('no function writes to a requirement on the dict branch only',
   not _shape_bugs,
   f'{_shape_bugs[:4]} -- a dataclass on the compile path would be untouched'
   if _shape_bugs else 'both shapes handled everywhere')

print()
bad = [l for l, ok, _d in R if not ok]
print('=' * 78)
print(f'{len(R) - len(bad)}/{len(R)} checks pass')
print('ALL PASS' if not bad else 'FAILED:\n   ' + '\n   '.join(bad))
print('=' * 78)
